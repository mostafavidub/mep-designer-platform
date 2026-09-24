"""Semantic, source-preserving dimension engine for Planha drawing output.

This module intentionally separates:
1) source dimension evidence;
2) semantic dimension intent;
3) view/profile visibility;
4) CAD materialization; and
5) exact-file QA.

Source dimensions are never silently destroyed. A dimension may be regenerated,
suppressed in a view, retained only as evidence, or blocked as a conflict.
Reference drawings are calibration evidence only; they never provide hidden
numeric engineering defaults.
"""
from __future__ import annotations

from collections import Counter
import math
import re
from pathlib import Path
from typing import Iterable

import ezdxf
from ezdxf import bbox
from app.drawing_unit_sanity import infer_drawing_unit_scale


SOURCE_LAYER = "PLANHA-A-DIM-SOURCE"
SETOUT_LAYER = "PLANHA-M-DIM-SETOUT"
CHECK_LAYER = "PLANHA-M-DIM-CHECK"
DIMSTYLE = "PLANHA-DIM"
APPID = "PLANHA_DIMENSION"

CRITICAL_SOURCE_TYPES = {
    "PROPERTY", "SETBACK", "BUILDING_OVERALL", "GRID", "STRUCTURAL_SET_OUT",
    "SHAFT", "STAIR_CORE", "CODE_CLEARANCE",
}
SOURCE_VISIBLE_BY_PROFILE = {
    "ARCHITECTURAL_PLAN": {
        "PROPERTY", "SETBACK", "BUILDING_OVERALL", "GRID", "STRUCTURAL_SET_OUT",
        "WALL_SETOUT", "SHAFT", "STAIR_CORE", "CODE_CLEARANCE", "OPENING",
    },
    "MECHANICAL_PLAN": {
        "BUILDING_OVERALL", "GRID", "STRUCTURAL_SET_OUT", "SHAFT",
        "STAIR_CORE", "CODE_CLEARANCE",
    },
    "ROOF_PLAN": {"BUILDING_OVERALL", "GRID", "SHAFT", "STAIR_CORE"},
    "PARKING_PLAN": {
        "BUILDING_OVERALL", "GRID", "STRUCTURAL_SET_OUT", "SHAFT",
        "STAIR_CORE", "CODE_CLEARANCE",
    },
    "DETAIL": set(),
}


def _norm(value):
    return (
        str(value or "")
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("\u200c", " ")
        .strip()
        .lower()
    )


def _xy(value):
    try:
        return (float(value.x), float(value.y))
    except Exception:
        try:
            return (float(value[0]), float(value[1]))
        except Exception:
            return None


def _inside(point, bounds, tol=0.0):
    if not point or not bounds:
        return False
    x, y = point
    return (
        float(bounds[0]) - tol <= x <= float(bounds[2]) + tol
        and float(bounds[1]) - tol <= y <= float(bounds[3]) + tol
    )


def _point_segment_distance(point, a, b):
    px, py = point
    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    den = vx * vx + vy * vy
    if den <= 1e-18:
        return math.dist(point, a), a
    t = ((px - ax) * vx + (py - ay) * vy) / den
    t = max(0.0, min(1.0, t))
    q = (ax + t * vx, ay + t * vy)
    return math.dist(point, q), q


def _line_angle(a, b):
    return math.atan2(float(b[1]) - float(a[1]), float(b[0]) - float(a[0]))


def _axis_delta(angle_a, angle_b):
    """Smallest difference between two undirected axes."""
    diff = abs((angle_a - angle_b) % math.pi)
    return min(diff, math.pi - diff)


def _simple_numeric_override(text):
    value = str(text or "").strip()
    if not value or value == "<>" or "<>" in value:
        return None
    value = value.replace(",", ".").replace("٫", ".")
    if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _override_status(measured, displayed_text):
    """Classify source text without promoting it to engineering truth.

    The 1% threshold is an anomaly heuristic derived from drafting behavior, not
    a code tolerance. The exact geometry remains authoritative for calculation.
    """
    text=str(displayed_text or "").strip()
    if not text or text=="<>" or "<>" in text:
        return "EXACT"
    numeric=_simple_numeric_override(text)
    if numeric is None:
        return "NON_NUMERIC_OVERRIDE"
    measured=abs(float(measured or 0.0))
    if measured<=1e-12:
        return "CONFLICT"
    delta=abs(float(numeric)-measured)
    return "MINOR_OVERRIDE" if delta<=max(measured*.03,1e-6) else "CONFLICT"


def _display_number(value):
    if value is None:
        return ""
    value = float(value)
    # Planha presentation convention only: formatting never changes the
    # engineering measurement. This is not inferred from the reference corpus.
    if abs(value) >= 100 and abs(value - round(value)) < 1e-7:
        return str(int(round(value)))
    return f"{value:.2f}"


def _dimension_geometry(entity):
    p1 = _xy(getattr(entity.dxf, "defpoint2", None))
    p2 = _xy(getattr(entity.dxf, "defpoint3", None))
    base = _xy(getattr(entity.dxf, "defpoint", None))
    if not p1 or not p2:
        try:
            ex = bbox.extents([entity], fast=True)
            if ex.has_data:
                p1 = p1 or (float(ex.extmin.x), float(ex.extmin.y))
                p2 = p2 or (float(ex.extmax.x), float(ex.extmax.y))
        except Exception:
            pass
    return p1, p2, base


def _reference(kind, ref_id, a, b, priority, **extra):
    return {
        "id": ref_id,
        "kind": kind,
        "a": (float(a[0]), float(a[1])),
        "b": (float(b[0]), float(b[1])),
        "priority": int(priority),
        **extra,
    }


def _poly_edges(points):
    pts = [tuple(map(float, p[:2])) for p in points or []]
    if len(pts) < 2:
        return []
    edges = list(zip(pts, pts[1:]))
    if len(pts) >= 3 and pts[0] != pts[-1]:
        edges.append((pts[-1], pts[0]))
    return edges


def _semantic_item_edges(item):
    """Return only geometry explicitly carried by an upstream semantic item."""
    if not isinstance(item, dict):
        return []
    start=tuple(item.get("start") or ())
    end=tuple(item.get("end") or ())
    if len(start)==2 and len(end)==2 and start!=end:
        return [(tuple(map(float,start)),tuple(map(float,end)))]
    points=item.get("polygon") or item.get("points")
    edges=_poly_edges(points)
    if edges:
        return edges
    bounds=item.get("bounds")
    if isinstance(bounds,(list,tuple)) and len(bounds)==4:
        x1,y1,x2,y2=map(float,bounds)
        if x2>x1 and y2>y1:
            return [
                ((x1,y1),(x2,y1)),((x2,y1),(x2,y2)),
                ((x2,y2),(x1,y2)),((x1,y2),(x1,y1)),
            ]
    return []


