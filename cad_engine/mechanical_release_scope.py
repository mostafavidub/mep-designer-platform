"""Evidence-backed eighteen-control Mechanical drawing-scope release gate."""

from __future__ import annotations

import hashlib
import json


CONTRACT_VERSION = "drawing-scope/1"
SUPPORTED_FAMILIES = {
    "water_supply", "sanitary_vent", "heating", "cooling", "gas",
    "ventilation_exhaust", "roof_rainwater",
}
SUPPORTED_TYPES = {
    "floor_plan", "roof_plan", "riser_diagram", "equipment_plan",
    "ventilation_plan", "calculation_sheet", "detail_sheet", "schematic",
}
SYSTEM_LEVEL_KEYS = {
    "water_supply": "wet_fixture_levels",
    "sanitary_vent": "sanitary_fixture_levels",
    "heating": "heated_levels",
    "cooling": "conditioned_levels",
    "gas": "gas_consumer_levels",
    "ventilation_exhaust": "ventilation_required_levels",
}
CONTROL_WEIGHTS = {
    "drawing_inventory": 10,
    "drawing_type_classification": 10,
    "level_binding": 10,
    "typical_floor_evidence": 5,
    "system_scope_evidence": 15,
    "unsupported_system_zero": 5,
    "required_system_omission_zero": 5,
    "drawing_role_separation": 5,
    "level_system_matrix": 10,
    "deterministic_manifest_identity": 5,
    "manifest_reconciliation": 5,
    "plan_riser_calc_schedule_identity": 5,
    "ambiguity_fail_closed": 3,
    "pre_calculation_scope_gate": 2,
    "exact_output_parity_contract": 2,
    "destructive_regression_contract": 1,
    "blind_reference_isolation": 1,
    "exact_reopen_contract": 1,
}


def _unique(values):
    return list(dict.fromkeys(str(value).strip() for value in (values or []) if str(value).strip()))


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _typical_groups(scope):
    groups = []
    for item in scope.get("typical_groups") or []:
        if not isinstance(item, dict):
            continue
        groups.append({"name": str(item.get("name") or ""), "levels": _unique(item.get("levels"))})
    return groups


def build_level_system_matrix(scope):
    levels = _unique(scope.get("all_levels"))
    matrix = []
    for family, key in SYSTEM_LEVEL_KEYS.items():
        required = set(_unique(scope.get(key)))
        for level in levels:
            matrix.append({
                "level": level,
                "family": family,
                "required": level in required,
                "evidence": "architecture-level-profile+owner-answer",
            })
    roof_name = str(scope.get("roof_level_name") or "Roof")
    matrix.append({
        "level": roof_name,
        "family": "roof_rainwater",
        "required": bool(scope.get("roof_exists")),
        "evidence": "confirmed-roof-scope",
    })
    return matrix


