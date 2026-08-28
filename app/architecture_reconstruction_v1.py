"""Architecture Reconstruction v1.

Builds a structured architectural model from the source DXF instead of reducing
it to plan titles and room counts. The reconstruction is deliberately
conservative: semantic layers/block names provide classification, while room
polygons are only accepted when a closed polyline actually contains the room
label point.
"""
from collections import Counter
import math
import re

import ezdxf
from ezdxf import bbox

from . import auto_inference as base_inference

RECONSTRUCTION_VERSION = "architecture-reconstruction-v1"

LAYER_HINTS = {
    "wall": ("wall", "دیوار", "ديوار"),
    "door": ("door", "در وپنجره", "در وپنچره", "در"),
    "window": ("window", "win", "پنجره"),
    "column": ("column", "columns", "ستون"),
    "stair": ("stair", "stairs", "peleh", "پله", "راه پله", "راهپله"),
    "shaft": ("shaft", "شفت"),
    "furniture": ("furniture", "furn", "fur", "cabinet", "مبلمان", "کابینت"),
}

BLOCK_HINTS = {
    "door": ("door", "doоr", "d90", "d120", "d140"),
    "window": ("window", "win", "پنجره"),
    "column": ("column", "columns", "ستون"),
    "stair": ("stair", "peleh", "پله"),
    "shaft": ("shaft", "شفت"),
}


def _norm(value):
    value = str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").lower()
    value = re.sub(r"[_./\\:-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _matches(value, terms):
    s = _norm(value)
    return bool(s) and any(_norm(t) in s for t in terms)


def _classify(layer="", block=""):
    for kind, terms in BLOCK_HINTS.items():
        if block and _matches(block, terms):
            return kind
    for kind, terms in LAYER_HINTS.items():
        if layer and _matches(layer, terms):
            return kind
    return None


def _point(entity):
    try:
        p = entity.dxf.insert
        return float(p.x), float(p.y)
    except Exception:
        return None


def _entity_points(entity):
    try:
        typ = entity.dxftype()
        if typ == "LINE":
            a, b = entity.dxf.start, entity.dxf.end
            return [(float(a.x), float(a.y)), (float(b.x), float(b.y))]
        if typ == "LWPOLYLINE":
            return [(float(x), float(y)) for x, y, *_ in entity.get_points("xy")]
        if typ == "POLYLINE":
            return [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
        if typ in {"ARC", "CIRCLE"}:
            c = entity.dxf.center
            r = float(entity.dxf.radius)
            return [(float(c.x-r), float(c.y-r)), (float(c.x+r), float(c.y+r))]
        if typ == "INSERT":
            ext = bbox.extents(list(entity.virtual_entities()), fast=True)
            if ext.has_data:
                return [(float(ext.extmin.x), float(ext.extmin.y)), (float(ext.extmax.x), float(ext.extmax.y))]
            p = _point(entity)
            return [p] if p else []
    except Exception:
        return []
    return []


def _bounds(points):
    if not points:
        return None
    xs = [p[0] for p in points]; ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _centroid(bounds):
    if not bounds:
        return None
    return [(bounds[0]+bounds[2])/2.0, (bounds[1]+bounds[3])/2.0]


def _poly_area(points):
    if len(points) < 3:
        return 0.0
    return abs(sum(points[i][0]*points[(i+1)%len(points)][1] - points[(i+1)%len(points)][0]*points[i][1] for i in range(len(points))) / 2.0)


def _contains(poly, point):
    x, y = point; inside = False
    n = len(poly)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]; xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and x < (xj-xi)*(y-yi)/((yj-yi) or 1e-12)+xi:
            inside = not inside
        j = i
    return inside


def _text_value(entity):
    try:
        if entity.dxftype() == "TEXT":
            return str(entity.dxf.text or "").strip()
        if entity.dxftype() == "MTEXT":
            return str(entity.plain_text() or "").strip()
    except Exception:
        pass
    return ""


def reconstruct_dxf(path, base_result=None):
    result = dict(base_result or {})
    try:
        doc = ezdxf.readfile(path)
    except Exception as exc:
        result["architecture_reconstruction_version"] = RECONSTRUCTION_VERSION
        result["architecture_reconstruction_diagnostics"] = [f"read_failed:{type(exc).__name__}"]
        return result

    msp = doc.modelspace()
    primitives = []
    closed_polygons = []
    layer_counts = Counter()

    for entity in msp:
        typ = entity.dxftype()
        layer = str(getattr(entity.dxf, "layer", "") or "")
        block = str(getattr(entity.dxf, "name", "") or "") if typ == "INSERT" else ""
        kind = _classify(layer, block)
        pts = _entity_points(entity)
        b = _bounds(pts)
        if kind and b:
            row = {
                "kind": kind, "entity_type": typ, "layer": layer, "block": block or None,
                "bounds": [round(v, 6) for v in b], "centroid": [round(v, 6) for v in _centroid(b)],
            }
            primitives.append(row); layer_counts[kind] += 1
        if typ in {"LWPOLYLINE", "POLYLINE"} and len(pts) >= 3:
            closed = bool(getattr(entity, "closed", False) or getattr(entity, "is_closed", False))
            if closed:
                area = _poly_area(pts)
                if area > 0:
                    closed_polygons.append({"points": pts, "bounds": b, "area": area, "layer": layer})

    rooms = []
    for item in result.get("text_labels") or []:
        room_type = base_inference.classify_room(item.get("text") or "")
        if not room_type:
            continue
        try:
            p = (float(item["x"]), float(item["y"]))
        except Exception:
            continue
        containing = [poly for poly in closed_polygons if _contains(poly["points"], p)]
        polygon = min(containing, key=lambda x: x["area"]) if containing else None
        rooms.append({
            "type": room_type,
            "label": str(item.get("text") or ""),
            "label_point": [round(p[0], 6), round(p[1], 6)],
            "source_type": item.get("source_type"), "source_name": item.get("source_name"),
            "polygon": [[round(x, 6), round(y, 6)] for x, y in polygon["points"]] if polygon else None,
            "bounds": [round(v, 6) for v in polygon["bounds"]] if polygon else None,
            "area_drawing_units2": round(polygon["area"], 4) if polygon else None,
            "polygon_confidence": "high" if polygon else "label_only",
        })

    result["architecture_reconstruction_version"] = RECONSTRUCTION_VERSION
    result["architecture_primitives"] = primitives[:50000]
    result["architecture_primitive_counts"] = dict(layer_counts)
    result["architecture_rooms"] = rooms[:10000]
    result["architecture_reconstruction_diagnostics"] = []
    return result


def _inside(bounds, point):
    return bool(bounds and point and bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3])


