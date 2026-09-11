"""Independent, fail-closed reasonableness gate for mechanical calculations.

This module does not calculate design values.  It verifies that canonical
calculation records are dimensionally explicit, physically plausible,
conservative across a network, traceable, and independently reviewed before a
submission-ready artifact can be claimed.
"""
from __future__ import annotations

import math
from collections import defaultdict


SCHEMA = "mechanical-calculation-reasonableness/1"

# Broad safety envelopes.  They detect unit/scale corruption and impossible
# values; they are not design defaults and never replace project/code bases.
SAFETY_LIMITS = {
    "size_mm": (6.0, 1200.0),
    "slope_percent": (0.1, 15.0),
    "downstream_load": (0.0, 10_000_000.0),
    "flow_lps": (0.0, 10_000.0),
    "flow_m3h": (0.0, 100_000.0),
    "velocity_m_s": (0.0, 15.0),
    "pressure_drop_pa_m": (0.0, 100_000.0),
    "equivalent_length_m": (0.0, 10_000.0),
    "friction_head_m": (0.0, 2_000.0),
    "pump_head_m": (0.0, 2_000.0),
    "capacity_w": (0.0, 50_000_000.0),
    "capacity_btu_h": (0.0, 200_000_000.0),
}

UNIT_BY_FIELD = {
    "size_mm": "mm", "slope_percent": "%", "downstream_load": "load_unit",
    "flow_lps": "L/s", "flow_m3h": "m3/h", "velocity_m_s": "m/s",
    "pressure_drop_pa_m": "Pa/m", "equivalent_length_m": "m",
    "friction_head_m": "m", "pump_head_m": "m", "capacity_w": "W",
    "capacity_btu_h": "BTU/h",
}


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _limits(payload):
    configured = (((payload.get("network_design_basis") or {}).get("reasonableness_limits")) or {})
    result = dict(SAFETY_LIMITS)
    for key, value in configured.items():
        if isinstance(value, (list, tuple)) and len(value) == 2 and all(_number(x) is not None for x in value):
            result[key] = (float(value[0]), float(value[1]))
    return result


def _path_length_m(edge, drawing_unit_to_m):
    path = edge.get("plan_path") or []
    if len(path) < 2:
        return None
    return sum(math.hypot(float(b[0])-float(a[0]), float(b[1])-float(a[1]))
               for a, b in zip(path, path[1:])) * drawing_unit_to_m


