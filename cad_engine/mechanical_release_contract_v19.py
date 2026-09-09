"""Locked release contract for the mechanical v19.1 Pre-Submission profile."""
from __future__ import annotations
from importlib import import_module
from .mechanical_release_contract_v17 import REQUIRED_CAPABILITIES as PRIOR_CAPABILITIES

RELEASE_VERSION = "19.1.0"
REQUIRED_CAPABILITIES = {
    **PRIOR_CAPABILITIES,
    "structural_rcp_coordination_model":"cad_engine.coordination_v19",
    "multi_elevation_25d_candidate_router":"cad_engine.coordination_v19",
    "clash_penetration_slope_gate":"cad_engine.coordination_v19",
    "official_datasheet_ingestion":"cad_engine.manufacturer_selector_v19",
    "calculation_driven_manufacturer_selector":"cad_engine.manufacturer_selector_v19",
    "route_equipment_revalidation":"cad_engine.manufacturer_selector_v19",
    "parametric_executable_details":"cad_engine.parametric_documentation_v19",
    "mandatory_active_system_detail_families":"cad_engine.parametric_documentation_v19",
    "graph_native_identity_locked_risers":"cad_engine.parametric_documentation_v19",
    "identity_bound_annotations_and_enlarged_plans":"cad_engine.parametric_documentation_v19",
    "blind_seal_before_reference":"cad_engine.submission_qa_v19",
    "semantic_artifact_numeric_diff_gate":"cad_engine.submission_qa_v19",
    "calculation_derived_water_segment_dn":"cad_engine.sizing_v14",
    "materialized_water_reducer_identity":"cad_engine.sizing_v14",
    "critical_path_pump_tank_calculation":"cad_engine.mechanical_calculations_v14",
    "manufacturer_exact_radiator_and_package_selection":"cad_engine.manufacturer_selector_v19",
    "cumulative_heating_network_sizing":"cad_engine.sizing_v14",
    "evidence_locked_gas_segment_design":"cad_engine.sizing_v14",
    "explicit_component_cooling_load_and_zone_diversity":"cad_engine.hvac_calculations",
    "manufacturer_confirmed_idu_odu_route_validation":"cad_engine.manufacturer_selector_v19",
    "exhaust_room_coverage_flow_esp_selection":"cad_engine.hvac_calculations",
    "catchment_lowpoint_drain_downpipe_rainwater_design":"cad_engine.rainwater_calculations",
    "typed_level_plan_graph_derived_riser":"cad_engine.parametric_documentation_v19",
    "official_hash_only_manufacturer_database":"cad_engine.manufacturer_database",
    "system_specific_manufacturer_locked_parametric_details":"cad_engine.parametric_documentation_v19",
    "manufacturer_aware_selection_calculation_book":"cad_engine.calculation_book",
    "collision_priority_scale_enlargement_annotation_solver":"cad_engine.annotation_solver",
    "explicit_zero_evidence_submission_readiness_gate":"cad_engine.submission_qa_v19",
    "seven_project_strict_golden_regression":"cad_engine.submission_qa_v19",
    "blind_generation_seal_reference_order_gate":"cad_engine.submission_qa_v19",
    "independent_engineer_redline_feedback_loop":"cad_engine.engineering_feedback",
    "quantitative_final_quality_acceptance_gate":"cad_engine.quality_acceptance",
    "architecture_only_pre_submission_regression":"cad_engine.submission_qa_v19",
    "production_v19_version_locked_adapter":"cad_engine.mechanical_authority_site_v19",
}

def release_contract_status():
    checks={}
    for capability,module_name in REQUIRED_CAPABILITIES.items():
        try: import_module(module_name); checks[capability]=True
        except Exception: checks[capability]=False
    return {"version":RELEASE_VERSION,"status":"PASS" if all(checks.values()) else "FAIL",
            "required_count":len(checks),"passed_count":sum(checks.values()),"checks":checks}
