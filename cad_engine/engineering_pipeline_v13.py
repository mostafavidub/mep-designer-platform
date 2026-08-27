"""Engineering-grade mechanical design pipeline v13.

The pipeline intentionally separates architectural reconstruction from downstream
mechanical reasoning.  Each stage returns explicit, testable data rather than
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


def _classify_room(text):
    s = _norm(text)
    if not s:
        return None
    for kind, terms in ROOM_ALIASES.items():
        if any(_norm(term) in s for term in terms):
            return kind
    return None


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
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            hit = not hit
        j = i
    return hit


def _polygon_area(poly):
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly))) / 2.0)


def reconstruct_architecture(path):
    """Reconstruct a conservative architectural model from DXF.

    The result is deliberately evidence-bearing: rooms are tied to real text and
    enclosing polygons when available; shafts/walls/doors/columns are retained
    as geometry or block evidence for routing and clash checks.
    """
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    layer_names = {str(layer.dxf.name): _norm(layer.dxf.name) for layer in doc.layers}

    polygons = []
    lines = []
    inserts = []
    texts = []
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
            p = _point(e)
            value = _entity_text(e).strip()
            if p and value:
                texts.append({"text": value, "layer": layer, "point": p})

    rooms = []
    for t in texts:
        room_type = _classify_room(t["text"])
        if not room_type:
            continue
        containing = [p for p in polygons if _inside(t["point"], p["points"])]
        enclosure = min(containing, key=lambda p: p["area"]) if containing else None
        rooms.append({
            "id": f"ROOM-{len(rooms)+1:03d}",
            "type": room_type,
            "label": t["text"],
            "label_point": t["point"],
            "polygon": enclosure["points"] if enclosure else None,
            "area": enclosure["area"] if enclosure else None,
            "evidence": ["room_text"] + (["enclosing_closed_polyline"] if enclosure else []),
        })

    def layer_has(*tokens):
        return [name for name, normalized in layer_names.items() if any(token in normalized for token in tokens)]

    wall_layers = set(layer_has("wall", "دیوار"))
    door_layers = set(layer_has("door", "در "))
    shaft_layers = set(layer_has("shaft", "شفت"))
    column_layers = set(layer_has("column", "ستون"))

    shafts = [p for p in polygons if p["layer"] in shaft_layers]
    doors = [i for i in inserts if i["layer"] in door_layers or "door" in _norm(i["name"])]
    columns = [i for i in inserts if i["layer"] in column_layers or "column" in _norm(i["name"])]
    walls = [line for line in lines if not wall_layers or line["layer"] in wall_layers]

    ext = bbox.extents(msp, fast=True)
    bounds = None
    if ext.has_data:
        bounds = [float(ext.extmin.x), float(ext.extmin.y), float(ext.extmax.x), float(ext.extmax.y)]

    return {
        "version": "architecture-reconstruction-v13.1",
        "units": int(doc.header.get("$INSUNITS", 0) or 0),
        "bounds": bounds,
        "rooms": rooms,
        "walls": walls,
        "doors": doors,
        "columns": columns,
        "shafts": [{"layer": p["layer"], "polygon": p["points"], "area": p["area"]} for p in shafts],
        "all_inserts": inserts,
        "all_texts": texts,
        "quality": {
            "room_count": len(rooms),
            "rooms_with_polygon": sum(1 for r in rooms if r["polygon"]),
            "wall_segments": len(walls),
            "shaft_count": len(shafts),
        },
    }
