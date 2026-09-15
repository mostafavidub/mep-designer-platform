"""Professional, fail-closed execution-detail contract and independent QA."""
from __future__ import annotations

from hashlib import sha256
import json
import math

CONTRACT = "mechanical-execution-detail/1"
CONTROL_WEIGHTS = {
    "scope_matrix": 5, "active_system_coverage": 6, "unique_identity": 5,
    "owner_traceability": 7, "bidirectional_plan_callout": 5,
    "calculation_parameter_parity": 8, "schedule_parameter_parity": 5,
    "executable_geometry": 8, "dimension_completeness": 7,
    "fitting_and_assembly_sequence": 5, "supports_and_anchors": 5,
    "penetration_sleeve_firestop": 6, "insulation_and_corrosion": 4,
    "access_and_service_clearance": 5, "slope_and_flow_direction": 5,
    "coordination_constructability": 6, "print_readability": 4,
    "exact_dxf_entity_parity": 4,
}
assert len(CONTROL_WEIGHTS) == 18 and sum(CONTROL_WEIGHTS.values()) == 100

# These are engineering evidence categories, not guessed numeric defaults.  A
# project must supply the project/calculation-specific values before PASS.
FAMILY_REQUIREMENTS = {
    "sanitary_connection": ("pipe_dn_mm", "slope_percent", "trap", "vent", "cleanout"),
    "cleanout": ("pipe_dn_mm", "access_clearance_mm", "opening_direction"),
    "sanitary_riser": ("pipe_dn_mm", "levels", "cleanout", "offsets"),
    "vent_terminal": ("pipe_dn_mm", "terminal_height_mm", "weather_protection"),
    "vent_riser": ("pipe_dn_mm", "levels", "offsets"),
    "water_connection": ("pipe_dn_mm", "isolation_valve", "union"),
    "water_riser": ("pipe_dn_mm", "levels", "isolation_valves"),
    "radiator_connection": ("pipe_dn_mm", "trv", "lockshield", "flow_connection", "return_connection"),
    "heating_riser": ("pipe_dn_mm", "levels", "balancing_valves"),
    "split_connection": ("liquid_line_mm", "gas_line_mm", "power_isolator", "refrigerant_trap_policy"),
    "condensate_connection": ("pipe_dn_mm", "slope_percent", "trap", "cleanout"),
    "gas_connection": ("pipe_dn_mm", "isolation_valve", "regulator_or_meter"),
    "gas_riser": ("pipe_dn_mm", "levels", "isolation_valves"),
    "fan_connection": ("duct_size_mm", "flexible_connector", "backdraft_damper"),
    "exhaust_terminal": ("duct_size_mm", "weather_louver", "bird_screen"),
    "roof_drain": ("pipe_dn_mm", "catchment_id", "overflow_path"),
    "rainwater_riser": ("pipe_dn_mm", "levels", "offsets"),
}


def _stable(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return sha256(raw.encode()).hexdigest()


def _positive(value):
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def build_execution_detail(spec):
    """Build a governed detail record without inventing project parameters."""
    spec = dict(spec or {}); family = spec.get("family")
    if family not in FAMILY_REQUIREMENTS:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["SUPPORTED_DETAIL_FAMILY"], "detail": None}
    identity = dict(spec.get("identity") or {})
    params = dict(spec.get("parameters") or {})
    missing = ["identity." + key for key in ("source_plan_id", "source_pmm_id", "source_calc_id", "owner_id", "schedule_row_id") if not identity.get(key)]
    missing += ["parameters." + key for key in FAMILY_REQUIREMENTS[family] if params.get(key) in (None, "", [], {}, "PROJECT SELECTION")]
    for key in ("dimensions", "geometry", "installation_components", "constructability", "callout", "standards"):
        if not spec.get(key): missing.append(key)
    if missing:
        return {"status": "INPUT_REQUIRED", "missing_inputs": sorted(missing), "detail": None}
    seed = {"family": family, "identity": identity, "parameters": params}
    detail = {key: spec[key] for key in spec if key not in {"detail_id"}}
    detail["detail_id"] = spec.get("detail_id") or "DT-" + _stable(seed)[:12].upper()
    detail["contract"] = CONTRACT
    return {"status": "PASS", "detail": detail,
            "qa": {"label_only": False, "source_identity_complete": True, "project_parameters_complete": True}}


