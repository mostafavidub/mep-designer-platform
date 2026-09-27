"""Evidence-led, instance-aware classification of nested CAD blocks.

This module is deliberately independent from runtime wall admission.  It exists
to answer the prerequisite question: do nested blocks contain positively proven
wall assemblies?  Unknown blocks remain excluded; a block is never promoted
because its name is unfamiliar or because admitting it would close a polygon.
"""
from __future__ import annotations

from collections import Counter
import math
import re

from ezdxf import bbox as dxf_bbox
from shapely.geometry import LineString, Point, box
from shapely.strtree import STRtree


ROLES = {
    "ARCHITECTURAL_WALL_ASSEMBLY", "ARCHITECTURAL_PARTITION_ASSEMBLY",
    "DOOR_ASSEMBLY", "WINDOW_ASSEMBLY", "OPENING_ASSEMBLY",
    "STRUCTURAL_COLUMN_OR_CORE", "SANITARY_FIXTURE", "KITCHEN_CASEWORK",
    "FURNITURE", "ANNOTATION_SYMBOL", "DETAIL_GRAPHIC",
    "TEXT_GLYPH_GRAPHIC", "MIXED_ARCHITECTURAL_BLOCK", "UNKNOWN",
}


def _text(value):
    return re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", str(value or "").lower()).strip()


def _point(entity, name):
    try:
        value = getattr(entity.dxf, name)
        return (float(value.x), float(value.y))
    except Exception:
        return None


def _entity_geometry(entity):
    """Return auditable world-coordinate geometry for a virtual entity."""
    kind = entity.dxftype()
    rows = []
    if kind == "LINE":
        a, b = _point(entity, "start"), _point(entity, "end")
        if a and b and a != b:
            rows.append([a, b])
    elif kind in {"LWPOLYLINE", "POLYLINE"}:
        try:
            points = ([(float(x), float(y)) for x, y, *_ in entity.get_points()]
                      if kind == "LWPOLYLINE" else
                      [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices])
        except Exception:
            points = []
        if len(points) >= 2:
            closed = bool(getattr(entity, "closed", False)) or points[0] == points[-1]
            rows.extend([[a, b] for a, b in zip(points, points[1:] + ([points[0]] if closed else [])) if a != b])
    elif kind == "ARC":
        try:
            points = [(float(p.x), float(p.y)) for p in entity.flattening(.02)]
        except Exception:
            points = []
        if len(points) >= 2:
            rows.append(points)
    elif kind == "CIRCLE":
        center, radius = _point(entity, "center"), float(getattr(entity.dxf, "radius", 0) or 0)
        if center and radius > 0:
            rows.append([(center[0] + radius * math.cos(i * math.tau / 32),
                          center[1] + radius * math.sin(i * math.tau / 32)) for i in range(33)])
    return rows


def _bounds(geometries):
    points = [point for geometry in geometries for point in geometry]
    if not points:
        return None
    xs, ys = zip(*points)
    return [min(xs), min(ys), max(xs), max(ys)]


def _parallel_face_pairs(lines, metres_per_unit):
    scale = metres_per_unit or 1.0
    candidates = [line for line in lines if line.length * scale >= .45]
    count = 0
    for index, first in enumerate(candidates):
        a0, a1 = list(first.coords)[0], list(first.coords)[-1]
        angle_a = math.atan2(a1[1] - a0[1], a1[0] - a0[0])
        for second in candidates[index + 1:]:
            b0, b1 = list(second.coords)[0], list(second.coords)[-1]
            angle_b = math.atan2(b1[1] - b0[1], b1[0] - b0[0])
            delta = abs(math.sin(angle_a - angle_b))
            distance = first.distance(second) * scale
            if delta <= math.sin(math.radians(5)) and .05 <= distance <= .50:
                # Parallel buffers need not overlap; projected span is the useful check.
                span = min(first.length, second.length) * scale
                if span >= .45 and abs(first.length - second.length) * scale <= max(.75, span):
                    count += 1
    return count


