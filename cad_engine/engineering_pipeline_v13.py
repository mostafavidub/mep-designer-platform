"""Engineering-grade mechanical design pipeline v13.

The pipeline intentionally separates architectural reconstruction from downstream
mechanical reasoning. Each stage returns explicit, testable data rather than
writing decorative CAD geometry directly.
"""
from __future__ import annotations

from collections import defaultdict
import math
import re

import ezdxf
from ezdxf import bbox


ROOM_ALIASES = {
    "bathroom": ("bath", "bathroom", "حمام"),
    "toilet": ("wc", "toilet", "سرویس", "دستشویی"),
    "kitchen": ("kitchen", "آشپزخانه"),
    "living": ("living", "پذیرایی", "نشیمن"),
    "bedroom": ("bed", "bedroom", "خواب"),
    "parking": ("parking", "پارکینگ"),
    "mechanical": ("mechanical", "موتورخانه"),
}

FIXTURE_ALIASES = {
    "wc": ("wc", "toilet", "closet", "farangi", "فرنگی", "توالت"),
    "basin": ("basin", "lavatory", "rooshooee", "روشویی", "روشويی", "lav"),
    "sink": ("sink", "kitchen sink", "سینک"),
    "shower": ("shower", "دوش", "کابین دوش", "bath"),
    "floor_drain": ("floor drain", "fd", "k کفشور", "کفشور", "کف خواب"),
}

EQUIPMENT_ALIASES = {
    "radiator": ("rad", "radiator", "رادیاتور"),
    "fan_coil": ("fancoil", "fan coil", "fcu"),
    "split_indoor": ("indoor split", "split indoor", "indoor unit"),
    "exhaust_fan": ("exh fan", "exhaust fan", "fan"),
    "hood": ("hood", "هود"),
    "pump": ("pump", "پمپ"),
    "tank": ("tank", "مخزن"),
    "water_heater": ("water heater", "boiler", "آبگرمکن"),
    "stove": ("stove", "range", "اجاق"),
}


def _norm(value):
    value = str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").lower()
    value = re.sub(r"[_./\\:-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _entity_text(entity):
    try:
        if entity.dxftype() == "TEXT":
            return str(entity.dxf.text or "")
        if entity.dxftype() == "MTEXT":
            return str(entity.plain_text() or "")
    except Exception:
        pass
    return ""


def _classify(value, mapping):
    s = _norm(value)
    if not s:
        return None
    best = None
    best_len = 0
    for kind, terms in mapping.items():
        for term in terms:
            token = _norm(term)
            if not token:
                continue
            if len(token) <= 3 and token.isascii():
                hit = re.search(rf"(?:^|\s){re.escape(token)}(?:$|\s|\d)", s)
            else:
                hit = token in s
            if hit and len(token) > best_len:
                best = kind; best_len = len(token)
    return best


def _classify_room(text):
    return _classify(text, ROOM_ALIASES)


def _point(entity):
    for attr in ("insert", "location", "start"):
        try:
            p = getattr(entity.dxf, attr)
            return float(p.x), float(p.y)
        except Exception:
            continue
    return None


def _poly_points(entity):
    try:
        if entity.dxftype() == "LWPOLYLINE":
            return [(float(x), float(y)) for x, y, *_ in entity.get_points()]
        if entity.dxftype() == "POLYLINE":
            return [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
    except Exception:
        return []
    return []


def _closed_polygon(entity):
    pts = _poly_points(entity)
    if len(pts) < 3:
        return None
    try:
        closed = bool(entity.closed)
    except Exception:
        closed = False
    if not closed and pts[0] != pts[-1]:
        return None
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts if len(pts) >= 3 else None


def _inside(point, polygon):
    x, y = point
    hit = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]; xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            hit = not hit
        j = i
    return hit


def _polygon_area(poly):
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly))) / 2.0)


