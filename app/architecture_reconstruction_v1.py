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
from .dxf_input import read_input_dxf
from cad_engine.architectural_space_engine import reconstruct_architecture as reconstruct_canonical_architecture

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
    # Specific blocks win over generic layer names.
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
        canonical = reconstruct_canonical_architecture(path)
        result["canonical_architecture_model"] = canonical
        result["architecture_recognition_preview_svg"] = canonical.get("recognition_preview_svg")
        result["architecture_completeness"] = canonical.get("completeness")
    except Exception as exc:
        result["canonical_architecture_model"] = {
            "schema": "canonical-architectural-model/1.0", "physical_spaces": [],
            "completeness": {"status": "INPUT_REQUIRED", "release_allowed": False,
                             "downstream_engineering_allowed": False,
                             "issues": [{"code": "CANONICAL_RECONSTRUCTION_FAILED", "detail": type(exc).__name__}]},
        }
    try:
        doc, _recovery = read_input_dxf(path)
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


def enrich_auto(auto, analysis):
    auto = dict(auto or {})
    profiles = auto.get("level_profiles") or []
    all_rooms = []
    all_primitives = []
    canonical_models = []
    for f in (analysis or {}).get("files") or []:
        all_rooms.extend(f.get("architecture_rooms") or [])
        all_primitives.extend(f.get("architecture_primitives") or [])
        if f.get("canonical_architecture_model"):
            canonical_models.append(f["canonical_architecture_model"])

    # Assign semantic room labels to their closest canonical level title, then
    # derive a spatial envelope from those labels. The envelope prevents an
    # adjacent floor drawn elsewhere in modelspace from stealing walls/doors.
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
        # Partition reconstructed primitives by the same nearest-title rule as
        # rooms.  A room-label envelope can collapse to a few centimetres when
        # a level has only one label and would then discard its doors, walls and
        # shafts.  Nearest-title partitioning preserves the whole plan while
        # still preventing adjacent model-space plans from stealing entities.
        assigned_primitives = []
        for primitive in all_primitives:
            p = tuple(primitive.get("centroid") or [])
            if len(p) != 2:
                continue
            if other_titles and min(math.dist(p, t) for t in other_titles) < math.dist(p, title):
                continue
            assigned_primitives.append(primitive)
        spatial_points = [tuple(r["label_point"]) for r in assigned_rooms]
        for primitive in assigned_primitives:
            b = primitive.get("bounds") or []
            if len(b) == 4:
                spatial_points.extend(((b[0], b[1]), (b[2], b[3])))
        region = _expanded_bounds(spatial_points, pad_ratio=0.02)
        if region is None:
            # Roofs may have no room labels; use a bounded vicinity around title
            # rather than inventing a building polygon.
            region = [title[0]-1, title[1]-1, title[0]+1, title[1]+1]
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
    if canonical_models:
        physical_spaces = [space for model in canonical_models for space in model.get("physical_spaces") or []]
        functional_zones = [zone for model in canonical_models for zone in model.get("functional_zones") or []]
        issues = [issue for model in canonical_models for issue in (model.get("completeness") or {}).get("issues") or []]
        status = "CONFLICT" if any(i.get("status") == "CONFLICT" for i in issues) else ("INPUT_REQUIRED" if issues else "VERIFIED")
        canonical_levels = []
        for profile in level_rows:
            canonical_levels.append({**profile, "physical_space_ids": [s["physical_space_id"] for s in physical_spaces
                                                                        if s.get("level_id") in {None, profile.get("name")} ]})
        auto["architecture_model"] = {
            "schema": "canonical-architectural-model/1.0", "version": "canonical-architectural-model/1.0",
            "levels": canonical_levels, "level_count": len(canonical_levels), "physical_spaces": physical_spaces,
            "functional_zones": functional_zones,
            "architectural_objects": [obj for model in canonical_models for obj in model.get("architectural_objects") or []],
            "dimensions": [dim for model in canonical_models for dim in model.get("dimensions") or []],
            "frames": [frame for model in canonical_models for frame in model.get("frames") or []],
            "completeness": {"status": status, "release_allowed": status == "VERIFIED",
                             "downstream_engineering_allowed": status == "VERIFIED", "issues": issues},
            "source_models": [{"source": model.get("source"), "diagnostics": model.get("diagnostics")} for model in canonical_models],
            "recognition_previews": [model.get("recognition_preview_svg") for model in canonical_models if model.get("recognition_preview_svg")],
            # Migration projection for existing topology consumers.
            "room_count": len(physical_spaces), "primitive_count": sum(len(model.get("walls") or []) for model in canonical_models),
        }
        auto["architecture_completeness"] = auto["architecture_model"]["completeness"]
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