def _connection_count(lines, accepted_lines, tolerance):
    if not lines or not accepted_lines:
        return 0
    tree = STRtree(accepted_lines)
    connected = set()
    for line in lines:
        for point in (Point(line.coords[0]), Point(line.coords[-1])):
            for candidate in tree.query(point.buffer(tolerance)):
                other = accepted_lines[int(candidate)]
                if other.distance(point) <= tolerance:
                    connected.add((round(point.x, 5), round(point.y, 5)))
                    break
    return len(connected)


def classify_instance(*, name, layer, entity_counts, bounds, line_geometries,
                      external_connections, parallel_face_pairs, frame_bounds,
                      metres_per_unit=1.0):
    """Classify from positive/negative evidence and return a fail-closed action."""
    context = _text(f"{name} {layer}")
    width = (bounds[2] - bounds[0]) * metres_per_unit if bounds else 0
    height = (bounds[3] - bounds[1]) * metres_per_unit if bounds else 0
    extent = max(width, height)
    frame_extent = max(frame_bounds[2] - frame_bounds[0], frame_bounds[3] - frame_bounds[1]) * metres_per_unit
    line_count = entity_counts.get("LINE", 0) + entity_counts.get("LWPOLYLINE", 0) + entity_counts.get("POLYLINE", 0)
    curve_count = entity_counts.get("ARC", 0) + entity_counts.get("CIRCLE", 0) + entity_counts.get("SPLINE", 0)
    total = max(1, sum(entity_counts.values()))
    evidence, negative = [], []

    semantic_rules = [
        (("door", "درب"), "DOOR_ASSEMBLY"),
        (("window", "پنجره"), "WINDOW_ASSEMBLY"),
        (("opening", "بازشو"), "OPENING_ASSEMBLY"),
        (("wc", "toilet", "sink", "lav", "bath", "shower", "روشویی", "توالت"), "SANITARY_FIXTURE"),
        (("kitchen", "cabinet", "casework", "کابینت"), "KITCHEN_CASEWORK"),
        (("table", "chair", "bed", "sofa", "furn", "tbl"), "FURNITURE"),
        (("text", "glyph", "oblique", "font"), "TEXT_GLYPH_GRAPHIC"),
    ]
    hinted_role = next((role for tokens, role in semantic_rules if any(token in context for token in tokens)), None)
    if hinted_role:
        negative.append(f"SOURCE_CONTEXT:{hinted_role}")
    if curve_count / total >= .15:
        negative.append("CURVE_DENSE_OBJECT_GEOMETRY")
    if extent < .45:
        negative.append("SMALL_ISOLATED_FOOTPRINT")
    if entity_counts.get("DIMENSION", 0) or entity_counts.get("MTEXT", 0) or entity_counts.get("HATCH", 0):
        negative.append("ANNOTATION_OR_DETAIL_CONTENT")
    if external_connections >= 2:
        evidence.append("MULTIPLE_EXTERNAL_WALL_CONNECTIONS")
    if parallel_face_pairs >= 1:
        evidence.append("LOCAL_WALL_THICKNESS_PAIRS")
    if extent >= 1.5 and extent <= frame_extent * .8:
        evidence.append("ROOM_SCALE_EXTENT")
    if line_count / total >= .85 and curve_count == 0:
        evidence.append("PREDOMINANTLY_LINEAR_GEOMETRY")
    if line_geometries and sum(line.length for line in line_geometries) * metres_per_unit >= 3:
        evidence.append("MATERIAL_LENGTH")

    strong_wall = ("MULTIPLE_EXTERNAL_WALL_CONNECTIONS" in evidence and
                   "LOCAL_WALL_THICKNESS_PAIRS" in evidence and
                   "ROOM_SCALE_EXTENT" in evidence and
                   "PREDOMINANTLY_LINEAR_GEOMETRY" in evidence and
                   not negative)
    if strong_wall:
        role, action = "ARCHITECTURAL_PARTITION_ASSEMBLY", "ADMIT_WALL_CHILDREN"
        status = "PROVEN"
    elif hinted_role:
        role, action, status = hinted_role, "EXCLUDE_FROM_WALL_PIPELINE", "SUPPORTED_NON_WALL"
    elif "ANNOTATION_OR_DETAIL_CONTENT" in negative:
        role, action, status = "DETAIL_GRAPHIC", "EXCLUDE_FROM_WALL_PIPELINE", "SUPPORTED_NON_WALL"
    elif curve_count and extent <= 1.5:
        role, action, status = "FURNITURE", "EXCLUDE_FROM_WALL_PIPELINE", "SUPPORTED_NON_WALL"
    else:
        role, action, status = "UNKNOWN", "KEEP_EXCLUDED_UNRESOLVED", "UNRESOLVED"
    assert role in ROLES
    return {"role": role, "action": action, "status": status,
            "positive_evidence": evidence, "negative_evidence": negative,
            "features": {"width_m": width, "height_m": height, "extent_m": extent,
                         "external_connections": external_connections,
                         "parallel_face_pairs": parallel_face_pairs,
                         "line_count": line_count, "curve_count": curve_count}}