def reconstruct_architecture(path):
    """Reconstruct a conservative architectural model from DXF."""
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    layer_names = {str(layer.dxf.name): _norm(layer.dxf.name) for layer in doc.layers}

    polygons, lines, inserts, texts = [], [], [], []
    for e in msp:
        layer = str(getattr(e.dxf, "layer", "0") or "0")
        kind = e.dxftype()
        if kind in {"LWPOLYLINE", "POLYLINE"}:
            poly = _closed_polygon(e)
            if poly:
                polygons.append({"layer": layer, "points": poly, "area": _polygon_area(poly)})
        elif kind == "LINE":
            try:
                lines.append({"layer": layer, "start": (float(e.dxf.start.x), float(e.dxf.start.y)), "end": (float(e.dxf.end.x), float(e.dxf.end.y))})
            except Exception:
                pass
        elif kind == "INSERT":
            p = _point(e)
            if p:
                inserts.append({"name": str(e.dxf.name or ""), "layer": layer, "point": p})
        elif kind in {"TEXT", "MTEXT"}:
            p = _point(e); value = _entity_text(e).strip()
            if p and value:
                texts.append({"text": value, "layer": layer, "point": p})

    rooms = []
    for t in texts:
        room_type = _classify_room(t["text"])
        if not room_type:
            continue
        containing = [p for p in polygons if _inside(t["point"], p["points"])]
        enclosure = min(containing, key=lambda p: p["area"]) if containing else None
        rooms.append({"id": f"ROOM-{len(rooms)+1:03d}", "type": room_type, "label": t["text"], "label_point": t["point"],
                      "polygon": enclosure["points"] if enclosure else None, "area": enclosure["area"] if enclosure else None,
                      "evidence": ["room_text"] + (["enclosing_closed_polyline"] if enclosure else [])})

    def layer_has(*tokens):
        return [name for name, normalized in layer_names.items() if any(token in normalized for token in tokens)]

    wall_layers = set(layer_has("wall", "دیوار")); door_layers = set(layer_has("door", "در "))
    shaft_layers = set(layer_has("shaft", "شفت")); column_layers = set(layer_has("column", "ستون"))
    shafts = [p for p in polygons if p["layer"] in shaft_layers]
    doors = [i for i in inserts if i["layer"] in door_layers or "door" in _norm(i["name"])]
    columns = [i for i in inserts if i["layer"] in column_layers or "column" in _norm(i["name"])]
    walls = [line for line in lines if not wall_layers or line["layer"] in wall_layers]
    # Many architectural exporters encode wall faces as closed LWPOLYLINE
    # rectangles instead of LINE entities.  Preserve their edges as explicit
    # wall evidence so routing and acceptance do not see an empty floor.
    wall_polygons = [p for p in polygons if not wall_layers or p["layer"] in wall_layers]
    if not wall_polygons and not walls:
        wall_polygons = list(polygons)
    for polygon in wall_polygons:
        pts = polygon["points"]
        for index, start in enumerate(pts):
            end = pts[(index + 1) % len(pts)]
            if start != end:
                walls.append({"layer": polygon["layer"], "start": start, "end": end,
                              "source": "closed_polyline_edge"})

    ext = bbox.extents(msp, fast=True); bounds = None
    if ext.has_data:
        bounds = [float(ext.extmin.x), float(ext.extmin.y), float(ext.extmax.x), float(ext.extmax.y)]

    return {"version": "architecture-reconstruction-v13.1", "units": int(doc.header.get("$INSUNITS", 0) or 0), "bounds": bounds,
            "rooms": rooms, "walls": walls, "doors": doors, "columns": columns,
            "shafts": [{"layer": p["layer"], "polygon": p["points"], "area": p["area"]} for p in shafts],
            "all_inserts": inserts, "all_texts": texts,
            "quality": {"room_count": len(rooms), "rooms_with_polygon": sum(1 for r in rooms if r["polygon"]),
                        "wall_segments": len(walls), "shaft_count": len(shafts)}}


