"""Locked release contract for the mechanical canonical Pre-Submission profile."""
from __future__ import annotations
from importlib import import_module
from .mechanical_release_contract_reference import REQUIRED_CAPABILITIES as PRIOR_CAPABILITIES

REQUIRED_CAPABILITIES = {
    **PRIOR_CAPABILITIES,
    "structural_rcp_coordination_model":"cad_engine.mechanical_coordination",
    "multi_elevation_25d_candidate_router":"cad_engine.mechanical_coordination",
    "clash_penetration_slope_gate":"cad_engine.mechanical_coordination",
    "official_datasheet_ingestion":"cad_engine.mechanical_manufacturer_selector",
    "calculation_driven_manufacturer_selector":"cad_engine.mechanical_manufacturer_selector",
    "route_equipment_revalidation":"cad_engine.mechanical_manufacturer_selector",
    "parametric_executable_details":"cad_engine.mechanical_documentation",
    "mandatory_active_system_detail_families":"cad_engine.mechanical_documentation",
    "graph_native_identity_locked_risers":"cad_engine.mechanical_documentation",
    "identity_bound_annotations_and_enlarged_plans":"cad_engine.mechanical_documentation",
    "blind_seal_before_reference":"cad_engine.mechanical_submission_qa",
    "semantic_artifact_numeric_diff_gate":"cad_engine.mechanical_submission_qa",
    "calculation_derived_water_segment_dn":"cad_engine.mechanical_execution_sizing",
    "materialized_water_reducer_identity":"cad_engine.mechanical_execution_sizing",
    "critical_path_pump_tank_calculation":"cad_engine.mechanical_calculation_traceability",
    "manufacturer_exact_radiator_and_package_selection":"cad_engine.mechanical_manufacturer_selector",
    "cumulative_heating_network_sizing":"cad_engine.mechanical_execution_sizing",
    "evidence_locked_gas_segment_design":"cad_engine.mechanical_execution_sizing",
    "explicit_component_cooling_load_and_zone_diversity":"cad_engine.hvac_calculations",
    "manufacturer_confirmed_idu_odu_route_validation":"cad_engine.mechanical_manufacturer_selector",
    "exhaust_room_coverage_flow_esp_selection":"cad_engine.hvac_calculations",
    "catchment_lowpoint_drain_downpipe_rainwater_design":"cad_engine.rainwater_calculations",
    "typed_level_plan_graph_derived_riser":"cad_engine.mechanical_documentation",
    "official_hash_only_manufacturer_database":"cad_engine.manufacturer_database",
    "system_specific_manufacturer_locked_parametric_details":"cad_engine.mechanical_documentation",
    "manufacturer_aware_selection_calculation_book":"cad_engine.calculation_book",
    "collision_priority_scale_enlargement_annotation_solver":"cad_engine.annotation_solver",
    "explicit_zero_evidence_submission_readiness_gate":"cad_engine.mechanical_submission_qa",
    "seven_project_strict_golden_regression":"cad_engine.mechanical_submission_qa",
    "blind_generation_seal_reference_order_gate":"cad_engine.mechanical_submission_qa",
    "independent_engineer_redline_feedback_loop":"cad_engine.engineering_feedback",
    "quantitative_final_quality_acceptance_gate":"cad_engine.quality_acceptance",
    "architecture_only_pre_submission_regression":"cad_engine.mechanical_submission_qa",
    "production_canonical_authority_adapter":"cad_engine.mechanical_authority",
    "topology_routing_18_control_score":"cad_engine.topology_routing_gate",
    "equipment_selection_placement_18_control_score":"cad_engine.equipment_selection_placement_gate",
    "final_engineering_release_18_control_score":"cad_engine.final_engineering_release_gate",
}

def release_contract_status():
    checks={}
    for capability,module_name in REQUIRED_CAPABILITIES.items():
        try: import_module(module_name); checks[capability]=True
        except Exception: checks[capability]=False
    return {"status":"PASS" if all(checks.values()) else "FAIL",
            "required_count":len(checks),"passed_count":sum(checks.values()),"checks":checks}
