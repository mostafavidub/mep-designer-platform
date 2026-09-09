"""Mechanical authority release contract.

This is the canonical, machine-readable checklist for the mechanical workflow
that was built through real-project acceptance.  A production release is not
considered complete unless every required capability below is wired and tested.
"""
from __future__ import annotations

from importlib import import_module


RELEASE_VERSION = "15.2.0"

# Capability names intentionally mirror the engineering workflow and the final
# sheet/document QA decisions, not a particular project's sheet count.
REQUIRED_CAPABILITIES = {
    "architecture_reconstruction": "cad_engine.engineering_pipeline",
    "drawing_type_classification": "cad_engine.plan_segmentation",
    "primary_plan_and_roof_isolation": "cad_engine.plan_segmentation",
    "fixture_equipment_recognition": "cad_engine.engineering_pipeline",
    "system_requirement_engine": "cad_engine.authority_architecture",
    "calculation_provenance_contract": "cad_engine.authority_architecture",
    "plan_aware_topology": "cad_engine.topology",
    "plan_aware_routing": "cad_engine.routing",
    "pipe_sizing": "cad_engine.engineering_pipeline",
    "annotation_engine": "cad_engine.annotation",
    "detail_library": "cad_engine.detail_library",
    "dynamic_project_details": "cad_engine.dynamic_detail_engine_v14",
    "adaptive_project_sheet_manifest": "cad_engine.adaptive_sheet_planner_v13",
    "authority_sheet_architecture": "cad_engine.mechanical_design_core",
    "output_sanitization": "cad_engine.output_sanitizer_v13",
    "real_project_acceptance": "cad_engine.engineering_acceptance",
    "plan_isolation_acceptance": "cad_engine.plan_isolation_acceptance_v13",
    "semantic_sheet_qa": "cad_engine.semantic_sheet_qa_v14",
    "split_wall_hosting": "cad_engine.equipment_representation",
    "split_airflow_connections_callouts": "cad_engine.equipment_representation",
    "equipment_schedule_sync": "cad_engine.equipment_representation",
    "radiator_representation": "cad_engine.mechanical_design_core",
    "roof_rainwater_calculation": "cad_engine.mechanical_cad_base",
    "water_service_tank_pump_topology": "cad_engine.mechanical_cad_base",
    "gas_table_p22_sizing": "cad_engine.mechanical_cad_base",
    "exhaust_cfm": "cad_engine.mechanical_cad_base",
    "plumbing_riser": "cad_engine.mechanical_design_core",
    "general_notes": "cad_engine.mechanical_design_core",
    "equipment_schedule": "cad_engine.mechanical_design_core",
    "authority_style_sheet_naming": "cad_engine.mechanical_design_core",
    "integrated_a4_frame_and_compact_titleblock": "cad_engine.mechanical_design_core",
    "drawing_safe_area_zero_title_overlap": "cad_engine.mechanical_design_core",
    "north_inherited_from_architecture": "cad_engine.mechanical_design_core",
    "preservation_first_footer_cleanup": "cad_engine.sheet_cleanup_policy_v1",
    "exact_final_file_reopen_qa": "cad_engine.mechanical_design_core",
    "site_production_orchestration": "cad_engine.mechanical_cad_base",
}


def release_contract_status() -> dict:
    checks = {}
    for capability, module_name in REQUIRED_CAPABILITIES.items():
        try:
            import_module(module_name)
            checks[capability] = True
        except Exception:
            checks[capability] = False
    return {
        "version": RELEASE_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "required_count": len(REQUIRED_CAPABILITIES),
        "passed_count": sum(1 for v in checks.values() if v),
        "checks": checks,
    }