def build_reference_catalog(doc, plan_bounds, architecture=None, plan_id=None):
    """Build stable datums without trusting consultant layer names as authority."""
    architecture = architecture or {}
    refs = []
    x1, y1, x2, y2 = map(float, plan_bounds)
    refs.extend([
        _reference("PLAN_EDGE", "PLAN-LEFT", (x1, y1), (x1, y2), 40, side="LEFT"),
        _reference("PLAN_EDGE", "PLAN-RIGHT", (x2, y1), (x2, y2), 40, side="RIGHT"),
        _reference("PLAN_EDGE", "PLAN-BOTTOM", (x1, y1), (x2, y1), 40, side="BOTTOM"),
        _reference("PLAN_EDGE", "PLAN-TOP", (x1, y2), (x2, y2), 40, side="TOP"),
    ])

    valid_walls=[]
    for index, wall in enumerate(architecture.get("walls") or []):
        if plan_id and wall.get("plan_id") not in (None, plan_id):
            continue
        a = tuple(wall.get("start") or ())
        b = tuple(wall.get("end") or ())
        if len(a) != 2 or len(b) != 2:
            continue
        if not (_inside(a, plan_bounds, 0.5) or _inside(b, plan_bounds, 0.5)):
            continue
        valid_walls.append((index,wall,tuple(map(float,a)),tuple(map(float,b))))
    wall_points=[p for _,_,a,b in valid_walls for p in (a,b)]
    wall_extents=None
    if wall_points:
        xs=[p[0] for p in wall_points];ys=[p[1] for p in wall_points]
        wall_extents=(min(xs),min(ys),max(xs),max(ys))
    for index,wall,a,b in valid_walls:
        explicit_exterior=bool(wall.get("exterior") is True or wall.get("is_exterior") is True)
        envelope_side=None
        inferred_envelope=False
        if wall_extents:
            wx1,wy1,wx2,wy2=wall_extents
            tol=max(max(wx2-wx1,wy2-wy1)*.012,1e-6)
            vertical=abs(a[0]-b[0])<=max(abs(a[1]-b[1])*.02,1e-9)
            horizontal=abs(a[1]-b[1])<=max(abs(a[0]-b[0])*.02,1e-9)
            if vertical:
                if abs(a[0]-wx1)<=tol:
                    envelope_side="LEFT"
                elif abs(a[0]-wx2)<=tol:
                    envelope_side="RIGHT"
            elif horizontal:
                if abs(a[1]-wy1)<=tol:
                    envelope_side="BOTTOM"
                elif abs(a[1]-wy2)<=tol:
                    envelope_side="TOP"
            inferred_envelope=envelope_side is not None
        refs.append(_reference(
            "WALL_FACE",f"WALL-{index:04d}",a,b,20,
            envelope_candidate=bool(explicit_exterior or inferred_envelope),
            envelope_side=envelope_side,
            envelope_evidence=("explicit_exterior" if explicit_exterior else ("wall_extents" if inferred_envelope else None)),
            wall_id=str(wall.get("id") or f"WALL-{index:04d}"),
            source="semantic_geometry",
        ))

    for prefix, kind, collection, priority in (
        ("SHAFT", "SHAFT_FACE", architecture.get("shafts") or [], 10),
        ("COLUMN", "STRUCTURAL_FACE", architecture.get("columns") or [], 10),
        ("GRID", "GRID_AXIS", architecture.get("grids") or [], 0),
        ("PROPERTY", "PROPERTY_BOUNDARY", architecture.get("property_boundaries") or [], 5),
        ("STAIR", "STAIR_CORE_FACE", architecture.get("stairs") or [], 12),
        ("OPENING", "OPENING_JAMB", architecture.get("openings") or [], 15),
        ("DOOR", "OPENING_JAMB", architecture.get("doors") or [], 16),
        ("WINDOW", "OPENING_JAMB", architecture.get("windows") or [], 16),
    ):
        for index, item in enumerate(collection):
            if not isinstance(item,dict):
                continue
            if plan_id and item.get("plan_id") not in (None, plan_id):
                continue
            for edge_i, (a, b) in enumerate(_semantic_item_edges(item)):
                if _inside(a, plan_bounds, 0.5) or _inside(b, plan_bounds, 0.5):
                    refs.append(_reference(kind, f"{prefix}-{index:03d}-E{edge_i}", a, b, priority, source="semantic_geometry"))

    # Grid/property recognition may use layer vocabulary only as weak candidate
    # evidence; final binding still relies on actual geometry and proximity.
    for index, entity in enumerate(doc.modelspace()):
        if entity.dxftype() != "LINE":
            continue
        try:
            a = _xy(entity.dxf.start)
            b = _xy(entity.dxf.end)
        except Exception:
            continue
        if not a or not b or not (_inside(a, plan_bounds, 1.0) or _inside(b, plan_bounds, 1.0)):
            continue
        layer = _norm(getattr(entity.dxf, "layer", ""))
        if any(token in layer for token in ("grid", "axis", "axes", "محور")):
            refs.append(_reference("GRID_AXIS", f"GRID-{index:04d}", a, b, 0, source="layer_hint"))
        elif any(token in layer for token in ("property", "site", "boundary", "حد", "ملک")):
            refs.append(_reference("PROPERTY_BOUNDARY", f"PROPERTY-{index:04d}", a, b, 5, source="layer_hint"))

    return refs


def detect_local_axis(reference_catalog):
    """Detect the dominant local building axis; world X/Y is only the fallback."""
    weighted = []
    for ref in reference_catalog or []:
        if ref["kind"] not in {"GRID_AXIS", "WALL_FACE", "STRUCTURAL_FACE", "SHAFT_FACE", "STAIR_CORE_FACE"}:
            continue
        a, b = ref["a"], ref["b"]
        length = math.dist(a, b)
        if length <= 1e-9:
            continue
        angle = _line_angle(a, b) % (math.pi / 2.0)
        weighted.append((angle, length))
    if not weighted:
        return 0.0
    bins = {}
    step = math.radians(2.0)
    for angle, weight in weighted:
        key = int(round(angle / step))
        bins[key] = bins.get(key, 0.0) + weight
    winning = max(bins, key=bins.get)
    values = [(a, w) for a, w in weighted if int(round(a / step)) == winning]
    return sum(a * w for a, w in values) / max(sum(w for _, w in values), 1e-12)


def _nearest_reference(point, refs, tolerance):
    candidates = []
    for ref in refs or []:
        distance, projection = _point_segment_distance(point, ref["a"], ref["b"])
        if distance <= tolerance:
            candidates.append((ref["priority"], distance, ref, projection))
    if not candidates:
        return None
    _, distance, ref, projection = min(candidates, key=lambda item: (item[0], item[1]))
    return {"reference": ref, "distance": distance, "projection": projection}