def _expanded_bounds(points, pad_ratio=0.22):
    if not points:
        return None
    b = _bounds(points)
    w = max(b[2]-b[0], 1.0); h = max(b[3]-b[1], 1.0)
    px, py = w*pad_ratio, h*pad_ratio
    return [b[0]-px, b[1]-py, b[2]+px, b[3]+py]


def _room_geometry_points(rooms):
    points = []
    for room in rooms:
        polygon = room.get("polygon") or []
        if polygon:
            points.extend((float(p[0]), float(p[1])) for p in polygon if len(p) >= 2)
            continue
        bounds = room.get("bounds")
        if bounds and len(bounds) == 4:
            points.extend(((bounds[0], bounds[1]), (bounds[2], bounds[3])))
            continue
        label = room.get("label_point")
        if label and len(label) == 2:
            points.append((float(label[0]), float(label[1])))
    return points


def enrich_auto(auto, analysis):
    auto = dict(auto or {})
    profiles = auto.get("level_profiles") or []
    all_rooms = []
    all_primitives = []
    for f in (analysis or {}).get("files") or []:
        all_rooms.extend(f.get("architecture_rooms") or [])
        all_primitives.extend(f.get("architecture_primitives") or [])

    level_rows = []
    for profile in profiles:
        title = profile.get("title_point")
        if not title:
            continue
        title = tuple(float(v) for v in title)
        other_titles = [tuple(float(v) for v in p.get("title_point")) for p in profiles if p is not profile and p.get("title_point")]
        assigned_rooms = []
        for room in all_rooms:
            p = tuple(room.get("label_point") or [])
            if len(p) != 2:
                continue
            if other_titles and min(math.dist(p, t) for t in other_titles) < math.dist(p, title):
                continue
            assigned_rooms.append(room)
        geometry_points = _room_geometry_points(assigned_rooms)
        region = _expanded_bounds(geometry_points)
        if region is None:
            region = [title[0]-1, title[1]-1, title[0]+1, title[1]+1]
        assigned_primitives = [p for p in all_primitives if _inside(region, p.get("centroid"))]
        by_kind = {k: [p for p in assigned_primitives if p.get("kind") == k] for k in LAYER_HINTS}
        level_rows.append({
            "name": profile.get("name"), "roof": bool(profile.get("roof")),
            "title_point": list(title), "region_bounds": [round(v, 6) for v in region],
            "rooms": assigned_rooms,
            "walls": by_kind["wall"], "doors": by_kind["door"], "windows": by_kind["window"],
            "columns": by_kind["column"], "stairs": by_kind["stair"], "shafts": by_kind["shaft"],
            "fixed_furniture": by_kind["furniture"],
            "counts": {k: len(v) for k, v in by_kind.items()},
        })

    auto["architecture_model"] = {
        "version": RECONSTRUCTION_VERSION,
        "levels": level_rows,
        "level_count": len(level_rows),
        "room_count": sum(len(x["rooms"]) for x in level_rows),
        "primitive_count": sum(sum(x["counts"].values()) for x in level_rows),
    }
    return auto


def install(main_auto_module):
    if getattr(main_auto_module, "_architecture_reconstruction_v1_installed", False):
        return
    base_analyzer = main_auto_module.analyze_dxf_enhanced
    base_infer = main_auto_module.infer_architecture_facts

    def analyze(path):
        return reconstruct_dxf(path, base_analyzer(path))

    def infer(analysis, discipline):
        return enrich_auto(base_infer(analysis, discipline), analysis)

    main_auto_module.analyze_dxf_enhanced = analyze
    main_auto_module.infer_architecture_facts = infer
    main_auto_module.legacy.analyze_dxf = analyze
    main_auto_module._architecture_reconstruction_v1_installed = True
