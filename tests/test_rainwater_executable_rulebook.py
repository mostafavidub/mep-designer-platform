from copy import deepcopy
from io import StringIO
import json
from pathlib import Path

import ezdxf
import pytest

from cad_engine.executable_rulebook import (
    load_rulebook_module, module_dependency_identity, validate_rulebook_module,
)
from cad_engine.independent_deliverables import execute_registered_generator, _rainwater_plan_independent_qa
from cad_engine.mechanical_target_design import build_rainwater_package
from cad_engine.rainwater_calculations import design_roof_rainwater
from cad_engine.rainwater_rulebook import evaluate_rainwater_rules


def _asd_fixture():
    D,L,Lr,S,R,W,E=10,2,1.5,3,4,2.5,3.5
    cases={"ASD-1":D,"ASD-2":D+L}
    for alt,value in (("LR",Lr),("S",S),("R",R)):
        cases[f"ASD-3-{alt}"]=D+value
        cases[f"ASD-4-{alt}"]=D+.75*L+.75*value
    for sign,label in ((1,"POS"),(-1,"NEG")):
        cases[f"ASD-5-W-{label}"]=D+sign*W
        for alt,value in (("LR",Lr),("S",S),("R",R)):
            cases[f"ASD-6-{alt}-W-{label}"]=D+.75*L+sign*.75*W+.75*value
        cases[f"ASD-7-E-{label}"]=D+sign*.7*E
        cases[f"ASD-8-E-{label}"]=D+.75*L+sign*.75*.7*E+.75*S
        cases[f"ASD-9-W-{label}"]=.6*D+sign*W
        cases[f"ASD-10-E-{label}"]=.6*D+sign*.7*E
    governing=max(cases,key=lambda k:abs(cases[k]))
    return {"effect_type":"MOMENT","effect_unit":"kN_m","direction_convention":"positive about local structural y axis",
            "capacity_mode":"SYMMETRIC_ABSOLUTE","load_effects":{"D":D,"L":L,"Lr":Lr,"S":S,"R":R,"W":W,"E":E},
            "evaluated_cases":cases,"governing_case_id":governing,"allowable_capacity_abs":abs(cases[governing]),
            "allowable_stress_increase":False,"structural_analysis_id":"STRUCT-ASD-SYN-1"}


def _fluid_fixture():
    coefficients={"LRFD":{"1":1.4,"2":1.2,"3":1.2,"4":1.2,"5":1.2,"7":.9},
                  "ASD":{"1":1,"2":1,"3":1,"4":1,"5":1,"6":1,"7":1,"8":1,"10":.6}}
    return [{"method":method,"base_combination_number":case,"effect_type":"MOMENT","effect_unit":"kN_m",
             "base_effect_excluding_f":10,"fluid_effect_f":2,"declared_effect_including_f":10+factor*2,
             "analysis_id":f"FLUID-{method}-{case}"}
            for method,cases in coefficients.items() for case,factor in cases.items()]


