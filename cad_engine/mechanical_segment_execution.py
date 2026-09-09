"""Explicit execution sizing/material authority for v19 network segments.

No fixture load, sizing table, material, slope percentage, or route offset is
supplied by this module. Existing values carried by an authoritative supplied
graph are accepted as explicit evidence; otherwise a project/system basis is
required fail-closed.
"""
from __future__ import annotations

import math
import re


PAIRED_SYSTEMS = (("cold_water", "hot_water"), ("sanitary", "vent"),
                  ("heating_supply", "heating_return"),
                  ("refrigerant_liquid", "refrigerant_gas"))
GRAVITY_SYSTEMS = {"sanitary", "roof_rainwater"}


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group())
    except (TypeError, ValueError):
        return None


def _explicit_rows(rows):
    by_edge = {}
    by_calc = {}
    errors = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        edge_id = row.get("network_edge_id") or row.get("edge_id")
        calc_id = row.get("calc_id")
        if edge_id:
            if edge_id in by_edge:
                errors.append("DUPLICATE_SEGMENT_DESIGN_ROW:" + str(edge_id))
            by_edge[edge_id] = row
        if calc_id:
            if calc_id in by_calc and by_calc[calc_id] is not row:
                errors.append("DUPLICATE_CALCULATION_ID:" + str(calc_id))
            by_calc[calc_id] = row
    return by_edge, by_calc, errors


def _pick_size(load, table):
    valid = []
    for row in table or []:
        maximum = _number(row.get("max_load")) if isinstance(row, dict) else None
        size = _number(row.get("size_mm")) if isinstance(row, dict) else None
        if maximum is None or size is None:
            return None, "INVALID_EXPLICIT_SIZE_TABLE"
        valid.append((maximum, size))
    for maximum, size in sorted(valid, key=lambda value: value[0]):
        if load <= maximum:
            return size, None
    return None, "EXPLICIT_SIZE_TABLE_RANGE_EXCEEDED"


def _shift_path(path, offset):
    if not path:
        return []
    if offset in (None, [], ()):
        return [(float(p[0]), float(p[1])) for p in path]
    if not isinstance(offset, (list, tuple)) or len(offset) != 2:
        return None
    dx = _number(offset[0]); dy = _number(offset[1])
    if dx is None or dy is None:
        return None
    return [(float(p[0]) + dx, float(p[1]) + dy) for p in path]


def _fittings(path):
    rows = []
    for index in range(1, len(path or []) - 1):
        a, b, c = path[index - 1], path[index], path[index + 1]
        v1 = (a[0] - b[0], a[1] - b[1]); v2 = (c[0] - b[0], c[1] - b[1])
        n1 = math.hypot(*v1); n2 = math.hypot(*v2)
        if n1 <= 1e-12 or n2 <= 1e-12:
            continue
        cosine = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
        angle = round(180.0 - math.degrees(math.acos(cosine)), 3)
        if angle > 0.001:
            rows.append({"type": "DIRECTION_CHANGE", "angle_deg": angle, "source": "ROUTE_GEOMETRY"})
    return rows


def _path_key(path):
    return tuple((round(float(p[0]), 6), round(float(p[1]), 6)) for p in path or [])


