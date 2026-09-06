"""Machine-readable site/UI/panel contract for Electrical v19."""
from __future__ import annotations

from importlib import import_module

RELEASE_VERSION = "19.0.0"
REQUIRED_CAPABILITIES = {
    "design_basis_contract": "app.electrical_basis_contract",
    "question_workflow": "app.electrical_workflow",
    "active_questionnaire_patch": "app.electrical_runtime_patch",
    "drawing_set_contract": "app.electrical_drawing_set",
    "drawing_set_review": "app.electrical_review_fix",
    "panel_dispatcher": "app.discipline_workflow_dispatcher",
    "panel_recovery_integration": "app.electrical_design_integration",
    "standards_registry": "app.electrical_standards_registry",
    "execution_score": "app.electrical_execution_score",
}


def release_contract_status():
    checks = {}
    for capability, module in REQUIRED_CAPABILITIES.items():
        try:
            import_module(module)
            checks[capability] = True
        except Exception:
            checks[capability] = False
    return {
        "version": RELEASE_VERSION,
        "scope": "site-ui-panel-runtime",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "required_count": len(checks),
        "passed_count": sum(checks.values()),
        "checks": checks,
    }
