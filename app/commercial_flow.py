"""Customer dashboard, quotations, wallet and payment gate for project design."""

from datetime import datetime

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column


def register_commercial_flow(app, legacy):
    class Wallet(legacy.Base):
        __tablename__ = "wallets"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
        balance: Mapped[int] = mapped_column(Integer, default=8_500_000)
        updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    class ProjectQuote(legacy.Base):
        __tablename__ = "project_quotes"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), unique=True, index=True)
        amount: Mapped[int] = mapped_column(Integer)
        currency: Mapped[str] = mapped_column(String(20), default="تومان")
        paid: Mapped[bool] = mapped_column(Boolean, default=False)
        payment_method: Mapped[str] = mapped_column(String(30), default="")
        paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
        created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    class ServicePricing(legacy.Base):
        __tablename__ = "service_pricing"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        discipline: Mapped[str] = mapped_column(String(30), unique=True, index=True)
        enabled: Mapped[bool] = mapped_column(Boolean, default=True)
        minimum_price: Mapped[int] = mapped_column(Integer)
        price_per_m2: Mapped[int] = mapped_column(Integer)
        updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    legacy.Base.metadata.create_all(legacy.engine)

    DEFAULT_PRICING = {
        "mechanical": {"minimum_price": 4_900_000, "price_per_m2": 28_000},
        "electrical": {"minimum_price": 4_200_000, "price_per_m2": 24_000},
    }

    def service_pricing(discipline, db=None):
        owns_db = db is None
        db = db or legacy.Session()
        row = db.query(ServicePricing).filter(ServicePricing.discipline == discipline).first()
        if not row:
            defaults = DEFAULT_PRICING.get(discipline, DEFAULT_PRICING["mechanical"])
            row = ServicePricing(discipline=discipline, enabled=True, **defaults)
            db.add(row); db.commit(); db.refresh(row)
        data = {"discipline": row.discipline, "enabled": row.enabled, "minimum_price": row.minimum_price, "price_per_m2": row.price_per_m2}
        if owns_db: db.close()
        return data

    def project_area_m2(project):
        analysis = project.analysis or {}
        auto = analysis.get("architectural_auto") or {}
        candidates = [auto.get("geometry_area_m2"), analysis.get("geometry_area_m2")]
        for value in candidates:
            try:
                area = float(value)
                if 15 <= area <= 250_000: return round(area, 2)
            except (TypeError, ValueError):
                pass
        areas = []
        for item in analysis.get("files") or []:
            try:
                area = float(item.get("geometry_area_m2"))
                if 15 <= area <= 15_000: areas.append(area)
            except (TypeError, ValueError):
                pass
        return round(sum(areas), 2) if areas else None

    def wallet_for(user_id):
        db = legacy.Session()
        wallet = db.query(Wallet).filter(Wallet.user_id == user_id).first()
        if not wallet:
            wallet = Wallet(user_id=user_id, balance=8_500_000)
            db.add(wallet); db.commit(); db.refresh(wallet)
        data = {"balance": wallet.balance}
        db.close()
        return data

    def quote_amount(project):
        analysis = project.analysis or {}
        discipline = (project.answers or {}).get("discipline", analysis.get("discipline", "mechanical"))
        pricing = service_pricing(discipline)
        if not pricing["enabled"]: raise ValueError("این سرویس در حال حاضر غیرفعال است.")
        area = project_area_m2(project)
        metered = int(round((area or 0) * pricing["price_per_m2"]))
        return max(pricing["minimum_price"], metered)

    def quote_for(project):
        if project.status not in {"ready_to_design", "drawing_set_review", "queued", "designing", "quality_check", "ready"}:
            return None
        db = legacy.Session()
        quote = db.query(ProjectQuote).filter(ProjectQuote.project_id == project.id).first()
        if not quote:
            quote = ProjectQuote(project_id=project.id, amount=quote_amount(project))
            db.add(quote); db.commit(); db.refresh(quote)
        area = project_area_m2(project)
        pricing = service_pricing((project.answers or {}).get("discipline", (project.analysis or {}).get("discipline", "mechanical")))
        data = {"amount": quote.amount, "currency": quote.currency, "paid": quote.paid, "payment_method": quote.payment_method, "area_m2": area, "minimum_price": pricing["minimum_price"], "price_per_m2": pricing["price_per_m2"]}
        db.close()
        return data

    def commercial_context(project):
        return {"quote": quote_for(project), "wallet": wallet_for(project.user_id)}

    legacy.templates.env.globals["commercial_context"] = commercial_context
    legacy.templates.env.filters["money"] = lambda value: f"{int(value or 0):,}".replace(",", "٬")

    @app.get("/panel")
    def panel(request: Request):
        user = legacy.current_user(request); db = legacy.Session()
        projects = db.query(legacy.Project).filter(legacy.Project.user_id == user.id).order_by(legacy.Project.created_at.desc()).all()
        balance = wallet_for(user.id)["balance"]
        active_count = sum(p.status in {"analyzing", "asking", "queued", "designing", "quality_check"} for p in projects)
        response = legacy.templates.TemplateResponse("user_panel.html", {"request": request, "user": user, "projects": projects, "wallet_balance": balance, "active_count": active_count})
        db.close(); return response

    @app.get("/panel/projects/new")
    def new_project(request: Request):
        user = legacy.current_user(request)
        pricing = {key: service_pricing(key) for key in legacy.DISCIPLINES}
        return legacy.templates.TemplateResponse("new_project.html", {"request": request, "user": user, "wallet_balance": wallet_for(user.id)["balance"], "service_pricing": pricing})

    @app.get("/admin/pricing")
    def admin_pricing(request: Request):
        services = [service_pricing(key) | {"title": legacy.DISCIPLINES[key]["title"], "icon": legacy.DISCIPLINES[key]["icon"]} for key in ("mechanical", "electrical")]
        return legacy.templates.TemplateResponse("admin_pricing.html", {"request": request, "services": services, "saved": request.query_params.get("saved") == "1"})

    @app.post("/admin/pricing/{discipline}")
    def update_admin_pricing(discipline: str, enabled: str = Form(""), minimum_price: int = Form(...), price_per_m2: int = Form(...)):
        if discipline not in legacy.DISCIPLINES: raise HTTPException(404)
        if minimum_price < 0 or price_per_m2 < 0: raise HTTPException(422, "مبالغ نمی‌توانند منفی باشند.")
        db = legacy.Session(); row = db.query(ServicePricing).filter(ServicePricing.discipline == discipline).first()
        if not row:
            row = ServicePricing(discipline=discipline, minimum_price=minimum_price, price_per_m2=price_per_m2); db.add(row)
        row.enabled = enabled == "on"; row.minimum_price = minimum_price; row.price_per_m2 = price_per_m2; row.updated_at = datetime.utcnow()
        db.commit(); db.close(); return RedirectResponse("/admin/pricing?saved=1", 303)

    @app.post("/projects/{pid}/pay/wallet")
    def pay_wallet(pid: int, request: Request):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project: raise HTTPException(404)
        quote_data = quote_for(project)
        if not quote_data: db.close(); raise HTTPException(409, "پروژه هنوز آماده قیمت‌گذاری نیست.")
        quote = db.query(ProjectQuote).filter(ProjectQuote.project_id == pid).first()
        wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()
        if quote.paid: db.close(); return RedirectResponse(f"/projects/{pid}", 303)
        if wallet.balance < quote.amount: db.close(); raise HTTPException(409, "موجودی کیف پول کافی نیست.")
        wallet.balance -= quote.amount; wallet.updated_at = datetime.utcnow()
        quote.paid = True; quote.payment_method = "wallet"; quote.paid_at = datetime.utcnow()
        db.commit(); db.close(); return RedirectResponse(f"/projects/{pid}?payment=success", 303)

    @app.post("/projects/{pid}/pay/gateway")
    def pay_gateway(pid: int, request: Request):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project: raise HTTPException(404)
        quote_data = quote_for(project)
        if not quote_data: db.close(); raise HTTPException(409, "پروژه هنوز آماده قیمت‌گذاری نیست.")
        quote = db.query(ProjectQuote).filter(ProjectQuote.project_id == pid).first()
        # The production PSP callback can replace this atomic confirmation without changing the UI contract.
        quote.paid = True; quote.payment_method = "gateway"; quote.paid_at = datetime.utcnow()
        db.commit(); db.close(); return RedirectResponse(f"/projects/{pid}?payment=success", 303)

    def replace_with_payment_guard(path, json_response=False):
        old = None
        for route in list(app.router.routes):
            if getattr(route, "path", None) == path and "POST" in (getattr(route, "methods", set()) or set()):
                old = route.endpoint; app.router.routes.remove(route)
        if not old: return
        async def guarded(pid: int, request: Request):
            user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
            if not project: raise HTTPException(404)
            quote = db.query(ProjectQuote).filter(ProjectQuote.project_id == pid).first(); db.close()
            if not quote or not quote.paid:
                if json_response: return JSONResponse({"error": "payment_required", "message": "برای شروع طراحی ابتدا هزینه پروژه را پرداخت کنید."}, status_code=402)
                return RedirectResponse(f"/projects/{pid}?payment=required", 303)
            result = old(pid, request)
            if hasattr(result, "__await__"): result = await result
            return result
        app.add_api_route(path, guarded, methods=["POST"])

    replace_with_payment_guard("/projects/{pid}/design")
    replace_with_payment_guard("/projects/{pid}/design-json", json_response=True)
    replace_with_payment_guard("/projects/{pid}/approve-drawing-set")

    original_flow_payload = legacy.flow_payload
    def flow_payload_with_payment(project):
        data = original_flow_payload(project)
        if project.status in {"ready_to_design", "drawing_set_review"}:
            quote = quote_for(project)
            if quote and not quote["paid"]:
                data.update({"payment_required": True, "price": quote["amount"], "project_url": f"/projects/{project.id}"})
        return data
    legacy.flow_payload = flow_payload_with_payment

    @app.middleware("http")
    async def disabled_service_gate(request, call_next):
        discipline = None
        if request.method == "POST" and request.url.path.startswith("/api/upload/init/"):
            discipline = request.url.path.rsplit("/", 1)[-1]
        elif request.method == "POST" and request.url.path.startswith("/start-project/"):
            discipline = request.url.path.rsplit("/", 1)[-1]
        if discipline in legacy.DISCIPLINES and not service_pricing(discipline)["enabled"]:
            if request.url.path.startswith("/api/"): return JSONResponse({"error": "service_disabled", "message": "این سرویس موقتاً غیرفعال است."}, status_code=503)
            return HTMLResponse("این سرویس موقتاً غیرفعال است.", status_code=503)
        return await call_next(request)

    app.state.commercial = {"Wallet": Wallet, "ProjectQuote": ProjectQuote, "ServicePricing": ServicePricing, "quote_for": quote_for, "wallet_for": wallet_for, "service_pricing": service_pricing, "project_area_m2": project_area_m2}