def inventory_instances(doc, *, frames, accepted_lines_by_frame=None, metres_per_unit=1.0):
    """Inventory every transformed INSERT instance intersecting selected frames."""
    accepted_lines_by_frame = accepted_lines_by_frame or {}
    rows = []

    negative_roles = {"DOOR_ASSEMBLY", "WINDOW_ASSEMBLY", "OPENING_ASSEMBLY",
                      "SANITARY_FIXTURE", "KITCHEN_CASEWORK", "FURNITURE",
                      "ANNOTATION_SYMBOL", "DETAIL_GRAPHIC", "TEXT_GLYPH_GRAPHIC"}

    def visit(insert, parent_handle=None, path=(), depth=0, inherited_roles=None):
        if depth > 12:
            return
        handle = str(getattr(insert.dxf, "handle", "") or "VIRTUAL")
        name = str(getattr(insert.dxf, "name", "") or "")
        layer = str(getattr(insert.dxf, "layer", "0") or "0")
        try:
            definition = doc.blocks.get(name)
            definition_id = str(definition.block_record_handle or name)
            definition_handles = sorted(str(entity.dxf.handle or "") for entity in definition if entity.dxf.handle)
        except Exception:
            definition_id, definition_handles = name, []
        try:
            children = list(insert.virtual_entities())
        except Exception:
            children = []
        try:
            transform_matrix = [float(value) for value in insert.matrix44()]
        except Exception:
            transform_matrix = []
        geometries, linear_geometries, counts, source_handles = [], [], Counter(), []
        nested = []
        for child in children:
            counts[child.dxftype()] += 1
            source_handles.append(str(getattr(child.dxf, "handle", "") or ""))
            child_geometry = _entity_geometry(child)
            geometries.extend(child_geometry)
            if child.dxftype() in {"LINE", "LWPOLYLINE", "POLYLINE"}:
                linear_geometries.extend(child_geometry)
            if child.dxftype() == "INSERT":
                nested.append(child)
        # Use ezdxf's entity-aware cache for instance extents.  Reconstructing
        # bulged-polyline or non-uniformly transformed ARC extents from virtual
        # start/end angles can create kilometre-wide false boxes.
        try:
            extents = dxf_bbox.extents(children, fast=True)
            bounds = ([float(extents.extmin.x), float(extents.extmin.y),
                       float(extents.extmax.x), float(extents.extmax.y)]
                      if extents.has_data else None)
        except Exception:
            bounds = _bounds(linear_geometries or geometries)
        decisions_by_frame = {}
        if bounds:
            local_lines = [LineString(geometry) for geometry in linear_geometries if len(geometry) >= 2]
            for frame in frames:
                frame_bounds = frame["bounds"]
                if not box(*bounds).intersects(box(*frame_bounds)):
                    continue
                accepted = accepted_lines_by_frame.get(frame["frame_id"], [])
                tolerance = max(.015 / (metres_per_unit or 1.0), 1e-6)
                connections = _connection_count(local_lines, accepted, tolerance)
                pairs = _parallel_face_pairs(local_lines, metres_per_unit)
                decision = classify_instance(
                    name=name, layer=layer, entity_counts=counts, bounds=bounds,
                    line_geometries=local_lines, external_connections=connections,
                    parallel_face_pairs=pairs, frame_bounds=frame_bounds,
                    metres_per_unit=metres_per_unit)
                inherited_role = (inherited_roles or {}).get(frame["frame_id"])
                if inherited_role in negative_roles and decision["action"] == "ADMIT_WALL_CHILDREN":
                    decision = {**decision, "role": "UNKNOWN", "action": "KEEP_EXCLUDED_UNRESOLVED",
                                "status": "UNRESOLVED",
                                "negative_evidence": [*decision["negative_evidence"],
                                                      f"PARENT_NEGATIVE_ROLE:{inherited_role}"]}
                decisions_by_frame[frame["frame_id"]] = decision["role"]
                rows.append({"frame_id": frame["frame_id"], "definition_name": name,
                             "definition_id": definition_id, "instance_handle": handle,
                             "parent_instance_handle": parent_handle,
                             "instance_path": [*path, handle], "depth": depth,
                             "insert": list(_point(insert, "insert") or ()),
                             "rotation": float(getattr(insert.dxf, "rotation", 0) or 0),
                             "scale": [float(getattr(insert.dxf, key, 1) or 1) for key in ("xscale", "yscale", "zscale")],
                             "transform_matrix": transform_matrix,
                             "layer": layer, "bounds": bounds,
                             "entity_counts": dict(sorted(counts.items())),
                             "total_linear_length_m": sum(line.length for line in local_lines) * (metres_per_unit or 1.0),
                             "definition_child_handles": definition_handles,
                             "source_child_handles": sorted(set(filter(None, source_handles))),
                             "world_geometries": geometries, **decision})
        for child in nested:
            visit(child, handle, (*path, handle), depth + 1, decisions_by_frame)

    for insert in doc.modelspace().query("INSERT"):
        visit(insert)
    return rows