def _semantic_type(p1, p2, measurement, bind_a, bind_b, plan_bounds):
    ra=(bind_a or {}).get("reference", {})
    rb=(bind_b or {}).get("reference", {})
    kinds={ra.get("kind"),rb.get("kind")}
    kinds.discard(None)
    if kinds == {"GRID_AXIS"}:
        return "GRID"
    if "PROPERTY_BOUNDARY" in kinds and (
        "PLAN_EDGE" in kinds or "WALL_FACE" in kinds or "STRUCTURAL_FACE" in kinds
    ):
        return "SETBACK"
    if kinds == {"PROPERTY_BOUNDARY"}:
        return "PROPERTY"
    if "SHAFT_FACE" in kinds:
        return "SHAFT"
    if "STAIR_CORE_FACE" in kinds:
        return "STAIR_CORE"
    if "OPENING_JAMB" in kinds:
        return "OPENING"
    if "STRUCTURAL_FACE" in kinds:
        return "STRUCTURAL_SET_OUT"

    width=abs(float(plan_bounds[2])-float(plan_bounds[0]))
    height=abs(float(plan_bounds[3])-float(plan_bounds[1]))
    dx=abs(float(p2[0])-float(p1[0]));dy=abs(float(p2[1])-float(p1[1]))
    horizontal=dx>=dy
    axis_span=width if horizontal else height
    measured_span=max(abs(float(measurement or 0)),dx if horizontal else dy)
    coord1=float(p1[0] if horizontal else p1[1])
    coord2=float(p2[0] if horizontal else p2[1])
    low=float(plan_bounds[0] if horizontal else plan_bounds[1])
    high=float(plan_bounds[2] if horizontal else plan_bounds[3])
    boundary_tol=max(axis_span*.08,1e-6)
    opposite_bounds=(
        min(abs(coord1-low),abs(coord2-low))<=boundary_tol
        and min(abs(coord1-high),abs(coord2-high))<=boundary_tol
    )
    envelope_sides={ra.get("envelope_side"),rb.get("envelope_side")}
    opposite_envelope_pair=(
        ra.get("kind")=="WALL_FACE" and rb.get("kind")=="WALL_FACE"
        and bool(ra.get("envelope_candidate")) and bool(rb.get("envelope_candidate"))
        and envelope_sides in ({"LEFT","RIGHT"},{"TOP","BOTTOM"})
    )
    plan_edge_overall=("PLAN_EDGE" in kinds and opposite_bounds)
    if measured_span>=axis_span*.70 and (opposite_envelope_pair or plan_edge_overall):
        return "BUILDING_OVERALL"
    if kinds and kinds <= {"WALL_FACE"}:
        return "WALL_SETOUT"
    if "PLAN_EDGE" in kinds and measured_span>=axis_span*.70:
        return "BUILDING_OVERALL"
    return "UNKNOWN"


