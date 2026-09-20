"""Audited user confirmation of architectural spaces and shafts.

The review is a hard gate between CAD inference and engineering design. User
clicks select immutable CAD snap-node IDs; free coordinates are never trusted.
Every mutation is append-only, hash-chained, and bound to the architecture
artifact hash so a later upload invalidates previous approvals.
"""
from __future__ import annotations

from datetime import datetime, timezone
import heapq
import hashlib
import hmac
import json
import os
import re
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from shapely.geometry import Point, Polygon


SPACE_TYPES = {
    "LIVING": "پذیرایی", "LOUNGE": "نشیمن", "KITCHEN": "آشپزخانه",
    "BEDROOM": "اتاق خواب", "MASTER_BEDROOM": "اتاق خواب مستر",
    "BATHROOM": "حمام", "TOILET": "سرویس بهداشتی",
    "BATH_TOILET": "حمام و سرویس مشترک", "DRESSING": "رختکن",
    "CORRIDOR": "راهرو", "ENTRANCE": "ورودی", "STAIR": "راه‌پله",
    "ELEVATOR": "آسانسور", "PARKING": "پارکینگ", "STORAGE": "انباری",
    "BALCONY": "تراس یا بالکن", "MECHANICAL": "فضای تأسیسات",
    "LAUNDRY": "لاندری", "OFFICE": "اداری", "SHOP": "تجاری",
    "COMMON": "مشاع", "SHAFT": "شفت تأسیسات", "OPEN_PLAN": "فضای باز",
    "OTHER": "سایر",
}
RELATIONSHIPS = {
    "INDEPENDENT", "OPEN_PLAN_SHARED", "OPEN_PLAN_SEPARATE_CALC",
    "MASTER_BEDROOM", "MASTER_BATH", "MASTER_TOILET", "MASTER_DRESSING",
}
TYPE_MAP = {
    "living": "LIVING", "kitchen": "KITCHEN", "bedroom": "BEDROOM",
    "bath": "BATHROOM", "bathroom": "BATHROOM", "toilet": "TOILET",
    "stair": "STAIR", "parking": "PARKING", "mechanical": "MECHANICAL",
    "shaft": "SHAFT",
}


def _utcnow():
    return datetime.now(timezone.utc)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def architecture_source_hash(legacy, project_id):
    root = legacy.DATA_DIR / "projects" / str(project_id)
    candidates = [root / "architecture.dxf", root / "architecture.zip"]
    path = next((candidate for candidate in candidates if candidate.exists()), None)
    return _hash_file(path) if path else "SOURCE_NOT_LOCAL"


def _space_id(level_index, kind, label_point, ordinal):
    material = f"{level_index}|{kind}|{label_point}|{ordinal}"
    return "SPACE-" + hashlib.sha256(material.encode()).hexdigest()[:16].upper()


