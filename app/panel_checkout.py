"""Durable assistant handoff and transactional customer checkout.

Phone-only sign-in is deliberately retained; it is NOT proof of phone ownership.
Only the trusted panel bridge may mint the short-lived customer session.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import time
from datetime import datetime
from types import SimpleNamespace

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Integer, String, ForeignKey, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from . import mechanical_workflow
from .design_progress import set_project_progress


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def sign(value):
    secret = os.environ.get("PANEL_BRIDGE_TOKEN", "")
    if not secret:
        raise HTTPException(503, "ارتباط پنل تنظیم نشده است.")
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def authorize_bridge(request):
    supplied = request.headers.get("x-panel-token", "")
    secret = os.environ.get("PANEL_BRIDGE_TOKEN", "")
    if not secret or not secrets.compare_digest(secret, supplied):
        raise HTTPException(404)


def session_user(request):
    authorize_bridge(request)
    token = request.headers.get("x-customer-session", "")
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(401, "دوباره وارد پنل شوید.")
    uid, expiry, signature = parts
    if not uid.isdigit() or not expiry.isdigit() or int(expiry) <= time.time() or not secrets.compare_digest(signature, sign(f"customer:{uid}.{expiry}")):
        raise HTTPException(401, "نشست ورود منقضی شده است.")
    return int(uid)


def unresolved_questions(project):
    """Same key, presentation and numeric validation for every entry point."""
    from .main_auto import _present_question
    answers = dict(project.answers or {})
    if answers.get("discipline") == "mechanical":
        answers = mechanical_workflow.normalize_answers(answers)
    project.answers = answers
    questions = {q["key"]: q for q in project.questions or [] if isinstance(q, dict) and q.get("key")}
    if answers.get("discipline") == "mechanical":
        for key in mechanical_workflow.required_basis_questions(project):
            questions[key] = mechanical_workflow._question_payload(key)
    missing = []
    for key, question in questions.items():
        if key == 'gas_pressure' and mechanical_workflow._negative(answers.get('gas')):
            continue
        value = answers.get(key)
        if value is None or not str(value).strip() or mechanical_workflow._basis_answer_error(key, str(value)):
            missing.append(_present_question(question))
    return missing


def register_panel_checkout(app, legacy, Job, Link, status_payload, project_token):
    class Handoff(legacy.Base):
        __tablename__ = "panel_handoffs"
        token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
        project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
        expires: Mapped[int] = mapped_column(Integer)
        claimed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)

    class Checkout(legacy.Base):
        __tablename__ = "panel_checkouts"
        project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), primary_key=True)
        user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
        external_id: Mapped[str] = mapped_column(String(80), unique=True)
        amount: Mapped[int] = mapped_column(Integer, default=0)
        quote_token: Mapped[str] = mapped_column(String(64), default="")
        paid: Mapped[int] = mapped_column(Integer, default=0)
        area: Mapped[str] = mapped_column(String(40), default="")

    class Ledger(legacy.Base):
        __tablename__ = "panel_wallet_ledger"
        id: Mapped[str] = mapped_column(String(80), primary_key=True)
        user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
        project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), unique=True)
        amount: Mapped[int] = mapped_column(Integer)
        balance_after: Mapped[int] = mapped_column(Integer)
        created_at: Mapped[str] = mapped_column(String(40))

    class Profile(legacy.Base):
        __tablename__ = "panel_customer_profiles"
        user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
        phone: Mapped[str] = mapped_column(String(20))

    class Activity(legacy.Base):
        __tablename__ = "panel_account_activity"
        id: Mapped[str] = mapped_column(String(120), primary_key=True)
        user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
        request_hash: Mapped[str] = mapped_column(String(64))
        kind: Mapped[str] = mapped_column(String(40))
        amount: Mapped[int] = mapped_column(Integer)
        balance_after: Mapped[int] = mapped_column(Integer)
        description: Mapped[str] = mapped_column(String(500))
        actor: Mapped[str] = mapped_column(String(100))
        created_at: Mapped[str] = mapped_column(String(40))

    class PanelProject(legacy.Base):
        __tablename__ = "panel_customer_projects"
        id: Mapped[str] = mapped_column(String(80), primary_key=True)
        user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
        payload: Mapped[str] = mapped_column(Text)
        created_at: Mapped[str] = mapped_column(String(40))
        updated_at: Mapped[str] = mapped_column(String(40))

    for model in (Handoff, Checkout, Ledger, Profile, Activity, PanelProject):
        model.__table__.create(bind=legacy.engine, checkfirst=True)
    Wallet = app.state.commercial["Wallet"]
    pricing_for = app.state.commercial["service_pricing"]

    def apply_account_reconciliations():
        """Apply audited, idempotent wallet reconciliations configured for production."""
        raw = os.environ.get("PANEL_ACCOUNT_RECONCILIATIONS", "").strip()
        if not raw:
            return
        entries = json.loads(raw)
        if not isinstance(entries, list):
            raise RuntimeError("PANEL_ACCOUNT_RECONCILIATIONS must be a JSON list")
        with legacy.Session() as db:
            for entry in entries:
                uid = int(entry["user_id"])
                phone = re.sub(r"\D", "", str(entry["phone"]))
                amount = int(entry["amount"])
                request_id = str(entry["request_id"])
                if amount <= 0 or not re.fullmatch(r"[A-Za-z0-9-]{16,80}", request_id):
                    raise RuntimeError("Invalid account reconciliation entry")
                profile = db.get(Profile, uid)
                wallet = db.query(Wallet).filter(Wallet.user_id == uid).first()
                if not profile or re.sub(r"\D", "", profile.phone) != phone or not wallet:
                    raise RuntimeError(f"Account reconciliation target CUST-{uid} did not match")
                key = f"RECON-{uid}-{request_id}"
                if db.get(Activity, key):
                    continue
                wallet.balance += amount
                db.add(Activity(id=key, user_id=uid, request_hash=digest(json.dumps(entry, sort_keys=True)),
                                kind="account_reconciliation", amount=amount, balance_after=wallet.balance,
                                description=str(entry.get("reason", "Account reconciliation"))[:500],
                                actor="system-reconciliation", created_at=datetime.utcnow().isoformat()+'Z'))
            db.commit()

    apply_account_reconciliations()

    @app.middleware('http')
    async def freeze_claimed_drafts(request, call_next):
        match = re.fullmatch(r'/projects/(\d+)(?:/.*)?', request.url.path)
        if match and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            with legacy.Session() as db:
                if db.get(Checkout, int(match.group(1))):
                    return JSONResponse({'detail': 'این پروژه به پنل منتقل شده است؛ از پنل ادامه دهید.'}, status_code=409)
        return await call_next(request)

    def begin(db):
        # SQLite serializes before any reads; PostgreSQL locks the account below.
        if db.bind.dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))

    def account_id(uid):
        return f"CUST-{uid}"

    def require_account(db, uid):
        user = db.query(legacy.User).filter(legacy.User.id == uid).with_for_update().first()
        if not user or not db.get(Profile, uid):
            raise HTTPException(401)
        return user

    def account_history_score(db, uid):
        """Identify the established owner without treating an empty shell as history."""
        wallet = db.query(Wallet).filter(Wallet.user_id == uid).first()
        return sum((
            db.query(legacy.Project).filter(legacy.Project.user_id == uid).count(),
            db.query(Checkout).filter(Checkout.user_id == uid).count(),
            db.query(Ledger).filter(Ledger.user_id == uid).count(),
            db.query(Activity).filter(Activity.user_id == uid).count(),
            int(bool(wallet and wallet.balance)),
        ))

    def user_for_phone(db, phone):
        """Resolve a returning phone to its profile-backed account before creating one."""
        profiles = db.query(Profile).filter(Profile.phone == phone).order_by(Profile.user_id).all()
        if profiles:
            established = [p for p in profiles if account_history_score(db, p.user_id)]
            if len(established) > 1:
                raise HTTPException(409, "این شماره به چند حساب فعال متصل است؛ برای یکپارچه‌سازی حساب‌ها با پشتیبانی تماس بگیرید.")
            if established:
                return db.get(legacy.User, established[0].user_id)
            generated_email = f"phone-{digest(phone)}@panel.local"
            generated = db.query(legacy.User).filter(legacy.User.email == generated_email).first()
            if generated and any(p.user_id == generated.id for p in profiles):
                return generated
            return db.get(legacy.User, profiles[0].user_id)
        return db.query(legacy.User).filter(legacy.User.email == f"phone-{digest(phone)}@panel.local").first()

    def order_payload(db, order):
        project = db.get(legacy.Project, order.project_id)
        link = db.query(Link).filter(Link.project_id == project.id).first()
        data = status_payload(project)
        data.update(engine_project_id=project.id, project_token=project_token(link.external_project_id, link.external_user_hash))
        return {"id": order.external_id, "owner": account_id(order.user_id), "title": project.name,
                "service": "طراحی برق" if (project.answers or {}).get("discipline") == "electrical" else "طراحی مکانیک",
                "area": float(order.area or 0), "amount": order.amount, "paid": bool(order.paid),
                "quoteToken": order.quote_token, "answers": {k: v for k, v in (project.answers or {}).items() if isinstance(v, (str, int, float, bool))}, "engine": data}

    def state(db, uid):
        require_account(db, uid)
        wallet = db.query(Wallet).filter(Wallet.user_id == uid).first()
        entries = db.query(Ledger).filter(Ledger.user_id == uid).order_by(Ledger.created_at.desc()).all()
        orders = db.query(Checkout).filter(Checkout.user_id == uid).all()
        by_project = {o.project_id: o.external_id for o in orders}
        activities = db.query(Activity).filter(Activity.user_id == uid).all()
        transactions = [{"id": e.id, "owner": account_id(uid), "project": by_project.get(e.project_id, ""),
                         "title": "پرداخت پروژه از کیف پول", "amount": -e.amount,
                         "date": e.created_at, "status": "موفق", "category": "پروژه", "balanceAfter": e.balance_after} for e in entries]
        transactions.extend({"id": e.id, "owner": account_id(uid), "project": "",
                             "title": e.description, "amount": e.amount, "balanceAfter": e.balance_after,
                             "date": e.created_at, "status": "آزمایشی" if e.kind.startswith('demo_') else "موفق",
                             "category": e.kind, "actor": e.actor} for e in activities)
        durable_projects = []
        order_ids = {o.external_id for o in orders}
        for row in db.query(PanelProject).filter(PanelProject.user_id == uid).order_by(PanelProject.created_at.desc()).all():
            if row.id in order_ids:
                continue
            try:
                project = json.loads(row.payload)
            except (TypeError, ValueError):
                continue
            project.update(id=row.id, owner=account_id(uid))
            durable_projects.append(project)
        return {"userId": account_id(uid), "balance": wallet.balance if wallet else 0,
                "demoPayments": os.environ.get('PANEL_DEMO_PAYMENTS') == '1',
                "projects": [order_payload(db, o) for o in orders] + durable_projects,
                "transactions": sorted(transactions, key=lambda e: e['date'], reverse=True)}

    def import_projects(db, uid, rows):
        if not isinstance(rows, list) or len(rows) > 100:
            raise HTTPException(400, "فهرست پروژه‌ها معتبر نیست.")
        now = datetime.utcnow().isoformat() + "Z"
        allowed = {"title", "service", "area", "amount", "status", "progress", "date", "answers",
                   "engineProjectId", "engineProjectToken", "quoteToken", "paid", "designStage",
                   "designLabel", "designDetail", "designTimeline", "outputReady", "lastError"}
        for item in rows:
            if not isinstance(item, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{3,80}", str(item.get("id", ""))):
                raise HTTPException(400, "یکی از پروژه‌ها معتبر نیست.")
            project_id = str(item["id"])
            payload = {key: item[key] for key in allowed if key in item}
            encoded = json.dumps(payload, ensure_ascii=False)
            if len(encoded.encode()) > 20000:
                raise HTTPException(400, "حجم اطلاعات پروژه بیش از حد مجاز است.")
            row = db.get(PanelProject, project_id)
            if row and row.user_id != uid:
                raise HTTPException(409, "این پروژه متعلق به حساب دیگری است.")
            if row:
                row.payload = encoded
                row.updated_at = now
            else:
                db.add(PanelProject(id=project_id, user_id=uid, payload=encoded, created_at=now, updated_at=now))

    def adjust(db, uid, body, *, demo=False):
        request_id = str(body.get('requestId', ''))
        if not re.fullmatch(r'[A-Za-z0-9-]{16,80}', request_id):
            raise HTTPException(400, 'شناسه درخواست معتبر نیست.')
        amount = body.get('amount')
        reason = str(body.get('reason', '')).strip()
        kind = body.get('kind', 'credit')
        if type(amount) is not int or not 0 < amount <= 100000000 or kind not in ('credit', 'debit') or not 1 <= len(reason) <= 500:
            raise HTTPException(400, 'مبلغ و دلیل تغییر موجودی را صحیح وارد کنید.')
        if demo and (os.environ.get('PANEL_DEMO_PAYMENTS') != '1' or kind != 'credit'):
            raise HTTPException(409, 'پرداخت آزمایشی فعال نیست.')
        delta = -amount if kind == 'debit' else amount
        fingerprint = digest(json.dumps([delta, reason, demo], ensure_ascii=False))
        key = f"{'DEMO' if demo else 'ADJ'}-{uid}-{request_id}"
        previous = db.get(Activity, key)
        if previous:
            if previous.request_hash != fingerprint:
                raise HTTPException(409, 'این شناسه قبلاً برای درخواست دیگری استفاده شده است.')
            return
        wallet = db.query(Wallet).filter(Wallet.user_id == uid).with_for_update().one()
        if wallet.balance + delta < 0:
            raise HTTPException(409, 'موجودی کیف پول کافی نیست.')
        wallet.balance += delta
        db.add(Activity(id=key, user_id=uid, request_hash=fingerprint, kind='demo_topup' if demo else 'admin_adjustment',
                        amount=delta, balance_after=wallet.balance, description=reason,
                        actor=account_id(uid) if demo else 'panel-admin', created_at=datetime.utcnow().isoformat()+'Z'))

    @app.post('/internal/panel/admin/accounts')
    async def admin_accounts(request: Request):
        # Only the server-side admin proxy can reach this route with the bridge secret.
        authorize_bridge(request)
        body = await request.json()
        with legacy.Session() as db:
            begin(db)
            if body.get('action') == 'wallet_adjustment':
                match = re.fullmatch(r'CUST-(\d+)', str(body.get('userId', '')))
                if not match:
                    raise HTTPException(400, 'شناسه حساب معتبر نیست.')
                uid = int(match.group(1))
                require_account(db, uid)
                adjust(db, uid, body)
                db.commit()
            elif body.get('action') != 'state':
                raise HTTPException(400)
            profiles = []
            for phone, in db.query(Profile.phone).distinct().order_by(Profile.phone).all():
                try:
                    profiles.append(db.get(Profile, user_for_phone(db, phone).id))
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    # Keep genuinely active duplicates visible to administrators
                    # so they can be reconciled; only empty shells are collapsed.
                    profiles.extend(db.query(Profile).filter(Profile.phone == phone).order_by(Profile.user_id).all())
            accounts = [state(db, p.user_id) for p in profiles]
            return {'users': [{'id': account_id(p.user_id), 'mobile': p.phone, 'name': p.phone,
                               'wallet': a['balance'], 'active': True, 'admin': False, 'email': ''}
                              for p, a in zip(profiles, accounts)],
                    'projects': [p for a in accounts for p in a['projects'] if p.get('paid')],
                    'transactions': [t for a in accounts for t in a['transactions']]}

    @app.post("/internal/panel/customer/session")
    async def login(request: Request):
        authorize_bridge(request)
        body = await request.json()
        phone = str(body.get("phone", "")).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        if not re.fullmatch(r"09\d{9}", phone, flags=re.ASCII):
            raise HTTPException(400, "شماره موبایل معتبر وارد کنید.")
        with legacy.Session() as db:
            begin(db)
            email = f"phone-{digest(phone)}@panel.local"
            user = user_for_phone(db, phone)
            if not user:
                user = legacy.User(email=email)
                db.add(user); db.flush()
            if not db.query(Wallet).filter(Wallet.user_id == user.id).first():
                db.add(Wallet(user_id=user.id, balance=0))
            if not db.get(Profile, user.id):
                db.add(Profile(user_id=user.id, phone=phone))
            db.commit()
            expiry = int(time.time()) + 86400
            token = f"{user.id}.{expiry}"
            return {**state(db, user.id), "session": f"{token}.{sign('customer:' + token)}"}

    @app.post("/projects/{pid}/panel-handoff")
    def handoff(pid: int, request: Request):
        user = legacy.current_user(request)
        db, project = legacy.own_project(pid, user.id)
        if not project:
            raise HTTPException(404)
        try:
            if project.status not in ("asking", "ready_to_design", "drawing_set_review"):
                raise HTTPException(409, "تحلیل فایل هنوز کامل نشده است.")
            missing = unresolved_questions(project)
            if missing:
                project.questions = missing
                project.current_question = 0
                project.status = "asking"
                db.commit()
                return JSONResponse(legacy.flow_payload(project), status_code=409)
            token = secrets.token_urlsafe(32)
            db.add(Handoff(token_hash=digest(token), project_id=pid, expires=int(time.time()) + 86400))
            db.commit()
            origin = os.environ.get("PANEL_PUBLIC_URL", "https://engitools-admin.finodex-2798.chatgpt.site").rstrip("/")
            return {"url": f"{origin}/panel/projects/new#handoff={token}"}
        finally:
            db.close()

    @app.post("/internal/panel/customer/{action}")
    async def customer(action: str, request: Request):
        uid = session_user(request)
        body = await request.json()
        if action not in ("state", "import", "claim", "quote", "pay", "topup"):
            raise HTTPException(404)
        with legacy.Session() as db:
            begin(db)
            require_account(db, uid)
            if action == "state":
                return state(db, uid)
            if action == "import":
                import_projects(db, uid, body.get("projects"))
                db.commit()
                return state(db, uid)
            if action == 'topup':
                adjust(db, uid, {**body, 'kind': 'credit', 'reason': 'افزایش موجودی آزمایشی — بدون برداشت بانکی'}, demo=True)
                db.commit()
                return state(db, uid)
            if action == "claim":
                row = db.get(Handoff, digest(body.get("token", "")))
                if not row or row.expires < time.time() or row.claimed_by not in (None, uid):
                    raise HTTPException(404, "پیوند انتقال معتبر نیست یا منقضی شده است.")
                row.claimed_by = uid
                project = db.get(legacy.Project, row.project_id)
                order = db.get(Checkout, project.id)
                if order and order.user_id != uid:
                    raise HTTPException(404)
                if not order:
                    external_id = f"PRJ-{secrets.token_hex(8)}"
                    user_hash = digest(account_id(uid))
                    db.add(Link(external_project_id=external_id, external_user_hash=user_hash, project_id=project.id,
                                access_token_hash=digest(project_token(external_id, user_hash))))
                    order = Checkout(project_id=project.id, user_id=uid, external_id=external_id)
                    db.add(order)
                db.commit()
                from .main_auto import panel_analysis_payload, QUESTIONNAIRE_VERSION
                payload = order_payload(db, order)
                payload["analysis"] = {**panel_analysis_payload((project.analysis or {}).get("architectural_auto") or {}),
                                       "questions": [], "inferredAnswers": payload['answers'], "questionnaireVersion": QUESTIONNAIRE_VERSION}
                return payload
            try:
                pid = int(body.get("engineProjectId", 0))
            except (TypeError, ValueError):
                raise HTTPException(400)
            link = db.query(Link).filter(Link.project_id == pid).first()
            if not link or link.external_user_hash != digest(account_id(uid)):
                raise HTTPException(404)
            project = db.get(legacy.Project, pid)
            order = db.get(Checkout, pid)
            if not order:
                order = Checkout(project_id=pid, user_id=uid, external_id=link.external_project_id)
                db.add(order); db.flush()
            if order.paid:
                return {"project": order_payload(db, order), **state(db, uid)}
            if action == "quote":
                supplied = body.get("answers") or {}
                if not isinstance(supplied, dict):
                    raise HTTPException(400)
                # Do not let a client change discipline or inject internal fields.
                allowed = {q.get("key") for q in project.questions or [] if isinstance(q, dict)}
                if (project.answers or {}).get("discipline") == "mechanical":
                    allowed.update(mechanical_workflow.required_basis_questions(project))
                answers = dict(project.answers or {})
                answers.update({k: v for k, v in supplied.items() if k in allowed and isinstance(v, (str, int, float))})
                project.answers = answers
                missing = unresolved_questions(project)
                if missing:
                    db.commit()
                    return JSONResponse({"status": "asking", "questions": missing, "question_count": len(missing), "error": "اطلاعات پروژه را تکمیل کنید."}, status_code=409)
                try:
                    area = float(body.get("area", 0))
                except (ValueError, TypeError):
                    area = 0
                if not math.isfinite(area) or not 0 < area <= 100000:
                    raise HTTPException(400, "مساحت پروژه را تأیید کنید.")
                # Pricing is read from the server, never from the browser's amount.
                db.commit()
                pricing = pricing_for(answers.get("discipline", "mechanical"))
                begin(db)
                require_account(db, uid)
                db.refresh(order)
                db.refresh(project)
                if order.paid:
                    return {"project": order_payload(db, order), **state(db, uid)}
                if not pricing["enabled"]:
                    raise HTTPException(409, "این خدمت فعال نیست.")
                order.amount = max(pricing["minimum_price"], int(round(area * pricing["price_per_m2"])))
                order.area = str(area)
                order.quote_token = digest(json.dumps([order.amount, project.answers, order.area], sort_keys=True, ensure_ascii=False))
                db.commit()
                return {"project": order_payload(db, order), **state(db, uid)}
            demo = body.get('method') == 'gateway' and os.environ.get('PANEL_DEMO_PAYMENTS') == '1'
            if body.get("method") != "wallet" and not demo:
                raise HTTPException(503, "درگاه بانکی هنوز متصل نیست؛ پرداختی انجام نشد.")
            if not order.quote_token or not secrets.compare_digest(str(body.get("quoteToken", "")), order.quote_token):
                raise HTTPException(409, "قیمت نهایی را دوباره دریافت و تأیید کنید.")
            current_quote = digest(json.dumps([order.amount, project.answers, order.area], sort_keys=True, ensure_ascii=False))
            if not secrets.compare_digest(current_quote, order.quote_token):
                raise HTTPException(409, "اطلاعات پروژه تغییر کرده است؛ دوباره قیمت را تأیید کنید.")
            missing = unresolved_questions(project)
            if missing:
                raise HTTPException(409, "اطلاعات پروژه تغییر کرده است؛ دوباره قیمت را تأیید کنید.")
            wallet = db.query(Wallet).filter(Wallet.user_id == uid).with_for_update().first()
            if not wallet or (not demo and wallet.balance < order.amount):
                raise HTTPException(409, "موجودی کیف پول کافی نیست؛ هیچ مبلغی کسر نشد.")
            if (project.answers or {}).get("discipline") == "mechanical":
                proposal = mechanical_workflow.create_proposal(project)
                analysis = dict(project.analysis or {})
                analysis["drawing_set"] = mechanical_workflow.approve_drawing_set(proposal)
                project.analysis = analysis
            if not demo:
                wallet.balance -= order.amount
            order.paid = 1
            if demo:
                db.add(Activity(id=f'DEMO-PAY-{pid}', user_id=uid, request_hash=order.quote_token, kind='demo_payment',
                                amount=-order.amount, balance_after=wallet.balance,
                                description=f'پرداخت آزمایشی پروژه {order.external_id} — بدون برداشت بانکی یا کیف پول',
                                actor=account_id(uid), created_at=datetime.utcnow().isoformat()+'Z'))
            else:
                db.add(Ledger(id=f"TXN-{secrets.token_hex(12)}", user_id=uid, project_id=pid, amount=order.amount,
                              balance_after=wallet.balance, created_at=datetime.utcnow().isoformat() + "Z"))
            revision = legacy.Revision(project_id=pid, revision_no=(project.current_revision or 0) + 1, status="queued")
            db.add(revision); db.flush()
            db.add(Job(job_type="design", project_id=pid, revision_id=revision.id, status="queued"))
            project.status = "queued"
            project.last_error = ""
            set_project_progress(project, "queued")
            # Debit, ledger, paid marker and queue job either all commit or all roll back.
            db.commit()
            return {"project": order_payload(db, order), **state(db, uid)}

    app.state.panel_checkout = SimpleNamespace(Handoff=Handoff, Checkout=Checkout, Ledger=Ledger, Activity=Activity, Profile=Profile, PanelProject=PanelProject,
                                               session_user=session_user, apply_account_reconciliations=apply_account_reconciliations)
