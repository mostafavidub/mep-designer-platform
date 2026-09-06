"""Machine-readable CAD-runtime contract for the active Electrical system.

The dedicated CAD Docker image copies only ``cad_engine``. Site/UI capabilities
are validated by ``app.electrical_site_release_contract`` in the web service.
The contract revision is a schema/config revision, not a release number.
"""
from __future__ import annotations

from importlib import import_module

CONTRACT_REVISION = "electrical-release-contract/3"
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
    "construction_detail_and_evidence_qa": "cad_engine.electrical_v1.construction_qa",
    "submission_titleblock_and_cross_sheet_qa": "cad_engine.electrical_v1.submission_quality",
    "independent_sheet_composition": "cad_engine.electrical_v1.composer",
    "preservation_first_cleanup": "cad_engine.electrical_v1.cleanup_policy",
    "north_from_architecture_evidence": "cad_engine.electrical_v1.orientation",
    "semantic_visual_reopen_qa": "cad_engine.electrical_v1.qa",
    "authority_reopen_qa": "cad_engine.electrical_v1.authority_qa",
    "strict_authority_pipeline": "cad_engine.electrical_v1.acceptance_pipeline",
    "fail_closed_release_gate": "cad_engine.electrical_v1.release_gate",
    "runtime_support": "cad_engine.electrical_v1.runtime_support",
    "production_adapter": "cad_engine.electrical_v1.production",
    "production_http_route": "cad_engine.electrical_api",
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
        "scope": "cad-runtime",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "required_count": len(checks),
        "passed_count": sum(checks.values()),
        "checks": checks,
    }