def _review_state(legacy, project):
    analysis = dict(project.analysis or {})
    existing = dict(analysis.get("architecture_review") or {})
    source_hash = architecture_source_hash(legacy, project.id)
    if existing.get("source_hash") == source_hash and existing.get("spaces"):
        return existing
    model = ((analysis.get("architectural_auto") or {}).get("architecture_model") or {})
    spaces = []
    levels = []
    for level_index, level in enumerate(model.get("levels") or []):
        level_id = f"LEVEL-{level_index + 1:02d}"
        levels.append({
            "id": level_id, "name": level.get("name") or level_id,
            "frame": (level.get("canonical_frame") or {}).get("bounds"),
            "snap_points": ((level.get("review_geometry") or {}).get("snap_points") or []),
            "wall_segments": ((level.get("review_geometry") or {}).get("wall_segments") or []),
        })
        rows = list(level.get("rooms") or []) + [dict(row, type="shaft") for row in level.get("shafts") or []]
        for ordinal, row in enumerate(rows):
            kind = str(row.get("type") or row.get("kind") or "other")
            point = row.get("label_point") or row.get("centroid") or []
            confidence = row.get("polygon_confidence") or row.get("geometry_confidence") or "label_only"
            confirmed = bool(row.get("polygon") and confidence == "high")
            spaces.append({
                "id": _space_id(level_index, kind, point, ordinal),
                "level_id": level_id, "source_kind": kind,
                "space_type": TYPE_MAP.get(kind, "OTHER"),
                "display_name": row.get("label") or SPACE_TYPES.get(TYPE_MAP.get(kind, "OTHER")),
                "label_point": point, "polygon": row.get("polygon"),
                "bounds": row.get("bounds"), "confidence": confidence,
                "status": "AUTO_CONFIRMED" if confirmed else "REVIEW_REQUIRED",
                "provenance": row.get("provenance") or ("INFERRED" if row.get("polygon") else "LABEL_ONLY"),
                "relationship": "INDEPENDENT", "group_id": None,
                "warnings_acknowledged": [], "updated_at": None,
            })
    state = {
        "schema": "architecture-review/1", "source_hash": source_hash,
        "revision": 1,
        "status": "REVIEW_REQUIRED", "levels": levels, "spaces": spaces,
        "instructions_version": "architecture-review-guidance/1",
        "created_at": _utcnow().isoformat(), "confirmed_at": None,
    }
    state["status"] = _state_status(state)
    return state


def _state_status(state):
    levels_ready = all(level.get("frame") for level in state.get("levels") or [])
    spaces_ready = bool(state.get("spaces")) and all(
        row.get("status") in {"AUTO_CONFIRMED", "USER_CONFIRMED", "EXCLUDED_BY_USER"}
        for row in state.get("spaces") or []
    )
    return "READY_TO_CONFIRM" if levels_ready and spaces_ready else "REVIEW_REQUIRED"


def _event(db, Event, project, actor_id, action, before, after, metadata=None):
    previous = db.query(Event).filter(Event.project_id == project.id).order_by(Event.id.desc()).first()
    previous_hash = previous.event_hash if previous else "GENESIS"
    payload = {
        "project_id": project.id, "actor_id": actor_id, "action": action,
        "before": before, "after": after, "metadata": metadata or {},
        "previous_hash": previous_hash, "created_at": _utcnow().isoformat(),
    }
    event_hash = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    row = Event(project_id=project.id, user_id=actor_id, action=action,
                payload=payload, previous_hash=previous_hash, event_hash=event_hash,
                created_at=_utcnow())
    db.add(row)
    return row


def _nodes_for_level(state, level_id):
    level = next((row for row in state.get("levels") or [] if row.get("id") == level_id), None)
    if not level:
        raise HTTPException(422, "طبقه انتخاب‌شده معتبر نیست.")
    return level, {row["id"]: (float(row["x"]), float(row["y"])) for row in level.get("snap_points") or []}


def _shortest_wall_path(level, nodes, start, end, blocked_edge=None):
    graph = {node_id: [] for node_id in nodes}
    for segment in level.get("wall_segments") or []:
        a, b = segment.get("a_id"), segment.get("b_id")
        if a not in nodes or b not in nodes or {a, b} == set(blocked_edge or []):
            continue
        distance = ((nodes[a][0] - nodes[b][0]) ** 2 + (nodes[a][1] - nodes[b][1]) ** 2) ** .5
        graph[a].append((distance, b)); graph[b].append((distance, a))
    queue = [(0.0, start, (start,))]; best = {}
    while queue:
        distance, current, path = heapq.heappop(queue)
        if current == end:
            return distance, list(path)
        if distance >= best.get(current, float("inf")):
            continue
        best[current] = distance
        for weight, nxt in graph.get(current, []):
            if nxt not in path:
                heapq.heappush(queue, (distance + weight, nxt, path + (nxt,)))
    return None, []