def evaluate_execution_details(context, exact_output=None):
    """Independently score eighteen controls. Missing proof can never become PASS."""
    context = context or {}; exact_output = exact_output or {}
    missing = {key: [] for key in CONTROL_WEIGHTS}; errors = {key: [] for key in CONTROL_WEIGHTS}
    details = context.get("details") or []; requirements = context.get("requirements") or []
    required_ids = {item for row in requirements for item in row.get("required_ids") or []}
    by_id = {row.get("detail_id"): row for row in details if row.get("detail_id")}
    if not requirements: missing["scope_matrix"].append("EXECUTION_DETAIL_REQUIREMENT_MATRIX")
    elif any(not row.get("system") or not row.get("family") or not row.get("required_ids") for row in requirements): errors["scope_matrix"].append("INCOMPLETE_EXECUTION_DETAIL_REQUIREMENT")
    if set(by_id) != required_ids: errors["active_system_coverage"].append("EXECUTION_DETAIL_SCOPE_MISMATCH")
    if len(by_id) != len(details): errors["unique_identity"].append("MISSING_OR_DUPLICATE_DETAIL_ID")

    calculation_rows = {row.get("calc_id") or row.get("id"): row for row in context.get("calculation_rows") or []}
    schedule_rows = {row.get("schedule_row_id") or row.get("id"): row for row in context.get("schedule_rows") or []}
    callouts = {row.get("detail_id"): row for row in context.get("plan_callouts") or []}
    for did, row in by_id.items():
        family = row.get("family"); ident = row.get("identity") or {}; params = row.get("parameters") or {}
        if family not in FAMILY_REQUIREMENTS: errors["active_system_coverage"].append(f"{did}:UNSUPPORTED_FAMILY"); continue
        for key in ("source_plan_id", "source_pmm_id", "source_calc_id", "owner_id", "schedule_row_id"):
            if not ident.get(key): missing["owner_traceability"].append(f"{did}:{key}")
        co = callouts.get(did) or {}
        if co.get("source_plan_id") != ident.get("source_plan_id") or co.get("bidirectional") is not True:
            errors["bidirectional_plan_callout"].append(f"{did}:CALLOUT_MISMATCH")
        calc = calculation_rows.get(ident.get("source_calc_id"))
        if not calc: missing["calculation_parameter_parity"].append(f"{did}:CALCULATION_ROW")
        else:
            for key in FAMILY_REQUIREMENTS[family]:
                if key in calc and params.get(key) != calc.get(key): errors["calculation_parameter_parity"].append(f"{did}:{key}")
        sched = schedule_rows.get(ident.get("schedule_row_id"))
        if not sched: missing["schedule_parameter_parity"].append(f"{did}:SCHEDULE_ROW")
        elif any(key in sched and params.get(key) != sched.get(key) for key in FAMILY_REQUIREMENTS[family]): errors["schedule_parameter_parity"].append(f"{did}:SCHEDULE_VALUE_MISMATCH")
        geo = row.get("geometry") or {}
        if not _positive(geo.get("entity_count")) or not geo.get("primitives"): errors["executable_geometry"].append(f"{did}:NON_EXECUTABLE_GEOMETRY")
        dims = row.get("dimensions") or []
        if not dims or any(not item.get("parameter") or not _positive(item.get("value")) or not item.get("unit") for item in dims): errors["dimension_completeness"].append(f"{did}:DIMENSION_INCOMPLETE")
        components = row.get("installation_components") or []
        if len(components) < 2 or not row.get("assembly_sequence"): errors["fitting_and_assembly_sequence"].append(f"{did}:ASSEMBLY_INCOMPLETE")
        c = row.get("constructability") or {}
        if not c.get("supports") or not c.get("anchors"): missing["supports_and_anchors"].append(f"{did}:SUPPORT_ANCHOR_EVIDENCE")
        if not all(c.get(k) for k in ("penetration", "sleeve", "firestop")): missing["penetration_sleeve_firestop"].append(f"{did}:PENETRATION_ASSEMBLY")
        if not c.get("insulation") or not c.get("corrosion_protection"): missing["insulation_and_corrosion"].append(f"{did}:PROTECTION_SPEC")
        if not _positive(c.get("service_clearance_mm")) or not c.get("access_path"): errors["access_and_service_clearance"].append(f"{did}:ACCESS_CLEARANCE")
        if c.get("flow_direction") not in {"SHOWN", "NOT_APPLICABLE"} or c.get("slope_status") not in {"SHOWN", "NOT_APPLICABLE"}: errors["slope_and_flow_direction"].append(f"{did}:FLOW_OR_SLOPE")
        if c.get("coordination_status") != "PASS" or c.get("clashes"): errors["coordination_constructability"].append(f"{did}:COORDINATION")
        p = row.get("print_qa") or {}
        if p.get("status") != "PASS" or not _positive(p.get("minimum_text_height_mm")) or p.get("clipped") or p.get("overlaps"): errors["print_readability"].append(f"{did}:PRINT_QA")
    if not exact_output: missing["exact_dxf_entity_parity"].append("EXACT_DXF_DETAIL_EVIDENCE")
    elif exact_output.get("reopened") is not True or exact_output.get("immutable") is not True or set(exact_output.get("executable_detail_ids") or []) != set(by_id): errors["exact_dxf_entity_parity"].append("EXACT_DXF_EXECUTION_DETAIL_PARITY")

    controls=[]
    for name, weight in CONTROL_WEIGHTS.items():
        state = "FAIL" if errors[name] else ("INPUT_REQUIRED" if missing[name] else "PASS")
        controls.append({"id": name, "weight": weight, "status": state, "errors": sorted(set(errors[name])), "missing_inputs": sorted(set(missing[name]))})
    score = sum(row["weight"] for row in controls if row["status"] == "PASS")
    status = "FAIL" if any(row["status"] == "FAIL" for row in controls) else ("INPUT_REQUIRED" if any(row["status"] == "INPUT_REQUIRED" for row in controls) else "PASS")
    return {"contract": CONTRACT, "status": status, "score": score, "controls": controls,
            "release_allowed": status == "PASS" and score == 100,
            "errors": sorted({x for row in controls for x in row["errors"]}),
            "missing_inputs": sorted({x for row in controls for x in row["missing_inputs"]}),
            "evidence_hash": _stable({"context": context, "exact_output": exact_output})}
