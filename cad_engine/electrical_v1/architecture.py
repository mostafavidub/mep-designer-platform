from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import ezdxf
from ezdxf import bbox

from .models import (
    ArchitecturalEntity,
    ArchitecturalModel,
    DrawingFrame,
    EngineeringStatus,
    EvidenceValue,
    Level,
    Room,
)


FRAME_TYPES = {
    "ARCH_FLOOR_PLAN",
    "ROOF_PLAN",
    "SECTION",
    "ELEVATION",
    "DETAIL",
    "FURNITURE_PLAN",
    "STRUCTURAL_PLAN",
    "DUPLICATE",
    "UNKNOWN",
}
ELECTRICAL_ELIGIBLE = {"ARCH_FLOOR_PLAN", "ROOF_PLAN"}

ROOM_ALIASES = {
    "kitchen": ("kitchen", "آشپزخانه"),
    "bedroom": ("bedroom", "bed room", "اتاق خواب", "خواب"),
    "living": ("living", "lounge", "پذیرایی", "نشیمن", "هال"),
    "bathroom": ("bathroom", "bath", "حمام"),
    "toilet": ("toilet", "wc", "سرویس", "دستشویی"),
    "corridor": ("corridor", "hallway", "راهرو"),
    "stair": ("stair", "stairs", "راه پله", "راهپله"),
    "parking": ("parking", "پارکینگ"),
    "roof": ("roof", "بام", "پشت بام", "پشت‌بام"),
    "shaft": ("shaft", "شفت"),
    "entrance": ("entrance", "entry", "ورودی"),
    "service": ("service", "utility", "تأسیسات", "تاسیسات", "موتورخانه"),
    "common": ("common", "مشاعات", "لابی", "lobby"),
    "outdoor": ("yard", "terrace", "balcony", "حیاط", "تراس", "بالکن"),
    "commercial": ("shop", "commercial", "فروشگاه", "تجاری"),
    "office": ("office", "اداری", "دفتر"),
}

DRAWING_ALIASES = {
    "ROOF_PLAN": ("roof plan", "پلان بام", "پلان پشت بام", "پلان پشت‌بام"),
    "SECTION": ("section", "مقطع", "برش"),
    "ELEVATION": ("elevation", "نما"),
    "DETAIL": ("detail", "دیتیل", "جزئیات"),
    "FURNITURE_PLAN": ("furniture", "مبلمان", "فرنیچر"),
    "STRUCTURAL_PLAN": ("structural", "سازه", "تیرریزی", "فونداسیون"),
    "ARCH_FLOOR_PLAN": ("architectural plan", "floor plan", "پلان معماری", "پلان طبقه", "پلان همکف", "پلان تیپ"),
}

LEVEL_PATTERNS = (
    (r"(?:level|floor)\s*([+-]?\d+)", "LEVEL-{0}"),
    (r"طبقه\s*(?:شماره\s*)?([+-]?\d+)", "LEVEL-{0}"),
)


def _norm(value: Any) -> str:
    value = str(value or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    value = value.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").lower()
    value = re.sub(r"[_./\\:]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _text(entity) -> str:
    try:
        if entity.dxftype() == "TEXT":
            return str(entity.dxf.text or "")
        if entity.dxftype() == "MTEXT":
            return str(entity.plain_text() or "")
    except Exception:
        return ""
    return ""


def _point(entity) -> Optional[Tuple[float, float]]:
    for attr in ("insert", "location", "start"):
        try:
            p = getattr(entity.dxf, attr)
            return float(p.x), float(p.y)
        except Exception:
            continue
    return None


def _poly_points(entity) -> List[Tuple[float, float]]:
    try:
        if entity.dxftype() == "LWPOLYLINE":
            return [(float(x), float(y)) for x, y, *_ in entity.get_points("xy")]
        if entity.dxftype() == "POLYLINE":
            return [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
    except Exception:
        pass
    return []


def _is_closed(entity, pts) -> bool:
    try:
        if bool(entity.closed):
            return True
    except Exception:
        pass
    return len(pts) >= 3 and math.dist(pts[0], pts[-1]) < 1e-6


def _area(poly) -> float:
    if len(poly) < 3:
        return 0.0
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly))) / 2.0)