def _resolve_boundary(level, nodes, anchors, relationship):
    resolved = []
    ambiguity = []
    pairs = list(zip(anchors, anchors[1:] + anchors[:1]))
    for start, end in pairs:
        distance, path = _shortest_wall_path(level, nodes, start, end)
        if not path:
            if relationship in {"OPEN_PLAN_SHARED", "OPEN_PLAN_SEPARATE_CALC"}:
                path = [start, end]
            else:
                raise HTTPException(422, "دو نقطه انتخابی روی یک مسیر پیوسته دیوار قرار ندارند. یک گوشه میانی معتبر انتخاب کنید.")
        # Detect a materially equivalent alternate route.  In that case the
        # user must add an intermediate anchor rather than letting the engine
        # silently choose the wrong side of a room.
        if len(path) == 2:
            alt_distance, alt_path = _shortest_wall_path(level, nodes, start, end, (start, end))
            if alt_path and alt_distance <= distance * 1.05:
                ambiguity.append((start, end))
        resolved.extend(path[:-1])
    if ambiguity:
        raise HTTPException(422, "بین بعضی گوشه‌ها دو مسیر دیوار هم‌ارزش وجود دارد. یک نقطه میانی روی مسیر درست اضافه کنید.")
    return resolved


def _validate_space(state, existing, payload):
    if state.get("source_hash") == "SOURCE_NOT_LOCAL":
        raise HTTPException(409, "فایل معماری هنوز از فضای ذخیره‌سازی بازیابی نشده است؛ ثبت مرز جدید مجاز نیست.")
    space_type = str(payload.get("space_type") or "").upper()
    if space_type not in SPACE_TYPES:
        raise HTTPException(422, "نوع استاندارد فضا باید از فهرست انتخاب شود.")
    relationship = str(payload.get("relationship") or "INDEPENDENT").upper()
    if relationship not in RELATIONSHIPS:
        raise HTTPException(422, "نوع ارتباط فضا معتبر نیست.")
    group_id = str(payload.get("group_id") or "").strip() or None
    if relationship.startswith("MASTER_") and not group_id:
        raise HTTPException(422, "برای اجزای مستر باید یک شناسه مجموعه مستر انتخاب شود.")
    required_types = {
        "MASTER_BEDROOM": {"MASTER_BEDROOM"}, "MASTER_BATH": {"BATHROOM", "BATH_TOILET"},
        "MASTER_TOILET": {"TOILET", "BATH_TOILET"}, "MASTER_DRESSING": {"DRESSING"},
    }
    if relationship in required_types and space_type not in required_types[relationship]:
        raise HTTPException(422, "نوع فضا با نقش انتخاب‌شده در مجموعه مستر سازگار نیست.")
    node_ids = list(dict.fromkeys(payload.get("node_ids") or []))
    if len(node_ids) < 3:
        raise HTTPException(422, "حداقل سه گوشه معتبر انتخاب کنید.")
    level_id = str(payload.get("level_id") or existing.get("level_id") or "")
    level, nodes = _nodes_for_level(state, level_id)
    if any(node_id not in nodes for node_id in node_ids):
        raise HTTPException(422, "یک یا چند نقطه متعلق به نقاط Snap معتبر این پلان نیست.")
    resolved_node_ids = _resolve_boundary(level, nodes, node_ids, relationship)
    points = [nodes[node_id] for node_id in resolved_node_ids]
    polygon = Polygon(points)
    if not polygon.is_valid or polygon.area <= 1e-8:
        raise HTTPException(422, "مرز بسته معتبر نیست یا خودش را قطع می‌کند.")
    frame = level.get("frame")
    if frame and not Polygon([(frame[0], frame[1]), (frame[2], frame[1]),
                              (frame[2], frame[3]), (frame[0], frame[3])]).buffer(1e-7).contains(polygon):
        raise HTTPException(422, "مرز از قاب پلان این طبقه خارج شده است.")
    label = existing.get("label_point") or []
    if len(label) == 2 and not polygon.buffer(1e-7).contains(Point(label)):
        raise HTTPException(422, "مرز انتخابی نوشته یا نقطه تشخیص این فضا را در بر نمی‌گیرد.")
    for other in state.get("spaces") or []:
        if other.get("id") == existing.get("id") or other.get("status") == "EXCLUDED_BY_USER":
            continue
        other_points = other.get("polygon") or []
        if len(other_points) < 3 or other.get("level_id") != level_id:
            continue
        other_polygon = Polygon(other_points)
        overlap = polygon.intersection(other_polygon).area
        if overlap > min(polygon.area, other_polygon.area) * .02 and relationship not in {"OPEN_PLAN_SHARED", "OPEN_PLAN_SEPARATE_CALC"}:
            raise HTTPException(422, f"مرز با فضای «{other.get('display_name') or other.get('space_type')}» هم‌پوشانی دارد.")
    # Wet rooms in a master suite remain separate physical spaces. A parent
    # bedroom polygon may not swallow their label points.
    swallowed = []
    for other in state.get("spaces") or []:
        if other.get("id") == existing.get("id"):
            continue
        other_point = other.get("label_point") or []
        if len(other_point) == 2 and polygon.contains(Point(other_point)):
            swallowed.append(other)
    if space_type == "MASTER_BEDROOM" and any(row.get("space_type") in {"BATHROOM", "TOILET", "BATH_TOILET"} for row in swallowed):
        raise HTTPException(422, "حمام و سرویس مستر باید مرز مستقل داشته باشند و فقط با شناسه مجموعه مستر مرتبط شوند.")
    if swallowed and relationship not in {"OPEN_PLAN_SHARED", "OPEN_PLAN_SEPARATE_CALC"}:
        names = "، ".join(row.get("display_name") or row.get("space_type") for row in swallowed[:4])
        raise HTTPException(422, f"این مرز فضای مستقل دیگری ({names}) را هم در بر می‌گیرد. مرزها را جدا ثبت کنید.")
    return {
        **existing, "level_id": level_id, "space_type": space_type,
        "display_name": str(payload.get("display_name") or SPACE_TYPES[space_type]).strip()[:160],
        "polygon": [[round(x, 6), round(y, 6)] for x, y in points],
        "bounds": [round(v, 6) for v in polygon.bounds],
        "area_drawing_units2": round(float(polygon.area), 6),
        "confidence": "user_confirmed", "status": "USER_CONFIRMED",
        "provenance": "USER_CONFIRMED", "relationship": relationship,
        "group_id": group_id, "selected_node_ids": node_ids,
        "resolved_node_ids": resolved_node_ids,
        "boundary_resolution": "WALL_GRAPH_SHORTEST_PATH_WITH_AUTO_CLOSE",
        "warnings_acknowledged": list(payload.get("warnings_acknowledged") or []),
        "updated_at": _utcnow().isoformat(),
    }


