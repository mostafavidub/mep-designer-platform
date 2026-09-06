"""Transparent Electrical execution-readiness score.

A high score can never override a hard engineering blocker.  >=80 means the
project is operationally mature enough for execution review only when every
mandatory gate is also green/not-required.
"""
from __future__ import annotations

WEIGHTS = {
    "architecture_scope": 15,
    "design_basis": 15,
    "engineering_calculations": 20,
    "drawing_coverage_traceability": 15,
    "visual_documentation": 10,
    "same_file_reopen_semantic_qa": 10,
    "panel_flow_recovery": 10,
    "runtime_release_identity": 5,
}

MANDATORY = {
    "NO_FAKE_FINAL",
    "ARCHITECTURE_MODEL",
    "DESIGN_BASIS",
    "CIRCUIT_TOPOLOGY",
    "FINAL_FILE_REOPEN",
    "FINAL_REOPEN_AUTHORITY",
    "PANEL_FLOW_RECOVERY",
    "RUNTIME_RELEASE_IDENTITY",
}

CATEGORY_GATES = {
    "architecture_scope": {"ARCHITECTURE_MODEL", "PROJECT_MODEL", "SYSTEM_REQUIREMENTS", "PLAN_ISOLATION_AUTHORITY"},
    "design_basis": {"DESIGN_BASIS", "NO_FAKE_FINAL"},
    "engineering_calculations": {"LOAD_CALCULATION", "CABLE_SIZING", "BREAKER_SIZING", "VOLTAGE_DROP", "PHASE_BALANCE", "PANEL_DESIGN"},
    "drawing_coverage_traceability": {"SHEET_MANIFEST", "PANEL_SCHEDULE", "SINGLE_LINE", "RISER", "GROUNDING", "DETAIL_REFERENCE_PARITY_AUTHORITY"},
    "visual_documentation": {"LEGEND", "GENERAL_NOTES", "REFERENCE_SIMILARITY", "VISUAL_QA", "SAFE_DRAWING_AREA_AUTHORITY"},
    "same_file_reopen_semantic_qa": {"FINAL_FILE_REOPEN", "FINAL_REOPEN_AUTHORITY", "SEMANTIC_DUPLICATE_AUTHORITY", "FAMILY_PURITY"},
    "panel_flow_recovery": {"PANEL_FLOW_RECOVERY"},
    "runtime_release_identity": {"RUNTIME_RELEASE_IDENTITY", "ELECTRICAL_RELEASE_CONTRACT"},
}


def _status(gates, name):
    value = (gates or {}).get(name)
    if isinstance(value, dict):
        return str(value.get("status") or "UNKNOWN")
    if isinstance(value, str):
        return value
    return "UNKNOWN"


def score(gates):
    gates = dict(gates or {})
    categories = {}
    total = 0.0
    for category, weight in WEIGHTS.items():
        names = CATEGORY_GATES[category]
        applicable = [name for name in names if _status(gates, name) != "NOT_REQUIRED"]
        if not applicable:
            points = float(weight)
        else:
            passed = sum(1 for name in applicable if _status(gates, name) == "PASS")
            points = weight * passed / len(applicable)
        categories[category] = {"points": round(points, 2), "max": weight, "gates": {name: _status(gates, name) for name in names}}
        total += points
    hard_blockers = sorted(name for name in MANDATORY if _status(gates, name) not in {"PASS", "NOT_REQUIRED"})
    execution_ready = total >= 80 and not hard_blockers
    return {
        "version": "electrical-execution-score-v19.0",
        "score": round(total, 1),
        "threshold": 80,
        "execution_ready": execution_ready,
        "hard_blockers": hard_blockers,
        "categories": categories,
        "rule": "score>=80 AND zero mandatory blockers",
    }