def extract_source_dimension_registry(doc_or_path, plan_bounds=None, architecture=None, plan_id=None, reference_catalog=None):
    """Extract source dimensions as immutable evidence, independent of view visibility."""
    doc = (
        ezdxf.readfile(doc_or_path)
        if isinstance(doc_or_path, (str, bytes, Path))
        else doc_or_path
    )
    if plan_bounds is None:
        geometry=[
            e for e in doc.modelspace()
            if e.dxftype() not in {"DIMENSION","TEXT","MTEXT","LEADER","MLEADER"}
        ]
        try:
            ext=bbox.extents(geometry or list(doc.modelspace()),fast=True)
            if ext.has_data:
                plan_bounds=(
                    float(ext.extmin.x),float(ext.extmin.y),
                    float(ext.extmax.x),float(ext.extmax.y),
                )
        except Exception:
            plan_bounds=None
    if plan_bounds is None:
        return {"status":"INPUT_REQUIRED","records":[],"conflicts":[],"missing_inputs":["PLAN_BOUNDS"]}
    refs = list(reference_catalog) if reference_catalog is not None else build_reference_catalog(doc, plan_bounds, architecture=architecture, plan_id=plan_id)
    unit_evidence=infer_drawing_unit_scale(doc)
    effective_scale=unit_evidence.get("effective_scale_to_m")
    span = max(
        abs(float(plan_bounds[2]) - float(plan_bounds[0])),
        abs(float(plan_bounds[3]) - float(plan_bounds[1])),
        1.0,
    )
    bind_tol = max(span * 0.006, 0.02)
    records = []
    for index, entity in enumerate(doc.modelspace().query("DIMENSION")):
        p1, p2, base = _dimension_geometry(entity)
        if not p1 or not p2:
            continue
        if not (
            _inside(p1, plan_bounds, span * 0.12)
            or _inside(p2, plan_bounds, span * 0.12)
            or _inside(((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2), plan_bounds, span * 0.12)
        ):
            continue
        try:
            measured = abs(float(entity.get_measurement()))
        except Exception:
            measured = math.dist(p1, p2)
        text = str(getattr(entity.dxf, "text", "") or "").strip()
        simple_override = _simple_numeric_override(text)
        override_status=_override_status(measured,text)
        conflict_reason = None
        if measured <= max(span * 1e-9, 1e-9):
            conflict_reason = "ZERO_MEASUREMENT"
        elif override_status=="CONFLICT":
            conflict_reason = "DISPLAY_GEOMETRY_CONFLICT"

        bind_a = _nearest_reference(p1, refs, bind_tol)
        bind_b = _nearest_reference(p2, refs, bind_tol)
        semantic = _semantic_type(p1, p2, measured, bind_a, bind_b, plan_bounds)
        if override_status=="NON_NUMERIC_OVERRIDE" and semantic in CRITICAL_SOURCE_TYPES:
            conflict_reason = "NON_NUMERIC_CRITICAL_OVERRIDE"
        if conflict_reason and semantic in CRITICAL_SOURCE_TYPES:
            preservation = "FLAG_CONFLICT"
        elif semantic in CRITICAL_SOURCE_TYPES:
            preservation = "REGENERATE"
        elif semantic in {"WALL_SETOUT", "OPENING"}:
            preservation = "PRESERVE_AS_EVIDENCE"
        else:
            preservation = "PRESERVE_AS_EVIDENCE"

        displayed = (
            text
            if simple_override is not None and not conflict_reason
            else _display_number(measured)
        )
        records.append({
            "id": f"SRC-DIM-{plan_id or 'PLAN'}-{index:04d}",
            "source_handle": str(getattr(entity.dxf, "handle", "") or ""),
            "source_layer": str(getattr(entity.dxf, "layer", "") or ""),
            "source_style": str(getattr(entity.dxf, "dimstyle", "") or ""),
            "p1": p1,
            "p2": p2,
            "dimension_line_point": base,
            "measured_value": measured,
            "raw_measurement": measured,
            "measured_value_m": (measured*effective_scale if effective_scale is not None else None),
            "unit_evidence_source": unit_evidence.get("source"),
            "source_display_text": text,
            "displayed_value": displayed,
            "simple_numeric_override": simple_override,
            "override_status": override_status,
            "semantic_type": semantic,
            "purpose": semantic,
            "reference_point_a": p1,
            "reference_point_b": p2,
            "reference_a": (bind_a or {}).get("reference"),
            "reference_b": (bind_b or {}).get("reference"),
            "conflict": conflict_reason,
            "preservation_policy": preservation,
            "critical": semantic in CRITICAL_SOURCE_TYPES,
        })
    return {
        "status": "PASS",
        "plan_id": plan_id,
        "records": records,
        "dimension_count":len(records),
        "unit_evidence":unit_evidence,
        "reference_count": len(refs),
        "local_axis_deg": math.degrees(detect_local_axis(refs)),
        "counts": dict(Counter(row["semantic_type"] for row in records)),
        "conflicts": [row["id"] for row in records if row["conflict"]],
        "override_conflict_count":sum(1 for row in records if row["conflict"]),
    }


def drawing_profile(family, level=None):
    if str(level or "").upper() == "ROOF" or str(family or "").upper() == "ROOF":
        return "ROOF_PLAN"
    if str(family or "").upper() == "PARKING":
        return "PARKING_PLAN"
    return "MECHANICAL_PLAN"


def source_dimension_intents(registry, profile):
    visible = SOURCE_VISIBLE_BY_PROFILE.get(profile, set())
    intents = []
    for row in registry.get("records") or []:
        if row.get("conflict") and row.get("critical"):
            continue
        if row.get("override_status")=="NON_NUMERIC_OVERRIDE":
            # Preserve consultant drafting text as source evidence. Never turn
            # non-numeric content such as "20-30" into a fabricated measurement.
            continue
        if row.get("semantic_type") not in visible:
            continue
        intents.append({
            "id": "REGEN-" + row["id"],
            "purpose": row["semantic_type"],
            "source_kind": "SOURCE_REGENERATED",
            "source_dimension_id": row["id"],
            "reference_a": row.get("reference_a"),
            "reference_b": row.get("reference_b"),
            "world_p1": row["p1"],
            "world_p2": row["p2"],
            "world_base": row.get("dimension_line_point"),
            "measured_value": row["measured_value"],
            "engineering_value_m": row.get("measured_value_m"),
            "effective_scale_to_m": (registry.get("unit_evidence") or {}).get("effective_scale_to_m"),
            "unit_evidence_source": (registry.get("unit_evidence") or {}).get("source"),
            "displayed_value": row["displayed_value"],
            "required": bool(row.get("critical")),
            "priority": 100 if row.get("critical") else 60,
            "placement_zone": "SOURCE",
        })
    return intents


def collect_mechanical_targets(pipeline, plan_id):
    """Collect only construction-location targets; route vertices are not blanket-dimensioned."""
    targets = []
    for node in (pipeline.get("topology") or {}).get("nodes") or []:
        if node.get("plan_id") != plan_id or not node.get("point"):
            continue
        kind = _norm(node.get("kind"))
        category=_norm(node.get("category"))
        if kind in {"shaft","riser","vertical","stack"} or category=="vertical_core":
            targets.append({
                "id": str(node.get("id") or f"VERT-{len(targets)+1}"),
                "point": tuple(map(float, node["point"][:2])),
                "kind": "VERTICAL_CONNECTION",
                "priority": 100,
            })
        elif category=="equipment" or kind in {
            "floor_drain","roof_drain","cleanout","sleeve","penetration",
            "pump","tank","outdoor_unit","indoor_unit",
        }:
            targets.append({
                "id": str(node.get("id") or f"MECH-{len(targets)+1}"),
                "point": tuple(map(float, node["point"][:2])),
                "kind": "CONSTRUCTION_POINT",
                "priority": 85,
            })
    for equipment in (pipeline.get("hvac") or {}).get("equipment") or []:
        if equipment.get("plan_id") != plan_id or not equipment.get("point"):
            continue
        targets.append({
            "id": str(equipment.get("id") or f"EQUIP-{len(targets)+1}"),
            "point": tuple(map(float, equipment["point"][:2])),
            "kind": "EQUIPMENT",
            "priority": 80,
        })
    deduped = []
    seen = set()
    for row in targets:
        key = (row["id"], round(row["point"][0], 6), round(row["point"][1], 6))
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped


def _axis_reference_candidates(refs, measured_axis, tolerance=math.radians(8)):
    """Reference lines perpendicular to a measured axis constrain that coordinate."""
    wanted = (measured_axis + math.pi / 2.0) % math.pi
    rows = []
    for ref in refs or []:
        if ref["kind"] not in {
            "GRID_AXIS", "WALL_FACE", "SHAFT_FACE", "STRUCTURAL_FACE",
            "STAIR_CORE_FACE", "PROPERTY_BOUNDARY", "PLAN_EDGE"
        }:
            continue
        angle = _line_angle(ref["a"], ref["b"]) % math.pi
        if _axis_delta(angle, wanted) <= tolerance:
            rows.append(ref)
    return rows


def _best_datum(target, refs):
    candidates = []
    for ref in refs:
        distance, projection = _point_segment_distance(target, ref["a"], ref["b"])
        candidates.append((ref["priority"], distance, ref, projection))
    if not candidates:
        return None
    _, distance, ref, projection = min(candidates, key=lambda item: (item[0], item[1]))
    return {"reference": ref, "distance": distance, "projection": projection}


def determinacy_intents(targets, refs, local_axis):
    """Minimum two independent set-out constraints for free point targets."""
    intents = []
    missing = []
    axes = [local_axis, local_axis + math.pi / 2.0]
    for target in targets or []:
        constraints = 0
        for axis_index, axis in enumerate(axes):
            candidates = _axis_reference_candidates(refs, axis)
            datum = _best_datum(target["point"], candidates)
            if not datum:
                continue
            if datum["distance"] <= 1e-8:
                # Coincident datum is a host constraint and resolves one DOF.
                constraints += 1
                continue
            constraints += 1
            intents.append({
                "id": f"SET-{target['id']}-{axis_index}",
                "purpose": "SETOUT",
                "source_kind": "PLANHA_GENERATED",
                "mechanical_target_id": target["id"],
                "reference_a": {
                    "kind": "MECHANICAL_CENTER",
                    "id": target["id"],
                },
                "reference_b": datum["reference"],
                "world_p1": target["point"],
                "world_p2": datum["projection"],
                "world_base": None,
                "measured_value": datum["distance"],
                "engineering_value_m": None,
                "effective_scale_to_m": None,
                "unit_evidence_source": "INHERIT_SOURCE_REGISTRY",
                "displayed_value": _display_number(datum["distance"]),
                "required": True,
                "priority": target.get("priority", 50),
                "placement_zone": "LOCAL",
                "angle_deg": math.degrees(axis),
            })
        if constraints < 2:
            missing.append({
                "target_id": target["id"],
                "constraints": constraints,
                "required": 2,
            })
    return intents, missing



def governed_requirement_intents(requirements, refs, plan_id):
    """Convert explicit rule/compliance dimension requirements into intents.

    Regulatory clearances are never inferred from a visually similar gap. The
    upstream rule authority must provide a Rule ID, two stable semantic
    references and actual geometry. The dimension displays the actual designed
    clearance; the minimum is validation evidence only.
    """
    intents=[];errors=[]
    ref_by_id={str(ref.get("id")):ref for ref in refs or [] if ref.get("id")}
    allowed={"CODE_CLEARANCE","OPENING","SETOUT","CHECK"}
    for index,row in enumerate(requirements or []):
        if not isinstance(row,dict):
            errors.append({"id":f"REQ-{index}","reason":"INVALID_REQUIREMENT"})
            continue
        if row.get("plan_id") not in (None,plan_id):
            continue
        req_id=str(row.get("id") or f"REQ-{index:04d}")
        purpose=str(row.get("purpose") or "").upper()
        rule_id=str(row.get("rule_id") or "")
        if purpose not in allowed:
            errors.append({"id":req_id,"reason":"UNSUPPORTED_DIMENSION_PURPOSE"})
            continue
        if purpose=="CODE_CLEARANCE" and not rule_id:
            errors.append({"id":req_id,"reason":"CODE_CLEARANCE_RULE_ID_REQUIRED"})
            continue
        try:
            p1=tuple(map(float,row["p1"][:2]));p2=tuple(map(float,row["p2"][:2]))
        except Exception:
            errors.append({"id":req_id,"reason":"REQUIREMENT_GEOMETRY_REQUIRED"})
            continue
        ref_a_id=str(row.get("reference_a_id") or "")
        ref_b_id=str(row.get("reference_b_id") or "")
        ref_a=ref_by_id.get(ref_a_id);ref_b=ref_by_id.get(ref_b_id)
        if not ref_a or not ref_b:
            errors.append({"id":req_id,"reason":"STABLE_REFERENCE_PAIR_REQUIRED"})
            continue
        measured=math.dist(p1,p2)
        minimum_m=row.get("minimum_value_m")
        if purpose=="CODE_CLEARANCE" and minimum_m is None:
            errors.append({"id":req_id,"reason":"CODE_CLEARANCE_MINIMUM_METRE_VALUE_REQUIRED","rule_id":rule_id})
            continue
        if minimum_m is not None:
            try:minimum_m=float(minimum_m)
            except Exception:
                errors.append({"id":req_id,"reason":"INVALID_MINIMUM_METRE_VALUE","rule_id":rule_id})
                continue
        intents.append({
            "id":"REQ-"+req_id,
            "purpose":purpose,
            "source_kind":"GOVERNED_REQUIREMENT",
            "governance_rule_id":rule_id,
            "reference_a":ref_a,
            "reference_b":ref_b,
            "world_p1":p1,
            "world_p2":p2,
            "world_base":tuple(row.get("base")) if row.get("base") else None,
            "measured_value":measured,
            "displayed_value":_display_number(measured),
            "minimum_value_m":minimum_m,
            "required":bool(row.get("required",True)),
            "priority":int(row.get("priority",95)),
            "placement_zone":"LOCAL",
            "angle_deg":math.degrees(_line_angle(p1,p2)),
        })
    return intents,errors

def select_minimal_dimension_set(intents):
    """Remove exact semantic duplicates while preserving required check intent."""
    selected=[];seen=set()
    for row in intents or []:
        ra=row.get("reference_a") or {}; rb=row.get("reference_b") or {}
        ids=sorted([
            str(ra.get("id") or ra.get("element_id") or ""),
            str(rb.get("id") or rb.get("element_id") or ""),
        ])
        key=(
            str(row.get("board_id") or ""),
            str(row.get("purpose") or ""),
            str(row.get("orientation") or row.get("angle_deg") or ""),
            tuple(ids),
            tuple(round(float(x),6) for x in row.get("world_p1") or ()),
            tuple(round(float(x),6) for x in row.get("world_p2") or ()),
        )
        if key in seen:
            continue
        seen.add(key);selected.append(row)
    return selected


def _fit_transform(source_bounds, target_bounds):
    sx1, sy1, sx2, sy2 = map(float, source_bounds)
    tx1, ty1, tx2, ty2 = map(float, target_bounds)
    sw = max(sx2 - sx1, 1e-9)
    sh = max(sy2 - sy1, 1e-9)
    tw = tx2 - tx1
    th = ty2 - ty1
    scale = min(tw / sw, th / sh)
    nw = sw * scale
    nh = sh * scale
    dx = tx1 + (tw - nw) / 2.0
    dy = ty1 + (th - nh) / 2.0
    return scale, dx, dy


def _map_point(point, source_bounds, target_bounds):
    scale, dx, dy = _fit_transform(source_bounds, target_bounds)
    sx1, sy1, _, _ = map(float, source_bounds)
    return (
        dx + (float(point[0]) - sx1) * scale,
        dy + (float(point[1]) - sy1) * scale,
    )


def _boxes_overlap(a, b, clearance=0.03):
    return not (
        a[2] + clearance <= b[0]
        or b[2] + clearance <= a[0]
        or a[3] + clearance <= b[1]
        or b[3] + clearance <= a[1]
    )


def _text_box(base, text):
    width = max(0.26, 0.052 * max(len(str(text)), 4))
    height = 0.11
    return (base[0] - width / 2, base[1] - height / 2, base[0] + width / 2, base[1] + height / 2)


def place_intents(intents, source_bounds, board, obstacles=None):
    obstacles = list(obstacles or [])
    placed = []
    collisions = []
    plan_area = tuple(board["plan_area"] if isinstance(board, dict) else board.plan_area)
    board_bounds = tuple(board["bounds"] if isinstance(board, dict) else board.bounds)
    title_area = tuple(board["title_area"] if isinstance(board, dict) else board.title_area)
    tier = {"H": 0, "V": 0}

    for intent in sorted(intents, key=lambda row: (-int(row.get("priority", 0)), row["id"])):
        p1 = _map_point(intent["world_p1"], source_bounds, plan_area)
        p2 = _map_point(intent["world_p2"], source_bounds, plan_area)
        angle = math.radians(float(intent.get("angle_deg", math.degrees(_line_angle(intent["world_p1"], intent["world_p2"])))))
        if intent.get("source_kind") == "SOURCE_REGENERATED" and intent.get("world_base"):
            base = _map_point(intent["world_base"], source_bounds, plan_area)
            midpoint=((p1[0]+p2[0])/2,(p1[1]+p2[1])/2)
            horizontal=abs(math.cos(angle))>=abs(math.sin(angle))
            fallback=(
                (midpoint[0],min(max(plan_area[1]+.20,title_area[3]+.12),plan_area[3]-.20))
                if horizontal else
                (min(max(plan_area[0]+.20,board_bounds[0]+.20),plan_area[2]-.20),midpoint[1])
            )
            candidates = [base,fallback]
        elif intent.get("purpose") in {"BUILDING_OVERALL", "GRID", "PROPERTY", "SETBACK", "CHECK"}:
            horizontal = abs(math.cos(angle)) >= abs(math.sin(angle))
            key = "H" if horizontal else "V"
            tier[key] += 1
            if horizontal:
                y = max(plan_area[1] - 0.28 * tier[key], title_area[3] + 0.12)
                candidates = [((p1[0] + p2[0]) / 2, y)]
            else:
                x = max(board_bounds[0] + 0.18, plan_area[0] - 0.28 * tier[key])
                candidates = [(x, (p1[1] + p2[1]) / 2)]
        else:
            midpoint = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            normal = (-math.sin(angle), math.cos(angle))
            candidates = [
                (midpoint[0] + normal[0] * offset, midpoint[1] + normal[1] * offset)
                for offset in (0.22, -0.22, 0.38, -0.38, 0.56, -0.56)
            ]

        chosen = None
        for base in candidates:
            box = _text_box(base, intent["displayed_value"])
            if not (
                board_bounds[0] <= box[0] <= board_bounds[2]
                and board_bounds[1] <= box[1] <= board_bounds[3]
                and board_bounds[0] <= box[2] <= board_bounds[2]
                and title_area[3] <= box[3] <= board_bounds[3]
            ):
                continue
            if not any(_boxes_overlap(box, other) for other in obstacles):
                chosen = (base, box)
                break
        if chosen is None:
            base = candidates[0]
            box = _text_box(base, intent["displayed_value"])
            collisions.append(intent["id"])
        else:
            base, box = chosen
        obstacles.append(box)
        placed.append({
            **intent,
            "render_p1": p1,
            "render_p2": p2,
            "render_base": base,
            "text_box": box,
            "angle_deg": float(intent.get("angle_deg", math.degrees(angle))),
        })
    return placed, collisions


def _ensure_dimension_style(doc):
    if DIMSTYLE not in doc.dimstyles:
        doc.dimstyles.new(
            DIMSTYLE,
            dxfattribs={
                "dimtxt": 0.08,
                "dimasz": 0.06,
                "dimexo": 0.02,
                "dimexe": 0.04,
                "dimgap": 0.03,
            },
        )
    for name, color in ((SOURCE_LAYER, 8), (SETOUT_LAYER, 2), (CHECK_LAYER, 6)):
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    try:
        doc.appids.get(APPID)
    except Exception:
        doc.appids.add(APPID)


def materialize_dimension_intents(doc, msp, placed_intents):
    _ensure_dimension_style(doc)
    rows = []
    for intent in placed_intents or []:
        if intent.get("source_kind") == "SOURCE_REGENERATED":
            layer = SOURCE_LAYER
        elif intent.get("purpose") == "CHECK":
            layer = CHECK_LAYER
        else:
            layer = SETOUT_LAYER
        try:
            dim = msp.add_linear_dim(
                base=intent["render_base"],
                p1=intent["render_p1"],
                p2=intent["render_p2"],
                angle=float(intent["angle_deg"]),
                text=str(intent["displayed_value"]),
                dimstyle=DIMSTYLE,
                dxfattribs={"layer": layer},
            )
            dim.render()
            entity = dim.dimension
            marker="SOURCE_DIMENSION" if intent.get("source_kind")=="SOURCE_REGENERATED" else "SEMANTIC_DIMENSION"
            reference_a_id=str((intent.get("reference_a") or {}).get("id") or "")
            reference_b_id=str((intent.get("reference_b") or {}).get("id") or "")
            measured_value=float(intent.get("measured_value") or 0.0)
            engineering_value_m=intent.get("engineering_value_m")
            effective_scale_to_m=intent.get("effective_scale_to_m")
            unit_source=str(intent.get("unit_evidence_source") or "")
            governance_rule_id=str(intent.get("governance_rule_id") or "")
            trace_data=[
                (1000,marker),
                (1000,str(intent["id"])),
                (1000,str(intent.get("purpose") or "")),
                (1000,str(intent.get("mechanical_target_id") or intent.get("source_dimension_id") or "")),
                (1000,reference_a_id),
                (1000,reference_b_id),
                (1000,unit_source),
                (1000,governance_rule_id),
                (1040,measured_value),
            ]
            if engineering_value_m is not None:
                trace_data.append((1040,float(engineering_value_m)))
            if effective_scale_to_m is not None:
                trace_data.append((1040,float(effective_scale_to_m)))
            entity.set_xdata(APPID,trace_data)
            rows.append({
                "intent_id": intent["id"],
                "handle": str(getattr(entity.dxf, "handle", "") or ""),
                "layer": layer,
                "displayed_value": str(intent["displayed_value"]),
                "measured_value": measured_value,
                "engineering_value_m": engineering_value_m,
                "effective_scale_to_m": effective_scale_to_m,
                "unit_evidence_source": unit_source,
                "governance_rule_id": governance_rule_id,
                "reference_a_id": reference_a_id,
                "reference_b_id": reference_b_id,
                "purpose": intent["purpose"],
                "source_kind": intent["source_kind"],
                "required": bool(intent.get("required")),
            })
        except Exception as exc:
            rows.append({
                "intent_id": intent["id"],
                "handle": "",
                "layer": layer,
                "displayed_value": str(intent["displayed_value"]),
                "purpose": intent["purpose"],
                "source_kind": intent["source_kind"],
                "required": bool(intent.get("required")),
                "error": str(exc),
            })
    return rows


def build_and_materialize_plan_dimensions(doc, msp, board, plan, architecture, pipeline, family, level=None, reference_catalog=None):
    plan_id = plan.get("plan_id")
    source_bounds = tuple(plan["bounds"])
    refs = list(reference_catalog) if reference_catalog is not None else build_reference_catalog(doc, source_bounds, architecture=architecture, plan_id=plan_id)
    axis = detect_local_axis(refs)
    registry = extract_source_dimension_registry(
        doc,
        source_bounds,
        architecture=architecture,
        plan_id=plan_id,
        reference_catalog=refs,
    )
    profile = drawing_profile(family, level)
    source_intents = source_dimension_intents(registry, profile)
    targets = collect_mechanical_targets(pipeline, plan_id)
    generated_intents, missing = determinacy_intents(targets, refs, axis)
    governed_intents, governed_errors = governed_requirement_intents(
        pipeline.get("dimension_requirements") or [], refs, plan_id
    )
    effective_scale=(registry.get("unit_evidence") or {}).get("effective_scale_to_m")
    unit_source=(registry.get("unit_evidence") or {}).get("source")
    for intent in generated_intents + governed_intents:
        intent["effective_scale_to_m"]=effective_scale
        intent["unit_evidence_source"]=unit_source
        intent["engineering_value_m"]=(intent["measured_value"]*effective_scale if effective_scale is not None else None)
    if effective_scale is not None:
        for intent in governed_intents:
            minimum_m=intent.get("minimum_value_m")
            if minimum_m is not None and intent.get("engineering_value_m") is not None and intent["engineering_value_m"]+1e-9<float(minimum_m):
                governed_errors.append({
                    "id":intent["id"],"reason":"CODE_CLEARANCE_NOT_SATISFIED",
                    "actual_m":intent["engineering_value_m"],"minimum_m":float(minimum_m),
                    "rule_id":intent.get("governance_rule_id") or "",
                })
    all_intents = select_minimal_dimension_set(source_intents + generated_intents + governed_intents)
    placed, collisions = place_intents(all_intents, source_bounds, board)
    materialized = materialize_dimension_intents(doc, msp, placed)

    required = {row["id"] for row in all_intents if row.get("required")}
    successful = {
        row["intent_id"]
        for row in materialized
        if row.get("handle") and not row.get("error")
    }
    missing_required = sorted(required - successful)
    critical_conflicts = [
        row["id"]
        for row in registry.get("records") or []
        if row.get("critical") and row.get("conflict")
    ]
    errors = []
    if missing:
        errors.append("UNDER_DIMENSIONED_MECHANICAL_TARGETS")
    if missing_required:
        errors.append("REQUIRED_DIMENSION_NOT_MATERIALIZED")
    if collisions:
        errors.append("DIMENSION_TEXT_COLLISION")
    if critical_conflicts:
        errors.append("CRITICAL_SOURCE_DIMENSION_CONFLICT")
    if governed_errors:
        errors.append("GOVERNED_DIMENSION_REQUIREMENT_INVALID")
    if all_intents and effective_scale is None:
        errors.append("DIMENSION_UNIT_BASIS_REQUIRED")

    return {
        "status": "PASS" if not errors else "FAIL",
        "profile": profile,
        "source_registry": registry,
        "reference_catalog":refs,
        "source_dimension_count": len(registry.get("records") or []),
        "source_visible_count": len(source_intents),
        "source_intent_ids":[row["id"] for row in source_intents],
        "mechanical_target_count": len(targets),
        "mechanical_setout_intent_count": len(generated_intents),
        "governed_requirement_intent_count": len(governed_intents),
        "governed_requirement_errors": governed_errors,
        "intent_count": len(all_intents),
        "materialized": materialized,
        "missing_determinacy": missing,
        "missing_required": missing_required,
        "collision_intents": collisions,
        "critical_source_conflicts": critical_conflicts,
        "errors": errors,
        "local_axis_deg": math.degrees(axis),
        "policy": "minimum semantic set-out graph + intentional source/check dimensions",
    }


def validate_exact_file_dimensions(path, compose_report):
    """Reopen issued DXF and prove semantic dimensions exist and remain traceable."""
    reports = (compose_report or {}).get("dimensioning") or {}
    if not reports:
        return {
            "status": "PASS",
            "errors": [],
            "reason": "NO_APPLICABLE_ARCHITECTURAL_PLAN_DIMENSION_REPORTS",
            "exact_file_reopened": True,
        }
    doc = ezdxf.readfile(path)
    by_handle = {
        str(getattr(entity.dxf, "handle", "") or ""): entity
        for entity in doc.modelspace().query("DIMENSION")
    }
    errors = []
    per_sheet = {}
    for sheet, report in reports.items():
        sheet_errors = list(report.get("errors") or [])
        for item in report.get("materialized") or []:
            handle = item.get("handle")
            if not handle:
                if item.get("required"):
                    sheet_errors.append("MISSING_REQUIRED_DIMENSION_HANDLE:" + item["intent_id"])
                continue
            entity = by_handle.get(handle)
            if entity is None:
                sheet_errors.append("DIMENSION_MISSING_AFTER_REOPEN:" + item["intent_id"])
                continue
            try:
                geometric = abs(float(entity.get_measurement()))
            except Exception:
                geometric = 0.0
            if geometric <= 1e-12:
                sheet_errors.append("ZERO_RENDERED_DIMENSION:" + item["intent_id"])
            actual_text = str(getattr(entity.dxf, "text", "") or "")
            if actual_text != str(item.get("displayed_value") or ""):
                sheet_errors.append("DIMENSION_DISPLAY_CHANGED:" + item["intent_id"])
            try:
                trace=entity.get_xdata(APPID)
            except Exception:
                trace=[]
            strings=[value for code,value in trace if code==1000]
            doubles=[float(value) for code,value in trace if code==1040]
            expected_marker="SOURCE_DIMENSION" if item.get("source_kind")=="SOURCE_REGENERATED" else "SEMANTIC_DIMENSION"
            if len(strings)<8 or strings[0]!=expected_marker or strings[1]!=str(item["intent_id"]):
                sheet_errors.append("DIMENSION_TRACEABILITY_MISSING:" + item["intent_id"])
            elif strings[4]!=str(item.get("reference_a_id") or "") or strings[5]!=str(item.get("reference_b_id") or ""):
                sheet_errors.append("DIMENSION_REFERENCE_ID_CHANGED:" + item["intent_id"])
            elif strings[6]!=str(item.get("unit_evidence_source") or ""):
                sheet_errors.append("DIMENSION_UNIT_EVIDENCE_CHANGED:" + item["intent_id"])
            elif strings[7]!=str(item.get("governance_rule_id") or ""):
                sheet_errors.append("DIMENSION_RULE_ID_CHANGED:" + item["intent_id"])
            if not doubles or abs(doubles[0]-float(item.get("measured_value") or 0.0))>1e-9:
                sheet_errors.append("DIMENSION_ENGINEERING_VALUE_CHANGED:" + item["intent_id"])
            expected_m=item.get("engineering_value_m")
            expected_scale=item.get("effective_scale_to_m")
            if expected_m is not None and (len(doubles)<2 or not math.isfinite(doubles[1]) or abs(doubles[1]-float(expected_m))>1e-9):
                sheet_errors.append("DIMENSION_CANONICAL_METRE_VALUE_CHANGED:" + item["intent_id"])
            if expected_scale is not None and (len(doubles)<3 or not math.isfinite(doubles[2]) or abs(doubles[2]-float(expected_scale))>1e-12):
                sheet_errors.append("DIMENSION_UNIT_SCALE_CHANGED:" + item["intent_id"])
        per_sheet[sheet] = {
            "status": "PASS" if not sheet_errors else "FAIL",
            "errors": sorted(set(sheet_errors)),
            "intent_count": report.get("intent_count", 0),
            "source_dimension_count": report.get("source_dimension_count", 0),
            "mechanical_target_count": report.get("mechanical_target_count", 0),
        }
        errors.extend(f"{sheet}:{value}" for value in sheet_errors)
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": sorted(set(errors)),
        "per_sheet": per_sheet,
        "exact_file_reopened": True,
        "policy": "semantic completeness, source preservation, determinacy and exact-file materialization",
    }