def _inside(p, poly) -> bool:
    if not poly:
        return False
    x, y = p; inside = False; j = len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _bounds(poly) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _contains_bounds(outer, point) -> bool:
    return outer[0] <= point[0] <= outer[2] and outer[1] <= point[1] <= outer[3]


def _classify_room(text: str) -> Optional[str]:
    n = _norm(text)
    hits = []
    for kind, aliases in ROOM_ALIASES.items():
        for alias in aliases:
            token = _norm(alias)
            if token and token in n:
                hits.append((len(token), kind))
    return max(hits)[1] if hits else None


def classify_drawing_title(text: str) -> Tuple[str, float]:
    n = _norm(text)
    hits = []
    for kind, aliases in DRAWING_ALIASES.items():
        for alias in aliases:
            token = _norm(alias)
            if token and token in n:
                hits.append((len(token), kind))
    if not hits:
        return "UNKNOWN", 0.2
    kind = max(hits)[1]
    return kind, 0.95 if kind in {"ROOF_PLAN", "ARCH_FLOOR_PLAN"} else 0.9


def _infer_level_name(text: str, drawing_type: str, index: int) -> EvidenceValue:
    n = _norm(text)
    if drawing_type == "ROOF_PLAN":
        return EvidenceValue.final("ROOF", "architectural_evidence", 0.95)
    if "همکف" in n or "ground" in n:
        return EvidenceValue.final("GROUND", "architectural_evidence", 0.95)
    if "زیرزمین" in n or "basement" in n:
        m = re.search(r"(?:زیرزمین|basement)\s*([0-9]+)?", n)
        suffix = m.group(1) if m and m.group(1) else "1"
        return EvidenceValue.final(f"BASEMENT-{suffix}", "architectural_evidence", 0.85)
    for pattern, fmt in LEVEL_PATTERNS:
        match = re.search(pattern, n)
        if match:
            return EvidenceValue.final(fmt.format(match.group(1)), "architectural_evidence", 0.9)
    if "تیپ" in n or "typical" in n:
        return EvidenceValue.preliminary(f"TYPICAL-{index}", "architectural_evidence", 0.65, "exact repeated level range not parsed")
    return EvidenceValue.preliminary(f"LEVEL-{index}", "architectural_evidence", 0.35, "level identity inferred from eligible frame order")