def evaluate_calculation_reasonableness(payload: dict) -> dict:
    rows = payload.get("calculation_rows") or []
    graph = payload.get("network_graph") or {}
    basis = payload.get("network_design_basis") or {}
    errors, missing, warnings, checks = [], [], [], {}

    unit_to_m = _number(basis.get("drawing_unit_to_m"))
    if unit_to_m is None or unit_to_m <= 0:
        missing.append("DRAWING_UNIT_TO_M")
    checks["canonical_units"] = not missing

    by_edge, calc_ids = {}, set()
    limits = _limits(payload)
    for index, row in enumerate(rows):
        label = str(row.get("calc_id") or f"ROW-{index}")
        calc_id = row.get("calc_id")
        edge_id = row.get("network_edge_id") or row.get("edge_id")
        if not calc_id:
            missing.append(f"{label}:CALC_ID")
        elif calc_id in calc_ids:
            errors.append(f"DUPLICATE_CALC_ID:{calc_id}")
        calc_ids.add(calc_id)
        if edge_id:
            by_edge[edge_id] = row
        if not row.get("source") and not row.get("provenance"):
            missing.append(f"{label}:PROVENANCE")
        if not row.get("system"):
            missing.append(f"{label}:SYSTEM")
        for field, (low, high) in limits.items():
            if field not in row or row.get(field) is None:
                continue
            value = _number(row[field])
            if value is None:
                errors.append(f"{label}:NON_FINITE:{field}")
            elif value < low or value > high:
                errors.append(f"{label}:OUT_OF_RANGE:{field}:{value:g}")
            if field == "downstream_load" and not row.get("load_unit"):
                missing.append(f"{label}:LOAD_UNIT")
    checks["finite_bounded_values"] = not any("OUT_OF_RANGE" in x or "NON_FINITE" in x for x in errors)
    checks["calculation_provenance"] = not any("PROVENANCE" in x for x in missing)

    edges = graph.get("edges") or []
    edge_ids = {edge.get("id") for edge in edges}
    if set(by_edge) != edge_ids:
        absent = sorted(str(x) for x in edge_ids-set(by_edge))
        extra = sorted(str(x) for x in set(by_edge)-edge_ids)
        if absent: errors.append("CALCULATION_ROWS_MISSING_EDGES:" + ",".join(absent))
        if extra: errors.append("CALCULATION_ROWS_UNKNOWN_EDGES:" + ",".join(extra))
    checks["plan_riser_schedule_identity"] = set(by_edge) == edge_ids

    # Geometry and equivalent length: an equivalent length below the measured
    # route is impossible; a huge multiplier is a likely scale/frame leak.
    if unit_to_m and unit_to_m > 0:
        for edge in edges:
            row = by_edge.get(edge.get("id")) or {}
            actual = _path_length_m(edge, unit_to_m)
            equivalent = _number(row.get("equivalent_length_m"))
            if actual is not None and equivalent is not None:
                if equivalent + 1e-6 < actual:
                    errors.append(f"{row.get('calc_id')}:EQUIVALENT_LENGTH_BELOW_ROUTE")
                elif actual > 0 and equivalent / actual > 10:
                    errors.append(f"{row.get('calc_id')}:EQUIVALENT_LENGTH_SCALE_ANOMALY")
    checks["geometry_length_sanity"] = not any("EQUIVALENT_LENGTH" in x for x in errors)

    # A parent/main cannot carry less load than a connected child/branch.
    for edge in edges:
        row = by_edge.get(edge.get("id")) or {}
        parent_id = edge.get("parent_edge_id") or row.get("parent_edge_id")
        if parent_id and parent_id in by_edge:
            child = _number(row.get("downstream_load"))
            parent = _number(by_edge[parent_id].get("downstream_load"))
            if child is not None and parent is not None and parent + 1e-9 < child:
                errors.append(f"NETWORK_CONSERVATION:{parent_id}<{edge.get('id')}")
    checks["network_conservation"] = not any(x.startswith("NETWORK_CONSERVATION") for x in errors)

    requirements = payload.get("equipment_requirements") or {}
    totals = payload.get("calculation_totals") or {}
    pump_required = bool(totals.get("booster_required") or requirements.get("booster_required"))
    pump_head = _number(totals.get("pump_head_m"))
    if pump_required and (pump_head is None or pump_head <= 0):
        errors.append("PUMP_HEAD_ZERO_OR_MISSING_WHEN_BOOSTER_REQUIRED")
    declared_branches = totals.get("branches")
    endpoint_count = sum(len(edge.get("endpoint_ids") or []) for edge in edges)
    if declared_branches is not None and _number(declared_branches) == 0 and endpoint_count > 0:
        errors.append("BRANCHES_ZERO_WITH_CONNECTED_ENDPOINTS")
    checks["aggregate_sanity"] = not any(x in errors for x in (
        "PUMP_HEAD_ZERO_OR_MISSING_WHEN_BOOSTER_REQUIRED", "BRANCHES_ZERO_WITH_CONNECTED_ENDPOINTS"))

    # Required equipment capacity and pump head consistency.
    selected = payload.get("selected_equipment") or payload.get("equipment_selection") or []
    selected = selected if isinstance(selected, list) else selected.get("records") or selected.get("equipment") or []
    selected_by_id = {x.get("id") or x.get("tag"): x for x in selected}
    for item in requirements.get("equipment") or []:
        tag = item.get("id") or item.get("tag")
        chosen = selected_by_id.get(tag)
        if not chosen:
            missing.append(f"EQUIPMENT_SELECTION:{tag}")
            continue
        need = _number(item.get("required_capacity_w") or item.get("required_capacity_btu_h"))
        have = _number(chosen.get("capacity_w") or chosen.get("capacity_btu_h"))
        if need is not None and (have is None or have < need):
            errors.append(f"UNDERSIZED_EQUIPMENT:{tag}")
        max_oversize = _number(item.get("max_oversize_ratio"))
        if need and have and max_oversize and have/need > max_oversize:
            errors.append(f"OVERSIZED_EQUIPMENT:{tag}")
    checks["equipment_selection"] = not any("EQUIPMENT" in x for x in errors+missing)

    sensitivity = payload.get("sensitivity_checks")
    if sensitivity is None:
        missing.append("SENSITIVITY_CHECKS")
    else:
        for case in sensitivity:
            input_delta = abs(_number(case.get("input_delta_ratio")) or 0)
            output_delta = abs(_number(case.get("output_delta_ratio")) or 0)
            maximum = _number(case.get("max_response_ratio"))
            if maximum is None:
                missing.append(f"SENSITIVITY_LIMIT:{case.get('id','UNKNOWN')}")
            elif input_delta > 0 and output_delta/input_delta > maximum:
                errors.append(f"SENSITIVITY_JUMP:{case.get('id','UNKNOWN')}")
    checks["sensitivity"] = sensitivity is not None and not any("SENSITIVITY" in x for x in errors+missing)

    review = payload.get("engineer_review") or {}
    reviewed_ids = review.get("reviewed_calculation_ids") or review.get("calculation_ids")
    reviewer = review.get("reviewer") or review.get("reviewer_id")
    if not reviewer or not review.get("review_evidence_sha256") or not reviewed_ids:
        missing.append("INDEPENDENT_ENGINEER_REVIEW")
    elif set(reviewed_ids) - calc_ids:
        errors.append("ENGINEER_REVIEW_UNKNOWN_CALCULATION")
    checks["independent_engineer_review"] = not any("ENGINEER_REVIEW" in x for x in errors+missing)

    status = "FAIL" if errors else ("INPUT_REQUIRED" if missing else ("WARNING" if warnings else "PASS"))
    return {"schema": SCHEMA, "status": status, "release_allowed": status == "PASS",
            "errors": sorted(set(errors)), "missing_inputs": sorted(set(missing)),
            "warnings": sorted(set(warnings)), "checks": checks,
            "checked_rows": len(rows), "checked_edges": len(edges),
            "safety_limits_are_design_defaults": False}