def complete_snapshot():
    return {
        "roof": {
            "roof_id": "ROOF-RULEBOOK",
            "roof_type": "FLAT", "roof_role": "MAIN_ROOF",
            "boundary": [[0, 0], [20, 0], [20, 10], [0, 10]],
            "emergency_rainwater_shaft": {"id": "ERS-1", "point": [10, 1]},
            "stacks": [
                {"id": "RW1", "point": [4, 1], "dn_mm": 80, "systems": ["rainwater"], "water_column_height_m": 12, "component_pressure_rating_kpa": 150},
                {"id": "RW2", "point": [16, 1], "dn_mm": 80, "systems": ["rainwater"], "water_column_height_m": 12, "component_pressure_rating_kpa": 150},
            ],
            "catchments": [
                {"id": "C1", "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
                 "low_point": [2, 2], "drain": {"id": "D1", "point": [2, 2],
                    "strainer_height_mm": 100, "strainer_open_area_ratio": 1.5,
                    "watertight_connection": True},
                 "stack_id": "RW1", "roof_surface_slope_percent": 2.0,
                 "horizontal_pipe_slope_percent": 1.0, "slope_percent": 2.0,
                 "contributing_wall_areas_m2": [], "upstream_transfer_ids": [],
                 "route": [[2, 2], [4, 2], [4, 1]],
                 "emergency_overflow": {"type": "scupper", "point": [0, 2]}},
                {"id": "C2", "polygon": [[10, 0], [20, 0], [20, 10], [10, 10]],
                 "low_point": [18, 2], "drain": {"id": "D2", "point": [18, 2],
                    "strainer_height_mm": 110, "strainer_open_area_ratio": 1.6,
                    "watertight_connection": True},
                 "stack_id": "RW2", "roof_surface_slope_percent": 2.5,
                 "horizontal_pipe_slope_percent": 2.0, "slope_percent": 2.5,
                 "contributing_wall_areas_m2": [], "upstream_transfer_ids": [],
                 "route": [[18, 2], [16, 2], [16, 1]],
                 "emergency_overflow": {"type": "scupper", "point": [20, 2]}},
            ],
            "secondary_network": {
                "routes": [{"id": "SR1", "points": [[1, 9], [5, 9], [5, 10]]},
                           {"id": "SR2", "points": [[19, 9], [15, 9], [15, 10]]}],
                "discharge_points": [{"id": "SD1", "point": [5, 10]},
                                     {"id": "SD2", "point": [15, 10]}],
                "elevation_m": 1.0, "unobstructed": True, "outlet_visible": True,
            },
        },
        "design_basis": {
            "rainfall_intensity_mm_h": 100, "rainfall_duration_h": 1,
            "rainfall_return_period_years": 30, "rainfall_authority": "OFFICIAL_DATA",
            "runoff_coefficient": 1.0, "minimum_slope_percent": 2,
            "approved_engineering_method": "M16_APPENDIX_7",
            "engineering_method_authority": "ENGINEER_APPROVED",
            "drain_capacity_table": [{"dn_mm": 80, "max_flow_lps": 5}],
            "downpipe_capacity_table": [{"dn_mm": 80, "max_flow_lps": 5}],
        },
        "draft_assumption_basis": {"rainfall_authority": "OFFICIAL_DATA",
                                   "capacity_authority": "ENGINEER_APPROVED",
                                   "release_allowed": False},
        "rule_context": {
            "building_in_m4_scope": True,
            "rainwater_sanitary_separation_verified": True,
            "primary_network_elevation_m": 0,
            "structural_rain_load_R_review": "APPROVED",
            "structural_rain_load_R": 1.2,
            "structural_ponding_stability_review": "APPROVED",
            "rainwater_joints": [{"method":"RUBBER_RING","materials":["PVC"],"diameters_mm":[80,80]}],
            "cleanouts": [
                {"location_type":"STACK_BASE","dn_mm":80,"pipe_dn_mm":80,"watertight":True,"accessible":True},
                {"location_type":"DIRECTION_CHANGE_OVER_45","dn_mm":80,"pipe_dn_mm":80,"watertight":True,"accessible":True},
                {"location_type":"BUILDING_EXIT","dn_mm":80,"pipe_dn_mm":80,"watertight":True,"accessible":True}],
            "cleanout_segments": [{"dn_mm":80,"length_m":12,"max_cleanout_spacing_m":12}],
            "rainwater_components": [{"product_identity":"PVC-RW-80","material":"PLASTIC","above_lowest_floor":True,"fire_class":"B-s1-d0","firestop_rating":"SAME_AS_ASSEMBLY","exposures":["UV","FIRE_RATED_PENETRATION"],"protections":["UV","FIRE_RATED_PENETRATION"],"manufacturer_mark_permanent":True,"standard_mark_permanent":True,"certificate":{"id":"CERT-SYNTHETIC-001","issuer":"SYNTHETIC TEST LAB","issuer_competent":True,"standard":"ISIRI-SYNTHETIC","product_identity":"PVC-RW-80","evidence_provenance":{"source_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","verification_authority":"SYNTHETIC TEST AUTHORITY","verified_at":"2026-01-01T00:00:00Z","verification_status":"VALID"}}}],
            "rainwater_supports": [{"spacing_m":1.0,"allowed_spacing_m":1.2,"spacing_authority":"PRODUCT_APPROVAL","full_pipe_load_included":True,"corrosion_compatible":True,"anchorage_approved":True}],
            "upper_roof_discharges_to_lower_roof": False,
            "installation_stage_requires_test": True,
            "rainwater_leak_tests": [{"full_head_height_m":12,"highest_stack_height_m":12,"duration_minutes":15,"performed_before_covering":True,"leak_detected":False,"retest_passed":True}],
            "buried_gravity_rainwater_segments": [],
            "rainwater_discharge_destinations": [
                {"id":"OUT-1","destination_type":"APPROVED_SITE_DRAINAGE","inside_property":True,"causes_nuisance":False}],
            "structural_rainwater_loads": [
                {"component_id":"RW1","empty_component_mass_kg":12,"water_full_mass_kg":20,
                 "support_reaction_id":"REACTION-RW1","structural_review":{"status":"APPROVED","approval_id":"STRUCT-SYNTHETIC-1"}}],
            "waterproofing_interfaces": [{"entity_id":"ROOF-1","source_geometry_id":"SYNTHETIC-ROOF-1",
                "surface_type":"FLAT_ROOF","membrane_continuous":True,"drain_penetration_sealed":True,
                "upstand_detail_id":"WP-DETAIL-1"}],
            "basement_openings": [{"entity_id":"BO-1","source_geometry_id":"SYNTHETIC-BO-1",
                "opening_type":"WINDOW","runoff_interceptor_id":"INT-1","surface_water_entry_prevented":True,
                "below_grade_waterproofing_continuous":True}],
            "rainwater_route_entities": [{"route_id":"R-SYN-1","source_geometry_id":"G-R-SYN-1",
                "owner_unit_id":"UNIT-1","route_points":[[1,1],[3,1]],
                "private_space_polygons":[{"unit_id":"UNIT-2","polygon":[[5,5],[7,5],[7,7],[5,7]]}],
                "accessible_everywhere":True,"in_shaft":True,"shaft_id":"SH-1",
                "shaft_access_panel_id":"AP-1","shaft_interior_finish_smooth":True}],
            "suspended_ceiling_route_interfaces": [{"interface_id":"SC-1","source_geometry_id":"G-SC-1",
                "structural_soffit_elevation_m":3.2,"finished_ceiling_elevation_m":2.7,
                "finished_floor_elevation_m":0,"minimum_legal_clear_height_m":2.4,
                "independent_pipe_support":True,"no_ceiling_contact":True,"partition_continuity":True,
                "fire_protection_continuity":True}],
            "exterior_drainage_spaces": [{"space_id":"EXT-1","space_type":"SEMI_OPEN","polygon":[[0,0],[2,0],[2,2],[0,2]],
                "surface_elevation_points":[[0,0,.02],[2,0,.02],[2,2,.02],[0,2,.02]],"drain_point":[1,1],"drain_elevation_m":0,"route_points":[[1,1],[3,1]],
                "destination_type":"APPROVED_SITE_DRAINAGE","ponding_free":True}],
            "parking_drainage_areas": [{"area_id":"PK-1","polygon":[[0,0],[4,0],[4,4],[0,4]],
                "surface_elevation_points":[[0,0,.04],[4,0,.04],[4,4,.04],[0,4,.04]],"drain_point":[2,2],"drain_elevation_m":0,"route_points":[[2,2],[5,2]],
                "ponding_free":True,"at_ground_floor_entrance":True,"entrance_crest_above_exterior_m":0.05}],
            "rainwater_installation_interfaces": [{"interface_id":"OUTLET-1","source_geometry_id":"G-OUTLET-1",
                "interface_type":"OUTLET_OPENING","grate_detail_id":"GRATE-1","imposed_pressure_within_component_rating":True}],
            "nonpotable_reuse_connections": [{"connection_id":"NP-1","connection_type":"OPEN_DRAIN_DISCHARGE",
                "potable_network_separate":True,"nonpotable_identification":"PURPLE/NP","air_gap_mm":150}],
            "project_stage":"DESIGN",
            "rainwater_documentation": {k:"SYNTHETIC" for k in ("plans","riser_diagram","drains","pipe_routes","diameters","lengths","materials","flow_directions","slopes","cleanouts","outlet_elevation","installation_method","protection_method","maintenance_method","design_pressure","standard_symbols")},
            "roof_equipment_verified_absent":True,"roof_equipment_overflows":[],
            "rainwater_route_installation_records":[{"route_id":"R-SYN-1","gravity_flow_verified":True,
                "parallel_to_building_surfaces":True,"standard_fittings":True,"joint_watertight":True,
                "fire_resistant_material":True,"product_standard":"ISO-SYNTHETIC",
                "support_system":{"clamp_type":"CLIP","clamp_material":"STEEL","longitudinal_movement_allowed":True,"manufacturer_instruction_id":"MI-SYNTHETIC"},
                "plastic_vertical":True}],
            "demolition_verified_absent":True,"potable_makeup_verified_absent":True,"potable_storage_tanks_verified_absent":True,
            "interdisciplinary_compliance":{
                "architecture":{"status":"PASS","evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}},
                "structural":{"status":"PASS","evidence_provenance":{"verification_status":"VALID","source_sha256":"b"*64}}},
            "roof_access_safety":{"storeys_above_ground":5,"roof_slope_percent":0,"roof_use":"SERVICE",
                "access_type":"PUBLIC_STAIR","roof_accessible":True,"stair_headhouse_area_m2":12,
                "stair_enclosure_area_m2":12,"parapet_height_m":1.10,
                "roof_polygon":[[0,0],[21,0],[21,29.7],[0,29.7]],
                "parapet_polygon":[[-.1,-.1],[21.1,-.1],[21.1,29.8],[-.1,29.8]],
                "parapet_edge_segments":[{"start":a,"end":b,"height_m":1.10} for a,b in [([0,0],[21,0]),([21,0],[21,29.7]),([21,29.7],[0,29.7]),([0,29.7],[0,0])]]},
            "entrance_landing_interfaces":[{"entrance_id":"E-1","inside_landing_elevation_mm":0,"outside_landing_elevation_mm":0,
                "threshold_top_elevation_mm":20,"threshold_present":True,"accessible_route":True,"required_egress":True,
                "occupancy_group":"RESIDENTIAL","exterior_door":True}],
            "rain_on_snow_load_case":{"snow_region":2,"roof_slope_deg":0.5,"slope_run_w_m":15,
                "balanced_snow_load_kn_m2":1.0,"rain_surcharge_kn_m2":0.25,
                "simultaneous_effects":[],"declared_combined_load_kn_m2":1.25},
            "roof_service_live_loads":[{"area_id":"ROOF-1","load_area_type":"NORMAL_ROOF","uniform_load_kn_m2":1.5,"concentrated_load_kn":1.3},
                {"area_id":"WALK-1","load_area_type":"SERVICE_WALKWAY","uniform_load_kn_m2":2.0,"concentrated_load_kn":1.3},
                {"area_id":"LADDER-1","load_area_type":"FIXED_LADDER","ladder_length_m":6,"point_load_kn":1.35,"point_load_spacing_m":3,"rails_extend_above_support":True,"extension_point_load_kn":0.45}],
            "rainwater_material_installations":[{"installation_id":"MAT-1","material":"UPVC","standard":"EN 1329",
                "fitting_standard_compatible":True,"smooth_internal_bore":True,"joint_method":"SOLVENT_CEMENT_COLD",
                "manufacturer_instruction_id":"MI-1","buried":False,"ambient_temperature_c":5}],
            "rainwater_material_support_installations":[
                {"installation_id":"SUP-CIV-1","material_group":"CAST_IRON","orientation":"VERTICAL",
                 "clamp_type":"CLAMP","clamp_material":"CAST_IRON","support_connected_to_building":True,
                 "longitudinal_movement_allowed":True,"base_below_lowest_elbow":True,
                 "base_bearing":"CONCRETE","near_hub_or_joint":True},
                {"installation_id":"SUP-GSH-1","material_group":"GALVANIZED_STEEL","orientation":"HORIZONTAL",
                 "clamp_type":"HANGER","clamp_material":"STEEL_PROFILE","support_connected_to_building":True,
                 "longitudinal_movement_allowed":True,"thermal_movement_expected":True,
                 "pendular_movement_allowed":True,"fixed_points_anchored":True,"other_points_guided":True,
                 "clamp_over_insulation":True,"steel_liner_thickness_mm":1.5,"steel_liner_length_mm":300},
                {"installation_id":"SUP-CIH-1","material_group":"CAST_IRON","orientation":"HORIZONTAL",
                 "clamp_type":"U_BOLT","clamp_material":"CAST_IRON","support_connected_to_building":True,
                 "longitudinal_movement_allowed":True,"near_hub_or_joint":True,"buried_in_soil":True,
                 "continuous_sand_bedding":True},
                {"installation_id":"SUP-PLH-1","material_group":"PLASTIC","orientation":"HORIZONTAL",
                 "clamp_type":"CLAMP","clamp_material":"PLASTIC","support_connected_to_building":True,
                 "longitudinal_movement_allowed":True}],
            "potable_outlets_over_rainwater_receptors":[{"outlet_id":"AG-1","outlet_group":"GOOSENECK_SINK_LAUNDRY",
                "effective_diameter_mm":20,"near_wall":True,"vertical_air_gap_mm":65}],
            "structural_rainwater_load_combinations":{"effect_type":"MOMENT","effect_unit":"kN_m",
                "direction_convention":"positive about local structural y axis","capacity_mode":"SYMMETRIC_ABSOLUTE",
                "load_effects":{"D":10,"L":2,"Lr":1.5,"S":3,"R":4,"W":2.5,"E":3.5},
                "evaluated_cases":{"LRFD-1":14,"LRFD-2-LR":15.95,"LRFD-2-S":16.7,"LRFD-2-R":17.2,
                    "LRFD-3-LR-L":16.4,"LRFD-3-S-L":18.8,"LRFD-3-R-L":20.4,"LRFD-3-LR-W":16.4,
                    "LRFD-3-LR-W-POS":16.4,"LRFD-3-S-W-POS":18.8,"LRFD-3-R-W-POS":20.4,
                    "LRFD-4-LR-W-POS":18.75,"LRFD-4-S-W-POS":19.5,"LRFD-4-R-W-POS":20,
                    "LRFD-5-E-POS":18.1,"LRFD-6-W-POS":13,"LRFD-7-E-POS":12.5,
                    "LRFD-3-LR-W-NEG":12.4,"LRFD-3-S-W-NEG":14.8,"LRFD-3-R-W-NEG":16.4,
                    "LRFD-4-LR-W-NEG":10.75,"LRFD-4-S-W-NEG":11.5,"LRFD-4-R-W-NEG":12,
                    "LRFD-5-E-NEG":11.1,"LRFD-6-W-NEG":5,"LRFD-7-E-NEG":5.5},
                "governing_case_id":"LRFD-3-R-L","design_capacity_abs":20.4,"structural_analysis_id":"STRUCT-LRFD-SYN-1"},
            "structural_rainwater_asd_combinations":_asd_fixture(),
            "roof_primary_blockage_rain_loads":[{"roof_area_id":"ROOF-1","undeformed_roof_elevation_mm":1000,
                "secondary_inlet_elevation_mm":1060,"hydraulic_head_mm":20,"declared_rain_load_kn_m2":0.8,
                "primary_blocked":True,"roof_slope_percent":1.5,"primary_blockage_can_retain_water":True,
                "full_snow_load_kn_m2":1.2,"structural_analysis_id":"STRUCT-RAIN-SYN-1",
                "ponding_analysis":{"analysis_id":"POND-SYN-1","method":"ITERATIVE_DEFORMED_GEOMETRY",
                    "solver_version":"POND-SOLVER-1","structural_model_sha256":"a"*64,"convergence_tolerance_mm":0.1,
                    "iterations":[{"iteration":1,"water_surface_elevation_mm":1060,"max_deflection_mm":4,"residual_mm":1.2},
                        {"iteration":2,"water_surface_elevation_mm":1061,"max_deflection_mm":4.9,"residual_mm":0.05}],
                    "final_water_surface_elevation_mm":1061,"final_deformed_low_point_elevation_mm":995.1,
                    "declared_final_ponded_depth_mm":65.9,"stable":True,"governing_water_or_snow_load_kn_m2":1.2,
                    "structural_approval":{"approval_id":"SE-SYN-1","approver_role":"STRUCTURAL_ENGINEER",
                        "model_sha256":"a"*64,"status":"APPROVED"}}}],
            "roof_snow_load_basis":[{"roof_area_id":"ROOF-1","ground_snow_load_ps_kn_m2":1.0,
                "importance_factor_is":1.0,"exposure_factor_cn":1.0,"thermal_factor_ch":1.0,"slope_factor_cs":1.0,
                "roof_slope_degrees":0,"surface_slippery":False,"unobstructed_slide":False,"adequate_fall_space":False,
                "declared_balanced_roof_snow_pr_kn_m2":1.0,"declared_snow_unit_weight_kn_m3":2.63,
                "declared_balanced_snow_height_m":1/2.63,"classified_as_exposed_roof":False,
                "exposure_geometry_analysis_id":"SNOW-GEO-SYN-1","roof_obstructions":[{"id":"PARAPET-1","height_above_roof_m":1.1}],
                "eave_overhang":{"length_m":2.0,"declared_design_zone_length_m":1.5,"declared_design_load_kn_m2":2.0}}],
            "rooftop_snow_drift_features":[{"feature_id":"PARAPET-1","snow_region":4,"feature_type":"PARAPET",
                "face_width_m":20,"windward_roof_length_m":8,"leeward_roof_length_m":12,
                "perpendicular_roof_length_m":10,"drift_height_hd_m":1.2,"clear_height_hc_m":0.6,
                "declared_drift_width_w_m":2.4,"base_calculation_id":"SNOW-675-SYN-1",
                "declared_lu_m":10,"declared_max_drift_height_m":0.9,"drift_applied":True,
                "printed_reference_anomaly_acknowledged":True,"structural_interpretation":{"approval_id":"SE-DRIFT-SYN-1",
                    "approver_role":"STRUCTURAL_ENGINEER","status":"APPROVED","source_clause":"6-7-10 -> relation 6-7-5",
                    "source_printed_page":61,"source_document_sha256":"9702369223d5c04072d5e8e01871045c80ff494ffe8ae1357ebd90e78ff18201",
                    "structural_model_sha256":"c"*64}}],
            "fluid_load_combination_extensions":_fluid_fixture(),
            "heavy_rooftop_equipment_placements":[{"equipment_id":"RTU-SYN-1","operating_mass_kg":850,
                "support_member_type":"CANTILEVER","building_importance":"MEDIUM","building_storeys":5,
                "structural_model_sha256":"d"*64,
                "placement_structural_analysis":{"analysis_id":"PLACE-SYN-1","status":"APPROVED","model_sha256":"d"*64,"engineer_approval_id":"SE-PLACE-1"},
                "seismic_nonstructural_analysis":{"analysis_id":"SEISMIC-SYN-1","standard_2800_edition":"4",
                    "status":"APPROVED","model_sha256":"d"*64,"engineer_approval_id":"SE-SEISMIC-1"}}],
            "roof_live_load_reductions":[{"roof_area_id":"ROOF-1","roof_use_type":"ORDINARY","roof_geometry_type":"PITCHED",
                "tributary_area_m2":18,"roof_slope_percent":33,"slope_parameter_s":33,"unreduced_l0_kn_m2":1.5,"declared_lr_kn_m2":1.5}],
            "special_use_roof_live_load_reductions":[{"roof_area_id":"RG-1","special_use_type":"ROOF_GARDEN","unreduced_l0_kn_m2":4,"declared_design_live_load_kn_m2":3.2,"structural_model_sha256":"f"*64,"section_6_5_5_calculation":{"calculation_id":"655-SYN-1","method_clause":"6-5-5","tributary_area_m2":100,"result_kn_m2":3.2,"status":"APPROVED","model_sha256":"f"*64,"engineer_approval_id":"SE-655-1"}}],
            "roof_serviceability_deflection_checks":[{"member_id":"RB-1","span_mm":6000,"allowable_deflection_ratio":240,"calculated_deflection_mm":25,"load_combination_id":"SVC-D-L-R","analysis_id":"DEF-SYN-1","structural_model_sha256":"1"*64,"deflection_limit_source":{"code":"M9","edition":"PROJECT-CONTRACT","clause":"ROOF-SERVICEABILITY","member_type":"ROOF_BEAM","material":"REINFORCED_CONCRETE","load_condition":"SERVICE-D-L-R","attached_component_condition":"NONBRITTLE_FINISH","approved_ratio":240,"engineer_approval_id":"SE-LIMIT-1","structural_model_sha256":"1"*64,"status":"APPROVED"},"analysis_response":{"analysis_id":"DEF-SYN-1","model_sha256":"1"*64,"status":"APPROVED","engineer_approval_id":"SE-DEF-1"}}],
            "rainwater_maintenance_access_paths":[{"path_id":"MA-1","target_type":"MEP_ONLY_CORRIDOR","path_points":[[1,1],[1,5]],"required_clear_width_m":0.6,"corridor_polygon":[[0.5,0.5],[1.5,0.5],[1.5,5.5],[0.5,5.5]],"obstacle_polygons":[],"accessible_entrance_point":[1,1],"target_access_point":[1,5]}],
            "parking_ramp_profiles":[{"ramp_id":"PR-1","parking_type":"PRIVATE","covered":False,"parking_size":"MEDIUM","profile_points":[[0,0],[1,.1],[10,1.45],[11,1.55]]}],
        },
        "calculated_segments": [
            {"id": "S1", "size_mm": 80, "network_path_id":"P1","flow_order":0,"calc_id": "A", "plan_id": "A", "riser_id": "A", "schedule_id": "A"},
            {"id": "S2", "size_mm": 80, "network_path_id":"P1","flow_order":1,"calc_id": "B", "plan_id": "B", "riser_id": "B", "schedule_id": "B"},
        ],
        "calculated_catchments": [
            {"catchment_id":"C1","drain_dn_mm":80,"downpipe_dn_mm":80,"appendix7_evidence":{"base_rainfall_mm_h":25.4,"horizontal_slope_percent":1.0,"printed_anomaly_preserved":False}},
            {"catchment_id":"C2","drain_dn_mm":80,"downpipe_dn_mm":80,"appendix7_evidence":{"base_rainfall_mm_h":25.4,"horizontal_slope_percent":2.0,"printed_anomaly_preserved":False}},
        ],
    }


def by_id(result, rule_id):
    return next(row for row in result["evaluations"] if row["rule_id"] == rule_id)


def test_module_integrity_and_all_534_source_entries_have_nonpassing_dispositions():
    validation = validate_rulebook_module()
    assert validation["status"] == "PASS", validation
    assert validation["source_entry_count"] == 534
    coverage = load_rulebook_module()["coverage"]
    assert len({row["source_id"] for row in coverage["entries"]}) == 534
    assert all(row["automatic_pass"] is False for row in coverage["entries"])
    assert all(row["disposition"] in {"EXECUTABLE_RULE", "DEFINITION", "GUIDANCE",
        "DEPENDENCY_CONTEXT", "UNRESOLVED_CONTROL", "DOCUMENTED_NOT_APPLICABLE"}
        for row in coverage["entries"])


def test_complete_inputs_pass_every_implemented_rule_but_missing_implementation_chains_block_release():
    result = evaluate_rainwater_rules(complete_snapshot())
    assert all(row["status"] in {"PASS", "NOT_APPLICABLE"} for row in result["evaluations"]), result
    assert result["unresolved_source_controls"] == 179
    assert result["status"] == "INPUT_REQUIRED"
    assert result["release_allowed"] is False


@pytest.mark.parametrize("rule_id,mutator", [
    ("IR-M4-1396-4.9.5.2-FLAT-ROOF-SLOPE", lambda s: s["roof"]["catchments"][0].update(roof_surface_slope_percent=1.9)),
    ("IR-M4-M16-MAIN-ROOF-MIN-TWO-DRAINS-STACKS", lambda s: s["roof"].update(catchments=s["roof"]["catchments"][:1], stacks=s["roof"]["stacks"][:1])),
    ("IR-M4-1396-4.9.5.2-RAIN-SANITARY-SEPARATION", lambda s: s["rule_context"].update(rainwater_sanitary_separation_verified=False)),
    ("IR-M4-1396-4.9.14.4-EMERGENCY-SHAFT", lambda s: s["roof"].pop("emergency_rainwater_shaft")),
    ("IR-M6-1398-6.8.4-SECONDARY-SEPARATION", lambda s: s["roof"]["secondary_network"].update(discharge_points=[{"id":"SDX","point":[4,1]}])),
    ("IR-M16-1396-16.6.2.1-A-RAINFALL-BASIS", lambda s: s["draft_assumption_basis"].update(rainfall_authority="USER_CONFIRMED_UNVERIFIED")),
    ("IR-M16-1396-16.6.2.1-T-EMERGENCY-PATH", lambda s: s["roof"]["secondary_network"].update(outlet_visible=False)),
    ("IR-M16-1396-16.6.2.3-DRAIN-STRAINER-WATERTIGHT", lambda s: s["roof"]["catchments"][0]["drain"].update(strainer_height_mm=99)),
    ("IR-M16-1396-16.6.2.5-HORIZONTAL-SLOPE", lambda s: s["roof"]["catchments"][0].update(horizontal_pipe_slope_percent=.9)),
    ("IR-M16-1396-16.6.2.5-STACK-DN-SEPARATION", lambda s: s["roof"]["stacks"][0].update(dn_mm=75)),
    ("IR-M16-1396-16.6.2.1-NO-DIAMETER-REDUCTION", lambda s: s["calculated_segments"][1].update(size_mm=75)),
    ("IR-STRUCTURAL-RAIN-LOAD-R-DEPENDENCY", lambda s: s["rule_context"].update(structural_ponding_stability_review="REJECTED")),
    ("PLANHA-RW-INTERNAL-TRACE-001", lambda s: s["calculated_segments"][0].update(plan_id="OTHER")),
])
def test_each_operative_validator_has_a_destructive_boundary(rule_id, mutator):
    snapshot = complete_snapshot(); mutator(snapshot)
    assert by_id(evaluate_rainwater_rules(snapshot), rule_id)["status"] == "FAIL"


@pytest.mark.parametrize("rule_id,mutator", [
    ("IR-M4-1396-4.9.5.2-FLAT-ROOF-SLOPE", lambda s: s["roof"].pop("roof_type")),
    ("IR-M4-M16-MAIN-ROOF-MIN-TWO-DRAINS-STACKS", lambda s: s["roof"].pop("roof_role")),
    ("IR-M4-1396-4.9.5.2-RAIN-SANITARY-SEPARATION", lambda s: s["rule_context"].pop("rainwater_sanitary_separation_verified")),
    ("IR-M4-1396-4.9.14.4-EMERGENCY-SHAFT", lambda s: s["rule_context"].pop("building_in_m4_scope")),
    ("IR-M6-1398-6.8.4-SECONDARY-SEPARATION", lambda s: s["roof"]["secondary_network"].pop("discharge_points")),
    ("IR-M16-1396-16.6.2.1-A-RAINFALL-BASIS", lambda s: s["design_basis"].pop("rainfall_return_period_years")),
    ("IR-M16-1396-16.6.2.1-T-EMERGENCY-PATH", lambda s: s["rule_context"].pop("structural_rain_load_R_review")),
    ("IR-M16-1396-16.6.2.3-DRAIN-STRAINER-WATERTIGHT", lambda s: s["roof"]["catchments"][0]["drain"].pop("watertight_connection")),
    ("IR-M16-1396-16.6.2.5-HORIZONTAL-SLOPE", lambda s: s["roof"]["catchments"][0].pop("horizontal_pipe_slope_percent")),
    ("IR-M16-1396-16.6.2.5-STACK-DN-SEPARATION", lambda s: s["roof"]["stacks"][0].pop("dn_mm")),
    ("IR-M16-1396-16.6.2.1-NO-DIAMETER-REDUCTION", lambda s: s.update(calculated_segments=[])),
    ("IR-STRUCTURAL-RAIN-LOAD-R-DEPENDENCY", lambda s: s["rule_context"].pop("structural_rain_load_R")),
    ("PLANHA-RW-INTERNAL-TRACE-001", lambda s: s.update(calculated_segments=[])),
])
def test_unknown_is_never_not_applicable_or_pass(rule_id, mutator):
    snapshot=complete_snapshot();mutator(snapshot)
    assert by_id(evaluate_rainwater_rules(snapshot),rule_id)["status"]=="INPUT_REQUIRED"


def test_real_exceptions_are_not_applicable_but_unknown_is_not():
    snapshot=complete_snapshot();snapshot["roof"]["roof_type"]="PITCHED"
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M4-1396-4.9.5.2-FLAT-ROOF-SLOPE")["status"]=="NOT_APPLICABLE"
    snapshot=complete_snapshot();snapshot["roof"]["roof_role"]="PENTHOUSE_ROOF"
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M4-M16-MAIN-ROOF-MIN-TWO-DRAINS-STACKS")["status"]=="NOT_APPLICABLE"


def test_llm_cannot_override_fixed_obligation():
    snapshot=complete_snapshot();snapshot["roof"]["catchments"][0]["roof_surface_slope_percent"]=1
    result=evaluate_rainwater_rules(snapshot,llm_suggestions={"force_pass":True})
    assert result["llm_suggestions_ignored"] is True
    assert by_id(result,"IR-M4-1396-4.9.5.2-FLAT-ROOF-SLOPE")["status"]=="FAIL"


def test_dependency_identity_invalidates_on_rule_version_change(tmp_path):
    source=Path(__file__).parents[1]/"data/rulebook/modules/mechanical/rainwater"
    target=tmp_path/"rainwater";target.mkdir()
    for name in ("module.json","rules.json","source_coverage.json"):
        (target/name).write_bytes((source/name).read_bytes())
    first=module_dependency_identity(target)
    payload=json.loads((target/"rules.json").read_text());payload["version"]="1.0.1"
    (target/"rules.json").write_text(json.dumps(payload,ensure_ascii=False))
    assert module_dependency_identity(target)!=first


@pytest.mark.parametrize("rule_id,mutator", [
    ("IR-M16-1396-FULL-COLUMN-STATIC-PRESSURE", lambda s: s["roof"]["stacks"][0].update(component_pressure_rating_kpa=100)),
    ("IR-M16-1396-FORBIDDEN-JOINTS", lambda s: s["rule_context"].update(rainwater_joints=[{"method":"ADHESIVE","materials":["PVC","PP"],"diameters_mm":[80,80]}])),
    ("IR-M16-1396-16.6.2.4-CLEANOUTS", lambda s: s["rule_context"]["cleanout_segments"][0].update(max_cleanout_spacing_m=16)),
    ("IR-M16-1396-ENVIRONMENTAL-FIRE-PROTECTION", lambda s: s["rule_context"]["rainwater_components"][0].update(protections=["UV"])),
    ("IR-M16-1396-PIPE-SUPPORTS", lambda s: s["rule_context"]["rainwater_supports"][0].update(spacing_m=1.3)),
    ("IR-M16-1396-FULL-HEAD-LEAK-TEST", lambda s: s["rule_context"]["rainwater_leak_tests"][0].update(duration_minutes=14)),
])
def test_mechanical_batch_destructive_boundaries(rule_id, mutator):
    snapshot=complete_snapshot(); mutator(snapshot)
    assert by_id(evaluate_rainwater_rules(snapshot),rule_id)["status"]=="FAIL"


def test_upper_roof_discharge_is_conditional_and_checks_geometry_detail():
    snapshot=complete_snapshot()
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M16-1396-UPPER-ROOF-DISCHARGE-PROTECTION")["status"]=="NOT_APPLICABLE"
    snapshot["rule_context"].update(upper_roof_discharges_to_lower_roof=True,
        upper_roof_discharges=[{"elbow_configuration":"ONE_90","impact_protection":"STONE"}])
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M16-1396-UPPER-ROOF-DISCHARGE-PROTECTION")["status"]=="PASS"
    snapshot["rule_context"]["upper_roof_discharges"][0]["impact_protection"]="NONE"
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M16-1396-UPPER-ROOF-DISCHARGE-PROTECTION")["status"]=="FAIL"


def test_material_certificate_marking_requires_real_external_evidence_and_rejects_mismatch():
    snapshot=complete_snapshot(); component=snapshot["rule_context"]["rainwater_components"][0]
    component["certificate"]["product_identity"]="OTHER"
    result=by_id(evaluate_rainwater_rules(snapshot),"IR-M16-1396-MATERIAL-CERTIFICATE-MARKING")
    assert result["status"]=="FAIL" and "CERTIFICATE_PRODUCT_IDENTITY_MISMATCH" in result["errors"][0]
    component["certificate"]["product_identity"]="PVC-RW-80"
    component["certificate"].pop("evidence_provenance")
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M16-1396-MATERIAL-CERTIFICATE-MARKING")["status"]=="INPUT_REQUIRED"
    component.pop("certificate")
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M16-1396-MATERIAL-CERTIFICATE-MARKING")["status"]=="INPUT_REQUIRED"


def test_appendix7_multilevel_effective_area_changes_real_sizing_without_double_counting():
    snapshot=complete_snapshot()
    snapshot["design_basis"]["rainfall_intensity_mm_h"]=100
    snapshot["roof"]["catchments"][0]["contributing_wall_areas_m2"]=[100]
    snapshot["roof"]["catchments"][1]["upstream_transfer_ids"]=["C1"]
    snapshot["roof"]["catchments"][1]["horizontal_pipe_slope_percent"]=2.0
    result=design_roof_rainwater(snapshot["roof"],snapshot["design_basis"],
        rule_context=snapshot["rule_context"],draft_assumption_basis=snapshot["draft_assumption_basis"])
    rows={row["catchment_id"]:row for row in result["catchments"]}
    assert rows["C1"]["effective_area_m2"]==150
    assert rows["C2"]["effective_area_m2"]==250
    assert rows["C2"]["downpipe_dn_mm"]==100
    snapshot["roof"]["catchments"][1]["upstream_transfer_ids"]=["C1","C1"]
    failed=design_roof_rainwater(snapshot["roof"],snapshot["design_basis"],
        rule_context=snapshot["rule_context"],draft_assumption_basis=snapshot["draft_assumption_basis"])
    assert failed["status"]=="FAIL" and any("TRANSFER_DUPLICATE" in error for error in failed["errors"])


def test_appendix7_complete_tables_preserve_dn250_four_percent_printed_anomaly():
    snapshot=complete_snapshot(); catchment=snapshot["roof"]["catchments"][0]
    catchment["polygon"]=[[0,0],[3000,0],[3000,1],[0,1]]
    catchment["low_point"]=[2,0.5];catchment["drain"]["point"]=[2,0.5]
    catchment["route"]=[[2,0.5],[4,0.5],[4,1]];catchment["horizontal_pipe_slope_percent"]=4.0
    snapshot["roof"]["boundary"]=[[0,0],[3000,0],[3000,10],[0,10]]
    result=design_roof_rainwater(snapshot["roof"],snapshot["design_basis"],
        rule_context=snapshot["rule_context"],draft_assumption_basis=snapshot["draft_assumption_basis"])
    row=result["catchments"][0]
    assert row["downpipe_dn_mm"]==250
    assert row["appendix7_evidence"]["horizontal_table_area_m2"]==15984
    assert row["appendix7_evidence"]["horizontal_table_flow_lps"]==112.52
    assert row["appendix7_evidence"]["printed_anomaly_preserved"] is True


def test_trench_burial_is_conditional_and_enforces_dimensions():
    snapshot=complete_snapshot()
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M16-1396-TRENCH-BURIAL")["status"]=="NOT_APPLICABLE"
    snapshot["rule_context"]["buried_gravity_rainwater_segments"]=[{"id":"B1","soil_condition":"ROCK","continuous_shaped_bedding":True,"balanced_compaction":True,"lift_mm":150,"rock_overcut_mm":74,"inspection_before_covering":True}]
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M16-1396-TRENCH-BURIAL")["status"]=="FAIL"
    snapshot["rule_context"]["buried_gravity_rainwater_segments"][0]["rock_overcut_mm"]=75
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M16-1396-TRENCH-BURIAL")["status"]=="PASS"


def test_architectural_discharge_boundary_rejects_public_way_and_requires_surface_permit():
    snapshot=complete_snapshot(); rows=snapshot["rule_context"]["rainwater_discharge_destinations"]
    rows[0].update(destination_type="PUBLIC_WAY",inside_property=False)
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M4-1396-RAINWATER-DISCHARGE-BOUNDARY")["status"]=="FAIL"
    rows[0].update(destination_type="OWN_PROPERTY_SURFACE",inside_property=True)
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M4-1396-RAINWATER-DISCHARGE-BOUNDARY")["status"]=="INPUT_REQUIRED"
    rows[0]["permit"]={"id":"PERMIT-SYNTHETIC","status":"APPROVED"}
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M4-1396-RAINWATER-DISCHARGE-BOUNDARY")["status"]=="PASS"


def test_structural_dead_load_requires_water_full_mass_and_real_approval_reference():
    snapshot=complete_snapshot(); row=snapshot["rule_context"]["structural_rainwater_loads"][0]
    row["water_full_mass_kg"]=11
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M6-1398-PERMANENT-RAINWATER-DEAD-LOAD")["status"]=="FAIL"
    row["water_full_mass_kg"]=20;row["structural_review"].pop("approval_id")
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M6-1398-PERMANENT-RAINWATER-DEAD-LOAD")["status"]=="INPUT_REQUIRED"

def test_waterproofing_interface_positive_negative_unknown_and_exception():
    snapshot=complete_snapshot(); rule="IR-M4-1396-4.9.10.1-WATERPROOFING-INTERFACE"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    snapshot["rule_context"]["waterproofing_interfaces"][0]["membrane_continuous"]=False
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    snapshot["rule_context"].pop("waterproofing_interfaces")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot["rule_context"]["waterproofing_interfaces"]=[{"entity_id":"B1","source_geometry_id":"G-B1",
        "surface_type":"LOW_EXPOSURE_BALCONY","exposure_classification_evidence_id":"ARCH-SYNTHETIC-1"}]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"

def test_basement_entry_positive_negative_unknown_and_verified_absence():
    snapshot=complete_snapshot(); rule="IR-M4-1396-BASEMENT-ENTRY-RUNOFF-PROTECTION"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    snapshot["rule_context"]["basement_openings"][0]["surface_water_entry_prevented"]=False
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    snapshot["rule_context"].pop("basement_openings")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot["rule_context"]["basement_openings"]=[]
    snapshot["rule_context"]["basement_openings_verified_absent"]=True
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="NOT_APPLICABLE"

def test_shaft_access_private_route_positive_negative_and_unknown():
    snapshot=complete_snapshot();rule="IR-M4-1396-SHAFT-ACCESS-PRIVATE-ROUTE"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    route=snapshot["rule_context"]["rainwater_route_entities"][0]
    route["route_points"]=[[1,1],[6,6]]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    route["rerouted_route_id"]="R-SYN-REROUTED"
    route["rerouted_route_points"]=[[1,1],[6,6]]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    route["rerouted_route_points"]=[[1,1],[3,1]]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    snapshot["rule_context"].pop("rainwater_route_entities")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"

def test_suspended_ceiling_clearance_support_positive_negative_unknown_exception():
    snapshot=complete_snapshot();rule="IR-M4-1396-SUSPENDED-CEILING-CLEARANCE-SEPARATION"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    snapshot["rule_context"]["suspended_ceiling_route_interfaces"][0]["finished_ceiling_elevation_m"]=2.3
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    snapshot["rule_context"].pop("suspended_ceiling_route_interfaces")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot["rule_context"]["suspended_ceiling_route_interfaces"]=[]
    snapshot["rule_context"]["suspended_ceiling_interfaces_verified_absent"]=True
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="NOT_APPLICABLE"

def test_pitched_roof_property_setback_group_thresholds_and_unknown():
    snapshot=complete_snapshot();rule="IR-M4-1396-PITCHED-ROOF-PROPERTY-SAFETY"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="NOT_APPLICABLE"
    snapshot["roof"]["roof_type"]="PITCHED"
    snapshot["rule_context"].update(building_group=6,building_floor_count=6,pitched_roof_edges=[{
        "edge_id":"PE-1","edge_points":[[0,0],[1,0]],"boundary_points":[[0,-.39],[1,-.39]],
        "slopes_toward_boundary":True,"snow_ice_retention":True,"worker_safety_anchor_id":"ANCHOR-1"}])
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    snapshot["rule_context"]["pitched_roof_edges"][0]["boundary_points"]=[[0,-.4],[1,-.4]]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    snapshot["rule_context"].pop("building_group")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"

def test_exterior_and_parking_drainage_boundaries_unknown_and_exceptions():
    snapshot=complete_snapshot(); exterior="IR-M4-1396-EXTERIOR-SPACE-DRAINAGE";parking="IR-M4-1396-PARKING-SURFACE-RUNOFF"
    assert by_id(evaluate_rainwater_rules(snapshot),exterior)["status"]=="PASS"
    snapshot["rule_context"]["exterior_drainage_spaces"][0]["route_points"]=[[0,0],[3,1]]
    assert by_id(evaluate_rainwater_rules(snapshot),exterior)["status"]=="FAIL"
    snapshot["rule_context"]["exterior_drainage_spaces"][0]["route_points"]=[[1,1],[3,1]]
    snapshot["rule_context"]["exterior_drainage_spaces"][0]["destination_type"]="PUBLIC_WAY"
    assert by_id(evaluate_rainwater_rules(snapshot),exterior)["status"]=="FAIL"
    snapshot["rule_context"].pop("exterior_drainage_spaces")
    assert by_id(evaluate_rainwater_rules(snapshot),exterior)["status"]=="INPUT_REQUIRED"
    snapshot["rule_context"]["exterior_drainage_spaces"]=[];snapshot["rule_context"]["exterior_drainage_spaces_verified_absent"]=True
    assert by_id(evaluate_rainwater_rules(snapshot),exterior)["status"]=="NOT_APPLICABLE"
    snapshot=complete_snapshot();snapshot["rule_context"]["parking_drainage_areas"][0]["entrance_crest_above_exterior_m"]=0
    assert by_id(evaluate_rainwater_rules(snapshot),parking)["status"]=="FAIL"
    snapshot["rule_context"]["parking_drainage_areas"][0]["approved_alternative"]={"id":"AUTH-SYNTHETIC-1"}
    assert by_id(evaluate_rainwater_rules(snapshot),parking)["status"]=="PASS"

def test_installation_protection_rejects_elevator_shaft_and_requires_valid_structural_provenance():
    snapshot=complete_snapshot();rule="IR-M16-1396-INSTALLATION-PROTECTION-PENETRATIONS"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    snapshot["rule_context"]["rainwater_installation_interfaces"][0]["interface_type"]="ELEVATOR_SHAFT"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    snapshot["rule_context"]["rainwater_installation_interfaces"]=[{"interface_id":"PEN-1","source_geometry_id":"G-PEN-1",
        "interface_type":"STRUCTURAL_OPENING","sleeve_or_clearance_detail_id":"SL-1","structural_approval":{"id":"ONLY-ID"}}]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"

def test_nonpotable_separation_rejects_direct_connection_and_requires_backflow_provenance():
    snapshot=complete_snapshot();rule="IR-M16-1396-NONPOTABLE-SEPARATION-BACKFLOW"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row=snapshot["rule_context"]["nonpotable_reuse_connections"][0];row["connection_type"]="DIRECT_POTABLE_TO_NONPOTABLE"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row.update(connection_type="POTABLE_MAKEUP",backflow_device={"product_identity":"BF-1","standard":"SYNTH","device_type":"RPZ","accessible":True})
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_rules_change_design_status_and_final_target_gate_but_preserve_honest_draft():
    snapshot=complete_snapshot();snapshot["roof"]["catchments"][0]["roof_surface_slope_percent"]=1
    result=design_roof_rainwater(snapshot["roof"],snapshot["design_basis"],
        rule_context=snapshot["rule_context"],draft_assumption_basis=snapshot["draft_assumption_basis"])
    assert result["status"]=="PASS" and result["design_compliance_status"]=="FAIL"
    package=build_rainwater_package(snapshot)
    assert package["status"]=="FAIL" and package["blocked_at"]=="rainwater_rulebook"


def test_real_dxf_reopens_with_secondary_routes_discharges_rule_labels_and_calc_linkage():
    snapshot=complete_snapshot()
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS",generated
    assert generated["qa"]["checks"]["rulebook_identity_present"] is True
    assert generated["qa"]["checks"]["secondary_network_reconciled"] is True
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")));msp=doc.modelspace()
    assert len(msp.query('LWPOLYLINE[layer=="RW-SECONDARY"]'))==2
    assert len(msp.query('CIRCLE[layer=="RW-SECONDARY-DISCHARGE"]'))==2
    text=" ".join(entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-RULE"]'))
    assert "RULEBOOK 2.22.0" in text and "COMPLIANCE=INPUT_REQUIRED" in text
    detail_text=" ".join(entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-DETAIL"]'))
    assert "ARCHITECTURAL WATERPROOFING / BASEMENT RUNOFF DETAILS" in detail_text
    assert "UPSTAND=WP-DETAIL-1" in detail_text and "INTERCEPTOR=INT-1" in detail_text
    assert "ACCESS PANEL=AP-1" in detail_text and "INDEPENDENT SUPPORT=True" in detail_text
    assert "EXTERIOR EXT-1" in detail_text and "PARKING PK-1" in detail_text
    assert "INSTALL OUTLET-1" in detail_text and "GRATE=GRATE-1" in detail_text
    assert "NONPOTABLE NP-1" in detail_text and "AIR GAP=150mm" in detail_text
    assert "ROOF ACCESS | TYPE=PUBLIC_STAIR" in detail_text and "PARAPET=1.1m" in detail_text
    assert "ENTRANCE E-1 | INSIDE=0mm" in detail_text
    assert "RAIN ON SNOW | REGION=2" in detail_text and "COMBINED=1.25kN/m2" in detail_text
    assert "ROOF LIVE LOAD WALK-1 | TYPE=SERVICE_WALKWAY" in detail_text
    assert "MATERIAL MAT-1 | UPVC | STD=EN 1329" in detail_text
    assert "SUPPORT INSTALL SUP-CIV-1 | CAST_IRON/VERTICAL" in detail_text
    assert "SUPPORT INSTALL SUP-GSH-1 | GALVANIZED_STEEL/HORIZONTAL" in detail_text
    assert "POTABLE AIR GAP AG-1 | GROUP=GOOSENECK_SINK_LAUNDRY" in detail_text
    assert "LRFD RAINWATER LOAD COMBINATIONS | GOVERNING=LRFD-3-R-L" in detail_text
    assert "ASD RAINWATER LOAD COMBINATIONS" in detail_text
    assert "PRIMARY BLOCKAGE RAIN LOAD ROOF-1 | DS=60.0mm | DH=20mm | R=0.8kN/m2" in detail_text
    access=list(msp.query('LWPOLYLINE[layer=="RW-MAINT-ACCESS"]'))
    assert len(access)==1 and list(access[0].get_points("xy"))==[(1.0,1.0),(1.0,5.0)]
    ramp=list(msp.query('LWPOLYLINE[layer=="RW-PARKING-RAMP-PROFILE"]'))
    assert len(ramp)==1 and list(ramp[0].get_points("xy"))==[(0.0,0.0),(1.0,.1),(10.0,1.45),(11.0,1.55)]
    assert "ROOF SNOW LOAD ROOF-1 | PR=1.0kN/m2" in detail_text
    assert generated["qa"]["checks"]["architecture_route_geometry_reconciled"] is True
    audit_route=list(msp.query('LWPOLYLINE[layer=="RW-ARCH-ROUTE-AUDIT"]'))[0]
    audit_route.set_points([(1,1),(6,6)])
    stream=StringIO();doc.write(stream)
    tampered=_rainwater_plan_independent_qa(snapshot,generated["result"],stream.getvalue().encode("utf-8"))
    assert tampered["status"]=="FAIL"
    assert "ARCHITECTURE_ROUTE_GEOMETRY_MISMATCH" in tampered["errors"]
    assert all(row["calc_id"] in " ".join(entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-ANNOTATION"]'))
               for row in generated["result"]["catchments"])


def test_document_closeout_is_stage_specific_and_provenance_checked():
    snapshot=complete_snapshot(); rule="IR-M16-1396-DOCUMENTATION-STAGE-CLOSEOUT"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    snapshot["rule_context"]["project_stage"]="FINAL_INSPECTION"
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="INPUT_REQUIRED"
    assert "rainwater_documentation.final_inspection.valid_provenance" in result["missing_inputs"]


def test_roof_equipment_overflow_rejects_forbidden_receptor_and_preserves_cooler_exception():
    snapshot=complete_snapshot(); c=snapshot["rule_context"]
    c["roof_equipment_overflows"]=[{"equipment_id":"T-1","equipment_type":"TANK","route_points":[[1,1],[2,1]],"receptor_type":"ROOF_RAINWATER_DRAIN","discharges_loose_on_roof":False}]
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M16-1396-ROOF-EQUIPMENT-OVERFLOW")["status"]=="FAIL"
    c["roof_equipment_overflows"][0]["equipment_type"]="EVAPORATIVE_COOLER"
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M16-1396-ROOF-EQUIPMENT-OVERFLOW")["status"]=="PASS"


def test_route_installation_rejects_concrete_embedding_and_non_gravity_claim():
    snapshot=complete_snapshot(); r=snapshot["rule_context"]["rainwater_route_installation_records"][0]
    r["gravity_flow_verified"]=False;r["embedded_in_concrete"]=True
    result=by_id(evaluate_rainwater_rules(snapshot),"IR-M16-1396-MATERIAL-ROUTE-SUPPORT-COMPLETION")
    assert result["status"]=="FAIL"
    assert "ROUTE_0_NOT_GRAVITY_FLOW" in result["errors"] and "ROUTE_0_EMBEDDED_IN_CONCRETE" in result["errors"]


def test_owner_module_dependencies_are_fail_closed_and_require_valid_provenance():
    snapshot=complete_snapshot();rule="IR-M6-OWNER-MODULE-COMPLIANCE-DEPENDENCY"
    snapshot["rule_context"]["interdisciplinary_compliance"]["structural"]={"status":"PASS"}
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot["rule_context"]["interdisciplinary_compliance"]["structural"]={"status":"FAIL","evidence_provenance":{"verification_status":"VALID","source_sha256":"c"*64}}
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="FAIL" and "STRUCTURAL_OWNER_MODULE_NOT_PASS" in result["errors"]


def test_roof_access_parapet_uses_geometry_and_preserves_steep_roof_exception():
    snapshot=complete_snapshot();rule="IR-M4-1396-ROOF-ACCESS-PARAPET-GEOMETRY";r=snapshot["rule_context"]["roof_access_safety"]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    r["parapet_height_m"]=1.09
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    r["parapet_height_m"]=1.10;r["parapet_polygon"]=[[0,0],[10,0],[10,10],[0,10]]
    assert "PARAPET_DOES_NOT_ENCLOSE_ACCESSIBLE_ROOF" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    r["parapet_polygon"]=[[-.1,-.1],[21.1,-.1],[21.1,29.8],[-.1,29.8]];r["parapet_edge_segments"].pop()
    assert "PARAPET_EDGE_3_NOT_CONTINUOUS_OR_TOO_LOW" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    r["parapet_edge_segments"].append({"start":[0,29.7],"end":[0,0],"height_m":1.10,"opening":True,
        "opening_guard_id":"G-1","opening_geometry":{"start":[0,10],"end":[0,12]},
        "opening_guard_geometry":{"start":[0,10.5],"end":[0,11.5],"height_m":1.10}})
    assert "PARAPET_EDGE_3_OPENING_GUARD_GEOMETRY_INSUFFICIENT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    r.update(roof_slope_percent=34,roof_use="NO_USE",roof_accessible=False,access_type="LADDER")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"


def test_entrance_landing_threshold_boundaries_and_public_occupancy_prohibition():
    snapshot=complete_snapshot();rule="IR-M4-1396-ENTRANCE-LANDING-THRESHOLD";r=snapshot["rule_context"]["entrance_landing_interfaces"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    r["threshold_top_elevation_mm"]=20.1
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    r.update(threshold_top_elevation_mm=0,occupancy_group="ASSEMBLY",threshold_present=True)
    assert "ENTRANCE_0_PUBLIC_OCCUPANCY_THRESHOLD_FORBIDDEN" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    r.update(occupancy_group="RESIDENTIAL",threshold_present=False,inside_landing_elevation_mm=0,outside_landing_elevation_mm=-1)
    assert "ENTRANCE_0_LANDINGS_NOT_SAME_LEVEL" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_rain_on_snow_boundary_and_forbidden_simultaneous_effects():
    snapshot=complete_snapshot();rule="IR-M6-1398-RAIN-ON-SNOW-LOAD-CASE";r=snapshot["rule_context"]["rain_on_snow_load_case"]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    r["rain_surcharge_kn_m2"]=0.24
    assert "RAIN_ON_SNOW_SURCHARGE_NOT_0_25_KN_M2" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    r.update(rain_surcharge_kn_m2=.25,simultaneous_effects=["SLIDING_SNOW"])
    assert "RAIN_ON_SNOW_COMBINED_WITH_FORBIDDEN_SNOW_EFFECT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    r.update(simultaneous_effects=[],roof_slope_deg=1.0,rain_surcharge_kn_m2=0,declared_combined_load_kn_m2=1.0)
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"


def test_roof_service_live_load_minima_and_ladder_boundaries():
    snapshot=complete_snapshot();rule="IR-M6-1398-ROOF-SERVICE-LIVE-LOADS";rows=snapshot["rule_context"]["roof_service_live_loads"]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    rows[1]["uniform_load_kn_m2"]=1.99
    assert "ROOF_LOAD_1_UNIFORM_BELOW_2_KN_M2" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    rows[1]["uniform_load_kn_m2"]=2;rows[2]["point_load_spacing_m"]=3.01
    assert "ROOF_LOAD_2_LADDER_POINT_SPACING_ABOVE_3_M" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_material_standard_joint_detail_rejects_burial_pressure_and_temperature_boundaries():
    snapshot=complete_snapshot();rule="IR-M16-1396-MATERIAL-STANDARD-JOINT-DETAIL";r=snapshot["rule_context"]["rainwater_material_installations"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    r.update(buried=True,burial_marking="B")
    assert "MATERIAL_0_BURIAL_MARKING_D_OR_BD_REQUIRED" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    r.update(buried=False,ambient_temperature_c=4.9,burial_marking=None)
    assert "MATERIAL_0_UPVC_ADHESIVE_BELOW_5C" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    r.update(material="PP",standard="EN 1451",joint_method="RUBBER_RING_PUSH_FIT",ambient_temperature_c=20,water_column_height_m=6.01)
    assert "MATERIAL_0_PP_ABOVE_6M_WATER_COLUMN_FORBIDDEN" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_material_support_details_enforce_bearing_movement_liner_and_bedding():
    snapshot=complete_snapshot();rule="IR-M16-1396-MATERIAL-SUPPORT-INSTALLATION-DETAIL"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    rows=snapshot["rule_context"]["rainwater_material_support_installations"]
    rows[0]["base_below_lowest_elbow"]=False
    assert "SUPPORT_0_BASE_NOT_BELOW_LOWEST_ELBOW" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    rows[0]["base_below_lowest_elbow"]=True;rows[1]["steel_liner_thickness_mm"]=1.49
    assert "SUPPORT_1_INSULATION_LINER_BELOW_1_5_MM" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    rows[1]["steel_liner_thickness_mm"]=1.5;rows[2]["continuous_sand_bedding"]=False
    assert "SUPPORT_2_BURIED_CAST_IRON_WITHOUT_SAND_BEDDING" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot["rule_context"].pop("rainwater_material_support_installations")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_potable_outlet_air_gap_table_boundaries_and_unknown():
    snapshot=complete_snapshot();rule="IR-M16-1396-POTABLE-OUTLET-AIR-GAP-TABLE";row=snapshot["rule_context"]["potable_outlets_over_rainwater_receptors"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["vertical_air_gap_mm"]=64.9
    assert "AIR_GAP_0_BELOW_65_MM" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row.update(outlet_group="OVER_25_MM",effective_diameter_mm=30,near_wall=False,vertical_air_gap_mm=60)
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["near_wall"]=True
    assert "AIR_GAP_0_BELOW_90_MM" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot["rule_context"].pop("potable_outlets_over_rainwater_receptors")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_lrfd_load_combinations_recompute_rain_cases_and_capacity():
    snapshot=complete_snapshot();rule="IR-M6-1398-LRFD-RAINWATER-LOAD-COMBINATIONS";row=snapshot["rule_context"]["structural_rainwater_load_combinations"]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["evaluated_cases"]["LRFD-3-R-L"]-=.1
    assert "LOAD_COMBINATION_MISMATCH:LRFD-3-R-L" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["evaluated_cases"]["LRFD-3-R-L"]+=.1;row["design_capacity_abs"]=20.39
    assert "DESIGN_CAPACITY_BELOW_GOVERNING_EFFECT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["design_capacity_abs"]=20.4;row["effect_unit"]="mm"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot["rule_context"].pop("structural_rainwater_load_combinations")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_asd_load_combinations_recompute_signed_cases_and_prohibit_stress_increase():
    snapshot=complete_snapshot();rule="IR-M6-1398-ASD-RAINWATER-LOAD-COMBINATIONS";row=snapshot["rule_context"]["structural_rainwater_asd_combinations"]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["evaluated_cases"]["ASD-6-R-W-POS"]-=.1
    assert "ASD_LOAD_COMBINATION_MISMATCH:ASD-6-R-W-POS" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["evaluated_cases"]["ASD-6-R-W-POS"]+=.1;row["allowable_stress_increase"]=True
    assert "ALLOWABLE_STRESS_INCREASE_PROHIBITED" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["allowable_stress_increase"]=False;row["effect_unit"]="mm"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_primary_blockage_rain_load_uses_elevations_hydraulic_head_and_ponding_analysis():
    snapshot=complete_snapshot();rule="IR-M6-1398-PRIMARY-BLOCKAGE-RAIN-LOAD-PONDING";row=snapshot["rule_context"]["roof_primary_blockage_rain_loads"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["declared_rain_load_kn_m2"]=.79
    assert "RAIN_LOAD_0_FORMULA_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["declared_rain_load_kn_m2"]=.8;row["ponding_analysis"]["stable"]=False
    assert "RAIN_LOAD_0_PONDING_UNSTABLE" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["ponding_analysis"]=None
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["ponding_analysis"]=complete_snapshot()["rule_context"]["roof_primary_blockage_rain_loads"][0]["ponding_analysis"]
    row["ponding_analysis"]["governing_water_or_snow_load_kn_m2"]=1.19
    assert "RAIN_LOAD_0_PONDING_GOVERNING_LOAD_BELOW_RAIN_OR_SNOW" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["ponding_analysis"]=complete_snapshot()["rule_context"]["roof_primary_blockage_rain_loads"][0]["ponding_analysis"]
    row["ponding_analysis"]["iterations"][-1]["residual_mm"]=.11
    assert "RAIN_LOAD_0_PONDING_NOT_NUMERICALLY_CONVERGED" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["ponding_analysis"]["iterations"][-1]["residual_mm"]=.05
    row["ponding_analysis"]["structural_approval"]["model_sha256"]="b"*64
    assert "RAIN_LOAD_0_PONDING_APPROVAL_MODEL_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["roof_slope_percent"]=3;row["primary_blockage_can_retain_water"]=True
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"


def test_roof_snow_load_basis_recomputes_formulas_and_checks_obstruction_geometry():
    snapshot=complete_snapshot();rule="IR-M6-1398-ROOF-SNOW-LOAD-BASIS";row=snapshot["rule_context"]["roof_snow_load_basis"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["declared_balanced_roof_snow_pr_kn_m2"]=.99
    assert "SNOW_0_PR_FORMULA_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["declared_balanced_roof_snow_pr_kn_m2"]=1;row["classified_as_exposed_roof"]=True
    assert "SNOW_0_EXPOSED_CLASSIFICATION_CONTRADICTED_BY_OBSTRUCTION_0" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row.pop("exposure_geometry_analysis_id")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row=complete_snapshot()["rule_context"]["roof_snow_load_basis"][0];snapshot["rule_context"]["roof_snow_load_basis"]=[row]
    row.update(roof_slope_degrees=50,slope_factor_cs=1)
    assert "SNOW_0_SLOPE_FACTOR_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["roof_snow_load_basis"][0];snapshot["rule_context"]["roof_snow_load_basis"]=[row]
    row["eave_overhang"]["declared_design_load_kn_m2"]=1.9
    assert "SNOW_0_OVERHANG_LOAD_NOT_DOUBLE_PR" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_rooftop_snow_drift_uses_feature_geometry_and_width_exception():
    snapshot=complete_snapshot();rule="IR-M6-1398-ROOFTOP-SNOW-DRIFT-GEOMETRY";row=snapshot["rule_context"]["rooftop_snow_drift_features"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["declared_lu_m"]=12
    assert "DRIFT_0_LU_GEOMETRY_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row.update(feature_type="ROOFTOP_RAISED_FEATURE",face_width_m=4.49,drift_applied=False)
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["drift_applied"]=True
    assert "DRIFT_0_APPLIED_TO_RAISED_FEATURE_BELOW_4_5_M" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["rooftop_snow_drift_features"][0];snapshot["rule_context"]["rooftop_snow_drift_features"]=[row]
    row["declared_drift_width_w_m"]=2.39
    assert "DRIFT_0_RELATION_6_7_5_WIDTH_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["rooftop_snow_drift_features"][0];snapshot["rule_context"]["rooftop_snow_drift_features"]=[row]
    row["structural_interpretation"]["structural_model_sha256"]=""
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_fluid_load_extensions_use_dead_load_coefficients_for_all_required_cases():
    snapshot=complete_snapshot();rule="IR-M6-1398-FLUID-LOAD-COMBINATION-EXTENSIONS";rows=snapshot["rule_context"]["fluid_load_combination_extensions"]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    rows[0]["declared_effect_including_f"]-=.1
    assert "FLUID_0_COMBINATION_EFFECT_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();snapshot["rule_context"]["fluid_load_combination_extensions"]=[r for r in snapshot["rule_context"]["fluid_load_combination_extensions"] if not (r["method"]=="ASD" and r["base_combination_number"]=="10")]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_heavy_rooftop_equipment_requires_model_bound_placement_and_seismic_analysis():
    snapshot=complete_snapshot();rule="IR-M6-1398-HEAVY-ROOFTOP-EQUIPMENT-PLACEMENT";row=snapshot["rule_context"]["heavy_rooftop_equipment_placements"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["placement_structural_analysis"]["model_sha256"]="e"*64
    assert "EQUIPMENT_0_PLACEMENT_MODEL_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["heavy_rooftop_equipment_placements"][0];snapshot["rule_context"]["heavy_rooftop_equipment_placements"]=[row]
    row.pop("seismic_nonstructural_analysis")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_roof_live_load_reduction_recomputes_r1_r2_and_limits():
    snapshot=complete_snapshot();rule="IR-M6-1398-ROOF-LIVE-LOAD-REDUCTION";row=snapshot["rule_context"]["roof_live_load_reductions"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row.update(tributary_area_m2=54,roof_slope_percent=100,slope_parameter_s=100,declared_lr_kn_m2=.6)
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["declared_lr_kn_m2"]=.61
    assert "ROOF_LIVE_0_REDUCTION_FORMULA_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["roof_live_load_reductions"][0];snapshot["rule_context"]["roof_live_load_reductions"]=[row]
    row["roof_slope_degrees"]=18.26
    assert "ROOF_LIVE_0_DEGREE_INPUT_NOT_S_PARAMETER" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_special_use_roof_and_serviceability_contracts():
    snapshot=complete_snapshot();rule="IR-M6-1398-SPECIAL-USE-ROOF-LIVE-LOAD-REDUCTION";row=snapshot["rule_context"]["special_use_roof_live_load_reductions"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["declared_design_live_load_kn_m2"]=3.1
    assert "SPECIAL_ROOF_0_DESIGN_LOAD_BELOW_APPROVED_RESULT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();rule="IR-M6-1398-ROOF-SERVICEABILITY-DEFLECTION";row=snapshot["rule_context"]["roof_serviceability_deflection_checks"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["calculated_deflection_mm"]=25.01
    assert "DEFLECTION_0_EXCEEDS_ALLOWABLE" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["roof_serviceability_deflection_checks"][0];snapshot["rule_context"]["roof_serviceability_deflection_checks"]=[row]
    row["allowable_deflection_ratio"]=300
    assert "DEFLECTION_0_LIMIT_RATIO_SOURCE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_m4_maintenance_access_uses_actual_corridor_obstacles_and_endpoints():
    snapshot=complete_snapshot();rule="IR-M4-1396-RAINWATER-MAINTENANCE-ACCESS-GEOMETRY";row=snapshot["rule_context"]["rainwater_maintenance_access_paths"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["obstacle_polygons"]=[{"polygon":[[.8,2],[1.2,2],[1.2,3],[.8,3]]}]
    assert "ACCESS_0_FOOTPRINT_BLOCKED_BY_OBSTACLE_0" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["rainwater_maintenance_access_paths"][0];snapshot["rule_context"]["rainwater_maintenance_access_paths"]=[row];row["target_access_point"]=[1.2,5]
    assert "ACCESS_0_END_NOT_CONNECTED_TO_TARGET" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["rainwater_maintenance_access_paths"][0];snapshot["rule_context"]["rainwater_maintenance_access_paths"]=[row];row["corridor_polygon"]=[[.8,.5],[1.2,.5],[1.2,5.5],[.8,5.5]]
    assert "ACCESS_0_CLEAR_FOOTPRINT_OUTSIDE_CORRIDOR" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["rainwater_maintenance_access_paths"][0];snapshot["rule_context"]["rainwater_maintenance_access_paths"]=[row];row["path_points"]=[[1,1]]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_m4_parking_ramp_profile_uses_actual_station_elevations_and_boundaries():
    snapshot=complete_snapshot();rule="IR-M4-1396-PARKING-RAMP-RUNOFF-INTERFACE-GEOMETRY";row=snapshot["rule_context"]["parking_ramp_profiles"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["profile_points"][1][1]=.101
    assert "PARKING_RAMP_0_END_ZONE_SLOPE_ABOVE_10_PERCENT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["parking_ramp_profiles"][0];snapshot["rule_context"]["parking_ramp_profiles"]=[row];row["profile_points"][2][1]=1.54
    assert "PARKING_RAMP_0_BODY_SLOPE_ABOVE_15_PERCENT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["parking_ramp_profiles"][0];snapshot["rule_context"]["parking_ramp_profiles"]=[row];row["profile_points"][1][0]=1.1
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
