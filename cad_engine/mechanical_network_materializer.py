"""Graph-native CAD materialization for authoritative canonical network segments.

The legacy renderer may create sheet frames, copied architecture and supporting
content, but route entities inside approved plan boards are replaced here from
the already-sized canonical graph. This module never computes topology or sizing.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import re
import shutil
import tempfile

import ezdxf
from ezdxf import bbox

from .mechanical_network_topology import _typed_level


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
    sx1, sy1, sx2, sy2 = map(float, source_bounds)
    tx1, ty1, tx2, ty2 = map(float, target_bounds)
    if sx2 <= sx1 or sy2 <= sy1:
        raise ValueError("INVALID_SOURCE_BOUNDS")
    rx = (float(point[0]) - sx1) / (sx2 - sx1)
    ry = (float(point[1]) - sy1) / (sy2 - sy1)
    return (tx1 + rx * (tx2 - tx1), ty1 + ry * (ty2 - ty1))


def _source_extents(src):
    doc = ezdxf.readfile(src)
    ext = bbox.extents(doc.modelspace(), fast=True)
    if not ext.has_data:
        return None
    return [float(ext.extmin.x), float(ext.extmin.y), float(ext.extmax.x), float(ext.extmax.y)]


def _row_level_type(value):
    text = str(value or "").strip().upper()
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
        candidates = []
        for row in manifest:
            if str(row.get("family") or "").upper() != family:
                continue
            if str(row.get("purpose") or "PLAN").upper() != "PLAN":
                continue
            if str(row.get("level") or "").upper() == "SERVICE":
                continue
            if _row_level_type(row.get("level")) != level.get("type"):
                continue
            board = boards.get(row.get("old_sheet")) or {}
            area = board.get("plan_area")
            if isinstance(area, (list, tuple)) and len(area) == 4:
                candidates.append((row, board))
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
        for edge in drawable:
            target = targets[edge["id"]]
            layer, color, lineweight = ROUTE_LAYERS[edge["system"]]
            _ensure_layer(doc, layer, color, lineweight)
            points = [_map_point(point, target["source_bounds"], target["target_bounds"]) for point in edge.get("plan_path") or []]
            if len(points) < 2:
                raise ValueError("DRAWABLE_SEGMENT_PATH_MISSING:" + str(edge.get("id")))
            route = msp.add_lwpolyline(points, dxfattribs={"layer": layer, "lineweight": lineweight})
            _set_identity(route, "NETWORK_SEGMENT", edge)
            midpoint = points[len(points) // 2]
            label = msp.add_mtext(_route_label(edge), dxfattribs={"layer": layer, "char_height": 0.06})
            label.dxf.insert = (midpoint[0] + 0.08, midpoint[1] + 0.08)
            label.dxf.width = 4.2
            _set_identity(label, "NETWORK_ANNOTATION", edge)
            materialized.append(edge["id"])
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
                "reopen_counts": dict(counts), "exact_file_reopened": True,
                "identity_policy": "DXF_XDATA_EDGE_ID_EQUALS_NETWORK_EDGE_ID"}
    except Exception as exc:
        shutil.copy2(backup, dst)
        return {"status": "FAIL", "errors": ["NETWORK_MATERIALIZATION_EXCEPTION:" + str(exc)]}
    finally:
        backup.unlink(missing_ok=True)