def design_authoritative_segments(network, design_basis=None, calculation_rows=None):
    """Enrich every graph edge with explicit execution data and stable identities."""
    if not isinstance(network, dict) or not network.get("nodes") or not network.get("edges"):
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["NETWORK_GRAPH"], "network": None,
                "calculation_rows": [], "annotations": []}
    basis = design_basis or {}
    systems_basis = basis.get("systems") if isinstance(basis, dict) else None
    systems_basis = systems_basis if isinstance(systems_basis, dict) else {}
    by_edge, by_calc, row_errors = _explicit_rows(calculation_rows)
    if row_errors:
        return {"status": "FAIL", "errors": sorted(set(row_errors)), "network": None,
                "calculation_rows": [], "annotations": []}

    errors = []
    missing = []
    enriched_edges = []
    output_rows = []
    annotations = []
    nodes_by_id = {row.get("id"): row for row in network.get("nodes") or [] if row.get("id")}

    for edge in network.get("edges") or []:
        edge_id = edge.get("id")
        calc_id = edge.get("calc_id")
        if not calc_id:
            errors.append("NETWORK_EDGE_CALC_ID_REQUIRED:" + str(edge_id))
            continue
        row = by_edge.get(edge_id) or by_calc.get(calc_id) or {}
        if row.get("calc_id") not in (None, "", calc_id):
            errors.append("CALC_ID_MISMATCH:" + str(edge_id))
            continue
        cfg = systems_basis.get(edge.get("system")) or {}

        row_size = row.get("size_mm") if "size_mm" in row else row.get("size")
        size = _number(row_size)
        if size is None:
            size = _number(edge.get("size_mm") if edge.get("size_mm") is not None else edge.get("size"))
        downstream_load = _number(row.get("downstream_load"))
        load_unit = row.get("load_unit")
        size_source = row.get("size_source") or edge.get("size_source")
        if size is not None and not size_source:
            size_source = "SUPPLIED_NETWORK_GRAPH" if edge.get("size") is not None or edge.get("size_mm") is not None else calc_id

        if size is None:
            endpoint_loads = cfg.get("endpoint_loads") if isinstance(cfg, dict) else None
            load_by_type = cfg.get("endpoint_load_by_type") if isinstance(cfg, dict) else None
            if not isinstance(endpoint_loads, dict) and isinstance(load_by_type, dict):
                endpoint_loads = {}
                for endpoint_id in edge.get("endpoint_ids") or []:
                    endpoint_type = (nodes_by_id.get(endpoint_id) or {}).get("type")
                    if endpoint_type in load_by_type:
                        endpoint_loads[endpoint_id] = load_by_type[endpoint_type]
            size_table = cfg.get("size_table") if isinstance(cfg, dict) else None
            load_unit = cfg.get("load_unit") if isinstance(cfg, dict) else None
            if not isinstance(endpoint_loads, dict):
                missing.append("ENDPOINT_LOADS:%s" % edge.get("system"))
            if not isinstance(size_table, list) or not size_table:
                missing.append("SIZE_TABLE:%s" % edge.get("system"))
            if not load_unit:
                missing.append("LOAD_UNIT:%s" % edge.get("system"))
            endpoint_ids = edge.get("endpoint_ids") or []
            unknown = [value for value in endpoint_ids if not isinstance(endpoint_loads, dict) or _number(endpoint_loads.get(value)) is None]
            if unknown:
                missing.extend("ENDPOINT_LOAD:%s:%s" % (edge.get("system"), value) for value in unknown)
            if not unknown and isinstance(endpoint_loads, dict) and isinstance(size_table, list) and size_table and load_unit:
                downstream_load = sum(float(endpoint_loads[value]) for value in endpoint_ids)
                size, pick_error = _pick_size(downstream_load, size_table)
                if pick_error:
                    errors.append(pick_error + ":" + str(edge_id))
                else:
                    size_source = "EXPLICIT_SYSTEM_SIZE_TABLE:" + str(edge.get("system"))

        material = row.get("material") or edge.get("material") or cfg.get("material")
        material_source = row.get("material_source") or edge.get("material_source") or cfg.get("material_source")
        if material and not material_source:
            material_source = "SUPPLIED_NETWORK_GRAPH" if edge.get("material") else None
        if not material:
            missing.append("MATERIAL:%s" % edge.get("system"))
        if not material_source:
            missing.append("MATERIAL_SOURCE:%s" % edge.get("system"))

        slope = _number(row.get("slope_percent")) if "slope_percent" in row else _number(edge.get("slope_percent"))
        requires_slope = row.get("requires_slope") if "requires_slope" in row else edge.get("requires_slope")
        if requires_slope is None:
            requires_slope = cfg.get("requires_slope") if "requires_slope" in cfg else edge.get("system") in GRAVITY_SYSTEMS
        if bool(requires_slope) and slope is None:
            slope = _number(cfg.get("slope_percent"))
            if slope is None:
                missing.append("SLOPE_PERCENT:%s" % edge.get("system"))

        path = _shift_path(edge.get("plan_path") or [], cfg.get("plan_offset_xy") if isinstance(cfg, dict) else None)
        if path is None:
            errors.append("INVALID_PLAN_OFFSET:%s" % edge.get("system"))
            path = []

        enriched = dict(edge)
        enriched.update({
            "size": size, "size_mm": size, "material": material, "slope_percent": slope,
            "requires_slope": bool(requires_slope),
            "size_source": size_source, "material_source": material_source,
            "plan_path": path, "fittings": _fittings(path),
            "plan_id": calc_id, "riser_id": calc_id, "schedule_id": calc_id,
        })
        enriched_edges.append(enriched)
        row_source = "EXPLICIT_SEGMENT_ROW" if row and any(key in row for key in ("size", "size_mm", "material")) else (
            "SUPPLIED_NETWORK_GRAPH" if edge.get("size") is not None or edge.get("size_mm") is not None else "EXPLICIT_SYSTEM_DESIGN_BASIS")
        output_rows.append({
            "calc_id": calc_id, "network_edge_id": edge_id, "system": edge.get("system"),
            "downstream_endpoint_ids": sorted(edge.get("endpoint_ids") or []),
            "downstream_load": downstream_load, "load_unit": load_unit,
            "size_mm": size, "material": material, "slope_percent": slope,
            "size_source": size_source, "material_source": material_source,
            "source": row_source,
        })
        label = "DN%s | %s" % (("%g" % size) if size is not None else "?", material or "?")
        if slope is not None:
            label += " | S=%g%%" % slope
        annotations.append({"network_edge_id": edge_id, "calc_id": calc_id, "text": label,
                            "source": "SEGMENT_EXECUTION_RECORD"})

    if errors:
        return {"status": "FAIL", "errors": sorted(set(errors)), "missing_inputs": sorted(set(missing)),
                "network": None, "calculation_rows": output_rows, "annotations": annotations}
    if missing:
        return {"status": "INPUT_REQUIRED", "missing_inputs": sorted(set(missing)), "errors": [],
                "network": None, "calculation_rows": output_rows, "annotations": annotations}

    geometry_rows = [row for row in enriched_edges if row.get("draw_on_plan") and len(row.get("plan_path") or []) >= 2]
    duplicate_same = []
    seen = {}
    for row in geometry_rows:
        key = (row.get("system"), tuple(row.get("levels") or []), _path_key(row.get("plan_path")))
        if key in seen:
            duplicate_same.extend([seen[key], row.get("id")])
        else:
            seen[key] = row.get("id")
    if duplicate_same:
        return {"status": "FAIL", "errors": ["DUPLICATE_EXECUTION_GEOMETRY:" + ",".join(sorted(set(duplicate_same)))],
                "network": None, "calculation_rows": output_rows, "annotations": annotations}

    overlay_missing = []
    for system_a, system_b in PAIRED_SYSTEMS:
        a_rows = [row for row in geometry_rows if row.get("system") == system_a]
        b_rows = [row for row in geometry_rows if row.get("system") == system_b]
        b_keys = {(tuple(row.get("levels") or []), _path_key(row.get("plan_path"))) for row in b_rows}
        if any((tuple(row.get("levels") or []), _path_key(row.get("plan_path"))) in b_keys for row in a_rows):
            overlay_missing.append("PLAN_SEPARATION_OFFSET:%s:%s" % (system_a, system_b))
    if overlay_missing:
        return {"status": "INPUT_REQUIRED", "missing_inputs": sorted(set(overlay_missing)), "errors": [],
                "network": None, "calculation_rows": output_rows, "annotations": annotations}

    enriched_network = dict(network)
    enriched_network["edges"] = enriched_edges
    enriched_network["execution_authority"] = "EXPLICIT_PROJECT_OR_SYSTEM_BASIS_ONLY"
    enriched_network["quality"] = {**(network.get("quality") or {}),
        "execution_segments": len(enriched_edges), "execution_segments_complete": len(enriched_edges),
        "duplicate_execution_geometry": 0, "paired_system_overlays": 0,
    }
    return {"status": "PASS", "network": enriched_network, "calculation_rows": output_rows,
            "annotations": annotations, "qa": {"one_calc_row_per_edge": len(output_rows) == len(enriched_edges),
            "hidden_numeric_defaults": False, "reference_corpus_values_used_as_defaults": False}}