def _require_revision(state, payload):
    try:
        supplied = int(payload.get("review_revision"))
    except (TypeError, ValueError):
        raise HTTPException(409, "نسخه بازبینی نامعتبر است؛ صفحه را تازه‌سازی کنید.")
    if supplied != int(state.get("revision") or 1):
        raise HTTPException(409, "این پروژه هم‌زمان در صفحه دیگری تغییر کرده است؛ برای جلوگیری از بازنویسی، صفحه را تازه‌سازی کنید.")


def _require_mutable(state):
    if state.get("status") == "CONFIRMED":
        raise HTTPException(409, "مدل معماری قفل شده است. برای اصلاح مبنا، فایل معماری اصلاح‌شده را دوباره بارگذاری کنید تا تأیید قبلی باطل و سابقه حفظ شود.")


def _sync_model(analysis, state):
    auto = dict(analysis.get("architectural_auto") or {})
    model = dict(auto.get("architecture_model") or {})
    by_level = {row["id"]: row for row in state.get("levels") or []}
    for index, level in enumerate(model.get("levels") or []):
        level_id = f"LEVEL-{index + 1:02d}"
        reviewed = [row for row in state.get("spaces") or [] if row.get("level_id") == level_id]
        level["canonical_frame"] = {**(level.get("canonical_frame") or {}),
                                    "bounds": by_level.get(level_id, {}).get("frame")}
        rooms = []
        shafts = []
        for row in reviewed:
            if row.get("status") == "EXCLUDED_BY_USER":
                continue
            target = {
                "id": row["id"], "type": row["source_kind"], "label": row["display_name"],
                "label_point": row.get("label_point"), "polygon": row.get("polygon"),
                "bounds": row.get("bounds"), "polygon_confidence": row.get("confidence"),
                "provenance": row.get("provenance"), "space_type": row.get("space_type"),
                "relationship": row.get("relationship"), "group_id": row.get("group_id"),
            }
            (shafts if row.get("space_type") == "SHAFT" else rooms).append(target)
        level["rooms"] = rooms; level["shafts"] = shafts
    model["status"] = "PASS" if state.get("status") == "CONFIRMED" else "INPUT_REQUIRED"
    if model["status"] == "PASS":
        model["missing_inputs"] = [key for key in model.get("missing_inputs") or []
                                   if key not in {"CANONICAL_PLAN_FRAME", "ROOM_BOUNDARY_GEOMETRY", "SHAFT_BOUNDARY_GEOMETRY"}]
        if model["missing_inputs"]:
            model["status"] = "INPUT_REQUIRED"
    auto["architecture_model"] = model; analysis["architectural_auto"] = auto
    analysis["architecture_review"] = state
    return analysis