def definition_summary(instances):
    grouped = {}
    for row in instances:
        key = (row["frame_id"], row["definition_id"])
        summary = grouped.setdefault(key, {"frame_id": row["frame_id"],
                                           "definition_id": row["definition_id"],
                                           "definition_name": row["definition_name"],
                                           "instance_count": 0, "roles": Counter(),
                                           "actions": Counter(), "entity_counts": Counter(),
                                           "total_linear_length_m": 0.0,
                                           "positive_evidence": Counter(), "negative_evidence": Counter(),
                                           "instance_handles": []})
        summary["instance_count"] += 1
        summary["roles"][row["role"]] += 1
        summary["actions"][row["action"]] += 1
        summary["entity_counts"].update(row["entity_counts"])
        summary["total_linear_length_m"] += row["total_linear_length_m"]
        summary["positive_evidence"].update(row["positive_evidence"])
        summary["negative_evidence"].update(row["negative_evidence"])
        summary["instance_handles"].append(row["instance_handle"])
    output = []
    for summary in grouped.values():
        summary["roles"] = dict(sorted(summary["roles"].items()))
        summary["actions"] = dict(sorted(summary["actions"].items()))
        summary["entity_counts"] = dict(sorted(summary["entity_counts"].items()))
        summary["total_linear_length_m"] = round(summary["total_linear_length_m"], 6)
        summary["positive_evidence"] = dict(sorted(summary["positive_evidence"].items()))
        summary["negative_evidence"] = dict(sorted(summary["negative_evidence"].items()))
        summary["instance_handles"] = sorted(summary["instance_handles"])
        output.append(summary)
    return sorted(output, key=lambda row: (row["frame_id"], row["definition_name"], row["instance_handles"]))