def source_preservation_complete(dimension_report):
    """Separate source-knowledge preservation from view-specific materialization."""
    registry = (dimension_report or {}).get("source_registry") or {}
    rows = registry.get("records") or []
    visible_materialized = {
        item.get("intent_id")
        for item in (dimension_report or {}).get("materialized") or []
        if item.get("source_kind") == "SOURCE_REGENERATED" and item.get("handle")
    }
    if "source_intent_ids" in (dimension_report or {}):
        required_visible=set((dimension_report or {}).get("source_intent_ids") or [])
    else:
        # Fail-safe for older reports that did not distinguish suppression:
        # assume critical source dimensions were intended to be materialized.
        required_visible={"REGEN-"+row["id"] for row in rows if row.get("critical")}

    missing = []
    conflicts = []
    suppressed_but_preserved=[]
    for row in rows:
        if not row.get("critical"):
            continue
        if row.get("conflict"):
            conflicts.append(row["id"])
            continue
        expected = "REGEN-" + row["id"]
        if expected not in required_visible:
            suppressed_but_preserved.append(row["id"])
            continue
        if expected not in visible_materialized:
            missing.append(row["id"])
    return {
        "pass": not missing and not conflicts,
        "missing_critical_source_dimensions": missing,
        "critical_source_conflicts": conflicts,
        "suppressed_but_preserved_critical_dimensions":suppressed_but_preserved,
        "source_dimension_count": len(rows),
        "critical_source_dimension_count": sum(1 for row in rows if row.get("critical")),
        "policy":"registry preservation is mandatory; view materialization is drawing-profile specific",
    }