def review_complete(project):
    review = ((project.analysis or {}).get("architecture_review") or {})
    return review.get("status") == "CONFIRMED"


def _final_integrity(state):
    groups = {}
    for row in state.get("spaces") or []:
        if row.get("status") == "EXCLUDED_BY_USER":
            continue
        if row.get("relationship", "").startswith("MASTER_"):
            groups.setdefault(row.get("group_id"), set()).add(row.get("relationship"))
    incomplete = [group for group, roles in groups.items() if "MASTER_BEDROOM" not in roles]
    if incomplete:
        raise HTTPException(422, "هر مجموعه مستر باید یک فضای «اتاق خواب مستر» داشته باشد: " + "، ".join(incomplete))


def _verify_chain(events):
    previous = "GENESIS"
    for row in sorted(events, key=lambda item: item.id):
        calculated = hashlib.sha256(_canonical(row.payload or {}).encode()).hexdigest()
        if row.previous_hash != previous or row.event_hash != calculated:
            return False
        previous = row.event_hash
    return True


def _require_admin(request):
    expected = os.getenv("PANEL_BRIDGE_TOKEN", "")
    supplied = request.headers.get("x-panel-token", "")
    if expected and supplied and hmac.compare_digest(expected, supplied):
        return
    forwarded = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip().lower()
    host = (forwarded or request.headers.get("host", "")).split(":", 1)[0]
    allowed = {value.strip().lower() for value in os.getenv("ADMIN_REVIEW_HOSTS", "admin.planha.com").split(",") if value.strip()}
    if host not in allowed:
        raise HTTPException(403, "دسترسی به سوابق پشتیبانی فقط از پنل ادمین مجاز است.")


