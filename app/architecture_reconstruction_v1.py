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
    reconstruction_diagnostics = []
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

    semantic_labels = []
    for item in result.get("text_labels") or []:
        room_type = base_inference.classify_room(item.get("text") or "")
        if not room_type:
            continue
        try:
            p = (float(item["x"]), float(item["y"]))
        except Exception:
            continue
        semantic_labels.append((item, room_type, p))

    # A print border, apartment outline or other large closed polyline often
    # encloses several labels.  Treating it as every enclosed room's polygon
    # fabricates room geometry.  A polygon is authoritative for a room only
    # when it encloses exactly one semantic space/shaft label.
    polygon_label_counts = {
        id(poly): sum(1 for _item, _kind, point in semantic_labels if _contains(poly["points"], point))
        for poly in closed_polygons
    }
    rooms = []
    for item, room_type, p in semantic_labels:
        containing = [poly for poly in closed_polygons if _contains(poly["points"], p)]
        exclusive = [poly for poly in containing if polygon_label_counts.get(id(poly)) == 1]
        polygon = min(exclusive, key=lambda x: x["area"]) if exclusive else None
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

    try:
        from cad_engine.plan_segmentation import analyze_plan_frames
        frame_analysis = analyze_plan_frames(path)
        result["architecture_plan_frames"] = [
            {
                "bounds": [round(float(v), 6) for v in row.get("bounds") or []],
                "drawing_type": row.get("drawing_type"),
                "level": row.get("level"),
                "represented_levels": list(row.get("represented_levels") or []),
                "confidence": row.get("confidence"),
                "handle": row.get("handle"),
                "title_text": list(row.get("title_text") or []),
            }
            for row in frame_analysis.get("candidates") or []
            if len(row.get("bounds") or []) == 4
        ]
    except Exception as exc:
        result["architecture_plan_frames"] = []
        reconstruction_diagnostics.append(
            f"plan_frame_analysis_failed:{type(exc).__name__}"
        )

    result["architecture_reconstruction_version"] = RECONSTRUCTION_VERSION
    result["architecture_primitives"] = primitives[:50000]
    result["architecture_primitive_counts"] = dict(layer_counts)
    result["architecture_rooms"] = rooms[:10000]
    result["architecture_reconstruction_diagnostics"] = reconstruction_diagnostics
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


def _bounds_overlap(a, b, tolerance=0.0):
    return not (a[2] < b[0]-tolerance or b[2] < a[0]-tolerance or
                a[3] < b[1]-tolerance or b[3] < a[1]-tolerance)


def _merge_symbol_components(items, kind, tolerance=0.015):
    """Collapse line/arc fragments that describe one semantic CAD symbol."""
    pending = [dict(item) for item in items]
    merged = []
    while pending:
        component = [pending.pop(0)]
        changed = True
        while changed:
            changed = False
            component_bounds = _bounds([p for row in component for p in (
                (row["bounds"][0], row["bounds"][1]), (row["bounds"][2], row["bounds"][3])
            )])
            for row in list(pending):
                if row.get("layer") == component[0].get("layer") and _bounds_overlap(
                    component_bounds, row.get("bounds") or [0, 0, 0, 0], tolerance
                ):
                    pending.remove(row); component.append(row); changed = True
        points = [p for row in component for p in (
            (row["bounds"][0], row["bounds"][1]), (row["bounds"][2], row["bounds"][3])
        )]
        bounds = _bounds(points)
        merged.append({
            "kind": kind,
            "entity_type": "COMPOSITE" if len(component) > 1 else component[0].get("entity_type"),
            "layer": component[0].get("layer"),
            "block": component[0].get("block"),
            "bounds": [round(v, 6) for v in bounds],
            "centroid": [round(v, 6) for v in _centroid(bounds)],
            "source_entity_count": len(component),
            "geometry_confidence": "semantic_layer_component",
        })
    return merged


def _matching_plan_frame(profile, frames):
    title = profile.get("title_point")
    if not title or len(title) != 2:
        return None
    matches = [row for row in frames if row.get("drawing_type") in {"ARCH_FLOOR_PLAN", "ROOF_PLAN"}
               and _inside(row.get("bounds"), title)]
    return matches[0] if len(matches) == 1 else None