def recognize_fixtures_equipment(architecture):
    """Recognize installed fixtures/equipment using block, layer and nearby-text evidence.

    A detection is assigned to a room only when its insertion point lies inside a
    reconstructed room polygon. This prevents legend blocks from becoming fake
    installed fixtures.
    """
    rows = []
    texts = architecture.get("all_texts") or []
    rooms = [r for r in architecture.get("rooms") or [] if r.get("polygon")]
    for item in architecture.get("all_inserts") or []:
        signals = []
        fixture = _classify(item.get("name"), FIXTURE_ALIASES) or _classify(item.get("layer"), FIXTURE_ALIASES)
        equipment = _classify(item.get("name"), EQUIPMENT_ALIASES) or _classify(item.get("layer"), EQUIPMENT_ALIASES)
        category = "fixture" if fixture else ("equipment" if equipment else None)
        kind = fixture or equipment
        if not category:
            # nearby explicit text can identify a generic block
            nearest = sorted(((math.dist(item["point"], t["point"]), t) for t in texts), key=lambda x: x[0])[:3]
            for distance, t in nearest:
                if distance > 1200:
                    continue
                kind = _classify(t["text"], FIXTURE_ALIASES); category = "fixture" if kind else None
                if not kind:
                    kind = _classify(t["text"], EQUIPMENT_ALIASES); category = "equipment" if kind else None
                if kind:
                    signals.append("nearby_text"); break
        if not category:
            continue
        if _classify(item.get("name"), FIXTURE_ALIASES if category == "fixture" else EQUIPMENT_ALIASES):
            signals.append("block_name")
        if _classify(item.get("layer"), FIXTURE_ALIASES if category == "fixture" else EQUIPMENT_ALIASES):
            signals.append("layer_name")
        room = next((r for r in rooms if _inside(item["point"], r["polygon"])), None)
        confidence = 0.93 if "block_name" in signals else (0.82 if "layer_name" in signals else 0.68)
        rows.append({"id": f"MEP-{len(rows)+1:03d}", "category": category, "type": kind, "point": item["point"],
                     "block": item.get("name"), "layer": item.get("layer"), "room_id": room.get("id") if room else None,
                     "confidence": confidence, "evidence": signals or ["nearby_text"]})
    # Explicit fixture labels are valid installed-object evidence when the
    # source uses exploded symbols or anonymous blocks.  Deduplicate them from
    # nearby block detections and retain room assignment for topology.
    for text in texts:
        # Room-use labels such as BATHROOM are not installed fixture labels.
        # Without this guard the short legacy alias "bath" fabricates a shower.
        if _classify_room(text.get("text")):
            continue
        kind = _classify(text.get("text"), FIXTURE_ALIASES)
        if not kind:
            continue
        point = text["point"]
        if any(row.get("type") == kind and math.dist(tuple(row["point"]), tuple(point)) < 80 for row in rows):
            continue
        room = next((r for r in rooms if _inside(point, r["polygon"])), None)
        rows.append({"id": f"MEP-{len(rows)+1:03d}", "category": "fixture",
                     "type": kind, "point": point, "block": "", "layer": text.get("layer"),
                     "room_id": room.get("id") if room else None, "confidence": 0.76,
                     "evidence": ["explicit_text"]})

    # When architectural room programs are explicit but fixture blocks are
    # exploded/anonymous, create traceable preliminary fixture endpoints from
    # the accepted room use.  These are design proposals, not claimed detections.
    inferred_by_room = {
        "kitchen": ("sink",),
        "bathroom": ("shower", "basin", "floor_drain"),
        "toilet": ("wc", "basin", "floor_drain"),
    }
    for room in rooms:
        point = room.get("label_point")
        if not point:
            continue
        for kind in inferred_by_room.get(room.get("type"), ()):
            if any(row.get("type") == kind and row.get("room_id") == room.get("id") for row in rows):
                continue
            offset = 35.0 * (1 + len([r for r in rows if r.get("room_id") == room.get("id")]))
            proposed = (float(point[0]) + offset, float(point[1]) + offset * 0.35)
            rows.append({"id": f"MEP-{len(rows)+1:03d}", "category": "fixture",
                         "type": kind, "point": proposed, "block": "", "layer": "ROOM-PROGRAM",
                         "room_id": room.get("id"), "confidence": 0.62,
                         "status": "proposed", "evidence": ["room_program_inference"]})

    return {"version": "fixture-equipment-recognition-v13.2", "detections": rows,
            "fixtures": [r for r in rows if r["category"] == "fixture"],
            "equipment": [r for r in rows if r["category"] == "equipment"],
            "quality": {"detected": len(rows), "installed_detected": sum(1 for r in rows if r.get("status") != "proposed"),
                        "proposed": sum(1 for r in rows if r.get("status") == "proposed"),
                        "room_assigned": sum(1 for r in rows if r.get("room_id"))}}