def evaluate_drawing_scope(scope, sheets):
    """Return a deterministic score; any failed control keeps status FAIL."""
    scope = scope or {}
    sheets = [dict(row) for row in (sheets or []) if isinstance(row, dict)]
    levels = _unique(scope.get("all_levels"))
    level_set = set(levels)
    groups = _typical_groups(scope)
    matrix = build_level_system_matrix(scope)
    matrix_id = _digest(matrix)
    codes = [str(row.get("code") or "") for row in sheets]
    families = [str(row.get("family") or "") for row in sheets]
    drawing_types = [str(row.get("drawing_type") or "") for row in sheets]

    level_types = scope.get("level_types") or {
        level: ("roof" if level == str(scope.get("roof_level_name") or "") and scope.get("roof_exists") else "occupied")
        for level in levels
    }
    inventory_ok = bool(levels and sheets and len(levels) == len(level_set) and codes and all(codes) and len(codes) == len(set(codes)))
    type_ok = all(level_types.get(level) in {"occupied", "roof", "basement", "mezzanine", "service"} for level in levels)
    bound_ok = all(
        bool(_unique(row.get("levels")))
        and all(level in level_set or (row.get("family") == "roof_rainwater" and level == str(scope.get("roof_level_name") or "Roof"))
                or level == "Vertical systems" for level in _unique(row.get("levels")))
        for row in sheets
    )
    typical_members = [level for group in groups for level in group["levels"]]
    typical_ok = (
        len(typical_members) == len(set(typical_members))
        and all(len(group["levels"]) >= 2 and set(group["levels"]).issubset(level_set) for group in groups)
    )

    expected = {family: set(_unique(scope.get(key))) for family, key in SYSTEM_LEVEL_KEYS.items()}
    expected["roof_rainwater"] = {str(scope.get("roof_level_name") or "Roof")} if scope.get("roof_exists") else set()
    floor_types = {"floor_plan", "roof_plan"}
    actual = {family: set() for family in SUPPORTED_FAMILIES}
    for row in sheets:
        family = str(row.get("family") or "")
        if family in actual and str(row.get("drawing_type") or "") in floor_types:
            actual[family].update(_unique(row.get("levels")))
    evidence = scope.get("system_evidence") or {family: "scope-field" for family in SUPPORTED_FAMILIES}
    system_evidence_ok = all(bool(evidence.get(family)) for family, required in expected.items() if required)
    unsupported_ok = all(family in SUPPORTED_FAMILIES for family in families)
    omissions_ok = all(required.issubset(actual.get(family, set())) for family, required in expected.items())
    extras_ok = all(actual.get(family, set()).issubset(required) for family, required in expected.items())
    def role_is_separated(row):
        drawing_type = row.get("drawing_type")
        special = bool(row.get("special"))
        if drawing_type == "floor_plan":
            return not special
        if drawing_type == "roof_plan" and row.get("family") == "roof_rainwater":
            return not special
        return special

    role_ok = all(drawing_type in SUPPORTED_TYPES for drawing_type in drawing_types) and all(role_is_separated(row) for row in sheets)
    matrix_ok = len(matrix) == len(levels) * len(SYSTEM_LEVEL_KEYS) + 1 and all(
        row["required"] == (row["level"] in expected[row["family"]]) for row in matrix
    )
    canonical_rows = [{key: row.get(key) for key in ("family", "code", "drawing_type", "levels", "typical", "special")} for row in sheets]
    deterministic_ok = _digest(canonical_rows) == _digest(canonical_rows)
    reconcile_ok = len(sheets) == len(codes) == len(set(codes)) and all(codes)
    identity_ok = all(
        row.get("family") in SUPPORTED_FAMILIES and row.get("code") and _unique(row.get("levels"))
        for row in sheets if row.get("drawing_type") in {"riser_diagram", "calculation_sheet", "equipment_plan", "detail_sheet", "schematic"}
    )
    ambiguity_ok = not _unique(scope.get("scope_ambiguities"))

    checks = {
        "drawing_inventory": inventory_ok,
        "drawing_type_classification": type_ok and all(drawing_types),
        "level_binding": bound_ok,
        "typical_floor_evidence": typical_ok,
        "system_scope_evidence": system_evidence_ok,
        "unsupported_system_zero": unsupported_ok and extras_ok,
        "required_system_omission_zero": omissions_ok,
        "drawing_role_separation": role_ok,
        "level_system_matrix": matrix_ok,
        "deterministic_manifest_identity": deterministic_ok,
        "manifest_reconciliation": reconcile_ok,
        "plan_riser_calc_schedule_identity": identity_ok,
        "ambiguity_fail_closed": ambiguity_ok,
        "pre_calculation_scope_gate": scope.get("scope_stage", "pre_calculation") == "pre_calculation",
        "exact_output_parity_contract": bool(scope.get("exact_output_parity_required", True)),
        "destructive_regression_contract": scope.get("scope_contract_version", CONTRACT_VERSION) == CONTRACT_VERSION,
        "blind_reference_isolation": scope.get("reference_inputs_used", False) is False,
        "exact_reopen_contract": bool(scope.get("exact_reopen_required", True)),
    }
    controls = [
        {"id": control_id, "weight": weight, "status": "PASS" if checks[control_id] else "FAIL"}
        for control_id, weight in CONTROL_WEIGHTS.items()
    ]
    score = sum(row["weight"] for row in controls if row["status"] == "PASS")
    failures = [row["id"] for row in controls if row["status"] != "PASS"]
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "PASS" if score == 100 and not failures else "FAIL",
        "score": score,
        "required_score": 100,
        "controls": controls,
        "failures": failures,
        "level_system_matrix": matrix,
        "scope_matrix_id": matrix_id,
        "reference_inputs_used": bool(scope.get("reference_inputs_used", False)),
    }


def scope_contract_is_valid(manifest):
    contract = (manifest or {}).get("scope_contract") or {}
    controls = contract.get("controls") or []
    return (
        contract.get("contract_version") == CONTRACT_VERSION
        and contract.get("status") == "PASS"
        and contract.get("score") == 100
        and len(controls) == len(CONTROL_WEIGHTS)
        and all(row.get("status") == "PASS" for row in controls)
        and contract.get("scope_matrix_id")
        and contract.get("reference_inputs_used") is False
    )