def _candidate_frames(polygons: List[Dict[str, Any]], texts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not polygons:
        return []
    areas = sorted(p["area"] for p in polygons if p["area"] > 0)
    median = areas[len(areas)//2] if areas else 0
    candidates = []
    for poly in polygons:
        x1, y1, x2, y2 = poly["bounds"]
        w, h = x2 - x1, y2 - y1
        if w <= 0 or h <= 0:
            continue
        ratio = max(w/h, h/w)
        # A frame is a large, reasonably rectangular closed polyline containing title/text evidence.
        local_text = [t for t in texts if _contains_bounds(poly["bounds"], t["point"])]
        title_hits = [(t, classify_drawing_title(t["text"])) for t in local_text]
        title_hits = [(t, c) for t, c in title_hits if c[0] != "UNKNOWN"]
        large = poly["area"] >= max(median * 4.0, 1.0)
        if (large and ratio <= 8.0 and local_text) or title_hits:
            candidates.append({**poly, "local_text": local_text, "title_hits": title_hits})
    # Remove nested candidates when a smaller candidate has the same strongest title evidence.
    candidates.sort(key=lambda x: x["area"])
    return candidates


def reconstruct_architecture(path: str | Path) -> ArchitecturalModel:
    path = str(path)
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    unit_map = {4: "mm", 5: "cm", 6: "m"}
    units = EvidenceValue.final(unit_map[insunits], "architectural_evidence", 1.0) if insunits in unit_map else EvidenceValue.input_required("DXF $INSUNITS is missing/unsupported")
    scale_to_m = {4: 0.001, 5: 0.01, 6: 1.0}.get(insunits)

    texts: List[Dict[str, Any]] = []
    polygons: List[Dict[str, Any]] = []
    entities: List[ArchitecturalEntity] = []
    wall_segments = []
    inserts = []

    for idx, entity in enumerate(msp):
        layer = str(getattr(entity.dxf, "layer", "0") or "0")
        kind = entity.dxftype()
        if kind in {"TEXT", "MTEXT"}:
            p = _point(entity); value = _text(entity).strip()
            if p and value:
                texts.append({"point": p, "text": value, "layer": layer})
        elif kind in {"LWPOLYLINE", "POLYLINE"}:
            pts = _poly_points(entity)
            if len(pts) >= 3 and _is_closed(entity, pts):
                if math.dist(pts[0], pts[-1]) < 1e-6:
                    pts = pts[:-1]
                polygons.append({"points": pts, "area": _area(pts), "bounds": _bounds(pts), "layer": layer, "index": idx})
        elif kind == "LINE":
            try:
                a = (float(entity.dxf.start.x), float(entity.dxf.start.y)); b = (float(entity.dxf.end.x), float(entity.dxf.end.y))
                wall_segments.append((idx, layer, a, b))
            except Exception:
                pass
        elif kind == "INSERT":
            p = _point(entity)
            if p:
                inserts.append((idx, layer, str(entity.dxf.name or ""), p))

    frame_candidates = _candidate_frames(polygons, texts)
    frames: List[DrawingFrame] = []
    for i, candidate in enumerate(frame_candidates, 1):
        if candidate["title_hits"]:
            title_entity, (drawing_type, conf) = max(candidate["title_hits"], key=lambda x: x[1][1])
            title = title_entity["text"]
        else:
            title = max(candidate["local_text"], key=lambda x: len(x["text"]))["text"] if candidate["local_text"] else None
            drawing_type, conf = classify_drawing_title(title or "")
        frames.append(DrawingFrame(
            id=f"FRAME-{i:03d}", classification=drawing_type, bounds=candidate["bounds"],
            title=title, confidence=conf, eligible_for_electrical=drawing_type in ELECTRICAL_ELIGIBLE,
        ))

    # If there are no geometric frames, retain title-derived virtual scopes as PRELIMINARY frames.
    if not frames:
        hits = [(t, classify_drawing_title(t["text"])) for t in texts]
        hits = [(t, c) for t, c in hits if c[0] in ELECTRICAL_ELIGIBLE]
        for i, (t, (drawing_type, conf)) in enumerate(hits, 1):
            x, y = t["point"]
            frames.append(DrawingFrame(id=f"FRAME-{i:03d}", classification=drawing_type,
                                       bounds=(x-1.0, y-1.0, x+1.0, y+1.0), title=t["text"],
                                       confidence=min(conf, 0.55), eligible_for_electrical=True))

    eligible = [f for f in frames if f.eligible_for_electrical]
    levels: List[Level] = []
    frame_to_level: Dict[str, str] = {}
    for i, frame in enumerate(eligible, 1):
        ev = _infer_level_name(frame.title or "", frame.classification, i)
        base = str(ev.value or f"LEVEL-{i}")
        level_id = f"LVL-{i:03d}"
        frame.level_id = level_id; frame_to_level[frame.id] = level_id
        levels.append(Level(id=level_id, name=ev, frame_ids=[frame.id], special_type="roof" if frame.classification == "ROOF_PLAN" else None))

    def owning_frame(point) -> Optional[DrawingFrame]:
        owners = [f for f in eligible if _contains_bounds(f.bounds, point)]
        if not owners:
            return None
        return min(owners, key=lambda f: (f.bounds[2]-f.bounds[0])*(f.bounds[3]-f.bounds[1]))

    rooms: List[Room] = []
    room_polys = [p for p in polygons if not any(p["bounds"] == f.bounds for f in frames)]
    for t in texts:
        room_type = _classify_room(t["text"])
        if not room_type:
            continue
        frame = owning_frame(t["point"])
        if not frame or not frame.level_id:
            continue
        containing = [p for p in room_polys if _inside(t["point"], p["points"])]
        enclosure = min(containing, key=lambda p: p["area"]) if containing else None
        area_ev = EvidenceValue.unknown("room polygon not detected")
        if enclosure and scale_to_m:
            area_ev = EvidenceValue.final(enclosure["area"] * scale_to_m * scale_to_m, "architectural_evidence", 0.9)
        elif enclosure:
            area_ev = EvidenceValue.input_required("DXF unit required to convert room area")
        room = Room(
            id=f"ROOM-{len(rooms)+1:03d}", level_id=frame.level_id,
            room_type=EvidenceValue.final(room_type, "architectural_evidence", 0.9),
            polygon=enclosure["points"] if enclosure else None, label_point=t["point"], label=t["text"], frame_id=frame.id,
            area_m2=area_ev,
        )
        rooms.append(room)

    for level in levels:
        level.room_ids = [r.id for r in rooms if r.level_id == level.id]

    # Preserve host primitives and opening/block evidence. Layer names are metadata, not the sole semantic authority.
    for idx, layer, a, b in wall_segments:
        frame = owning_frame(((a[0]+b[0])/2, (a[1]+b[1])/2))
        if frame:
            entities.append(ArchitecturalEntity(id=f"LINE-{idx}", kind="line_candidate", level_id=frame.level_id,
                                                geometry={"a": a, "b": b}, frame_id=frame.id, attributes={"layer": layer}))
    for idx, layer, name, p in inserts:
        frame = owning_frame(p)
        if not frame:
            continue
        n = _norm(name + " " + layer)
        kind = "insert"
        if any(x in n for x in ("door", "در ")): kind = "door"
        elif any(x in n for x in ("window", "پنجره")): kind = "window"
        elif any(x in n for x in ("stair", "پله")): kind = "stair"
        elif any(x in n for x in ("shaft", "شفت")): kind = "shaft"
        entities.append(ArchitecturalEntity(id=f"INSERT-{idx}", kind=kind, level_id=frame.level_id,
                                            geometry={"point": p}, frame_id=frame.id,
                                            attributes={"layer": layer, "block": name}))

    footprint_ev = EvidenceValue.unknown("building footprint requires a defensible enclosing architectural polygon")
    footprint_candidates = [p for p in room_polys if any(_inside(r.label_point, p["points"]) for r in rooms if r.label_point)]
    if footprint_candidates and scale_to_m:
        largest = max(footprint_candidates, key=lambda p: p["area"])
        footprint_ev = EvidenceValue.preliminary(
            {"polygon": largest["points"], "area_m2": largest["area"] * scale_to_m * scale_to_m},
            "architectural_evidence", 0.55, "largest room-containing closed polygon; requires footprint classifier confirmation",
        )

    model = ArchitecturalModel(path, units, levels, rooms, frames, entities, footprint_ev)
    if not frame_candidates:
        model.issues.append("physical_print_frames_not_detected; virtual title scopes are preliminary")
    if any(r.polygon is None for r in rooms):
        model.issues.append("some_rooms_lack_boundaries")
    return model


def assert_no_cross_frame_connection(frame_a: Optional[str], frame_b: Optional[str]) -> None:
    if frame_a and frame_b and frame_a != frame_b:
        raise ValueError(f"cross_frame_geometry_forbidden:{frame_a}->{frame_b}")
