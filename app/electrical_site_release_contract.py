"""Machine-readable site/UI/panel contract for the active Electrical system."""
from __future__ import annotations

from importlib import import_module

CONTRACT_REVISION = "electrical-site-contract/1"
REQUIRED_CAPABILITIES = {
    "design_basis_contract": "app.electrical_basis_contract",
    "question_workflow": "app.electrical_workflow",
    "active_questionnaire_patch": "app.electrical_runtime_patch",
    "drawing_set_contract": "app.electrical_drawing_set",
    "drawing_set_review": "app.electrical_review_fix",
    "panel_dispatcher": "app.discipline_workflow_dispatcher",
    "panel_recovery_integration": "app.electrical_design_integration",
    "rulebook": "app.electrical_rulebook",
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
        "contract_revision": CONTRACT_REVISION,
        "scope": "site-ui-panel-runtime",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "required_count": len(checks),
        "passed_count": sum(checks.values()),
        "checks": checks,
    }
