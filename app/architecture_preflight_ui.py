"""Thin project-bound UI/transport for Architecture Preflight.

All engineering state, allowed answers and qualification decisions come from the
canonical backend. This module translates them for display and transports a
bounded decision; it never infers architecture or accepts geometry from clients.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hmac
import math
import secrets

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from cad_engine.architecture_review_engine import execute_preflight, plan_preflight
from cad_engine.build_identity import build_identity
from cad_engine.architecture_contract import content_hash


PERSISTENCE_KEY = "architecture_preflight_ui"
CLIENT_FIELDS = {"review_item_id", "decision", "review_fingerprint", "request_id"}

ANSWER_LABELS = {
    "DOOR": "در", "WINDOW": "پنجره", "OPEN_PASSAGE": "بازشوی بدون در",
    "CONTINUOUS_WALL": "دیوار پیوسته", "UNKNOWN": "نامشخص",
    "DUCT": "داکت", "SHAFT": "شفت", "LIGHTWELL": "نورگیر", "VOID": "فضای خالی",
    "NOT_A_VOID": "فضای خالی یا داکت نیست", "SAME_PHYSICAL_SPACE": "یک فضای فیزیکی",
    "SEPARATE_PHYSICAL_SPACES": "دو فضای مجزا", "TOILET": "سرویس بهداشتی",
    "KITCHEN": "آشپزخانه", "LIVING": "نشیمن", "BEDROOM": "اتاق خواب",
    "CORRIDOR": "راهرو", "PARKING": "پارکینگ",
}
STATE_COPY = {
    "AUTO_VALIDATED": ("بررسی معماری تکمیل شد", "ورودی معماری موردنیاز موتور، از کنترل مستقل عبور کرده است."),
    "QUICK_REVIEW_REQUIRED": ("یک مورد نیاز به تأیید دارد", "فقط موارد محدود و قابل تفسیر نمایش داده می‌شوند."),
    "ARCHITECTURE_INPUT_REQUIRED": ("اطلاعات فایل برای تصمیم قطعی کافی نیست", "تأیید ساده نمی‌تواند شواهد مهندسی گمشده را ایجاد کند."),
    "CONFLICT": ("تعارض مسدودکننده در معماری", "این تعارض باید در منبع یا پردازش داخلی برطرف شود."),
}
IMPACT_LABELS = {
    "RELEASE_CRITICAL": "مسدودکننده تأیید معماری",
    "DOWNSTREAM_CRITICAL": "اثرگذار بر طراحی پایین‌دست",
    "REVIEW_CRITICAL": "نیازمند بررسی پیش از ادامه",
    "NONCRITICAL_DIAGNOSTIC": "جزئیات غیرمسدودکننده تحلیل",
}
QUESTION_COPY = {
    "SPACE_CLASSIFICATION": "کاربری این فضای موجود در نقشه چیست؟",
    "OPEN_PLAN_CONFIRMATION": "آیا این محدوده یک فضای فیزیکی یکپارچه است؟",
    "PORTAL_INTERPRETATION": "این موقعیت در نقشه معماری چیست؟",
    "VOID_INTERPRETATION": "این محدوده بسته در نقشه معماری چیست؟",
    "WALL_CONTINUITY_INTERPRETATION": "در این موقعیت، دیوار پیوسته است یا بازشو وجود دارد؟",
    "FRAME_LEVEL_CLASSIFICATION": "این قاب به کدام طبقه تعلق دارد؟",
    "SOURCE_ROLE_CLASSIFICATION": "نقش این عنصر موجود در فایل چیست؟",
    "OTHER_BOUNDED_SOURCE_INTERPRETATION": "تفسیر درست این شواهد موجود چیست؟",
}
GUIDANCE_LABELS = {
    "EFFECTIVE_SCALE_REQUIRED": "واحد یا مقیاس معتبر فایل مشخص نیست.",
    "FRAME_LEVEL_UNRESOLVED": "طبقه مرتبط با این قاب مشخص نیست.",
    "VOID_SOURCE_GEOMETRY_REQUIRED": "مرز بسته و قابل‌اثبات برای داکت یا فضای خالی موجود نیست.",
    "PORTAL_TOPOLOGY_UNRESOLVED": "بازشوی هندسی قابل‌اثبات در دیوار موجود نیست.",
}
CORRECTION_LABELS = {
    "EFFECTIVE_SCALE_REQUIRED": "واحد یا مقیاس فایل را در منبع معماری مشخص و دوباره بارگذاری کنید.",
    "FRAME_LEVEL_UNRESOLVED": "نام و محدوده طبقه را در فایل معماری روشن کنید.",
    "VOID_SOURCE_GEOMETRY_REQUIRED": "مرز بسته داکت یا فضای خالی را در فایل معماری کامل کنید.",
    "PORTAL_TOPOLOGY_UNRESOLVED": "هندسه بازشوی در را در فایل معماری اصلاح یا تکمیل کنید.",
}


def _finite_point(value):
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        point = [float(value[0]), float(value[1])]
    except (TypeError, ValueError):
        return None
    return point if all(math.isfinite(x) and abs(x) <= 1e9 for x in point) else None


def _safe_line(points, *, closed=False):
    if not isinstance(points, list) or len(points) > 10000:
        return None
    clean = [point for point in (_finite_point(x) for x in points) if point is not None]
    if len(clean) < 2:
        return None
    return {"points": clean, "closed": bool(closed)}


def _viewer_model(canonical, item):
    preview = deepcopy(item.get("preview_spec") or {})
    bounds = preview.get("crop_bounds")
    try:
        bounds = [float(x) for x in bounds]
        if len(bounds) != 4 or not all(math.isfinite(x) for x in bounds) or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            bounds = None
    except (TypeError, ValueError):
        bounds = None
    primitives = []
    requested = set(preview.get("overlay_layers_requested") or [])
    wall_ids = set(preview.get("related_wall_ids") or [])
    space_ids = set(preview.get("related_space_ids") or [])
    gap_ids = set(preview.get("related_gap_ids") or [])
    for wall in canonical.get("walls") or []:
        if wall.get("wall_id") in wall_ids:
            line = _safe_line(wall.get("centerline") or [])
            if line: primitives.append({**line, "kind": "wall", "id": wall.get("wall_id")})
    for space in canonical.get("physical_spaces") or []:
        if space.get("physical_space_id") in space_ids:
            line = _safe_line(space.get("polygon") or [], closed=True)
            if line: primitives.append({**line, "kind": "space", "id": space.get("physical_space_id")})
    for aperture in canonical.get("apertures") or []:
        if aperture.get("aperture_id") in gap_ids:
            line = _safe_line(aperture.get("geometry") or [])
            if line: primitives.append({**line, "kind": "aperture", "id": aperture.get("aperture_id")})
    highlight = preview.get("highlight_geometry")
    if isinstance(highlight, dict):
        highlight = highlight.get("points") or highlight.get("geometry")
    line = _safe_line(highlight or [], closed=False)
    if line: primitives.append({**line, "kind": "focus", "id": item.get("object_or_region_id")})
    return {"frame_id": preview.get("frame_id") or item.get("frame_or_level_id"),
            "crop_bounds": bounds, "primitives": primitives,
            "overlay_layers_requested": sorted(str(x) for x in requested),
            "source_handles": [str(x) for x in (preview.get("source_handles") or [])[:200]],
            "question_focus": str(preview.get("question_focus") or "")}


def _evidence_rows(summary):
    if not isinstance(summary, dict):
        return []
    rows = []
    for key in sorted(summary):
        value = summary[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            rows.append({"key": str(key), "value": "—" if value is None else str(value)})
        elif isinstance(value, list):
            rows.append({"key": str(key), "value": "، ".join(str(x) for x in value[:30])})
    return rows


def preflight_view_model(canonical, plan, snapshot=None, registry=None):
    state = plan.get("primary_state")
    title, description = STATE_COPY.get(state, STATE_COPY["CONFLICT"])
    registry = registry or plan.get("review_registry") or {}
    items = plan.get("review_items") or []
    current = items[0] if items else None
    question = None
    if current:
        answers = [{"value": value, "label": ANSWER_LABELS.get(value, value)}
                   for value in current.get("allowed_answers") or []]
        question = {"review_item_id": current.get("review_item_id"),
                    "review_fingerprint": current.get("review_fingerprint"),
                    "text": QUESTION_COPY.get(current.get("question_type"), QUESTION_COPY["OTHER_BOUNDED_SOURCE_INTERPRETATION"]),
                    "question_type": current.get("question_type"), "answers": answers,
                    "impact": current.get("impact_classification"),
                    "impact_label": IMPACT_LABELS.get(current.get("impact_classification"), "نیازمند بررسی"),
                    "evidence": _evidence_rows(current.get("evidence_summary")),
                    "recommendation": ANSWER_LABELS.get(current.get("ai_recommendation"), current.get("ai_recommendation")),
                    "recommendation_confidence": current.get("ai_recommendation_confidence"),
                    "viewer": _viewer_model(canonical, current),
                    "technical": {"frame": current.get("frame_or_level_id"),
                                  "object": current.get("object_or_region_id"),
                                  "issue_ids": current.get("validator_issue_ids_covered") or [],
                                  "source_handles": (current.get("preview_spec") or {}).get("source_handles") or [],
                                  "fingerprint": str(current.get("review_fingerprint") or "")[:16]}}
    source_actions = []
    for row in plan.get("source_input_requirements") or []:
        missing = row.get("missing_evidence")
        source_actions.append({**deepcopy(row),
                               "missing_label": GUIDANCE_LABELS.get(missing, "شواهد لازم در فایل معماری موجود نیست."),
                               "impact_label": IMPACT_LABELS.get(row.get("impact_classification"), "مانع ادامهٔ ایمن فرایند است."),
                               "correction_label": CORRECTION_LABELS.get(missing, "منبع معماری را مطابق راهنمای فنی پروژه اصلاح کنید.")})
    accepted = registry.get("accepted_decisions") or []
    total = len(accepted) + len(items)
    return {"state": state, "title": title, "description": description, "question": question,
            "remaining_count": len(items), "reviewed_count": len(accepted), "total_count": total,
            "source_actions": source_actions, "engine_defects": plan.get("engine_defects") or [],
            "diagnostics": plan.get("noncritical_diagnostics") or [],
            "raw_validator_codes": plan.get("raw_validator_codes") or [],
            "snapshot": deepcopy(snapshot), "source_sha256": plan.get("source_sha256"),
            "canonical_model_hash": plan.get("canonical_model_hash")}


def _load_state(project):
    stored = deepcopy((project.analysis or {}).get(PERSISTENCE_KEY) or {})
    canonical = stored.get("canonical_model")
    if not isinstance(canonical, dict):
        raise HTTPException(409, "ARCHITECTURE_PREFLIGHT_NOT_AVAILABLE")
    source_sha = (canonical.get("source") or {}).get("source_sha256")
    if stored.get("source_sha256") and stored.get("source_sha256") != source_sha:
        raise HTTPException(409, "STALE_ARCHITECTURE_SOURCE")
    if stored.get("canonical_model_hash") and stored.get("canonical_model_hash") != canonical.get("canonical_model_hash"):
        raise HTTPException(409, "STALE_ARCHITECTURE_MODEL")
    registry = stored.get("review_registry")
    result = execute_preflight(canonical, review_registry=registry,
                               engine_identity=build_identity(), created_at=stored.get("created_at") or "UNSPECIFIED")
    plan = result["preflight_plan"]
    # Only current server revalidation can supply an authoritative snapshot.
    # Persisted snapshots are historical artifacts, never a fallback authority.
    snapshot = result.get("snapshot")
    return stored, canonical, registry, result, preflight_view_model(canonical, plan, snapshot, result.get("review_registry"))


def _csrf_token(request):
    token = request.session.get("architecture_preflight_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["architecture_preflight_csrf"] = token
    return token


def architecture_preflight_blocking(project):
    stored = (project.analysis or {}).get(PERSISTENCE_KEY) or {}
    canonical = stored.get("canonical_model")
    if not isinstance(canonical, dict):
        return False
    plan = plan_preflight(canonical, review_registry=stored.get("review_registry"))
    return plan.get("primary_state") != "AUTO_VALIDATED"


def register_architecture_preflight_ui(app, legacy):
    legacy.templates.env.globals["architecture_preflight_blocking"] = architecture_preflight_blocking
    @app.get("/projects/{pid}/architecture-preflight", response_class=HTMLResponse)
    def architecture_preflight_page(pid: int, request: Request):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project:
            raise HTTPException(404)
        try:
            _stored, canonical, _registry, result, view = _load_state(project)
            response = legacy.templates.TemplateResponse("architecture_preflight.html", {
                "request": request, "p": project, "preflight": view,
                "viewer_data": (view.get("question") or {}).get("viewer") or {},
                "plan": result["preflight_plan"], "canonical": canonical,
                "csrf_token": _csrf_token(request),
            })
        finally:
            db.close()
        return response

    @app.get("/projects/{pid}/architecture-preflight/state")
    def architecture_preflight_state(pid: int, request: Request):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project:
            raise HTTPException(404)
        try:
            _stored, _canonical, _registry, _result, view = _load_state(project)
            return JSONResponse(view)
        finally:
            db.close()

    @app.post("/projects/{pid}/architecture-preflight/review/{review_item_id}")
    async def architecture_preflight_review(pid: int, review_item_id: str, request: Request):
        user = legacy.current_user(request)
        db = legacy.Session()
        project = db.query(legacy.Project).filter(legacy.Project.id == pid,
                                                   legacy.Project.user_id == user.id).with_for_update().first()
        if not project:
            db.close(); raise HTTPException(404)
        try:
            expected_csrf = request.session.get("architecture_preflight_csrf") or ""
            supplied_csrf = request.headers.get("x-csrf-token") or ""
            if not expected_csrf or not hmac.compare_digest(expected_csrf, supplied_csrf):
                raise HTTPException(403, "CSRF_TOKEN_INVALID")
            if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise HTTPException(415, "JSON_REQUIRED")
            payload = await request.json()
            if not isinstance(payload, dict) or set(payload) != CLIENT_FIELDS:
                raise HTTPException(422, "REVIEW_PAYLOAD_FIELDS_INVALID")
            if payload.get("review_item_id") != review_item_id:
                raise HTTPException(409, "REVIEW_ITEM_PROJECT_BINDING_INVALID")
            stored, canonical, registry, initial, _view = _load_state(project)
            request_id = str(payload.get("request_id") or "")
            if not request_id or len(request_id) > 128:
                raise HTTPException(422, "REQUEST_ID_INVALID")
            request_hash = content_hash([pid, review_item_id, payload.get("review_fingerprint"), payload.get("decision")])
            prior = (stored.get("requests") or {}).get(request_id)
            if prior:
                if prior.get("request_hash") != request_hash:
                    raise HTTPException(409, "IDEMPOTENCY_KEY_REUSED")
                view = _view
                return JSONResponse({"ok": True, "idempotent_replay": True, "preflight": view,
                                     "redirect_url": f"/projects/{pid}/architecture-preflight"})
            plan = initial["preflight_plan"]
            item = next((x for x in plan.get("review_items") or [] if x.get("review_item_id") == review_item_id), None)
            if not item:
                raise HTTPException(409, "STALE_REVIEW_DECISION")
            if payload.get("review_fingerprint") != item.get("review_fingerprint"):
                raise HTTPException(409, "STALE_REVIEW_DECISION")
            if payload.get("decision") not in (item.get("allowed_answers") or []):
                raise HTTPException(422, "REVIEW_DECISION_NOT_ALLOWED")
            authoritative = {key: item.get(key) for key in
                             ("source_sha256", "frame_or_level_id", "object_or_region_id",
                              "geometry_fingerprint", "evidence_fingerprint", "review_scope", "review_fingerprint")}
            authoritative.update(review_item_id=review_item_id, decision=payload["decision"])
            result = execute_preflight(canonical, [authoritative], registry,
                                       engine_identity=build_identity(),
                                       created_at=datetime.now(timezone.utc).isoformat())
            rejected = result.get("rejected_review_decisions") or []
            stale = result.get("stale_review_decisions") or []
            if stale:
                raise HTTPException(409, "STALE_REVIEW_DECISION")
            if rejected:
                raise HTTPException(422, "REVIEW_DECISION_REJECTED")
            stored["canonical_model"] = deepcopy(result.get("reviewed_canonical_model") or canonical)
            stored["review_registry"] = deepcopy(result.get("review_registry") or {})
            stored["snapshot"] = deepcopy(result.get("snapshot"))
            stored["last_validator_report_hash"] = (result.get("validator_report") or {}).get("report_hash")
            stored["updated_at"] = datetime.now(timezone.utc).isoformat()
            requests = dict(stored.get("requests") or {})
            requests[request_id] = {"request_hash": request_hash, "review_item_id": review_item_id,
                                    "decision_id": ((result.get("accepted_review_decisions") or [{}])[0]).get("decision_id")}
            stored["requests"] = requests
            stored["source_sha256"] = (stored["canonical_model"].get("source") or {}).get("source_sha256")
            stored["canonical_model_hash"] = stored["canonical_model"].get("canonical_model_hash")
            analysis = dict(project.analysis or {}); analysis[PERSISTENCE_KEY] = stored; project.analysis = analysis
            db.commit()
            view = preflight_view_model(stored["canonical_model"], result["preflight_plan"],
                                        stored.get("snapshot"), stored["review_registry"])
            return JSONResponse({"ok": True, "preflight": view,
                                 "redirect_url": f"/projects/{pid}/architecture-preflight"})
        except HTTPException:
            db.rollback(); raise
        except Exception:
            db.rollback(); raise HTTPException(500, "ARCHITECTURE_PREFLIGHT_INTERNAL_ERROR")
        finally:
            db.close()

    app.state.architecture_preflight_ui = {"persistence_key": PERSISTENCE_KEY,
                                           "view_model": preflight_view_model,
                                           "answer_labels": ANSWER_LABELS}

    def guard_design_route(path, *, json_response=False):
        old = None
        for route in list(app.router.routes):
            if getattr(route, "path", None) == path and "POST" in (getattr(route, "methods", set()) or set()):
                old = route.endpoint; app.router.routes.remove(route)
        if not old:
            return
        async def guarded(pid: int, request: Request):
            user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
            if not project:
                raise HTTPException(404)
            blocked = architecture_preflight_blocking(project); db.close()
            if blocked:
                if json_response:
                    return JSONResponse({"error": "architecture_preflight_required",
                                         "preflight_url": f"/projects/{pid}/architecture-preflight"}, status_code=409)
                return RedirectResponse(f"/projects/{pid}/architecture-preflight", 303)
            result = old(pid, request)
            if hasattr(result, "__await__"):
                result = await result
            return result
        app.add_api_route(path, guarded, methods=["POST"])

    guard_design_route("/projects/{pid}/design")
    guard_design_route("/projects/{pid}/design-json", json_response=True)
