"""Graph-native CAD materialization for authoritative canonical network segments.

The legacy renderer may create sheet frames, copied architecture and supporting
content, but route entities inside approved plan boards are replaced here from
the already-sized canonical graph. This module never computes topology or sizing.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import math
import re
import shutil
import tempfile

import ezdxf
from ezdxf import bbox

from .mechanical_network_topology import _typed_level
from .coordinate_integrity import uniform_fit, map_point, transform_evidence


APPID = "ENGITOOLS_MECHANICAL"
SYSTEM_FAMILY = {
    "cold_water": "WATER", "hot_water": "WATER",
    "sanitary": "SANITARY_VENT", "vent": "SANITARY_VENT",
    "heating_supply": "HEATING", "heating_return": "HEATING",
    "gas": "GAS",
    "refrigerant_liquid": "SPLIT_AC", "refrigerant_gas": "SPLIT_AC", "condensate": "SPLIT_AC",
    "exhaust": "EXHAUST", "roof_rainwater": "ROOF",
}
ROUTE_LAYERS = {
    "sanitary": ("ENGITOOLS-M-SANITARY", 1, 60),
    "vent": ("ENGITOOLS-M-VENT", 3, 30),
    "cold_water": ("ENGITOOLS-M-COLD_WATER", 5, 30),
    "hot_water": ("ENGITOOLS-M-HOT_WATER", 1, 30),
    "heating_supply": ("ENGITOOLS-M-HEAT-FLOW", 2, 35),
    "heating_return": ("ENGITOOLS-M-HEAT-RETURN", 6, 35),
    "gas": ("ENGITOOLS-M-GAS", 2, 35),
    "refrigerant_liquid": ("ENGITOOLS-M-HVAC-REFRIG", 6, 30),
    "refrigerant_gas": ("ENGITOOLS-M-HVAC-REFRIG", 6, 30),
    "condensate": ("ENGITOOLS-M-HVAC-COND", 4, 25),
    "exhaust": ("ENGITOOLS-M-EXHAUST", 6, 30),
    "roof_rainwater": ("ENGITOOLS-M-RAINWATER", 4, 35),
}


def _ensure_layer(doc, name, color, lineweight):
    try:
        layer = doc.layers.get(name)
    except Exception:
        layer = doc.layers.add(name, color=color, lineweight=lineweight)
    layer.dxf.color = color
    layer.dxf.lineweight = lineweight


def _ensure_appid(doc):
    try:
        doc.appids.get(APPID)
    except Exception:
        doc.appids.add(APPID)


def _entity_center(entity):
    try:
        ext = bbox.extents([entity], fast=True)
        if ext.has_data:
            return ((float(ext.extmin.x) + float(ext.extmax.x)) / 2,
                    (float(ext.extmin.y) + float(ext.extmax.y)) / 2)
    except Exception:
        pass
    return None


def _inside(point, bounds, tolerance=1e-6):
    return bool(point and bounds and bounds[0] - tolerance <= point[0] <= bounds[2] + tolerance
                and bounds[1] - tolerance <= point[1] <= bounds[3] + tolerance)


def _map_point(point, source_bounds, target_bounds):
    return map_point(point, uniform_fit(source_bounds, target_bounds))


def _source_extents(src):
    doc = ezdxf.readfile(src)
    ext = bbox.extents(doc.modelspace(), fast=True)
    if not ext.has_data:
        return None
    return [float(ext.extmin.x), float(ext.extmin.y), float(ext.extmax.x), float(ext.extmax.y)]


def _row_level_type(value):
    text = str(value or "").strip().upper()
    # The drawing manifest uses stable public level identifiers while the
    # engineering graph uses semantic level types.  Normalize that boundary
    # explicitly; relying on the free-text parser makes LEVEL-01/LEVEL-02
    # unrecognisable and leaves otherwise valid graph edges without a board.
    manifest_aliases = {
        "LEVEL-00": "GROUND",
        "LEVEL-0": "GROUND",
        "LEVEL-01": "FIRST",
        "LEVEL-1": "FIRST",
        "LEVEL-02": "SECOND",
        "LEVEL-2": "SECOND",
    }
    if text in manifest_aliases:
        return manifest_aliases[text]
    if text in {"GROUND", "FIRST", "SECOND", "ROOF", "BASEMENT", "MEZZANINE"}:
        return text
    if re.fullmatch(r"TYPICAL_[1-9]\d*_[1-9]\d*", text):
        return text
    return _typed_level(value, roof=text == "ROOF")


def _target_board_map(report, network, src):
    composition = (report or {}).get("composition") or {}
    manifest = composition.get("manifest") or []
    boards = composition.get("boards") or {}
    levels = {row.get("id"): row for row in network.get("levels") or []}
    fallback_bounds = _source_extents(src) if len(levels) == 1 else None
    targets = {}
    errors = []
    for edge in network.get("edges") or []:
        if not edge.get("draw_on_plan") or len(edge.get("plan_path") or []) < 2:
            continue
        edge_levels = edge.get("levels") or []
        if len(edge_levels) != 1:
            continue
        level = levels.get(edge_levels[0])
        if not level:
            errors.append("EDGE_LEVEL_UNKNOWN:" + str(edge.get("id")))
            continue
        family = SYSTEM_FAMILY.get(edge.get("system"))
        if not family:
            errors.append("SYSTEM_FAMILY_UNMAPPED:" + str(edge.get("system")))
            continue
        candidate_groups = {0: [], 1: [], 2: []}
        for row in manifest:
            row_family = str(row.get("family") or "").upper()
            # A canonical roof-coordination plan is intentionally shared by
            # roof rainwater, vent terminations and roof water equipment.  It
            # is the approved roof board, not a missing per-system floor plan.
            row_drawing_type = str(row.get("drawing_type") or row.get("approved_drawing_type") or "").upper()
            roof_coordination = (
                level.get("type") == "ROOF"
                and family in {"SANITARY_VENT", "WATER"}
                and (row_family in {"ROOF", "ROOF_RAINWATER"} or row_drawing_type == "ROOF_PLAN")
            )
            row_level_type = _row_level_type(row.get("level"))
            roof_service_fallback = (
                level.get("type") == "ROOF"
                and row_family == family
                and str(row.get("level") or "").upper() == "SERVICE"
                and (
                    str(row.get("purpose") or "PLAN").upper() == "PLAN"
                    or (
                        str(row.get("purpose") or "").upper() == "SCHEMATIC"
                        and str(row.get("derived_support_role") or "").upper() == "VENT_ROOF_TERMINATION"
                    )
                )
            )
            exact_level = row_family == family and row_level_type == level.get("type")
            if not (exact_level or roof_coordination or roof_service_fallback):
                continue
            if (str(row.get("purpose") or "PLAN").upper() != "PLAN"
                    and not roof_coordination and not roof_service_fallback):
                continue
            board = boards.get(row.get("old_sheet")) or {}
            area = board.get("plan_area")
            if isinstance(area, (list, tuple)) and len(area) == 4:
                priority = 0 if exact_level else (1 if roof_coordination else 2)
                candidate_groups[priority].append((row, board))
        candidates = next((candidate_groups[value] for value in (0, 1, 2)
                           if candidate_groups[value]), [])
        if not candidates:
            errors.append("TARGET_PLAN_BOARD_REQUIRED:%s:%s" % (family, level.get("type")))
            continue
        if len(candidates) > 1:
            errors.append("AMBIGUOUS_TARGET_PLAN_BOARD:%s:%s" % (family, level.get("type")))
            continue
        source_bounds = level.get("region_bounds") or fallback_bounds
        if not source_bounds:
            errors.append("SOURCE_LEVEL_BOUNDS_REQUIRED:" + str(level.get("name") or level.get("id")))
            continue
        row, board = candidates[0]
        targets[edge.get("id")] = {
            "row": row, "board": board, "source_bounds": source_bounds,
            "target_bounds": list(board["plan_area"]), "family": family,
        }
    return targets, sorted(set(errors))


def _remove_legacy_route_entities(msp, target_bounds, layers):
    removed = 0
    for entity in list(msp):
        layer = str(getattr(entity.dxf, "layer", "") or "")
        if layer not in layers:
            continue
        if entity.dxftype() not in {"LINE", "LWPOLYLINE", "POLYLINE", "TEXT", "MTEXT", "CIRCLE", "ARC"}:
            continue
        if _inside(_entity_center(entity), target_bounds, tolerance=0.02):
            msp.delete_entity(entity)
            removed += 1
    return removed


def _set_identity(entity, marker, edge):
    entity.set_xdata(APPID, [
        (1000, marker),
        (1000, str(edge.get("id") or "")),
        (1000, str(edge.get("calc_id") or "")),
        (1000, str(edge.get("system") or "")),
        (1000, str(edge.get("size_mm") or edge.get("size") or "")),
        (1000, str(edge.get("material") or "")),
        (1000, str(edge.get("plan_representation_id") or "")),
        (1000, str(edge.get("riser_representation_id") or "")),
        (1000, str(edge.get("schedule_row_id") or "")),
        (1000, str(edge.get("slope_percent") if edge.get("slope_percent") is not None else "")),
        (1000, str(edge.get("downstream_load") if edge.get("downstream_load") is not None else "")),
        (1000, str(edge.get("load_unit") or "")),
        (1000, str(edge.get("from") or "")),
        (1000, str(edge.get("to") or "")),
        (1000, "|".join(str(value) for value in edge.get("levels") or [])),
    ])


def _route_label(edge):
    size = edge.get("size_mm") if edge.get("size_mm") is not None else edge.get("size")
    text = "%s | DN%s | %s" % (str(edge.get("system") or "").upper(), "%g" % float(size), edge.get("material"))
    if edge.get("slope_percent") is not None:
        text += " | S=%g%%" % float(edge.get("slope_percent"))
    return text


def _reopen_counts(dst):
    doc = ezdxf.readfile(dst)
    counts = Counter()
    for entity in doc.modelspace():
        if entity.dxftype() != "LWPOLYLINE":
            continue
        try:
            data = entity.get_xdata(APPID)
        except Exception:
            continue
        strings = [value for code, value in data if code == 1000]
        if len(strings) >= 2 and strings[0] == "NETWORK_SEGMENT":
            counts[strings[1]] += 1
    return counts


def materialize_authoritative_network(src: Path, dst: Path, report: dict, network: dict) -> dict:
    """Replace legacy plan routes with graph-native execution segments transactionally."""
    src = Path(src); dst = Path(dst)
    if not dst.exists():
        return {"status": "FAIL", "errors": ["MATERIALIZATION_TARGET_DXF_MISSING"]}
    if not network.get("edges") or not network.get("levels"):
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["EXECUTION_NETWORK_GRAPH"]}
    incomplete = [edge.get("id") for edge in network.get("edges") or []
                  if not edge.get("size") or not edge.get("material") or not edge.get("calc_id")]
    if incomplete:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["EXECUTION_DATA:" + str(value) for value in incomplete]}
    targets, target_errors = _target_board_map(report, network, src)
    if target_errors:
        return {"status": "INPUT_REQUIRED", "missing_inputs": target_errors}

    drawable = [edge for edge in network.get("edges") or [] if edge.get("id") in targets]
    if not drawable:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["DRAWABLE_AUTHORITY_SEGMENTS"]}

    fd, backup_name = tempfile.mkstemp(prefix="engitools-mechanical-network-", suffix=".dxf")
    Path(backup_name).unlink(missing_ok=True)
    backup = Path(backup_name)
    shutil.copy2(dst, backup)
    try:
        doc = ezdxf.readfile(dst)
        msp = doc.modelspace()
        _ensure_appid(doc)
        by_board = defaultdict(list)
        for edge in drawable:
            target = targets[edge["id"]]
            board_id = str(target["row"].get("old_sheet") or target["row"].get("code") or "")
            by_board[board_id].append((edge, target))
        removed = 0
        for rows in by_board.values():
            layers = set()
            target_bounds = rows[0][1]["target_bounds"]
            for edge, _ in rows:
                layer_info = ROUTE_LAYERS.get(edge.get("system"))
                if not layer_info:
                    raise ValueError("ROUTE_LAYER_UNMAPPED:" + str(edge.get("system")))
                layers.add(layer_info[0])
            removed += _remove_legacy_route_entities(msp, target_bounds, layers)

        materialized = []
        coordinate_transforms = []
        for edge in drawable:
            target = targets[edge["id"]]
            layer, color, lineweight = ROUTE_LAYERS[edge["system"]]
            _ensure_layer(doc, layer, color, lineweight)
            source_points = [tuple(map(float, point[:2])) for point in edge.get("plan_path") or []]
            transform = uniform_fit(target["source_bounds"], target["target_bounds"])
            evidence = transform_evidence(transform, source_points)
            if not evidence["uniform"] or not evidence["roundtrip_pass"]:
                raise ValueError("NON_UNIFORM_OR_NON_REVERSIBLE_COORDINATE_TRANSFORM:" + str(edge.get("id")))
            points = [map_point(point, transform) for point in source_points]
            if len(points) < 2:
                raise ValueError("DRAWABLE_SEGMENT_PATH_MISSING:" + str(edge.get("id")))
            outside = [point for point in points
                       if not _inside(point, target["target_bounds"], tolerance=0.03)]
            if outside:
                # Keep the gate fail-closed, but retain enough bounded evidence
                # to distinguish a small coordinate drift from a wrongly
                # assigned endpoint.  This is intentionally diagnostic only;
                # routes are never clipped or silently moved into the board.
                raise ValueError(
                    "MATERIALIZED_SEGMENT_OUTSIDE_PLAN_BOARD:%s:SOURCE=%s:TARGET=%s:OUTSIDE=%s"
                    % (
                        edge.get("id"),
                        [round(float(value), 6) for value in target["source_bounds"]],
                        [round(float(value), 6) for value in target["target_bounds"]],
                        [[round(float(value), 6) for value in point] for point in outside[:3]],
                    )
                )
            # ``points`` are now in paper-space units.  A fixed 0.01 drawing-unit
            # cutoff incorrectly rejects real, short fixture branches whenever a
            # large architectural source extent is uniformly fitted onto a board.
            # Degeneracy is a geometric-zero condition, not a plotted-length
            # preference: retain every positive, reversible segment and let the
            # downstream legibility/annotation QA judge its presentation.
            materialized_length = sum(
                math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
                for i in range(1, len(points))
            )
            coordinate_scale = max(
                1.0,
                *(abs(value) for point in points for value in point[:2]),
            )
            geometric_zero_tolerance = max(math.ulp(coordinate_scale) * 32, 1e-12)
            if materialized_length <= geometric_zero_tolerance:
                raise ValueError("MATERIALIZED_SEGMENT_DEGENERATE:" + str(edge.get("id")))
            route = msp.add_lwpolyline(points, dxfattribs={"layer": layer, "lineweight": lineweight})
            _set_identity(route, "NETWORK_SEGMENT", edge)
            midpoint = points[len(points) // 2]
            label = msp.add_mtext(_route_label(edge), dxfattribs={"layer": layer, "char_height": 0.06})
            label.dxf.insert = (midpoint[0] + 0.08, midpoint[1] + 0.08)
            label.dxf.width = 4.2
            _set_identity(label, "NETWORK_ANNOTATION", edge)
            materialized.append(edge["id"])
            coordinate_transforms.append({"edge_id": edge["id"], "board_id": str(target["row"].get("old_sheet") or ""), **evidence})
        doc.saveas(dst)

        counts = _reopen_counts(dst)
        expected = set(materialized)
        missing = sorted(value for value in expected if counts.get(value, 0) == 0)
        duplicates = sorted(value for value in expected if counts.get(value, 0) != 1 and counts.get(value, 0) > 0)
        unknown = sorted(value for value in counts if value not in expected)
        if missing or duplicates or unknown:
            shutil.copy2(backup, dst)
            return {"status": "FAIL", "errors": [
                *( ["MATERIALIZED_SEGMENTS_MISSING:" + ",".join(missing)] if missing else [] ),
                *( ["MATERIALIZED_SEGMENTS_NOT_EXACTLY_ONCE:" + ",".join(duplicates)] if duplicates else [] ),
                *( ["UNKNOWN_MATERIALIZED_SEGMENTS:" + ",".join(unknown)] if unknown else [] ),
            ], "exact_file_reopened": True, "reopen_counts": dict(counts)}
        return {"status": "PASS", "removed_legacy_entities": removed,
                "materialized_segments": len(materialized), "expected_segments": len(expected),
                "materialized_edge_ids": sorted(expected),
                "coordinate_transforms": coordinate_transforms,
                "reopen_counts": dict(counts), "exact_file_reopened": True,
                "transactional_exact_output": True,
                "identity_policy": "DXF_XDATA_EDGE_ID_EQUALS_NETWORK_EDGE_ID"}
    except Exception as exc:
        shutil.copy2(backup, dst)
        return {"status": "FAIL", "errors": ["NETWORK_MATERIALIZATION_EXCEPTION:" + str(exc)]}
    finally:
        backup.unlink(missing_ok=True)