def install(app, legacy):
    class ArchitectureReviewEvent(legacy.Base):
        __tablename__ = "architecture_review_events"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
        user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
        action: Mapped[str] = mapped_column(String(80))
        payload: Mapped[dict] = mapped_column(JSON)
        previous_hash: Mapped[str] = mapped_column(String(64))
        event_hash: Mapped[str] = mapped_column(String(64), unique=True)
        created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    from .schema_management import create_table_during_registration
    create_table_during_registration(ArchitectureReviewEvent.__table__, legacy.engine)

    original_analyze = legacy.analyze_project_job
    def analyze_project_job(project_id):
        original_analyze(project_id)
        with legacy.Session() as db:
            project = db.get(legacy.Project, project_id)
            if not project:
                return
            model = (((project.analysis or {}).get("architectural_auto") or {}).get("architecture_model") or {})
            if model.get("status") != "INPUT_REQUIRED":
                return
            state = _review_state(legacy, project)
            before = (project.analysis or {}).get("architecture_review")
            analysis = dict(project.analysis or {}); analysis["architecture_review"] = state
            project.analysis = analysis; project.status = "architecture_review"
            _event(db, ArchitectureReviewEvent, project, project.user_id,
                   "REVIEW_CREATED", before, {"status": state["status"], "source_hash": state["source_hash"]})
            db.commit()
    legacy.analyze_project_job = analyze_project_job

    @app.get("/projects/{pid}/architecture-review")
    def customer_review(pid: int, request: Request):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project: raise HTTPException(404)
        state = _review_state(legacy, project)
        if (project.analysis or {}).get("architecture_review") != state:
            previous = (project.analysis or {}).get("architecture_review") or {}
            analysis = dict(project.analysis or {}); analysis["architecture_review"] = state
            project.analysis = analysis
            if previous.get("source_hash") and previous.get("source_hash") != state.get("source_hash"):
                _event(db, ArchitectureReviewEvent, project, user.id, "APPROVAL_INVALIDATED_BY_SOURCE_CHANGE",
                       {"source_hash": previous.get("source_hash"), "status": previous.get("status")},
                       {"source_hash": state.get("source_hash"), "status": state.get("status")})
            db.commit()
        events = db.query(ArchitectureReviewEvent).filter_by(project_id=pid).order_by(ArchitectureReviewEvent.id.desc()).limit(100).all()
        response = legacy.templates.TemplateResponse("architecture_review.html", {
            "request": request, "p": project, "review": state,
            "space_types": SPACE_TYPES, "events": events, "admin_view": False,
        })
        db.close(); return response

    @app.post("/projects/{pid}/architecture-review/spaces/{space_id}")
    async def save_space(pid: int, space_id: str, request: Request):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project: raise HTTPException(404)
        state = _review_state(legacy, project); payload = await request.json()
        _require_mutable(state)
        _require_revision(state, payload)
        spaces = state.get("spaces") or []
        existing = next((row for row in spaces if row.get("id") == space_id), None)
        if space_id == "NEW":
            existing = {"id": "SPACE-USER-" + hashlib.sha256(f"{pid}|{_utcnow().isoformat()}".encode()).hexdigest()[:12].upper(),
                        "level_id": payload.get("level_id"), "source_kind": "user_defined",
                        "label_point": [], "status": "REVIEW_REQUIRED"}
            spaces.append(existing)
        if not existing: db.close(); raise HTTPException(404)
        before = dict(existing); updated = _validate_space(state, existing, payload)
        spaces[spaces.index(existing)] = updated; state["spaces"] = spaces
        state["revision"] = int(state.get("revision") or 1) + 1
        state["status"] = _state_status(state)
        analysis = _sync_model(dict(project.analysis or {}), state); project.analysis = analysis
        _event(db, ArchitectureReviewEvent, project, user.id, "SPACE_CONFIRMED", before, updated,
               {"ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent", "")[:300]})
        db.commit(); db.close()
        return JSONResponse({"ok": True, "space": updated, "review_status": state["status"], "revision": state["revision"]})

    @app.post("/projects/{pid}/architecture-review/spaces/{space_id}/exclude")
    async def exclude_space(pid: int, space_id: str, request: Request):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project: raise HTTPException(404)
        state = _review_state(legacy, project); payload = await request.json()
        _require_mutable(state)
        _require_revision(state, payload)
        reason = str(payload.get("reason") or "").strip()
        if len(reason) < 10:
            db.close(); raise HTTPException(422, "دلیل حذف تشخیص باید حداقل ۱۰ نویسه و قابل استناد باشد.")
        spaces = state.get("spaces") or []
        existing = next((row for row in spaces if row.get("id") == space_id), None)
        if not existing: db.close(); raise HTTPException(404)
        before = dict(existing); updated = {**existing, "status": "EXCLUDED_BY_USER",
            "exclusion_reason": reason[:500], "provenance": "USER_CONFIRMED",
            "updated_at": _utcnow().isoformat()}
        spaces[spaces.index(existing)] = updated; state["spaces"] = spaces
        state["revision"] = int(state.get("revision") or 1) + 1; state["status"] = _state_status(state)
        project.analysis = _sync_model(dict(project.analysis or {}), state)
        _event(db, ArchitectureReviewEvent, project, user.id, "SPACE_EXCLUDED", before, updated,
               {"ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent", "")[:300]})
        db.commit(); db.close()
        return JSONResponse({"ok": True, "space": updated, "review_status": state["status"], "revision": state["revision"]})

    @app.post("/projects/{pid}/architecture-review/confirm")
    async def confirm_review(pid: int, request: Request):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project: raise HTTPException(404)
        state = _review_state(legacy, project)
        if state.get("source_hash") == "SOURCE_NOT_LOCAL":
            db.close(); raise HTTPException(409, "فایل معماری برای تطبیق هش در دسترس نیست.")
        if _state_status(state) != "READY_TO_CONFIRM":
            db.close(); raise HTTPException(409, "همه قاب‌ها و فضاهای نیازمند بررسی هنوز تعیین تکلیف نشده‌اند.")
        _final_integrity(state)
        payload = await request.json()
        _require_revision(state, payload)
        required = {"reviewed_plan", "separate_wet_rooms", "understands_responsibility"}
        acknowledgements = set(payload.get("acknowledgements") or [])
        if not required.issubset(acknowledgements):
            db.close(); raise HTTPException(422, "سه تأیید نهایی باید خوانده و انتخاب شوند.")
        before = {"status": state.get("status")}; state["status"] = "CONFIRMED"
        state["confirmed_at"] = _utcnow().isoformat(); state["confirmed_by"] = user.id
        state["revision"] = int(state.get("revision") or 1) + 1
        state["acknowledgements"] = sorted(acknowledgements)
        project.analysis = _sync_model(dict(project.analysis or {}), state)
        project.status = "asking" if (project.current_question or 0) < len(project.questions or []) else "ready_to_design"
        if project.status == "ready_to_design" and str((project.answers or {}).get("discipline") or "") == "mechanical":
            from . import mechanical_workflow
            mechanical_workflow._advance_mechanical(project)
        _event(db, ArchitectureReviewEvent, project, user.id, "REVIEW_CONFIRMED", before,
               {"status": "CONFIRMED", "source_hash": state["source_hash"]},
               {"ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent", "")[:300]})
        db.commit(); next_url = f"/projects/{pid}"; db.close()
        return JSONResponse({"ok": True, "next_url": next_url})

    @app.get("/admin/projects/{pid}/architecture-review")
    def admin_review(pid: int, request: Request):
        _require_admin(request)
        db = legacy.Session(); project = db.get(legacy.Project, pid)
        if not project: db.close(); raise HTTPException(404)
        state = _review_state(legacy, project)
        events = db.query(ArchitectureReviewEvent).filter_by(project_id=pid).order_by(ArchitectureReviewEvent.id.desc()).all()
        response = legacy.templates.TemplateResponse("architecture_review.html", {
            "request": request, "p": project, "review": state,
            "space_types": SPACE_TYPES, "events": events, "admin_view": True,
            "chain_valid": _verify_chain(events),
        })
        db.close(); return response

    @app.get("/admin/architecture-reviews")
    def admin_review_index(request: Request):
        _require_admin(request)
        db = legacy.Session()
        rows = db.query(ArchitectureReviewEvent).order_by(ArchitectureReviewEvent.id.desc()).limit(1000).all()
        project_ids = list(dict.fromkeys(row.project_id for row in rows))
        projects = {row.id: row for row in db.query(legacy.Project).filter(legacy.Project.id.in_(project_ids)).all()} if project_ids else {}
        response = legacy.templates.TemplateResponse("architecture_review_admin.html", {
            "request": request, "events": rows, "projects": projects,
        })
        db.close(); return response

    app.state.architecture_review = {
        "Event": ArchitectureReviewEvent, "review_complete": review_complete,
        "space_types": SPACE_TYPES,
    }
