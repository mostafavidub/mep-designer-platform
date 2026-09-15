"""Canonical Plan/Riser/Calculation/Schedule identity and numeric parity gate."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path

import ezdxf

APPID = "ENGITOOLS_MECHANICAL"
NUMERIC_FIELDS = ("size_mm", "slope_percent", "downstream_load")


def _stable(prefix, edge_id):
    return f"{prefix}-" + sha256(str(edge_id).encode()).hexdigest()[:14].upper()


def representation_ids(edge):
    edge_id = edge.get("id")
    return {
        "plan_representation_id": edge.get("plan_representation_id") or _stable("PLANREP", edge_id),
        "riser_representation_id": edge.get("riser_representation_id") or _stable("RISERREP", edge_id),
        "schedule_row_id": edge.get("schedule_row_id") or _stable("SCHROW", edge_id),
    }


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _numeric_equal(left, right, *, tolerance=1e-6):
    a, b = _number(left), _number(right)
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=tolerance, abs_tol=tolerance)


def _projection(edge, calc):
    ids = representation_ids(edge)
    common = {
        "network_edge_id": edge.get("id"), "calc_id": calc.get("calc_id"),
        "system": edge.get("system"), "levels": list(edge.get("levels") or []),
        "from_node_id": edge.get("from"), "to_node_id": edge.get("to"),
        "endpoint_ids": sorted(edge.get("endpoint_ids") or []),
        "size_mm": calc.get("size_mm"), "material": calc.get("material"),
        "slope_percent": calc.get("slope_percent"),
        "downstream_load": calc.get("downstream_load"), "load_unit": calc.get("load_unit"),
    }
    return {
        "identity": {**ids, "calc_id": calc.get("calc_id"), "network_edge_id": edge.get("id")},
        "plan": {**common, "representation_id": ids["plan_representation_id"],
                 "applicable": bool(edge.get("draw_on_plan")), "path": list(edge.get("plan_path") or [])},
        "riser": {**common, "representation_id": ids["riser_representation_id"],
                  "role": edge.get("role"), "shaft_key": edge.get("shaft_key")},
        "calculation": {**common, "representation_id": calc.get("calc_id"),
                        "source": calc.get("source") or calc.get("provenance"),
                        "size_source": calc.get("size_source"), "material_source": calc.get("material_source")},
        "schedule": {**common, "representation_id": ids["schedule_row_id"],
                     "kind": "NETWORK_SEGMENT"},
    }


def _exact_plan_records(path):
    records, malformed = [], []
    doc = ezdxf.readfile(Path(path))
    for entity in doc.modelspace():
        if entity.dxftype() != "LWPOLYLINE":
            continue
        try:
            values = [str(value) for code, value in entity.get_xdata(APPID) if code == 1000]
        except Exception:
            continue
        if not values or values[0] != "NETWORK_SEGMENT":
            continue
        if len(values) < 15:
            malformed.append(str(getattr(entity.dxf, "handle", "UNKNOWN")))
            continue
        records.append({
            "network_edge_id": values[1], "calc_id": values[2], "system": values[3],
            "size_mm": values[4], "material": values[5], "plan_representation_id": values[6],
            "riser_representation_id": values[7], "schedule_row_id": values[8],
            "slope_percent": values[9] or None, "downstream_load": values[10] or None,
            "load_unit": values[11] or None, "from_node_id": values[12], "to_node_id": values[13],
            "levels": values[14].split("|") if values[14] else [],
        })
    return records, malformed


def reconcile_cross_document_outputs(network, calculation_rows, *, exact_dxf=None, exact_required=False):
    """Build four projections and require bidirectional, numeric and exact-file parity."""
    graph = network or {}; edges = list(graph.get("edges") or []); calculations = list(calculation_rows or [])
    errors, missing = [], []
    edge_ids = [row.get("id") for row in edges]; calc_ids = [row.get("calc_id") for row in calculations]
    if not edges: missing.append("AUTHORITATIVE_NETWORK_EDGES")
    if not calculations: missing.append("AUTHORITATIVE_CALCULATION_ROWS")
    if any(not value for value in edge_ids) or len(edge_ids) != len(set(edge_ids)): errors.append("DUPLICATE_OR_MISSING_EDGE_ID")
    if any(not value for value in calc_ids) or len(calc_ids) != len(set(calc_ids)): errors.append("DUPLICATE_OR_MISSING_CALC_ID")
    calc_by_edge = {}
    for row in calculations:
        edge_id = row.get("network_edge_id")
        if not edge_id: errors.append("CALCULATION_EDGE_ID_MISSING:" + str(row.get("calc_id"))); continue
        if edge_id in calc_by_edge: errors.append("MULTIPLE_CALCULATIONS_FOR_EDGE:" + str(edge_id))
        calc_by_edge[edge_id] = row
    edge_by_id = {row.get("id"): row for row in edges if row.get("id")}
    projections = []
    for edge in edges:
        calc = calc_by_edge.get(edge.get("id"))
        if not calc: errors.append("CALCULATION_FOR_EDGE_MISSING:" + str(edge.get("id"))); continue
        if calc.get("calc_id") != edge.get("calc_id"): errors.append("EDGE_CALC_ID_MISMATCH:" + str(edge.get("id")))
        for field in ("size_mm", "material"):
            edge_value = edge.get(field) if field in edge else edge.get("size") if field == "size_mm" else None
            if field == "material": edge_value = edge.get("material")
            if field == "size_mm" and not _numeric_equal(edge_value, calc.get(field)):
                errors.append("NUMERIC_MISMATCH:%s:%s" % (edge.get("id"), field))
            if field == "material" and str(edge_value or "") != str(calc.get(field) or ""):
                errors.append("VALUE_MISMATCH:%s:%s" % (edge.get("id"), field))
        for field in ("slope_percent", "downstream_load"):
            if not _numeric_equal(edge.get(field), calc.get(field)):
                errors.append("NUMERIC_MISMATCH:%s:%s" % (edge.get("id"), field))
        if str(edge.get("load_unit") or "") != str(calc.get("load_unit") or ""):
            errors.append("VALUE_MISMATCH:%s:load_unit" % edge.get("id"))
        if edge.get("draw_on_plan") and len(edge.get("plan_path") or []) < 2:
            errors.append("PLAN_GEOMETRY_MISSING:" + str(edge.get("id")))
        projections.append(_projection(edge, calc))
    orphan_calcs = sorted(str(key) for key in set(calc_by_edge) - set(edge_by_id))
    if orphan_calcs: errors.append("ORPHAN_CALCULATIONS:" + ",".join(orphan_calcs))
    identity_sets = {key: [row["identity"][key] for row in projections]
                     for key in ("plan_representation_id", "riser_representation_id", "schedule_row_id")}
    for key, values in identity_sets.items():
        if any(not value for value in values) or len(values) != len(set(values)):
            errors.append("DUPLICATE_OR_MISSING_" + key.upper())

    exact_records, malformed = [], []
    if exact_dxf is not None:
        try: exact_records, malformed = _exact_plan_records(exact_dxf)
        except Exception as exc: errors.append("EXACT_DXF_REOPEN_FAILED:" + type(exc).__name__)
    elif exact_required:
        missing.append("EXACT_DXF_REQUIRED")
    if malformed: errors.append("MALFORMED_PLAN_IDENTITY_XDATA:" + ",".join(malformed))
    expected_plan = {row["identity"]["network_edge_id"]: row for row in projections if row["plan"]["applicable"]}
    actual_counts = Counter(row["network_edge_id"] for row in exact_records)
    if exact_dxf is not None:
        for edge_id, projection in expected_plan.items():
            if actual_counts.get(edge_id) != 1:
                errors.append("EXACT_PLAN_REPRESENTATION_COUNT:%s:%s" % (edge_id, actual_counts.get(edge_id, 0)))
                continue
            actual = next(row for row in exact_records if row["network_edge_id"] == edge_id)
            expected = projection["identity"]
            for key in ("calc_id", "plan_representation_id", "riser_representation_id", "schedule_row_id"):
                if actual.get(key) != expected.get(key): errors.append("EXACT_IDENTITY_MISMATCH:%s:%s" % (edge_id, key))
            for key in NUMERIC_FIELDS:
                if not _numeric_equal(actual.get(key), projection["plan"].get(key)):
                    errors.append("EXACT_NUMERIC_MISMATCH:%s:%s" % (edge_id, key))
            for key in ("system", "material", "load_unit", "from_node_id", "to_node_id"):
                if str(actual.get(key) or "") != str(projection["plan"].get(key) or ""):
                    errors.append("EXACT_VALUE_MISMATCH:%s:%s" % (edge_id, key))
            if actual.get("levels") != projection["plan"].get("levels"):
                errors.append("EXACT_LEVEL_MISMATCH:" + edge_id)
        unknown = sorted(set(actual_counts) - set(expected_plan))
        if unknown: errors.append("UNKNOWN_EXACT_PLAN_REPRESENTATIONS:" + ",".join(unknown))

    checks = {
        "authoritative_graph": bool(edges), "unique_edge_identity": bool(edge_ids) and len(edge_ids) == len(set(edge_ids)),
        "one_calculation_per_edge": len(calc_by_edge) == len(edges), "calculation_to_edge_coverage": not orphan_calcs,
        "calculation_provenance": all(row["calculation"].get("source") for row in projections),
        "plan_projection_complete": all(not row["plan"]["applicable"] or len(row["plan"]["path"]) >= 2 for row in projections),
        "riser_projection_complete": len(projections) == len(edges), "schedule_projection_complete": len(projections) == len(edges),
        "unique_plan_representation": len(identity_sets.get("plan_representation_id", [])) == len(set(identity_sets.get("plan_representation_id", []))),
        "unique_riser_representation": len(identity_sets.get("riser_representation_id", [])) == len(set(identity_sets.get("riser_representation_id", []))),
        "unique_schedule_row": len(identity_sets.get("schedule_row_id", [])) == len(set(identity_sets.get("schedule_row_id", []))),
        "size_parity": not any(":size_mm" in row for row in errors), "material_parity": not any(":material" in row for row in errors),
        "slope_parity": not any(":slope_percent" in row for row in errors), "load_parity": not any(":downstream_load" in row or ":load_unit" in row for row in errors),
        "level_node_parity": not any("LEVEL_MISMATCH" in row or "VALUE_MISMATCH" in row and any(x in row for x in ("from_node_id","to_node_id")) for row in errors),
        "orphan_output_zero": not orphan_calcs and not any("UNKNOWN_EXACT" in row for row in errors),
        "exact_file_identity": (not exact_required and exact_dxf is None) or (
            exact_dxf is not None and not malformed
            and all(actual_counts.get(key) == 1 for key in expected_plan)
            and not any(row.startswith(("EXACT_", "UNKNOWN_EXACT")) for row in errors)),
    }
    failed = [name for name, passed in checks.items() if not passed]
    status = "FAIL" if errors else ("INPUT_REQUIRED" if missing or failed else "PASS")
    registry = {"records": projections,
                "schedule_rows": [row["schedule"] for row in projections],
                "identity_hash": sha256(json.dumps(projections, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()}
    return {"status": status, "rule_id": "MEP-PRCS-001", "registry": registry,
            "errors": sorted(set(errors)), "missing_inputs": sorted(set(missing)), "checks": checks,
            "failed_checks": failed, "passed_count": sum(checks.values()), "required_count": len(checks),
            "score": round(100 * sum(checks.values()) / len(checks), 2),
            "coverage": {"edges": len(edges), "calculations": len(calculations), "plans": len(expected_plan),
                         "risers": len(projections), "schedules": len(projections), "exact_plans": len(exact_records)}}