def enrich_auto(auto, analysis):
    auto = dict(auto or {})
    profiles = auto.get("level_profiles") or []
    all_rooms = []
    all_primitives = []
    all_frames = []
    for f in (analysis or {}).get("files") or []:
        all_rooms.extend(f.get("architecture_rooms") or [])
        all_primitives.extend(f.get("architecture_primitives") or [])
        all_frames.extend(f.get("architecture_plan_frames") or [])

    # Assign semantic room labels to their closest canonical level title, then
    # derive a spatial envelope from those labels. The envelope prevents an
    # adjacent floor drawn elsewhere in modelspace from stealing walls/doors.
    level_rows = []
    for profile in profiles:
        title = profile.get("title_point")
        if not title:
            continue
        title = tuple(float(v) for v in title)
        canonical_frame = _matching_plan_frame(profile, all_frames)
        canonical_bounds = canonical_frame.get("bounds") if canonical_frame else None
        other_titles = [tuple(float(v) for v in p.get("title_point")) for p in profiles if p is not profile and p.get("title_point")]
        assigned_rooms = []
        for room in all_rooms:
            p = tuple(room.get("label_point") or [])
            if len(p) != 2:
                continue
            if canonical_bounds and not _inside(canonical_bounds, p):
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
            if canonical_bounds and not _inside(canonical_bounds, p):
                continue
            if other_titles and min(math.dist(p, t) for t in other_titles) < math.dist(p, title):
                continue
            assigned_primitives.append(primitive)
        spatial_points = [tuple(r["label_point"]) for r in assigned_rooms]
        for primitive in assigned_primitives:
            b = primitive.get("bounds") or []
            if len(b) == 4:
                spatial_points.extend(((b[0], b[1]), (b[2], b[3])))
        region = list(canonical_bounds) if canonical_bounds else _expanded_bounds(spatial_points, pad_ratio=0.02)
        if region is None:
            # Roofs may have no room labels; use a bounded vicinity around title
            # rather than inventing a building polygon.
            region = [title[0]-1, title[1]-1, title[0]+1, title[1]+1]
        by_kind = {k: [p for p in assigned_primitives if p.get("kind") == k] for k in LAYER_HINTS}
        for symbol_kind in ("door", "window", "column", "stair", "shaft"):
            by_kind[symbol_kind] = _merge_symbol_components(by_kind[symbol_kind], symbol_kind)

        # Shaft text is valid evidence of a shaft location even when the
        # architect did not draw the shaft on a semantic layer.  Keep the
        # geometry explicitly label-only instead of inventing a shaft box.
        shaft_labels = [room for room in assigned_rooms if room.get("type") == "shaft"]
        assigned_rooms = [room for room in assigned_rooms if room.get("type") != "shaft"]
        for shaft in shaft_labels:
            point = list(shaft.get("label_point") or [0.0, 0.0])
            by_kind["shaft"].append({
                "kind": "shaft", "entity_type": "TEXT_EVIDENCE", "layer": None, "block": None,
                "bounds": shaft.get("bounds"), "centroid": _centroid(shaft.get("bounds")) or point,
                "label": shaft.get("label"), "label_point": point,
                "geometry_confidence": "high" if shaft.get("bounds") else "label_only",
                "provenance": "architectural_shaft_label",
            })
        level_rows.append({
            "name": profile.get("name"), "roof": bool(profile.get("roof")),
            "title_point": list(title), "region_bounds": [round(v, 6) for v in region],
            "canonical_frame": canonical_frame,
            "rooms": assigned_rooms,
            "walls": by_kind["wall"], "doors": by_kind["door"], "windows": by_kind["window"],
            "columns": by_kind["column"], "stairs": by_kind["stair"], "shafts": by_kind["shaft"],
            "fixed_furniture": by_kind["furniture"],
            "counts": {k: len(v) for k, v in by_kind.items()},
        })

    room_count = sum(len(x["rooms"]) for x in level_rows)
    rooms_with_polygon = sum(
        1 for level in level_rows for room in level["rooms"] if room.get("polygon")
    )
    shafts = [shaft for level in level_rows for shaft in level["shafts"]]
    shafts_with_geometry = sum(
        1 for shaft in shafts if shaft.get("geometry_confidence") != "label_only"
    )
    missing_inputs = []
    if any(level.get("canonical_frame") is None for level in level_rows):
        missing_inputs.append("CANONICAL_PLAN_FRAME")
    if room_count and rooms_with_polygon != room_count:
        missing_inputs.append("ROOM_BOUNDARY_GEOMETRY")
    if shafts and shafts_with_geometry != len(shafts):
        missing_inputs.append("SHAFT_BOUNDARY_GEOMETRY")
    auto["architecture_model"] = {
        "version": RECONSTRUCTION_VERSION,
        "levels": level_rows,
        "level_count": len(level_rows),
        "room_count": room_count,
        "primitive_count": sum(sum(x["counts"].values()) for x in level_rows),
        "status": "INPUT_REQUIRED" if missing_inputs else "PASS",
        "missing_inputs": missing_inputs,
        "quality": {
            "canonical_frame_count": sum(bool(x.get("canonical_frame")) for x in level_rows),
            "room_count": room_count,
            "rooms_with_valid_polygon": rooms_with_polygon,
            "shaft_count": len(shafts),
            "shafts_with_valid_geometry": shafts_with_geometry,
            "fabricated_geometry_count": 0,
        },
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
