"""Machine-readable production contract for the Electrical v19 workflow."""
from __future__ import annotations

from importlib import import_module

RELEASE_VERSION = "19.0.0"
REQUIRED_CAPABILITIES = {
    "evidence_model": "cad_engine.electrical_v1.models",
    "architecture_reconstruction": "cad_engine.electrical_v1.architecture",
    "authority_plan_isolation": "cad_engine.electrical_v1.authority_qa",
    "project_driven_design": "cad_engine.electrical_v1.design",
    "host_aware_placement": "cad_engine.electrical_v1.geometry_acceptance",
    "lighting_and_power": "cad_engine.electrical_v1.placement_lighting",
    "circuit_calculation_and_sizing": "cad_engine.electrical_v1.power",
    "plan_aware_routing": "cad_engine.electrical_v1.routing",
    "panel_riser_grounding": "cad_engine.electrical_v1.distribution",
    "service_and_single_line_traceability": "cad_engine.electrical_v1.service",
    "project_details_and_legend": "cad_engine.electrical_v1.documentation",
    "independent_sheet_composition": "cad_engine.electrical_v1.composer",
    "preservation_first_cleanup": "cad_engine.electrical_v1.cleanup_policy",
    "north_from_architecture_evidence": "cad_engine.electrical_v1.orientation",
    "semantic_visual_reopen_qa": "cad_engine.electrical_v1.qa",
    "authority_reopen_qa": "cad_engine.electrical_v1.authority_qa",
    "strict_authority_pipeline": "cad_engine.electrical_v1.strict_pipeline_v15_2",
    "fail_closed_release_gate": "cad_engine.electrical_v1.release_gate",
    "production_adapter": "cad_engine.electrical_v1.production_v19",
    "production_http_route": "cad_engine.electrical_api_v19",
    "site_design_basis_contract": "app.electrical_basis_contract",
    "site_question_workflow": "app.electrical_workflow",
    "site_active_questionnaire_patch": "app.electrical_runtime_patch",
    "site_drawing_set_contract": "app.electrical_drawing_set",
    "site_drawing_set_review": "app.electrical_review_fix",
    "site_panel_dispatcher": "app.discipline_workflow_dispatcher",
    "site_panel_recovery_integration": "app.electrical_design_integration",
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
        "status": "PASS" if all(checks.values()) else "FAIL",
        "required_count": len(checks),
        "passed_count": sum(checks.values()),
        "checks": checks,
    }