def apply_semantic_dimension_engine(src, dst, base_report, network, architecture_preservation=None):
    """Standalone governed adapter used by synthetic/golden validation.

    Production composition invokes the same primitives from mechanical_design_core.
    This adapter never changes network topology, sizing or equipment selection.
    """
    if architecture_preservation and architecture_preservation.get("status")!="PASS":
        return {"status":"FAIL","errors":["ARCHITECTURE_PRESERVATION_NOT_PASS"]}
    src=Path(src);dst=Path(dst)
    doc=ezdxf.readfile(dst);msp=doc.modelspace()
    # The CAD shell may have created provisional Planha dimensions before the
    # graph-native authoritative network is materialized. Remove only Planha-
    # owned dimension entities and regenerate from final authority below.
    for entity in list(msp.query("DIMENSION")):
        try:
            entity.get_xdata(APPID)
        except Exception:
            continue
        msp.delete_entity(entity)
    composition=(base_report or {}).get("composition") or {}
    rows=composition.get("manifest") or []; boards=composition.get("boards") or {}
    dimensioning={}; generated_count=0
    levels={}
    for level_row in (network or {}).get("levels") or []:
        for key in ("id","name","type"):
            value=str(level_row.get(key) or "")
            if value:levels[value]=level_row
    nodes=list((network or {}).get("nodes") or [])
    for row in rows:
        family=str(row.get("family") or "")
        if family not in {"ROOF","SANITARY_VENT","WATER","HEATING","GAS","SPLIT_AC","EXHAUST"}:
            continue
        board=dict(boards.get(row.get("old_sheet")) or {})
        if not board.get("plan_area"):
            continue
        level_name=str(row.get("level") or "")
        level=levels.get(level_name)
        if level is None and levels:
            level=next(iter(levels.values()))
        bounds=(level or {}).get("region_bounds")
        if not bounds:
            continue
        plan_id=str((level or {}).get("id") or level_name or row.get("code") or "PLAN")
        plan={"plan_id":plan_id,"bounds":tuple(map(float,bounds))}
        board.setdefault("bounds",(
            float(board["plan_area"][0])-.5,float(board["plan_area"][1])-.5,
            float(board["plan_area"][2])+.5,float(board["plan_area"][3])+.5,
        ))
        board.setdefault("title_area",(
            float(board["bounds"][0]),float(board["bounds"][1]),
            float(board["bounds"][2]),float(board["plan_area"][1])-.1,
        ))
        adapted=[]
        for node in nodes:
            if str(node.get("level") or "") not in {"",level_name,plan_id}:
                continue
            item=dict(node);item["plan_id"]=plan_id;adapted.append(item)
        pipeline={
            "topology":{"nodes":adapted},
            "hvac":{"equipment":[]},
            "dimension_requirements":list((network or {}).get("dimension_requirements") or []),
        }
        prior_dimension=((composition.get("dimensioning") or {}).get(str(row.get("code") or row.get("old_sheet"))) or {})
        report=build_and_materialize_plan_dimensions(
            doc,msp,board,plan,{"walls":[],"shafts":[],"columns":[]},pipeline,family,level_name,
            reference_catalog=prior_dimension.get("reference_catalog"),
        )
        dimensioning[str(row.get("code") or row.get("old_sheet"))]=report
        generated_count+=sum(
            1 for item in report.get("materialized") or []
            if item.get("source_kind")=="PLANHA_GENERATED" and item.get("handle")
        )
    doc.saveas(dst)
    exact=validate_exact_file_dimensions(dst,{"dimensioning":dimensioning})
    preservation=[source_preservation_complete(report) for report in dimensioning.values()]
    source_ok=all(item.get("pass") for item in preservation) if preservation else True
    status="PASS" if exact.get("status")=="PASS" and source_ok else "FAIL"
    return {
        "status":status,
        "dimensioning":dimensioning,
        "generated_dimension_count":generated_count,
        "source_preservation_proven":source_ok,
        "exact_file_qa":exact,
        "exact_file_reopened":True,
    }
