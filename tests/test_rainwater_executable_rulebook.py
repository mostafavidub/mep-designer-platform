from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path

import ezdxf
import pytest
from jsonschema import Draft202012Validator

from cad_engine.executable_rulebook import (
    load_rulebook_module, module_dependency_identity, validate_rulebook_module,
)
from cad_engine.independent_deliverables import execute_registered_generator, _rainwater_plan_independent_qa
from cad_engine.mechanical_target_design import build_rainwater_package
from cad_engine.rainwater_calculations import design_roof_rainwater
from cad_engine.rainwater_rulebook import VALIDATORS, evaluate_rainwater_rules


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
            "allowable_stress_increase":False,"wind_and_seismic_combined":False,"structural_analysis_id":"STRUCT-ASD-SYN-1"}


def _fluid_fixture():
    coefficients={"LRFD":{"1":1.4,"2":1.2,"3":1.2,"4":1.2,"5":1.2,"7":.9},
                  "ASD":{"1":1,"2":1,"3":1,"4":1,"5":1,"6":1,"7":1,"8":1,"10":.6}}
    return [{"method":method,"base_combination_number":case,"effect_type":"MOMENT","effect_unit":"kN_m",
             "base_effect_excluding_f":10,"fluid_effect_f":2,"declared_effect_including_f":10+factor*2,
             "analysis_id":f"FLUID-{method}-{case}"}
            for method,cases in coefficients.items() for case,factor in cases.items()]


def _flood_ice_fixture():
    D,L,Lr,S,R,W,Fa,Di,Wi=10,2,1.5,3,4,2.5,1.2,.8,1.1;cases={}
    for sign,label in ((1,"POS"),(-1,"NEG")):
        for alt,value in (("LR",Lr),("S",S),("R",R)):
            cases[f"LRFD-4-FLOOD-{alt}-{label}"]=1.2*D+sign*(1.6*W+2*Fa)+L+.5*value
            cases[f"ASD-6-FLOOD-{alt}-{label}"]=D+.75*L+sign*(.75*W+1.5*Fa)+.75*value
        cases[f"LRFD-6-FLOOD-{label}"]=.9*D+sign*(1.6*W+2*Fa)
        cases[f"ASD-5-FLOOD-{label}"]=D+sign*(W+1.5*Fa)
        cases[f"ASD-9-FLOOD-{label}"]=.6*D+sign*(W+1.5*Fa)
    cases["LRFD-2-ICE"]=1.2*D+1.6*L+.2*Di+.5*S;cases["ASD-2-ICE"]=D+L+.7*Di
    for sign,label in ((1,"POS"),(-1,"NEG")):
        cases[f"LRFD-4-ICE-{label}"]=1.2*D+L+Di+sign*1.6*Wi+.5*S
        cases[f"LRFD-6-ICE-{label}"]=.9*D+Di+sign*1.6*Wi
        cases[f"ASD-3-ICE-{label}"]=D+.7*Di+sign*1.1*Wi+S
        cases[f"ASD-9-ICE-{label}"]=.6*D+.7*Di+sign*1.1*Wi
    governing=max(cases,key=lambda case:abs(cases[case]))
    return {"flood_load_applicable":True,"atmospheric_ice_load_applicable":True,"flood_interface_id":"FLOOD-RWT-1","atmospheric_ice_component_id":"PIPE-ICE-1","load_effects":{"D":D,"L":L,"Lr":Lr,"S":S,"R":R,"W":W,"Fa":Fa,"Di":Di,"Wi":Wi},"effect_type":"MOMENT","effect_unit":"kN_m","direction_convention":"signed local y","structural_analysis_id":"STRUCT-FLOOD-ICE-1","structural_model_sha256":"a"*64,"evaluated_cases":cases,"governing_case_id":governing,"capacity_abs":abs(cases[governing])}


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
            "project_contract_id":"SYNTH-PROJECT-1","building_geometry_sha256":"a"*64,
            "emergency_access_rainwater_interfaces": [],
            "emergency_access_rainwater_interfaces_verified_absent": True,
            "rainwater_acoustic_interfaces": [],
            "rainwater_acoustic_interfaces_verified_absent": True,
            "rainwater_pollution_prevention_interfaces": [],
            "rainwater_pollution_prevention_interfaces_verified_absent": True,
            "rainwater_site_projection_interfaces": [],
            "rainwater_site_projection_interfaces_verified_absent": True,
            "deliverable_generation_phase":"PRE_GENERATION",
            "m4_rainwater_technical_document_register":{"register_id":"DOC-M4-1","design_basis_id":"DB-1",
                "calculation_basis_id":"CB-1","material_specification_id":"SPEC-1"},
            "m4_rainwater_material_selections":[{"selection_id":"MAT-M4-1","product_identity":"PVC-RW-80",
                "standard_or_approval":"ISIRI-SYNTHETIC","new_or_innovative":False}],
            "m4_construction_protection_plan":{"material_storage_method":"COVERED-DRY",
                "public_utility_protection_method":"BARRIER-AND-ACCESS","protected_landscape_method":"FENCED-ROOT-ZONE"},
            "construction_pipe_storage_zones":[],"construction_pipe_storage_zones_verified_absent":True,
            "rain_exposed_wood_components":[],"rain_exposed_wood_components_verified_absent":True,
            "roof_material_volumetric_loads":[],"roof_material_volumetric_loads_verified_absent":True,
            "roof_covering_surface_loads":[],"roof_covering_surface_loads_verified_absent":True,
            "vertical_rainwater_drift_interfaces":[],"vertical_rainwater_drift_interfaces_verified_absent":True,
            "exposed_rainwater_pipe_wind_loads":[],"exposed_rainwater_pipe_wind_loads_verified_absent":True,
            "atmospheric_ice_rainwater_components":[],"atmospheric_ice_rainwater_components_verified_absent":True,
            "rainwater_flood_ice_load_combination_extensions":{"flood_load_applicable":False,"atmospheric_ice_load_applicable":False},
            "occupied_space_rainwater_clearance_routes":[{"route_id":"RW-OCC-1","space_id":"OFFICE-1","space_type":"OCCUPANCY","space_polygon":[[6,6],[10,6],[10,9],[6,9]],"finished_floor_elevation_m":0,"crossing_is_local_overhead_projection":True,"general_space_clear_height_m":2.7,"bottom_envelope_points":[[6.5,7,2.05],[9.5,7,2.05]],"envelope_components":["PIPE","INSULATION","SUPPORT"]}],
            "rainwater_egress_width_interfaces":[{"egress_id":"EGR-1","path_geometry_model":"STRAIGHT_AXIS_PRISMATIC_SECTIONS","egress_polygon":[[0,0],[4,0],[4,10],[0,10]],"longitudinal_axis":[[2,.5],[2,9.5]],"required_clear_width_m":1.1,"cross_sections":[{"station_m":1,"points":[[.5,1],[3.5,1]]},{"station_m":5,"points":[[.5,5],[3.5,5]]},{"station_m":9,"points":[[.5,9],[3.5,9]]}],"rainwater_component_footprints":[{"component_id":"RW-EGR-1","polygon":[[.5,4.9],[.8,4.9],[.8,5.1],[.5,5.1]]}],"component_inventory_complete":True,"inventory_provenance":{"geometry_model_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","verification_status":"VALID","source_sha256":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"}}],
            "roof_cladding_wind_zones":[],"roof_cladding_wind_zones_verified_absent":True,
            "rainwater_attachment_net_wind_pressures":[],"rainwater_attachment_net_wind_pressures_verified_absent":True,
            "rainwater_storage_tank_wind_loads":[],"rainwater_storage_tank_wind_loads_verified_absent":True,
            "rainwater_support_member_wind_loads":[],"rainwater_support_member_wind_loads_verified_absent":True,
            "rainwater_site_flood_structural_interfaces":[],"rainwater_site_flood_structural_interfaces_verified_absent":True,
            "rainwater_canopy_wind_loads":[],"rainwater_canopy_wind_loads_verified_absent":True,
            "outdoor_rainwater_equipment_installations":[],"outdoor_rainwater_equipment_verified_absent":True,
            "rainwater_heavy_equipment_removal_routes":[],"rainwater_heavy_equipment_verified_absent":True,
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
                {"component_id":"RW1","empty_component_mass_kg":12,"contained_water_volume_m3":0.008,"water_full_mass_kg":20,
                 "support_reaction_id":"REACTION-RW1","declared_total_reaction_kn":0.196133,
                 "structural_review":{"status":"APPROVED","approval_id":"STRUCT-SYNTHETIC-1","reviewed_load_kn":0.196133}}],
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
            "main_entrance_runoff_elevation_interfaces":[{"entrance_id":"E-1","rainwater_runoff_interface":True,"main_entrance_floor_elevation_mm":0,"average_adjacent_way_elevation_mm":-1200,"site_condition":"STANDARD"}],
            "pedestrian_ramp_runoff_interfaces":[{"ramp_id":"PED-RAMP-1","rainwater_runoff_interface":True,"route_class":"MAIN_ACCESS_OR_EGRESS","accessible_required":True,"profile_points":[[0,0],[4,.32],[8,.64]],"landings":[{"landing_id":"PL-0","station_m":0,"polygon":[[0,0],[1.2,0],[1.2,1.2],[0,1.2]],"slope_x_percent":1,"slope_y_percent":1},{"landing_id":"PL-1","station_m":8,"polygon":[[8,0],[9.2,0],[9.2,1.2],[8,1.2]],"slope_x_percent":1,"slope_y_percent":1}],"drainage_route_id":"EXT-DRAIN-1","ponding_free":True,"accessibility_review":{"review_id":"ACCESS-PED-1","model_sha256":"a"*64,"status":"APPROVED","owner_module":"architecture_accessibility","source_sha256":"d"*64},"selected_surface":{"product_identity":"PED-NONSLIP-1","hard":True,"fixed":True,"application_detail_id":"PED-FIN-DET-1","product_approval":{"approval_id":"PED-FIN-APP-1","product_identity":"PED-NONSLIP-1","approved_for_wet_pedestrian_ramp":True,"source_sha256":"e"*64}}}],
            "visible_rainwater_facade_interfaces":[{"component_id":"RWD-F-1","component_type":"VISIBLE_DOWNPIPE","facade_id":"FACADE-NORTH","elevation_polyline":[[2,0],[2,6]],"architecture_response":{"review_id":"ARCH-FACADE-1","component_id":"RWD-F-1","facade_id":"FACADE-NORTH","model_sha256":"a"*64,"status":"APPROVED","source_sha256":"b"*64}}],
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
                "live_load_factor_basis":{"nominal_live_load_kpa":3,"occupancy_type":"OFFICE","live_load_reduction_applied":False,"declared_factor":.5},
                "wind_and_seismic_combined":False,
                "evaluated_cases":{"LRFD-1":14,"LRFD-2-LR":15.95,"LRFD-2-S":16.7,"LRFD-2-R":17.2,
                    "LRFD-3-LR-L":15.4,"LRFD-3-S-L":17.8,"LRFD-3-R-L":19.4,"LRFD-3-LR-W":16.4,
                    "LRFD-3-LR-W-POS":16.4,"LRFD-3-S-W-POS":18.8,"LRFD-3-R-W-POS":20.4,
                    "LRFD-4-LR-W-POS":17.75,"LRFD-4-S-W-POS":18.5,"LRFD-4-R-W-POS":19,
                    "LRFD-5-E-POS":17.1,"LRFD-6-W-POS":13,"LRFD-7-E-POS":12.5,
                    "LRFD-3-LR-W-NEG":12.4,"LRFD-3-S-W-NEG":14.8,"LRFD-3-R-W-NEG":16.4,
                    "LRFD-4-LR-W-NEG":9.75,"LRFD-4-S-W-NEG":10.5,"LRFD-4-R-W-NEG":11,
                    "LRFD-5-E-NEG":10.1,"LRFD-6-W-NEG":5,"LRFD-7-E-NEG":5.5},
                "governing_case_id":"LRFD-3-R-W-POS","design_capacity_abs":20.4,"structural_analysis_id":"STRUCT-LRFD-SYN-1"},
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
            "roof_snow_load_basis":[{"roof_area_id":"ROOF-1","snow_region":2,
                "snow_region_basis":{"source_clause":"M6 figure 6-7-1","verification_status":"VALID","snow_region":2,"source_sha256":"9"*64},
                "ground_snow_load_ps_kn_m2":1.0,
                "importance_factor_is":1.0,"exposure_factor_cn":1.0,"thermal_condition":"GENERAL","thermal_factor_ch":1.0,"slope_factor_cs":1.0,
                "roof_slope_degrees":0,"surface_slippery":False,"unobstructed_slide":False,"adequate_fall_space":False,
                "declared_balanced_roof_snow_pr_kn_m2":1.0,"declared_snow_unit_weight_kn_m3":2.63,
                "declared_balanced_snow_height_m":1/2.63,"classified_as_exposed_roof":False,
                "exposure_geometry_analysis_id":"SNOW-GEO-SYN-1","roof_obstructions":[{"id":"PARAPET-1","height_above_roof_m":1.1}],
                "eave_overhang":{"length_m":2.0,"declared_design_zone_length_m":1.5,"declared_design_load_kn_m2":2.0}}],
            "rooftop_snow_drift_features":[{"feature_id":"PARAPET-1","snow_region":4,"feature_type":"PARAPET",
                "face_width_m":20,"windward_roof_length_m":8,"leeward_roof_length_m":12,
                "perpendicular_roof_length_m":10,"drift_height_hd_m":1.2,"clear_height_hc_m":0.6,
                "declared_drift_width_w_m":2.4,"base_calculation_id":"SNOW-675-SYN-1",
                "declared_lu_m":10,"declared_max_drift_height_m":0.9,"drift_applied":True,"structural_model_sha256":"c"*64,
                "printed_reference_anomaly_acknowledged":True,"structural_interpretation":{"approval_id":"SE-DRIFT-SYN-1",
                    "approver_role":"STRUCTURAL_ENGINEER","status":"APPROVED","source_clause":"6-7-10 -> relation 6-7-5",
                    "source_printed_page":61,"source_document_sha256":"9702369223d5c04072d5e8e01871045c80ff494ffe8ae1357ebd90e78ff18201",
                    "structural_model_sha256":"c"*64,"feature_id":"PARAPET-1","base_calculation_id":"SNOW-675-SYN-1","approved_max_drift_height_m":0.9}}],
            "fluid_load_combination_extensions":_fluid_fixture(),
            "heavy_rooftop_equipment_placements":[{"equipment_id":"RTU-SYN-1","operating_mass_kg":850,
                "support_member_type":"CANTILEVER","building_importance":"MEDIUM","building_storeys":5,
                "structural_model_sha256":"d"*64,
                "placement_structural_analysis":{"analysis_id":"PLACE-SYN-1","status":"APPROVED","model_sha256":"d"*64,"engineer_approval_id":"SE-PLACE-1"},
                "seismic_nonstructural_analysis":{"analysis_id":"SEISMIC-SYN-1","standard_2800_edition":"4",
                    "status":"APPROVED","model_sha256":"d"*64,"engineer_approval_id":"SE-SEISMIC-1"}}],
            "roof_live_load_reductions":[{"roof_area_id":"ROOF-1","roof_use_type":"ORDINARY","roof_geometry_type":"PITCHED",
                "tributary_area_m2":18,"roof_slope_percent":33,"slope_parameter_s":33,"unreduced_l0_kn_m2":1.5,"declared_lr_kn_m2":1.5}],
            "special_use_roof_live_load_reductions":[{"roof_area_id":"RG-1","special_use_type":"ROOF_GARDEN","unreduced_l0_kn_m2":4,"declared_design_live_load_kn_m2":2.828,"structural_model_sha256":"f"*64,"member_location_factor_kll":1,"tributary_area_m2":100,"supported_floor_count":1,"is_assembly_area":False,"is_passenger_vehicle_area":False,"is_one_way_slab":False,"section_6_5_5_calculation":{"calculation_id":"655-SYN-1","method_clause":"6-5-5","result_kn_m2":2.828,"status":"APPROVED","model_sha256":"f"*64,"engineer_approval_id":"SE-655-1"}}],
            "rainwater_equipment_vibration_isolation_interfaces":[{"equipment_id":"RWP-1","equipment_type":"RAINWATER_PUMP","can_create_undesirable_vibration":True,"equipment_footprint":[[2,6],[4,6],[4,8],[2,8]],"support_points":[[2.3,6.3],[3.7,6.3],[3.7,7.7],[2.3,7.7]],"vibration_isolation_response":{"analysis_id":"VIB-SYN-1","equipment_id":"RWP-1","model_sha256":"a"*64,"required_isolator_type":"SPRING","status":"APPROVED","engineer_approval_id":"SE-VIB-1"},"selected_isolator":{"product_id":"ISO-SYN-1","equipment_id":"RWP-1","isolator_type":"SPRING","manufacturer":"SYNTHETIC","model":"S-1","product_data_sha256":"b"*64,"verification_status":"VALID"}}],
            "buried_rainwater_geotechnical_interfaces":[{"asset_id":"RWT-B-1","asset_type":"BURIED_RAINWATER_TANK","footprint":[[12,6],[15,6],[15,9],[12,9]],"retained_height_m":2,"groundwater_head_m":1,"ground_surface_elevation_m":100,"asset_base_elevation_m":98,"groundwater_elevation_m":99,"retaining_surface_orientation":"VERTICAL_LATERAL","pressure_direction":"NORMAL_TO_RETAINING_SURFACE","surface_surcharge_kpa":10,"expansive_soil":True,"seismic_lateral_effect_applicable":True,"integral_with_building_structure":False,"horizontal_floor_below_grade":True,"geotechnical_structural_response":{"analysis_id":"GEO-RWT-1","asset_id":"RWT-B-1","model_sha256":"a"*64,"site_investigation_id":"GEO-SYN-1","method":"EQUIVALENT_FLUID_APPROVED","method_applicable_to_asset":True,"source_sha256":"c"*64,"soil_equivalent_fluid_unit_weight_kn_m3":5,"reviewed_lateral_pressure_at_base_kpa":29.80665,"reviewed_uplift_pressure_kpa":9.80665,"expansive_soil_effect_included":True,"seismic_lateral_effect_included":True,"integral_pressure_variation_included":False,"stability_status":"APPROVED","status":"APPROVED","engineer_approval_id":"SE-GEO-1"}}],
            "rainwater_buried_h_load_combination_extensions":[{"asset_id":"RWT-B-1","effect_type":"PRESSURE","effect_unit":"kPa","base_effect":20,"h_effect_abs":5,"h_is_permanent":True,"evaluated_cases":{"LRFD-H-ADDITIVE":28,"LRFD-H-RELIEVING":15.5,"ASD-H-ADDITIVE":25,"ASD-H-RELIEVING":17},"governing_case_id":"LRFD-H-ADDITIVE","capacity_abs":28,"structural_analysis_id":"GEO-RWT-1","structural_model_sha256":"a"*64}],
            "rainwater_construction_stage_loads":[{"load_case_id":"CONST-RW-1","construction_stage":"ROOF_PIPE_INSTALLATION","loaded_footprint":[[5,6],[7,6],[7,8],[5,8]],"items":[{"item_id":"PIPE-BUNDLE-1","item_type":"RAINWATER_PIPE_BUNDLE","quantity":10,"unit_mass_kg":20}],"declared_total_mass_kg":200,"declared_distributed_load_kpa":0.4903325,"temporary_structural_response":{"analysis_id":"STRUCT-CONST-1","load_case_id":"CONST-RW-1","model_sha256":"a"*64,"reviewed_total_mass_kg":200,"reviewed_distributed_load_kpa":0.4903325,"status":"APPROVED","engineer_approval_id":"SE-CONST-1"}}],
            "rainwater_machinery_impact_loads":[{"equipment_id":"RWP-1","motion_type":"ROTATING","operating_mass_kg":100,"manufacturer_impact_factor":1.2,"declared_design_gravity_load_kn":1.176798,"support_structural_response":{"analysis_id":"STRUCT-IMPACT-1","equipment_id":"RWP-1","model_sha256":"a"*64,"reviewed_design_gravity_load_kn":1.176798,"status":"APPROVED","engineer_approval_id":"SE-IMPACT-1"}}],
            "rainwater_serviceability_movement_interfaces":[{"interface_id":"MOVE-RW-1","component_id":"RW-VERTICAL-1","route_points_3d":[[8,6,0],[8,6,3]],"local_axis_basis":{"unit":"mm","x":[1,0,0],"y":[0,1,0],"z":[0,0,1]},"fluid_effect_present":True,"soil_or_groundwater_effect_present":False,"stored_material_effect_present":False,"self_straining_causes":["TEMPERATURE","DIFFERENTIAL_SETTLEMENT"],"selected_joint_capacity_xyz_mm":{"x":10,"y":10,"z":2},"joint_capacity_envelope":{"method":"ELLIPSOIDAL_INTERACTION","product_id":"JOINT-1","product_model":"J-XYZ","verification_status":"VALID","source_sha256":"e"*64},"declared_governing_case_id":"D_PLUS_T","declared_governing_relative_displacement_xyz_mm":[6,8,0],"declared_governing_relative_displacement_norm_mm":10,"structural_movement_response":{"analysis_id":"STRUCT-MOVE-1","interface_id":"MOVE-RW-1","model_sha256":"a"*64,"service_load_combinations":{"W_SERVICE":{"fluid_effect_factor":1},"E_SERVICE":{"fluid_effect_factor":1}},"endpoint_displacements_mm":{"W_SERVICE":{"start_xyz_mm":[0,0,0],"end_xyz_mm":[3,4,0]},"E_SERVICE":{"start_xyz_mm":[0,0,0],"end_xyz_mm":[0,1,0]},"D_PLUS_T":{"start_xyz_mm":[0,0,0],"end_xyz_mm":[6,8,0]},"D_PLUS_075_L_ALT_T":{"start_xyz_mm":[0,0,0],"end_xyz_mm":[0,8,0]}},"status":"APPROVED","engineer_approval_id":"SE-MOVE-1","evidence_provenance":{"verification_status":"VALID","source_sha256":"d"*64,"method_source":"M6_SERVICEABILITY_OWNER_ANALYSIS"}}}],
            "roof_serviceability_deflection_checks":[{"member_id":"RB-1","span_mm":6000,"allowable_deflection_ratio":240,"calculated_deflection_mm":25,"load_combination_id":"SVC-D-L-R","analysis_id":"DEF-SYN-1","structural_model_sha256":"1"*64,"deflection_limit_source":{"code":"M9","edition":"PROJECT-CONTRACT","clause":"ROOF-SERVICEABILITY","member_type":"ROOF_BEAM","material":"REINFORCED_CONCRETE","load_condition":"SERVICE-D-L-R","attached_component_condition":"NONBRITTLE_FINISH","approved_ratio":240,"engineer_approval_id":"SE-LIMIT-1","structural_model_sha256":"1"*64,"status":"APPROVED"},"analysis_response":{"analysis_id":"DEF-SYN-1","model_sha256":"1"*64,"status":"APPROVED","engineer_approval_id":"SE-DEF-1"}}],
            "rainwater_maintenance_access_paths":[{"path_id":"MA-1","target_type":"MEP_ONLY_CORRIDOR","path_points":[[1,1],[1,5]],"required_clear_width_m":0.6,"corridor_polygon":[[0.5,0.5],[1.5,0.5],[1.5,5.5],[0.5,5.5]],"obstacle_polygons":[],"accessible_entrance_point":[1,1],"target_access_point":[1,5]}],
            "parking_ramp_profiles":[{"ramp_id":"PR-1","parking_type":"PRIVATE","covered":False,"parking_size":"MEDIUM","profile_points":[[0,0],[1,.1],[10,1.45],[11,1.55]]}],
            "parking_service_clearance_routes":[{"route_id":"RW-PK-1","parking_zone_id":"PK-ZONE-1","parking_size":"MEDIUM",
                "parking_polygon":[[6,3],[10,3],[10,6],[6,6]],"floor_elevation_m":0,
                "bottom_envelope_points":[[5,4,2.4],[11,4,2.4]],
                "envelope_components":["PIPE","INSULATION","SUPPORT"],"selected_route":"ORIGINAL"}],
            "covered_patio_natural_ventilation_reviews":[{"patio_id":"PATIO-1","cover_material_type":"TRANSPARENT",
                "patio_polygon":[[12,3],[16,3],[16,7],[12,7]],"architecture_geometry_sha256":"c"*64,
                "ventilation_analysis":{"analysis_id":"ARCH-VENT-1","analysis_method":"M4_NATURAL_VENTILATION",
                    "model_sha256":"c"*64,"status":"APPROVED","owner_module":"architecture",
                    "required_open_area_m2":0.8,"provided_open_area_m2":1.0,
                    "opening_polygons":[[[12,3],[13,3],[13,4],[12,4]]],"airflow_path_geometry_ids":["AIRPATH-1"],
                    "owner_review_id":"ARCH-REVIEW-1","evidence_provenance":{"verification_status":"VALID","source_sha256":"d"*64}}}],
            "exterior_intermediary_element_finishes":[{"element_id":"LIGHTWELL-WALL-1","element_type":"LIGHTWELL_BODY",
                "element_polygon":[[12,3],[16,3],[16,3.2],[12,3.2]],"exterior_exposures":["RAIN","UV","FREEZE_THAW"],
                "maintenance_plan_id":"MAINT-FINISH-1","selected_finish":{"product_identity":"FINISH-EXT-1",
                    "material":"CEMENTITIOUS_COATING","standard":"ISIRI-SYNTH-EXT","suitable_exposures":["RAIN","UV","FREEZE_THAW"],
                    "application_detail_id":"FINISH-DETAIL-1","product_approval":{"approval_id":"APP-FINISH-1","issuer":"SYNTHETIC TEST AUTHORITY","issuer_competent":True,
                        "product_identity":"FINISH-EXT-1","standard":"ISIRI-SYNTH-EXT",
                        "evidence_provenance":{"verification_status":"VALID","source_sha256":"e"*64}}}}],
            "external_light_air_conduit_route_inventories":[{"conduit_id":"LIGHT-AIR-1",
                "conduit_polygon":[[12,8],[16,8],[16,10],[12,10]],
                "required_functions":["MANDATORY_LIGHT","MANDATORY_NATURAL_VENTILATION"],
                "service_route_inventory_sha256":"a4194d783716ed25dee71cf1a6cf47510390399b26ee1cf2304071bd6695cbd1","service_route_inventory_complete":True,
                "route_inventory_provenance":{"verification_status":"VALID","source_sha256":"f"*64},
                "service_routes":[{"route_id":"RW-OUTSIDE-LA-1","system":"RAINWATER","route_points":[[10,7],[11,7]]}]}],
            "parking_ramp_surface_finishes":[{"ramp_id":"PR-1","ramp_polygon":[[0,0],[3,0],[3,11],[0,11]],
                "selected_surface":{"product_identity":"RAMP-FINISH-1","material":"TEXTURED_CONCRETE",
                    "application_detail_id":"RAMP-FINISH-DETAIL-1","product_approval":{"approval_id":"RAMP-APP-1",
                        "issuer":"SYNTHETIC PRODUCT AUTHORITY","issuer_competent":True,"product_identity":"RAMP-FINISH-1","approved_for_vehicle_ramp_wet":True,
                        "evidence_provenance":{"verification_status":"VALID","source_sha256":"1"*64}},
                    "wet_slip_test":{"report_id":"SLIP-WET-1","standard":"SYNTH-WET-SLIP","condition":"WET","status":"PASS",
                        "laboratory":"SYNTHETIC ACCREDITED LAB","product_identity":"RAMP-FINISH-1",
                        "laboratory_accreditation":{"accreditation_id":"LAB-ACC-1","laboratory":"SYNTHETIC ACCREDITED LAB",
                            "scope_standards":["SYNTH-WET-SLIP"],"evidence_provenance":{"verification_status":"VALID","source_sha256":"3"*64}},
                        "evidence_provenance":{"verification_status":"VALID","source_sha256":"2"*64}}}}],
            "external_light_air_conduit_traffic_guards":[{"conduit_id":"LIGHT-AIR-1","traffic_types":["PEDESTRIAN","VEHICLE"],
                "top_surface_elevation_points":[[12,8,0],[16,8,0]],"adjacent_ground_elevation_points":[[12,8,0],[16,8,0]],"geometry_sha256":"4"*64,
                "guard_product":{"product_identity":"GRATE-LA-1","material":"METAL","product_approval":{"approval_id":"GRATE-APP-1",
                    "issuer":"SYNTHETIC PRODUCT AUTHORITY","issuer_competent":True,"product_identity":"GRATE-LA-1",
                    "evidence_provenance":{"verification_status":"VALID","source_sha256":"5"*64}}},
                "structural_guard_analysis":{"analysis_id":"STRUCT-GRATE-1","model_sha256":"4"*64,"status":"APPROVED",
                    "load_case_types":["PEDESTRIAN","VEHICLE"],"engineer_approval_id":"STRUCT-APP-GRATE-1",
                    "evidence_provenance":{"verification_status":"VALID","source_sha256":"6"*64}},
                "accessibility_review":{"review_id":"ACCESS-GRATE-1","model_sha256":"4"*64,"status":"APPROVED",
                    "owner_module":"architecture_accessibility","accessible_route_geometry_ids":["ACCESS-ROUTE-1"],
                    "evidence_provenance":{"verification_status":"VALID","source_sha256":"7"*64}}}],
            "external_light_air_conduit_semi_open_finish_reviews":[{"conduit_id":"LIGHT-AIR-1",
                "floor_polygon":[[12,8],[16,8],[16,10],[12,10]],"wall_surface_ids":["LA-WALL-1","LA-WALL-2"],
                "architecture_geometry_sha256":"8"*64,"semi_open_finish_review":{"review_id":"ARCH-FINISH-LA-1",
                    "model_sha256":"8"*64,"status":"APPROVED","owner_module":"architecture",
                    "governing_clause_ids":["M4-SEMI-OPEN-FLOOR","M4-SEMI-OPEN-WALL"],"floor_finish_schedule_id":"FF-LA-1",
                    "wall_finish_schedule_ids":["WF-LA-1","WF-LA-2"],"owner_approval_id":"ARCH-APP-LA-1",
                    "evidence_provenance":{"verification_status":"VALID","source_sha256":"9"*64}}}],
            "under_open_space_parking_reviews":[{"parking_id":"PK-UNDER-OPEN-1","building_group":7,
                "parking_footprint_polygon":[[5,12],[15,12],[15,20],[5,20]],"architecture_geometry_sha256":"a1"*32,
                "rainwater_interface_ids":["OUT-1"],
                "urban_development_review":{"review_id":"URBAN-1","owner_module":"urban_planning","model_sha256":"a1"*32,"status":"APPROVED","owner_approval_id":"URBAN-APP-1","evidence_provenance":{"verification_status":"VALID","source_sha256":"b1"*32}},
                "basement_projection_review":{"review_id":"ARCH-PROJ-1","owner_module":"architecture","model_sha256":"a1"*32,"status":"APPROVED","owner_approval_id":"ARCH-PROJ-APP-1","evidence_provenance":{"verification_status":"VALID","source_sha256":"c1"*32}},
                "emergency_access_review":{"review_id":"FIRE-ACCESS-1","owner_module":"fire_emergency_access","model_sha256":"a1"*32,"status":"APPROVED","owner_approval_id":"FIRE-ACCESS-APP-1","evidence_provenance":{"verification_status":"VALID","source_sha256":"d1"*32}}}],
            "basement_parking_light_ventilation_strategies":[{"parking_id":"PK-B1","basement_storey_count":1,
                "direct_open_air_openings_possible":False,"selected_strategy":"EXTERNAL_LIGHT_AIR_CONDUIT",
                "strategy_geometry_ids":["LIGHT-AIR-1"],"architecture_geometry_sha256":"e1"*32,
                "architecture_strategy_review":{"review_id":"ARCH-STRATEGY-1","owner_module":"architecture","model_sha256":"e1"*32,
                    "status":"APPROVED","owner_approval_id":"ARCH-STRATEGY-APP-1","evidence_provenance":{"verification_status":"VALID","source_sha256":"f1"*32}}}],
            "transparent_roof_cleaning_safety_reviews":[{"roof_id":"GLASS-ROOF-1","roof_polygon":[[22,0],[28,0],[28,6],[22,6]],
                "cleaning_path_points":[[23,1],[27,1],[27,5]],"cleaning_anchor_points":[[23,1],[27,1],[27,5]],
                "architecture_geometry_sha256":"13"*32,"structural_cleaner_load_analysis":{"analysis_id":"STRUCT-CLEAN-1",
                    "model_sha256":"13"*32,"status":"APPROVED","load_case_id":"LC-CLEANER-1","load_case_type":"CLEANER_WEIGHT",
                    "engineer_approval_id":"STRUCT-CLEAN-APP-1","evidence_provenance":{"verification_status":"VALID","source_sha256":"14"*32}}}],
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


def test_all_canonical_rules_pass_strict_draft_2020_12_schema_validation():
    schema = json.loads(Path(
        "data/rulebook/schema/executable_rule.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    rules = load_rulebook_module()["registry"]["rules"]
    errors = [(rule["rule_id"], list(error.absolute_path), error.message)
              for rule in rules
              for error in Draft202012Validator(schema).iter_errors(rule)]
    assert len(rules) == 103
    assert errors == []


@pytest.mark.parametrize("mutation,expected_path", [
    (lambda rule: rule.update(owner="invented_owner"), ["owner"]),
    (lambda rule: rule["required_inputs"][0].update(
        authority=["INVENTED_AUTHORITY"]), ["required_inputs", 0, "authority", 0]),
    (lambda rule: rule["required_inputs"][0].update(
        duty_stage="AFTER_THE_FACT"), ["required_inputs", 0, "duty_stage"]),
    (lambda rule: rule["required_inputs"][0].update(
        hidden_override=True), ["required_inputs", 0]),
])
def test_strict_rule_schema_rejects_unknown_owner_authority_stage_and_fields(
        mutation, expected_path):
    schema = json.loads(Path(
        "data/rulebook/schema/executable_rule.schema.json").read_text())
    rule = deepcopy(load_rulebook_module()["registry"]["rules"][0])
    mutation(rule)
    errors = list(Draft202012Validator(schema).iter_errors(rule))
    assert errors
    assert any(list(error.absolute_path) == expected_path for error in errors)


@pytest.mark.parametrize("unused_owner", ["electrical", "fire", "shared"])
def test_strict_rule_schema_does_not_admit_plausible_but_unimplemented_owners(
        unused_owner):
    schema = json.loads(Path(
        "data/rulebook/schema/executable_rule.schema.json").read_text())
    rule = deepcopy(load_rulebook_module()["registry"]["rules"][0])
    rule["owner"] = unused_owner
    errors = list(Draft202012Validator(schema).iter_errors(rule))
    assert any(list(error.absolute_path) == ["owner"] for error in errors)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "nan", "-Infinity"])
def test_nonfinite_numeric_input_is_rejected_before_any_rule_comparison(bad):
    snapshot=complete_snapshot();snapshot["design_basis"]["rainfall_intensity_mm_h"]=bad
    result=evaluate_rainwater_rules(snapshot)
    assert result["status"]=="FAIL" and result["evaluations"]==[]
    assert any("rainfall_intensity_mm_h" in error for error in result["errors"])


def test_complete_inputs_close_source_inventory_but_never_authorize_release():
    result = evaluate_rainwater_rules(complete_snapshot())
    assert all(row["status"] in {"PASS", "NOT_APPLICABLE"} for row in result["evaluations"]), result
    assert result["unresolved_source_controls"] == 0
    assert result["status"] == "PASS"
    assert result["release_allowed"] is False


def test_canonical_disposition_counts_and_versioned_change_log_are_reconciled():
    coverage=json.loads(Path("data/rulebook/modules/mechanical/rainwater/source_coverage.json").read_text())
    entries=coverage["entries"]
    counts={name:sum(row["disposition"]==name for row in entries) for name in
            ("EXECUTABLE_RULE","UNRESOLVED_CONTROL","DEFINITION","GUIDANCE","DEPENDENCY_CONTEXT")}
    assert counts=={"EXECUTABLE_RULE":305,"UNRESOLVED_CONTROL":0,"DEFINITION":89,
                    "GUIDANCE":80,"DEPENDENCY_CONTEXT":60}
    assert sum(counts.values())==coverage["source_entry_count"]==534
    assert sum(len(row["rule_ids"]) for row in entries)==328
    changes={row["module_version"]:row for row in coverage["disposition_changes"]}
    assert changes["2.50.0"]["source_ids"]==["M6-115","M6-119","M6-120"]
    assert changes["2.51.0"]["source_ids"]==["M6-116","M6-126"]
    assert changes["2.52.0"]["source_ids"]==["M6-117","M6-118","M6-121"]
    assert changes["2.53.0"]["source_ids"]==["M6-129","M6-131"]
    assert changes["2.54.0"]["source_ids"]==["M6-147","M6-148"]
    assert changes["2.55.0"]["source_ids"]==["M6-127","M6-130","M6-133","M6-145"]
    assert changes["2.65.0"]["source_ids"]==["M6-026","M6-049","M6-050","M6-053","M6-054","M6-057"]
    assert changes["2.66.0"]["source_ids"]==["M6-058","M6-059","M6-060","M6-061","M6-062","M6-063"]
    assert changes["2.67.0"]["source_ids"]==["M6-028"]
    assert changes["2.68.0"]["source_ids"]==["M6-032","M6-033","M6-034","M6-035","M6-036","M6-037","M6-038","M6-039","M6-040"]
    assert changes["2.69.0"]["source_ids"]==["M6-042","M6-081"]
    assert changes["2.70.0"]["source_ids"]==["M6-064","M6-065","M6-066"]
    assert changes["2.71.0"]["source_ids"]==["M6-051","M6-052","M6-055","M6-056"]
    assert changes["2.72.0"]["source_ids"]==["M4-078","M4-079"]
    assert changes["2.73.0"]["source_ids"]==["M4-063","M4-064","M4-076"]
    assert changes["2.74.0"]["source_ids"]==["M6-018"]
    assert changes["2.75.0"]["source_ids"]==["M6-020","M6-025"]
    assert changes["2.76.0"]["source_ids"]==["M6-006","M6-012"]
    assert changes["2.77.0"]["source_ids"]==["M4-065","M4-046","M4-047"]
    assert changes["2.78.0"]["source_ids"]==["M4-042"]
    assert changes["2.79.0"]["source_ids"]==["M4-062","M4-072","M4-073","M4-074","M4-075"]
    assert changes["2.80.0"]["source_ids"]==["M4-061"]
    assert changes["2.81.0"]["source_ids"]==["M4-105","M4-106","M4-112"]
    assert changes["2.82.0"]["source_ids"]==["M4-002","M4-053","M4-056","M4-057","M4-059","M4-060"]
    assert changes["2.83.0"]["source_ids"]==["M4-065"]
    assert changes["2.84.0"]["source_ids"]==["M6-116"]
    restored={source_id for row in coverage["disposition_changes"] if row["module_version"]=="2.85.0" for source_id in row["source_ids"]}
    assert restored=={"M4-001","M4-004","M4-048","M4-049","M4-050","M4-051","M4-052","M4-055","M4-058",
                      "M4-068","M4-069","M4-082","M4-138","M4-156","M6-071","M6-076","M6-115","M6-119",
                      "M6-120","M6-126","M6-129","M6-131","M6-134","M6-145","M16-098"}


def test_semantic_inventory_has_no_nonreciprocal_executable_links_or_unresolved_controls():
    module=load_rulebook_module();rules={row["rule_id"]:row for row in module["registry"]["rules"]}
    coverage={row["source_id"]:row for row in module["coverage"]["entries"]}
    review=json.loads(Path("data/rulebook/modules/mechanical/rainwater/source_review_m4_m6.json").read_text())
    assert review["module_version"]==module["registry"]["version"]==module["coverage"]["module_version"]=="2.85.1"
    assert review["unresolved_entries"]==0
    assert not [row for row in coverage.values() if row["disposition"]=="UNRESOLVED_CONTROL"]
    for source_id,row in coverage.items():
        for rule_id in row["rule_ids"]:
            assert rule_id in rules
            assert source_id in {value for source in rules[rule_id]["sources"] for value in source["source_ids"]}
    for rule in rules.values():
        assert rule["validator"] in VALIDATORS
    focused={row["source_id"]:row for row in review["entries"]}
    restored_executable={"M4-001","M4-048","M4-049","M4-050","M4-051","M4-052","M4-055","M4-058",
                         "M4-138","M6-071","M6-076","M6-115","M6-119","M6-120","M6-126","M6-129",
                         "M6-131","M6-134","M6-145","M16-098"}
    restored_context={"M4-004","M4-068","M4-069","M4-082","M4-156"}
    for source_id in restored_executable:
        row=focused[source_id]
        assert coverage[source_id]["disposition"]==row["disposition"]=="EXECUTABLE_RULE"
        assert coverage[source_id]["rule_ids"]
        assert row["implementation_status"]=="IMPLEMENTED"
        validators={name.strip() for name in row["validator"].split(";")}
        assert row["producer"] and validators and validators <= set(VALIDATORS)
        assert row["test"] and "test_rainwater_executable_rulebook.py" in row["test"]
    for source_id in restored_context:
        row=focused[source_id]
        assert coverage[source_id]["disposition"]==row["disposition"]=="DEPENDENCY_CONTEXT"
        assert not coverage[source_id]["rule_ids"]
        assert row["implementation_status"]=="CLASSIFIED_CONTEXT"
        assert row["producer"] is row["validator"] is row["test"] is None
        assert row["reason"]
    for source_id in ("M4-002","M4-053","M4-056","M4-057","M4-059","M4-060"):
        row=focused[source_id]
        assert row["disposition"]=="EXECUTABLE_RULE" and row["implementation_status"]=="IMPLEMENTED"
        assert row["producer"] and row["validator"] in VALIDATORS and row["test"]
    assert coverage["M4-065"]["rule_ids"]==["IR-M4-1396-MAIN-ENTRANCE-RUNOFF-ELEVATION-INTERFACE"]


def test_m6_general_seismic_and_serviceability_rows_do_not_create_blanket_rainwater_gate():
    coverage=json.loads(Path("data/rulebook/modules/mechanical/rainwater/source_coverage.json").read_text())
    entries={row["source_id"]:row for row in coverage["entries"]}
    for source_id in ("M6-006","M6-012","M6-026","M6-049","M6-050","M6-053","M6-054","M6-057","M6-086","M6-092","M6-093","M6-094","M6-095","M6-096","M6-097","M6-098","M6-127","M6-130","M6-133"):
        assert entries[source_id]["disposition"]=="DEPENDENCY_CONTEXT"
        assert entries[source_id]["rule_ids"]==[]
    result=evaluate_rainwater_rules(complete_snapshot())
    assert not any(source_id in evaluation["source_ids"] for source_id in
                   ("M6-006","M6-012","M6-026","M6-049","M6-050","M6-053","M6-054","M6-057","M6-086","M6-092","M6-093","M6-094","M6-095","M6-096","M6-097","M6-098","M6-127","M6-130","M6-133")
                   for evaluation in result["evaluations"])
    assert entries["M6-005"]["disposition"]=="GUIDANCE" and entries["M6-005"]["rule_ids"]==[]


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
    snapshot["rule_context"]["buried_gravity_rainwater_segments"]=[{"id":"B1","soil_condition":"ROCK","continuous_shaped_bedding":True,"balanced_compaction":True,"lift_mm":150,"rock_overcut_mm":74,"inspection_before_covering":True,"affects_excavation_depth":False}]
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
    snapshot=complete_snapshot();snapshot["rule_context"]["structural_rainwater_loads"][0]["water_full_mass_kg"]=19
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M6-1398-PERMANENT-RAINWATER-DEAD-LOAD")["status"]=="FAIL"
    snapshot=complete_snapshot();snapshot["rule_context"]["structural_rainwater_loads"][0]["declared_total_reaction_kn"]=.1
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M6-1398-PERMANENT-RAINWATER-DEAD-LOAD")["status"]=="FAIL"
    snapshot=complete_snapshot();snapshot["rule_context"]["structural_rainwater_loads"][0]["structural_review"]["reviewed_load_kn"]=.1
    assert by_id(evaluate_rainwater_rules(snapshot),"IR-M6-1398-PERMANENT-RAINWATER-DEAD-LOAD")["status"]=="FAIL"

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


def test_m4_exterior_wall_roof_penetrations_require_geometry_bound_owner_reviews():
    snapshot=complete_snapshot();rule="IR-M16-1396-INSTALLATION-PROTECTION-PENETRATIONS"
    model_hash="c"*64;snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    reviews=[]
    for discipline in ("FIRE","ACOUSTIC","THERMAL","LAYER_INTEGRITY"):
        reviews.append({"discipline":discipline,"review_id":f"REV-{discipline}","assembly_id":"ROOF-A1",
            "detail_id":f"DET-{discipline}","model_sha256":model_hash,"status":"PASS",
            "evidence_provenance":{"verification_status":"VALID","source_sha256":discipline.lower().ljust(64,"0")}})
    snapshot["rule_context"]["rainwater_installation_interfaces"].append({
        "interface_id":"ROOF-PEN-1","source_geometry_id":"G-ROOF-PEN-1",
        "interface_type":"EXTERNAL_ROOF_PENETRATION","multilayer_assembly":True,
        "assembly_continuity_reviews":reviews,"imposed_pressure_within_component_rating":True})
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="PASS" and any("assembly=G-ROOF-PEN-1" in row for row in result["evidence"])
    reviews[0]["model_sha256"]="d"*64
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    reviews[0]["model_sha256"]=model_hash;reviews.pop()
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
    assert "RULEBOOK 2.85.1" in text and "COMPLIANCE=PASS" in text and "RELEASE NOT AUTHORIZED" in text
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
    assert "SPECIAL ROOF LOAD RG-1 | USE=ROOF_GARDEN | KLL=1 | At=100m2 | FLOORS=1 | L0=4 | L=2.828" in detail_text
    assert "VIBRATION ISOLATION RWP-1 | TYPE=RAINWATER_PUMP | CAPABLE=True | SUPPORTS=4 | ISOLATOR=ISO-SYN-1:SPRING | ANALYSIS=VIB-SYN-1" in detail_text
    assert len(msp.query('LWPOLYLINE[layer=="RW-VIBRATION-ISOLATION"]'))==1
    assert "BURIED RAINWATER RWT-B-1 | TYPE=BURIED_RAINWATER_TANK | H=2m | GW=1m | Q=10kPa | LATERAL=29.80665kPa | UPLIFT=9.80665kPa | ANALYSIS=GEO-RWT-1" in detail_text
    assert len(msp.query('LWPOLYLINE[layer=="RW-BURIED-GEOTECH"]'))==1
    assert "RAINWATER CONSTRUCTION LOAD CONST-RW-1 | STAGE=ROOF_PIPE_INSTALLATION | MASS=200kg | LOAD=0.4903325kPa | ANALYSIS=STRUCT-CONST-1" in detail_text
    assert len(msp.query('LWPOLYLINE[layer=="RW-CONSTRUCTION-LOAD"]'))==1
    assert "RAINWATER MACHINERY IMPACT RWP-1 | MOTION=ROTATING | MASS=100kg | FACTOR=1.2 | LOAD=1.176798kN | ANALYSIS=STRUCT-IMPACT-1" in detail_text
    assert "RAINWATER MOVEMENT MOVE-RW-1 | COMPONENT=RW-VERTICAL-1 | CAUSES=TEMPERATURE,DIFFERENTIAL_SETTLEMENT | CASE=D_PLUS_T | VECTOR=[6, 8, 0]mm | NORM=10mm" in detail_text
    assert len(msp.query('LWPOLYLINE[layer=="RW-SERVICE-MOVEMENT"]'))==1
    assert "MATERIAL MAT-1 | UPVC | STD=EN 1329" in detail_text
    assert "SUPPORT INSTALL SUP-CIV-1 | CAST_IRON/VERTICAL" in detail_text
    assert "SUPPORT INSTALL SUP-GSH-1 | GALVANIZED_STEEL/HORIZONTAL" in detail_text
    assert "POTABLE AIR GAP AG-1 | GROUP=GOOSENECK_SINK_LAUNDRY" in detail_text
    assert "LRFD RAINWATER LOAD COMBINATIONS | GOVERNING=LRFD-3-R-W-POS | L FACTOR=0.5 | L0=3kPa | OCCUPANCY=OFFICE | LIVE REDUCED=False" in detail_text
    assert "ASD RAINWATER LOAD COMBINATIONS" in detail_text
    assert "PRIMARY BLOCKAGE RAIN LOAD ROOF-1 | DS=60.0mm | DH=20mm | R=0.8kN/m2" in detail_text
    access=list(msp.query('LWPOLYLINE[layer=="RW-MAINT-ACCESS"]'))
    assert len(access)==1 and list(access[0].get_points("xy"))==[(1.0,1.0),(1.0,5.0)]
    ramp=list(msp.query('LWPOLYLINE[layer=="RW-PARKING-RAMP-PROFILE"]'))
    assert len(ramp)==1 and list(ramp[0].get_points("xy"))==[(0.0,0.0),(1.0,.1),(10.0,1.45),(11.0,1.55)]
    clearance_zone=list(msp.query('LWPOLYLINE[layer=="RW-PARKING-CLEARANCE-ZONE"]'))
    clearance_route=list(msp.query('LWPOLYLINE[layer=="RW-PARKING-CLEARANCE-ROUTE"]'))
    assert len(clearance_zone)==len(clearance_route)==1
    assert list(clearance_route[0].get_points("xy"))==[(5.0,4.0),(11.0,4.0)]
    assert generated["qa"]["checks"]["parking_clearance_geometry_reconciled"] is True
    assert generated["qa"]["checks"]["patio_ventilation_dependency_reconciled"] is True
    assert generated["qa"]["checks"]["exterior_finish_reconciled"] is True
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


def test_high_rise_closeout_and_actual_excavation_use_owner_stage_contracts():
    snapshot=complete_snapshot();docs=snapshot["rule_context"]["rainwater_documentation"]
    snapshot["rule_context"].update(project_stage="FINAL_INSPECTION",building_high_rise=True)
    evidence={"id":"E-1","evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}
    docs.update(supervisor_approval=evidence,final_inspection=evidence,
                nonconformities_corrected=evidence,operation_maintenance_manual=evidence)
    rule="IR-M16-1396-DOCUMENTATION-STAGE-CLOSEOUT"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    docs["high_rise_management_room_retention"]={"retention_id":"RET-1",
        "rainwater_as_built_artifact_sha256":"b"*64,"roof_access_key_register_id":"KEY-1",
        "evidence_provenance":{"verification_status":"VALID","source_sha256":"c"*64}}
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    segment={"id":"B-M7","soil_condition":"NORMAL","continuous_shaped_bedding":True,
        "balanced_compaction":True,"lift_mm":150,"inspection_before_covering":True,
        "affects_excavation_depth":True,"excavation_geometry_sha256":"d"*64,
        "m7_geotechnical_excavation_response":{"response_id":"M7-1","excavation_geometry_sha256":"d"*64,
            "status":"APPROVED","evidence_provenance":{"verification_status":"VALID","source_sha256":"e"*64}}}
    snapshot["rule_context"]["buried_gravity_rainwater_segments"]=[segment]
    trench="IR-M16-1396-TRENCH-BURIAL"
    assert by_id(evaluate_rainwater_rules(snapshot),trench)["status"]=="PASS"
    segment["m7_geotechnical_excavation_response"]["excavation_geometry_sha256"]="f"*64
    assert "BURIED_SEGMENT_0_M7_GEOMETRY_HASH_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),trench)["errors"]


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
    row["effect_unit"]="kN_m";row["wind_and_seismic_combined"]=True
    assert "WIND_AND_SEISMIC_EFFECTS_MUST_BE_EVALUATED_SEPARATELY" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["wind_and_seismic_combined"]=False;row["live_load_factor_basis"]["declared_factor"]=1
    assert "LRFD_LIVE_LOAD_FACTOR_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
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
    row["effect_unit"]="kN_m";row["wind_and_seismic_combined"]=True
    assert "ASD_WIND_AND_SEISMIC_EFFECTS_MUST_BE_EVALUATED_SEPARATELY" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_m6_116_wind_and_seismic_are_separate_in_both_methods():
    """Clause M6-116 is reciprocal to both real combination validators."""
    rules={row["rule_id"]:row for row in load_rulebook_module()["registry"]["rules"]}
    expected={"IR-M6-1398-LRFD-RAINWATER-LOAD-COMBINATIONS",
              "IR-M6-1398-ASD-RAINWATER-LOAD-COMBINATIONS"}
    for rule_id in expected:
        source_ids={sid for source in rules[rule_id]["sources"] for sid in source["source_ids"]}
        assert "M6-116" in source_ids
    snapshot=complete_snapshot()
    for rule_id,context_key,error in (
        ("IR-M6-1398-LRFD-RAINWATER-LOAD-COMBINATIONS",
         "structural_rainwater_load_combinations",
         "WIND_AND_SEISMIC_EFFECTS_MUST_BE_EVALUATED_SEPARATELY"),
        ("IR-M6-1398-ASD-RAINWATER-LOAD-COMBINATIONS",
         "structural_rainwater_asd_combinations",
         "ASD_WIND_AND_SEISMIC_EFFECTS_MUST_BE_EVALUATED_SEPARATELY")):
        assert by_id(evaluate_rainwater_rules(snapshot),rule_id)["status"]=="PASS"
        snapshot["rule_context"][context_key]["wind_and_seismic_combined"]=True
        assert error in by_id(evaluate_rainwater_rules(snapshot),rule_id)["errors"]
        snapshot["rule_context"][context_key]["wind_and_seismic_combined"]=False


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


def test_main_entrance_way_level_and_visible_facade_coordination_are_model_bound():
    snapshot=complete_snapshot();snapshot["rule_context"]["building_geometry_sha256"]="a"*64
    entrance="IR-M4-1396-MAIN-ENTRANCE-RUNOFF-ELEVATION-INTERFACE";row=snapshot["rule_context"]["main_entrance_runoff_elevation_interfaces"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),entrance)["status"]=="PASS"
    row["main_entrance_floor_elevation_mm"]=1
    assert "ENTRANCE_RUNOFF_0_FLOOR_ABOVE_AVERAGE_WAY_LIMIT" in by_id(evaluate_rainwater_rules(snapshot),entrance)["errors"]
    row=complete_snapshot()["rule_context"]["main_entrance_runoff_elevation_interfaces"][0];snapshot["rule_context"]["main_entrance_runoff_elevation_interfaces"]=[row]
    row.update(site_condition="SPECIAL_LOCAL_CONDITION",main_entrance_floor_elevation_mm=300)
    row["local_authority_adjustment"]={"approval_id":"MUN-ENT-1","authority":"SYNTHETIC MUNICIPAL AUTHORITY","status":"APPROVED","approved_max_delta_mm":1500,"source_sha256":"c"*64}
    assert by_id(evaluate_rainwater_rules(snapshot),entrance)["status"]=="PASS"
    row["local_authority_adjustment"]["status"]="REJECTED"
    assert "ENTRANCE_RUNOFF_0_LOCAL_ADJUSTMENT_NOT_APPROVED" in by_id(evaluate_rainwater_rules(snapshot),entrance)["errors"]
    row=complete_snapshot()["rule_context"]["main_entrance_runoff_elevation_interfaces"][0];snapshot["rule_context"]["main_entrance_runoff_elevation_interfaces"]=[row];row["rainwater_runoff_interface"]=False
    assert by_id(evaluate_rainwater_rules(snapshot),entrance)["status"]=="NOT_APPLICABLE"
    facade="IR-M4-1396-VISIBLE-RAINWATER-FACADE-COORDINATION";snapshot=complete_snapshot();snapshot["rule_context"]["building_geometry_sha256"]="a"*64
    assert by_id(evaluate_rainwater_rules(snapshot),facade)["status"]=="PASS"
    row=snapshot["rule_context"]["visible_rainwater_facade_interfaces"][0];row["architecture_response"]["status"]="REJECTED"
    assert "FACADE_0_ARCHITECTURE_RESPONSE_NOT_APPROVED" in by_id(evaluate_rainwater_rules(snapshot),facade)["errors"]
    row=complete_snapshot()["rule_context"]["visible_rainwater_facade_interfaces"][0];snapshot["rule_context"]["visible_rainwater_facade_interfaces"]=[row];row.pop("architecture_response")
    assert by_id(evaluate_rainwater_rules(snapshot),facade)["status"]=="INPUT_REQUIRED"
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",complete_snapshot());assert generated["status"]=="PASS"
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")));msp=doc.modelspace();detail=" ".join(entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-DETAIL"]'))
    assert "ENTRANCE RUNOFF E-1 | INTERFACE=True | MAIN FLOOR=0mm | AVERAGE WAY=-1200mm | SITE=STANDARD | BASIS=SOURCE_STANDARD" in detail
    assert "FACADE RAINWATER RWD-F-1 | TYPE=VISIBLE_DOWNPIPE | FACADE=FACADE-NORTH | REVIEW=ARCH-FACADE-1" in detail
    assert len(msp.query('LWPOLYLINE[layer=="RW-FACADE-COORDINATION"]'))==1


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
    row=complete_snapshot()["rule_context"]["roof_snow_load_basis"][0];snapshot["rule_context"]["roof_snow_load_basis"]=[row]
    row["snow_region_basis"]["snow_region"]=3
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["snow_region_basis"]["snow_region"]=2;row["snow_region"]=7
    assert "SNOW_0_REGION_OUT_OF_RANGE" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


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
    row=complete_snapshot()["rule_context"]["rooftop_snow_drift_features"][0];snapshot["rule_context"]["rooftop_snow_drift_features"]=[row]
    row["structural_interpretation"]["approved_max_drift_height_m"]=1.1
    assert "DRIFT_0_APPROVED_MAX_HEIGHT_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["structural_interpretation"]["approved_max_drift_height_m"]=.9
    row["structural_interpretation"]["feature_id"]="OTHER"
    assert "DRIFT_0_INTERPRETATION_SCOPE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


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
    row["declared_design_live_load_kn_m2"]=2.827
    assert "SPECIAL_ROOF_0_DESIGN_LOAD_BELOW_CALCULATED_RESULT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["special_use_roof_live_load_reductions"][0];snapshot["rule_context"]["special_use_roof_live_load_reductions"]=[row]
    row.update(is_assembly_area=True,declared_design_live_load_kn_m2=4)
    row["section_6_5_5_calculation"]["result_kn_m2"]=4
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["section_6_5_5_calculation"]["result_kn_m2"]=2.828
    assert "SPECIAL_ROOF_0_CALCULATION_RESULT_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["special_use_roof_live_load_reductions"][0];snapshot["rule_context"]["special_use_roof_live_load_reductions"]=[row]
    row.update(is_one_way_slab=True,one_way_slab_span_m=8)
    assert "SPECIAL_ROOF_0_ONE_WAY_TRIBUTARY_AREA_EXCEEDS_1_5_SPAN_SQUARED" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();rule="IR-M6-1398-ROOF-SERVICEABILITY-DEFLECTION";row=snapshot["rule_context"]["roof_serviceability_deflection_checks"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["calculated_deflection_mm"]=25.01
    assert "DEFLECTION_0_EXCEEDS_ALLOWABLE" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["roof_serviceability_deflection_checks"][0];snapshot["rule_context"]["roof_serviceability_deflection_checks"]=[row]
    row["allowable_deflection_ratio"]=300
    assert "DEFLECTION_0_LIMIT_RATIO_SOURCE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_rainwater_equipment_vibration_isolation_uses_geometry_owner_response_and_product():
    snapshot=complete_snapshot();snapshot["rule_context"]["building_geometry_sha256"]="a"*64
    rule="IR-M6-1398-RAINWATER-EQUIPMENT-VIBRATION-ISOLATION"
    row=snapshot["rule_context"]["rainwater_equipment_vibration_isolation_interfaces"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["support_points"][0]=[1,1]
    assert "VIBRATION_0_SUPPORT_0_OUTSIDE_EQUIPMENT_FOOTPRINT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["rainwater_equipment_vibration_isolation_interfaces"][0]
    snapshot["rule_context"]["rainwater_equipment_vibration_isolation_interfaces"]=[row]
    row["selected_isolator"]["isolator_type"]="ELASTOMERIC"
    assert "VIBRATION_0_ISOLATOR_TYPE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["rainwater_equipment_vibration_isolation_interfaces"][0]
    snapshot["rule_context"]["rainwater_equipment_vibration_isolation_interfaces"]=[row]
    row["vibration_isolation_response"]["model_sha256"]="0"*64
    assert "VIBRATION_0_MODEL_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_buried_rainwater_geotechnical_interface_recomputes_pressure_and_uplift():
    snapshot=complete_snapshot();snapshot["rule_context"]["building_geometry_sha256"]="a"*64
    rule="IR-M6-1398-BURIED-RAINWATER-GEOTECHNICAL-STRUCTURAL-INTERFACE"
    row=snapshot["rule_context"]["buried_rainwater_geotechnical_interfaces"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["geotechnical_structural_response"]["soil_equivalent_fluid_unit_weight_kn_m3"]=4.99
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert "BURIED_0_SOIL_EQUIVALENT_FLUID_WEIGHT_BELOW_5" in result["errors"]
    assert "BURIED_0_LATERAL_PRESSURE_MISMATCH" in result["errors"]
    row=complete_snapshot()["rule_context"]["buried_rainwater_geotechnical_interfaces"][0]
    snapshot["rule_context"]["buried_rainwater_geotechnical_interfaces"]=[row]
    row["geotechnical_structural_response"]["reviewed_uplift_pressure_kpa"]=0
    assert "BURIED_0_UPLIFT_PRESSURE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["buried_rainwater_geotechnical_interfaces"][0]
    snapshot["rule_context"]["buried_rainwater_geotechnical_interfaces"]=[row]
    row["geotechnical_structural_response"]["seismic_lateral_effect_included"]=False
    assert "BURIED_0_SEISMIC_LATERAL_EFFECT_INCLUDED_MISSING" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["buried_rainwater_geotechnical_interfaces"][0]
    snapshot["rule_context"]["buried_rainwater_geotechnical_interfaces"]=[row]
    row["groundwater_elevation_m"]=98.5
    assert "BURIED_0_GROUNDWATER_HEAD_ELEVATION_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["buried_rainwater_geotechnical_interfaces"][0]
    snapshot["rule_context"]["buried_rainwater_geotechnical_interfaces"]=[row]
    row["geotechnical_structural_response"]["method_applicable_to_asset"]=False
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="INPUT_REQUIRED" and not result["errors"]


def test_construction_stage_and_machinery_impact_loads_are_recomputed():
    snapshot=complete_snapshot();snapshot["rule_context"]["building_geometry_sha256"]="a"*64
    construction="IR-M6-1398-RAINWATER-CONSTRUCTION-STAGE-LOAD"
    row=snapshot["rule_context"]["rainwater_construction_stage_loads"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),construction)["status"]=="PASS"
    row["items"][0]["quantity"]=11
    result=by_id(evaluate_rainwater_rules(snapshot),construction)
    assert "CONSTRUCTION_LOAD_0_TOTAL_MASS_MISMATCH" in result["errors"]
    assert "CONSTRUCTION_LOAD_0_DISTRIBUTED_LOAD_MISMATCH" in result["errors"]
    snapshot=complete_snapshot();snapshot["rule_context"]["building_geometry_sha256"]="a"*64
    impact="IR-M6-1398-RAINWATER-MACHINERY-IMPACT-LOAD";row=snapshot["rule_context"]["rainwater_machinery_impact_loads"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),impact)["status"]=="PASS"
    row["manufacturer_impact_factor"]=1.1
    assert "MACHINERY_IMPACT_0_MANUFACTURER_FACTOR_BELOW_CODE_MINIMUM" in by_id(evaluate_rainwater_rules(snapshot),impact)["errors"]
    row=complete_snapshot()["rule_context"]["rainwater_machinery_impact_loads"][0]
    snapshot["rule_context"]["rainwater_machinery_impact_loads"]=[row];row["declared_design_gravity_load_kn"]=1.0
    assert "MACHINERY_IMPACT_0_DESIGN_LOAD_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),impact)["errors"]
    row=complete_snapshot()["rule_context"]["rainwater_machinery_impact_loads"][0]
    snapshot["rule_context"]["rainwater_machinery_impact_loads"]=[row];row["motion_type"]="OTHER"
    result=by_id(evaluate_rainwater_rules(snapshot),impact)
    assert result["status"]=="INPUT_REQUIRED" and not result["errors"]


def test_serviceability_movement_recomputes_vectors_and_preserves_unknown_fail_semantics():
    snapshot=complete_snapshot();snapshot["rule_context"]["building_geometry_sha256"]="a"*64
    rule="IR-M6-1398-RAINWATER-SERVICEABILITY-MOVEMENT-INTERFACE"
    row=snapshot["rule_context"]["rainwater_serviceability_movement_interfaces"][0]
    evaluated=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert evaluated["status"]=="PASS" and {"M6-011","M4-044"}.issubset(evaluated["source_ids"])
    row["structural_movement_response"]["service_load_combinations"]["W_SERVICE"]["fluid_effect_factor"]=.9
    assert "MOVEMENT_0_W_SERVICE_FLUID_EFFECT_FACTOR_NOT_ONE" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["rainwater_serviceability_movement_interfaces"][0]
    snapshot["rule_context"]["rainwater_serviceability_movement_interfaces"]=[row];row["selected_joint_capacity_xyz_mm"]["x"]=5.99
    assert "MOVEMENT_0_JOINT_X_CAPACITY_INSUFFICIENT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["rainwater_serviceability_movement_interfaces"][0]
    snapshot["rule_context"]["rainwater_serviceability_movement_interfaces"]=[row];row["selected_joint_capacity_xyz_mm"].update(x=7,y=7)
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert "MOVEMENT_0_JOINT_Y_CAPACITY_INSUFFICIENT" in result["errors"]
    assert "MOVEMENT_0_JOINT_X_CAPACITY_INSUFFICIENT" not in result["errors"]
    row=complete_snapshot()["rule_context"]["rainwater_serviceability_movement_interfaces"][0]
    snapshot["rule_context"]["rainwater_serviceability_movement_interfaces"]=[row];row["selected_joint_capacity_xyz_mm"].update(x=8,y=10)
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert "MOVEMENT_0_JOINT_X_CAPACITY_INSUFFICIENT" not in result["errors"] and "MOVEMENT_0_JOINT_Y_CAPACITY_INSUFFICIENT" not in result["errors"]
    assert "MOVEMENT_0_JOINT_INTERACTION_ENVELOPE_EXCEEDED" in result["errors"]
    row=complete_snapshot()["rule_context"]["rainwater_serviceability_movement_interfaces"][0]
    snapshot["rule_context"]["rainwater_serviceability_movement_interfaces"]=[row];row["self_straining_causes"]=["UNSUPPORTED"]
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="INPUT_REQUIRED" and not result["errors"]


def test_flood_ice_combination_extensions_recompute_signed_cases_and_capacity():
    snapshot=complete_snapshot();snapshot["rule_context"]["building_geometry_sha256"]="a"*64
    rule="IR-M6-1398-RAINWATER-FLOOD-ICE-LOAD-COMBINATION-EXTENSIONS";row=_flood_ice_fixture()
    row.update(flood_interface_id="RWT-EXT-1",atmospheric_ice_component_id="PIPE-ICE-1")
    snapshot["rule_context"]["rainwater_flood_ice_load_combination_extensions"]=row
    snapshot["rule_context"]["rainwater_site_flood_structural_interfaces"]=[{"asset_id":"RWT-EXT-1"}]
    snapshot["rule_context"]["atmospheric_ice_rainwater_components"]=[{"component_id":"PIPE-ICE-1"}]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["evaluated_cases"]["LRFD-4-FLOOD-R-POS"]+=.1
    assert "FLOOD_ICE_COMBINATION_MISMATCH:LRFD-4-FLOOD-R-POS" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=_flood_ice_fixture();row.update(flood_interface_id="RWT-EXT-1",atmospheric_ice_component_id="PIPE-ICE-1")
    snapshot["rule_context"]["rainwater_flood_ice_load_combination_extensions"]=row;row["capacity_abs"]-=.1
    assert "FLOOD_ICE_CAPACITY_BELOW_GOVERNING_EFFECT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=_flood_ice_fixture();row.update(flood_interface_id="MISSING",atmospheric_ice_component_id="PIPE-ICE-1")
    snapshot["rule_context"]["rainwater_flood_ice_load_combination_extensions"]=row
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot=complete_snapshot();snapshot["rule_context"]["building_geometry_sha256"]="a"*64
    flood_asset={"asset_id":"RWT-EXT-1","asset_footprint_polygon":[[0,0],[2,0],[2,2],[0,2]],"flood_hazard_polygon":[[1,1],[3,1],[3,3],[1,3]],"hazard_type":"DEBRIS_IMPACT","project_stage":"DESIGN","declared_intersection_area_m2":1,"flood_structural_response":{"analysis_id":"FLOOD-STRUCT-1","model_sha256":"a"*64,"reviewed_asset_id":"RWT-EXT-1","reviewed_hazard_type":"DEBRIS_IMPACT","status":"PASS","evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    snapshot["rule_context"]["rainwater_site_flood_structural_interfaces"]=[flood_asset]
    row=_flood_ice_fixture();row.update(flood_interface_id="RWT-EXT-1",atmospheric_ice_load_applicable=False)
    row["evaluated_cases"]={key:value for key,value in row["evaluated_cases"].items() if "ICE" not in key}
    row["governing_case_id"]=max(row["evaluated_cases"],key=lambda key:abs(row["evaluated_cases"][key]));row["capacity_abs"]=abs(row["evaluated_cases"][row["governing_case_id"]])
    snapshot["rule_context"]["rainwater_flood_ice_load_combination_extensions"]=row
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot);assert generated["status"]=="PASS",generated
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")));text=" ".join(entity.plain_text() for entity in doc.modelspace().query('MTEXT[layer=="RW-DETAIL"]'))
    assert "FLOOD ICE COMBINATIONS | FLOOD=True:RWT-EXT-1 | ICE=False:PIPE-ICE-1" in text


def test_occupied_space_clearance_uses_actual_3d_envelope_and_dxf():
    snapshot=complete_snapshot();rule="IR-M4-1396-OCCUPIED-SPACE-RAINWATER-CLEARANCE"
    row=snapshot["rule_context"]["occupied_space_rainwater_clearance_routes"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["bottom_envelope_points"][1][2]=2.049
    assert "OCCUPIED_CLEARANCE_0_BELOW_2_05M" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["occupied_space_rainwater_clearance_routes"][0]
    snapshot["rule_context"]["occupied_space_rainwater_clearance_routes"]=[row];row["general_space_clear_height_m"]=2.0
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["crossing_is_local_overhead_projection"]=False
    assert "OCCUPIED_CLEARANCE_0_SOURCE_SCOPE_CONTRADICTION_NOT_LOCAL_OVERHEAD_ELEMENT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["occupied_space_rainwater_clearance_routes"][0]
    snapshot["rule_context"]["occupied_space_rainwater_clearance_routes"]=[row];row["envelope_components"].remove("SUPPORT")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",complete_snapshot());assert generated["status"]=="PASS"
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")));msp=doc.modelspace();detail=" ".join(entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-DETAIL"]'))
    assert "OCCUPIED CLEARANCE RW-OCC-1 | SPACE=OFFICE-1:OCCUPANCY | LOCAL_OVERHEAD=True | GENERAL_SPACE_HEIGHT=2.7m | CLEARANCE=2.05m" in detail
    assert len(msp.query('LWPOLYLINE[layer=="RW-OCCUPIED-CLEARANCE-ZONE"]'))==1 and len(msp.query('LWPOLYLINE[layer=="RW-OCCUPIED-CLEARANCE-ROUTE"]'))==1


def test_egress_width_uses_actual_cross_sections_complete_inventory_and_dxf():
    snapshot=complete_snapshot();rule="IR-M4-1396-RAINWATER-EGRESS-WIDTH-OBSTRUCTION"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row=snapshot["rule_context"]["rainwater_egress_width_interfaces"][0]
    row["rainwater_component_footprints"][0]["polygon"]=[[.5,6.9],[3.1,6.9],[3.1,7.1],[.5,7.1]]
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert "EGRESS_0_CONTINUOUS_CLEAR_WIDTH_BELOW_REQUIRED" in result["errors"]
    assert not any("SECTION_" in error and "CONTINUOUS" not in error for error in result["errors"])
    row=complete_snapshot()["rule_context"]["rainwater_egress_width_interfaces"][0]
    snapshot["rule_context"]["rainwater_egress_width_interfaces"]=[row];row["component_inventory_complete"]=False
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row=complete_snapshot()["rule_context"]["rainwater_egress_width_interfaces"][0]
    snapshot["rule_context"]["rainwater_egress_width_interfaces"]=[row];row["path_geometry_model"]="CURVED_CENTERLINE"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",complete_snapshot());assert generated["status"]=="PASS",generated
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")));msp=doc.modelspace();detail=" ".join(entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-DETAIL"]'))
    assert "EGRESS WIDTH EGR-1 | REQUIRED=1.1m | SECTIONS=3 | INVENTORY_COMPLETE=True" in detail
    assert len(msp.query('LWPOLYLINE[layer=="RW-EGRESS-CLEARANCE-ZONE"]'))==1
    assert len(msp.query('LWPOLYLINE[layer=="RW-EGRESS-LONGITUDINAL-AXIS"]'))==1
    assert len(msp.query('LWPOLYLINE[layer=="RW-EGRESS-OBSTRUCTION"]'))==1
    assert len(msp.query('LWPOLYLINE[layer=="RW-EGRESS-CROSS-SECTION"]'))==3


def test_buried_h_load_factors_are_directional_stage_aware_and_consumed():
    snapshot=complete_snapshot();rule="IR-M6-1398-BURIED-H-LOAD-COMBINATION-EXTENSIONS"
    row=snapshot["rule_context"]["rainwater_buried_h_load_combination_extensions"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["evaluated_cases"]["LRFD-H-RELIEVING"]=15
    assert "BURIED_H_0_CASE_MISMATCH:LRFD-H-RELIEVING" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["rainwater_buried_h_load_combination_extensions"][0]
    snapshot["rule_context"]["rainwater_buried_h_load_combination_extensions"]=[row];row["h_is_permanent"]=False
    row["evaluated_cases"].update({"LRFD-H-RELIEVING":20,"ASD-H-RELIEVING":20})
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["asset_id"]="MISSING-ASSET"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",complete_snapshot());assert generated["status"]=="PASS"
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")));detail=" ".join(entity.plain_text() for entity in doc.modelspace().query('MTEXT[layer=="RW-DETAIL"]'))
    assert "BURIED H COMBINATIONS RWT-B-1 | H=5kPa | PERMANENT=True | GOVERNING=LRFD-H-ADDITIVE | CAPACITY=28kPa | ANALYSIS=GEO-RWT-1" in detail


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


def test_pedestrian_ramp_runoff_recomputes_slopes_landings_accessibility_and_finish():
    snapshot=complete_snapshot();snapshot["rule_context"]["building_geometry_sha256"]="a"*64
    rule="IR-M4-1396-PEDESTRIAN-RAMP-RUNOFF-INTERFACE";row=snapshot["rule_context"]["pedestrian_ramp_runoff_interfaces"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["profile_points"][1][1]=.33
    assert "PEDESTRIAN_RAMP_0_RUN_0_SLOPE_ABOVE_8_PERCENT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["pedestrian_ramp_runoff_interfaces"][0];snapshot["rule_context"]["pedestrian_ramp_runoff_interfaces"]=[row];row["landings"][1]["station_m"]=9.01
    assert "PEDESTRIAN_RAMP_0_RUN_0_BETWEEN_LANDINGS_ABOVE_9M" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["pedestrian_ramp_runoff_interfaces"][0];snapshot["rule_context"]["pedestrian_ramp_runoff_interfaces"]=[row];row["landings"][0]["slope_x_percent"]=2
    assert "PEDESTRIAN_RAMP_0_LANDING_0_SLOPE_X_NOT_BELOW_2_PERCENT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["pedestrian_ramp_runoff_interfaces"][0];snapshot["rule_context"]["pedestrian_ramp_runoff_interfaces"]=[row];row["accessibility_review"]["model_sha256"]="b"*64
    assert "PEDESTRIAN_RAMP_0_ACCESSIBILITY_MODEL_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row=complete_snapshot()["rule_context"]["pedestrian_ramp_runoff_interfaces"][0];snapshot["rule_context"]["pedestrian_ramp_runoff_interfaces"]=[row];row["selected_surface"]["product_approval"]["approved_for_wet_pedestrian_ramp"]=False
    assert "PEDESTRIAN_RAMP_0_SURFACE_NOT_APPROVED_NONSLIP_WET" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",complete_snapshot());assert generated["status"]=="PASS"
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")));msp=doc.modelspace();detail=" ".join(entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-DETAIL"]'))
    assert "PEDESTRIAN RAMP PED-RAMP-1 | CLASS=MAIN_ACCESS_OR_EGRESS | ACCESSIBLE=True:ACCESS-PED-1 | DRAIN=EXT-DRAIN-1 | SURFACE=PED-NONSLIP-1 | PONDING_FREE=True" in detail
    assert len(msp.query('LWPOLYLINE[layer=="RW-PEDESTRIAN-RAMP-PROFILE"]'))==1 and len(msp.query('LWPOLYLINE[layer=="RW-PEDESTRIAN-RAMP-LANDING"]'))==2


def test_m4_parking_service_clearance_uses_intersection_envelope_and_reroute():
    rule="IR-M4-1396-PARKING-SERVICE-CLEARANCE-GEOMETRY"
    snapshot=complete_snapshot();row=snapshot["rule_context"]["parking_service_clearance_routes"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["bottom_envelope_points"]=[[5,4,2.399],[11,4,2.399]]
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="FAIL" and "PARKING_CLEARANCE_0_BELOW_2.40_M_AND_NO_SELECTED_REROUTE" in result["errors"]
    row["reroute_bottom_envelope_points"]=[[5,5,2.45],[11,5,2.45]];row["selected_route"]="REROUTE"
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="PASS" and "selected=REROUTE" in result["evidence"][0]
    row["reroute_bottom_envelope_points"]=[[5,5,2.39],[11,5,2.39]]
    assert "PARKING_CLEARANCE_0_REROUTE_BELOW_2.40_M" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    assert build_rainwater_package(snapshot)["blocked_at"]=="rainwater_rulebook"
    snapshot=complete_snapshot();row=snapshot["rule_context"]["parking_service_clearance_routes"][0]
    row["bottom_envelope_points"]=[[5,4,2.5],[8,4,2.399],[11,4,2.5]]
    assert "PARKING_CLEARANCE_0_BELOW_2.40_M_AND_NO_SELECTED_REROUTE" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]

    snapshot=complete_snapshot();snapshot["rule_context"]["parking_service_clearance_routes"][0].pop("parking_polygon")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot=complete_snapshot();snapshot["rule_context"]["parking_service_clearance_verified_absent"]=True
    assert "PARKING_CLEARANCE_ROWS_CONTRADICT_VERIFIED_ABSENCE" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();snapshot["rule_context"]["parking_service_clearance_routes"]=[]
    snapshot["rule_context"]["parking_service_clearance_verified_absent"]=True
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="NOT_APPLICABLE"


def test_m4_parking_service_clearance_dxf_reopen_detects_tampering():
    snapshot=complete_snapshot();generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS",generated
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")));route=list(doc.modelspace().query('LWPOLYLINE[layer=="RW-PARKING-CLEARANCE-ROUTE"]'))[0]
    route.set_points([(5,4),(9,8)]);stream=StringIO();doc.write(stream)
    qa=_rainwater_plan_independent_qa(snapshot,generated["result"],stream.getvalue().encode("utf-8"))
    assert qa["status"]=="FAIL" and "PARKING_CLEARANCE_ROUTE_GEOMETRY_MISMATCH" in qa["errors"]


def test_m4_patio_ventilation_is_architecture_owned_dependency():
    rule="IR-M4-1396-COVERED-PATIO-NATURAL-VENTILATION-DEPENDENCY"
    snapshot=complete_snapshot();row=snapshot["rule_context"]["covered_patio_natural_ventilation_reviews"][0]
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="PASS" and "architecture_analysis=ARCH-VENT-1" in result["evidence"][0]
    row["ventilation_analysis"]["model_sha256"]="f"*64
    assert "PATIO_VENTILATION_0_MODEL_HASH_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();row=snapshot["rule_context"]["covered_patio_natural_ventilation_reviews"][0]
    row["ventilation_analysis"]["provided_open_area_m2"]=1.1
    assert "PATIO_VENTILATION_0_OPENING_AREA_GEOMETRY_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();snapshot["rule_context"]["covered_patio_natural_ventilation_reviews"][0]["ventilation_analysis"].pop("evidence_provenance")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot=complete_snapshot();snapshot["rule_context"]["covered_patio_natural_ventilation_reviews"]=[];snapshot["rule_context"]["covered_transparent_patios_verified_absent"]=True
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="NOT_APPLICABLE"


def test_m4_exterior_finish_requires_product_evidence_and_exposure_coverage():
    rule="IR-M4-1396-EXTERIOR-INTERMEDIARY-FINISH-DURABILITY"
    snapshot=complete_snapshot();row=snapshot["rule_context"]["exterior_intermediary_element_finishes"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["selected_finish"]["suitable_exposures"].remove("FREEZE_THAW")
    assert "EXTERIOR_FINISH_0_UNSUPPORTED_EXPOSURES:FREEZE_THAW" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();row=snapshot["rule_context"]["exterior_intermediary_element_finishes"][0]
    row["selected_finish"]["product_approval"]["product_identity"]="OTHER"
    assert "EXTERIOR_FINISH_0_APPROVAL_PRODUCT_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();snapshot["rule_context"]["exterior_intermediary_element_finishes"][0]["selected_finish"]["product_approval"].pop("evidence_provenance")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_m4_architecture_dependency_and_finish_dxf_tamper_are_detected():
    snapshot=complete_snapshot();generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS",generated
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")));msp=doc.modelspace()
    list(msp.query('LWPOLYLINE[layer=="RW-EXTERIOR-FINISH"]'))[0].set_points([(0,0),(1,0),(1,1),(0,1)])
    stream=StringIO();doc.write(stream)
    qa=_rainwater_plan_independent_qa(snapshot,generated["result"],stream.getvalue().encode("utf-8"))
    assert qa["status"]=="FAIL" and "EXTERIOR_FINISH_GEOMETRY_MISMATCH" in qa["errors"]


def test_m4_external_light_air_conduit_rejects_service_route_occupation():
    rule="IR-M4-1396-EXTERNAL-LIGHT-AIR-CONDUIT-EXCLUSIVE-USE"
    snapshot=complete_snapshot();row=snapshot["rule_context"]["external_light_air_conduit_route_inventories"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["service_routes"][0]["route_points"]=[[11,9],[15,9],[17,9]]
    assert "LIGHT_AIR_CONDUIT_0_USED_BY_SERVICE_ROUTE_RW-OUTSIDE-LA-1" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();snapshot["rule_context"]["external_light_air_conduit_route_inventories"][0]["service_route_inventory_complete"]=False
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_m4_parking_ramp_nonslip_surface_requires_matching_wet_evidence():
    rule="IR-M4-1396-PARKING-RAMP-NONSLIP-SURFACE"
    snapshot=complete_snapshot();row=snapshot["rule_context"]["parking_ramp_surface_finishes"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["selected_surface"].pop("wet_slip_test")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    snapshot=complete_snapshot();row=snapshot["rule_context"]["parking_ramp_surface_finishes"][0];snapshot["rule_context"]["project_stage"]="CONSTRUCTION"
    row["selected_surface"].pop("wet_slip_test")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot=complete_snapshot();row=snapshot["rule_context"]["parking_ramp_surface_finishes"][0];snapshot["rule_context"]["project_stage"]="CONSTRUCTION"
    row["selected_surface"]["wet_slip_test"]["condition"]="DRY"
    assert "PARKING_RAMP_FINISH_0_SLIP_TEST_NOT_WET" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();row=snapshot["rule_context"]["parking_ramp_surface_finishes"][0];snapshot["rule_context"]["project_stage"]="CONSTRUCTION"
    row["selected_surface"]["product_approval"]["approved_for_vehicle_ramp_wet"]=False
    assert "PARKING_RAMP_FINISH_0_NOT_APPROVED_FOR_WET_VEHICLE_RAMP" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();snapshot["rule_context"]["project_stage"]="CONSTRUCTION";snapshot["rule_context"]["parking_ramp_surface_finishes"][0]["selected_surface"]["wet_slip_test"].pop("evidence_provenance")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot=complete_snapshot();snapshot["rule_context"]["project_stage"]="AFTER_THE_FACT"
    snapshot["rule_context"]["parking_ramp_surface_finishes"][0]["selected_surface"].pop("wet_slip_test")
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="INPUT_REQUIRED"
    assert result["missing_inputs"]==["project_stage[supported_stage]"]


def test_m4_light_air_conduit_guard_reconciles_levels_and_specialist_approvals():
    rule="IR-M4-1396-LIGHT-AIR-CONDUIT-TRAFFIC-GUARD-DEPENDENCY"
    snapshot=complete_snapshot();row=snapshot["rule_context"]["external_light_air_conduit_traffic_guards"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["top_surface_elevation_points"][0][2]=.006
    assert "LIGHT_AIR_GUARD_0_TOP_NOT_FLUSH_WITH_GROUND" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();row=snapshot["rule_context"]["external_light_air_conduit_traffic_guards"][0]
    row["structural_guard_analysis"]["model_sha256"]="0"*64
    assert "LIGHT_AIR_GUARD_0_STRUCTURAL_MODEL_HASH_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();snapshot["rule_context"]["external_light_air_conduit_traffic_guards"][0]["accessibility_review"].pop("evidence_provenance")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_m4_light_air_conduit_finish_is_architecture_dependency():
    rule="IR-M4-1396-LIGHT-AIR-CONDUIT-SEMI-OPEN-FINISH-DEPENDENCY"
    snapshot=complete_snapshot();row=snapshot["rule_context"]["external_light_air_conduit_semi_open_finish_reviews"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["semi_open_finish_review"]["model_sha256"]="0"*64
    assert "LIGHT_AIR_FINISH_0_MODEL_HASH_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();snapshot["rule_context"]["external_light_air_conduit_semi_open_finish_reviews"][0]["semi_open_finish_review"].pop("governing_clause_ids")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_m4_permission_clause_is_not_fabricated_as_rainwater_rule():
    module=load_rulebook_module();coverage=next(row for row in module["coverage"]["entries"] if row["source_id"]=="M4-098")
    assert coverage["disposition"]=="GUIDANCE" and coverage["rule_ids"]==[]
    assert all("M4-098" not in source["source_ids"] for rule in module["registry"]["rules"] for source in rule["sources"])


def test_m4_under_open_space_parking_consumes_three_owner_reviews():
    rule="IR-M4-1396-UNDER-OPEN-SPACE-PARKING-DEPENDENCY"
    snapshot=complete_snapshot();row=snapshot["rule_context"]["under_open_space_parking_reviews"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["urban_development_review"]["model_sha256"]="0"*64
    assert any("MODEL_HASH_MISMATCH" in error for error in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"])
    snapshot=complete_snapshot();snapshot["rule_context"]["under_open_space_parking_reviews"][0]["emergency_access_review"].pop("evidence_provenance")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_m4_basement_parking_strategy_enforces_storey_and_owner_boundaries():
    rule="IR-M4-1396-BASEMENT-PARKING-LIGHT-VENTILATION-DEPENDENCY"
    snapshot=complete_snapshot();row=snapshot["rule_context"]["basement_parking_light_ventilation_strategies"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["basement_storey_count"]=2
    errors=by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    assert "BASEMENT_PARKING_0_PASSIVE_LIGHT_AIR_STRATEGY_ONLY_ONE_BASEMENT" in errors
    assert "BASEMENT_PARKING_0_MULTILEVEL_REQUIRES_MECHANICAL_AND_FIRE_DEPENDENCIES" in errors
    snapshot=complete_snapshot();row=snapshot["rule_context"]["basement_parking_light_ventilation_strategies"][0]
    row.update(basement_storey_count=2,selected_strategy="MECHANICAL_VENTILATION_AND_FIRE_SYSTEMS")
    row.pop("architecture_strategy_review")
    row["mechanical_ventilation_review"]={"review_id":"MECH-VENT-1","owner_module":"mechanical_ventilation","model_sha256":"e1"*32,"status":"APPROVED","owner_approval_id":"MECH-VENT-APP-1","evidence_provenance":{"verification_status":"VALID","source_sha256":"11"*32}}
    row["fire_system_review"]={"review_id":"FIRE-SYS-1","owner_module":"fire","model_sha256":"e1"*32,"status":"APPROVED","owner_approval_id":"FIRE-SYS-APP-1","evidence_provenance":{"verification_status":"VALID","source_sha256":"12"*32}}
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"


def test_m4_false_ceiling_scope_heading_is_not_duplicate_rule():
    module=load_rulebook_module();coverage=next(row for row in module["coverage"]["entries"] if row["source_id"]=="M4-125")
    assert coverage["disposition"]=="GUIDANCE" and coverage["rule_ids"]==[]
    ceiling=next(row for row in module["registry"]["rules"] if row["rule_id"]=="IR-M4-1396-SUSPENDED-CEILING-CLEARANCE-SEPARATION")
    assert {f"M4-{number:03d}" for number in range(126,133)}.issubset({sid for source in ceiling["sources"] for sid in source["source_ids"]})


def test_m4_climate_text_is_guidance_not_invented_hydraulic_rule():
    module=load_rulebook_module()
    coverage=next(row for row in module["coverage"]["entries"] if row["source_id"]=="M4-006")
    assert coverage["disposition"]=="GUIDANCE" and coverage["rule_ids"]==[]
    assert all("M4-006" not in source["source_ids"] for rule in module["registry"]["rules"] for source in rule["sources"])
    rainfall=next(rule for rule in module["registry"]["rules"] if rule["validator"]=="official_rainfall_basis")
    assert all(source["code"]!="M4" for source in rainfall["sources"])


def test_m4_green_cover_and_shading_text_do_not_invent_catchment_rules():
    module=load_rulebook_module()
    for source_id in ("M4-007","M4-008"):
        coverage=next(row for row in module["coverage"]["entries"] if row["source_id"]==source_id)
        assert coverage["disposition"]=="GUIDANCE" and coverage["rule_ids"]==[]
        assert all(source_id not in source["source_ids"] for rule in module["registry"]["rules"] for source in rule["sources"])


def test_m4_general_principles_and_scope_are_not_fabricated_as_rainwater_rules():
    module=load_rulebook_module();coverage={row["source_id"]:row for row in module["coverage"]["entries"]}
    expected={**{f"M4-{i:03d}":"GUIDANCE" for i in range(9,12)},
              **{f"M4-{i:03d}":"DEPENDENCY_CONTEXT" for i in range(12,20)}}
    for source_id,disposition in expected.items():
        assert coverage[source_id]["disposition"]==disposition and coverage[source_id]["rule_ids"]==[]
        assert all(source_id not in source["source_ids"] for rule in module["registry"]["rules"] for source in rule["sources"])


def test_m4_stage_documents_materials_and_physical_protection_are_stage_bound():
    snapshot=complete_snapshot();rule="IR-M4-1396-RAINWATER-STAGE-DOCUMENTS-MATERIALS-PROTECTION"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    snapshot["rule_context"]["deliverable_generation_phase"]="POST_GENERATION_QA"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot["rule_context"]["m4_rainwater_technical_document_register"].update(
        plans_id="PLAN-1",sections_id="SEC-1",details_id="DET-1",calculations_id="CALC-1")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    snapshot["rule_context"]["deliverable_generation_phase"]="PRE_GENERATION"
    snapshot["rule_context"]["project_stage"]="PERMIT_CHANGE"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot["rule_context"]["m4_rainwater_technical_document_register"]["approved_change_record"]={
        "change_id":"CH-1","approval_id":"AUTH-1","approved_revision":"R2",
        "evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    snapshot["rule_context"]["project_stage"]="CONSTRUCTION"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot["rule_context"]["m4_construction_protection_records"]=[{"record_id":"QA-1",
        "inspection_type":"MATERIAL_STORAGE_AND_PUBLIC_UTILITIES","inspected_at":"2026-01-01T00:00:00Z","result":"PASS",
        "project_contract_id":"SYNTH-PROJECT-1","model_sha256":"a"*64,
        "covered_protection_methods":["COVERED-DRY","BARRIER-AND-ACCESS","FENCED-ROOT-ZONE"],
        "evidence_provenance":{"verification_status":"VALID","source_sha256":"f"*64}}]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    snapshot["rule_context"]["m4_construction_protection_records"][0]["project_contract_id"]="OTHER"
    assert "M4_CONSTRUCTION_PROTECTION_0_PROJECT_SCOPE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot["rule_context"]["m4_construction_protection_records"][0]["project_contract_id"]="SYNTH-PROJECT-1"
    snapshot["rule_context"]["m4_construction_protection_records"][0]["model_sha256"]="0"*64
    assert "M4_CONSTRUCTION_PROTECTION_0_MODEL_HASH_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot["rule_context"]["m4_construction_protection_records"][0]["model_sha256"]="a"*64
    methods=snapshot["rule_context"]["m4_construction_protection_records"][0]["covered_protection_methods"]
    snapshot["rule_context"]["m4_construction_protection_records"][0]["covered_protection_methods"]=methods[:-1]
    assert "M4_CONSTRUCTION_PROTECTION_0_METHOD_COVERAGE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot["rule_context"]["m4_construction_protection_records"][0]["covered_protection_methods"]=methods
    provenance=snapshot["rule_context"]["m4_construction_protection_records"][0].pop("evidence_provenance")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    snapshot["rule_context"]["m4_construction_protection_records"][0]["evidence_provenance"]=provenance
    snapshot["rule_context"]["m4_construction_protection_records"][0]["result"]="FAIL"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    snapshot=complete_snapshot();snapshot["rule_context"]["m4_rainwater_material_selections"][0]["new_or_innovative"]=True
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_m6_pipe_storage_load_uses_geometry_units_and_no_double_counting():
    snapshot=complete_snapshot();rule="IR-M6-1398-PIPE-STORAGE-CONSTRUCTION-LOAD";model_hash="d"*64
    snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    row={"zone_id":"STORE-1","footprint_polygon":[[0,0],[2,0],[2,2],[0,2]],"stack_height_m":1.8,
        "load_method":"VOLUMETRIC_TABLE_M6_141","itemized_loads_included":False,
        "declared_surface_load_kn_m2":16.2,"declared_total_load_kn":64.8,
        "structural_floor_response":{"analysis_id":"STRUCT-STORE-1","model_sha256":model_hash,
            "reviewed_total_load_kn":64.8,"status":"PASS","evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    snapshot["rule_context"]["construction_pipe_storage_zones"]=[row]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["itemized_loads_included"]=True
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["itemized_loads_included"]=False;row["stack_height_m"]=1.81
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row.update(load_method="ENGINEER_ITEMIZED_ALTERNATIVE",declared_surface_load_kn_m2=18,declared_total_load_kn=72)
    row["alternative_load_method_response"]={"analysis_id":"ALT-STORE-1","method":"WEIGHED_ITEMIZED_STACK",
        "calculated_surface_load_kn_m2":18,"calculated_total_load_kn":72,"model_sha256":model_hash,"status":"PASS",
        "evidence_provenance":{"verification_status":"VALID","source_sha256":"b"*64}}
    row["structural_floor_response"]["reviewed_total_load_kn"]=72
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["stack_height_m"]=1.8;row["load_method"]="VOLUMETRIC_TABLE_M6_141";row["declared_total_load_kn"]=60
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"


def test_m6_rain_exposed_wood_density_flows_to_structural_load():
    snapshot=complete_snapshot();rule="IR-M6-1398-RAIN-EXPOSED-WOOD-DENSITY-LOAD";model_hash="d"*64
    snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    row={"component_id":"WOOD-SUP-1","volume_m3":.1,"base_dry_density_kg_m3":500,
        "moisture_condition":"RAIN_UNPROTECTED","declared_design_mass_kg":58,
        "structural_response":{"analysis_id":"STRUCT-WOOD-1","model_sha256":model_hash,
            "reviewed_load_kn":.568786,"status":"PASS","evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    snapshot["rule_context"]["rain_exposed_wood_components"]=[row]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["declared_design_mass_kg"]=50
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["declared_design_mass_kg"]=58;row["structural_response"]["reviewed_load_kn"]=.4
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"


def test_m6_roof_material_volume_load_flows_downstream_without_double_counting():
    snapshot=complete_snapshot();rule="IR-M6-1398-ROOF-MATERIAL-VOLUMETRIC-DEAD-LOAD";model_hash="d"*64
    snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    row={"component_id":"PVC-MEM-1","material_code":"PVC_SHEET","volume_m3":.05,
        "declared_mass_kg":70,"included_in_other_dead_load":False,
        "structural_response":{"analysis_id":"STRUCT-MAT-1","model_sha256":model_hash,
            "reviewed_load_kn":.6864655,"status":"PASS",
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    snapshot["rule_context"]["roof_material_volumetric_loads"]=[row]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["declared_mass_kg"]=50
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["declared_mass_kg"]=70;row["included_in_other_dead_load"]=True
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["included_in_other_dead_load"]=False;row["structural_response"]["reviewed_load_kn"]=.5
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["structural_response"]["reviewed_load_kn"]=.6864655
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS" and generated["qa"]["checks"]["exact_file_reopened"] is True
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")))
    labels=" ".join(entity.plain_text() for entity in doc.modelspace().query('MTEXT[layer=="RW-SCHEDULE"]'))
    assert "ROOF MATERIAL LOAD PVC-MEM-1" in labels and "STRUCT-MAT-1" in labels
    row.update(component_id="STEEL-HOLLOW-SUP-1",material_code="MILD_STEEL",volume_m3=.01,
               declared_mass_kg=78.5,included_in_other_dead_load=False,
               component_geometry={"type":"HOLLOW_CYLINDER","outer_diameter_m":.22,
                   "wall_thickness_m":.01,"length_m":1.515761362779956})
    row["structural_response"].update(analysis_id="STRUCT-METAL-1",reviewed_load_kn=.769822025)
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["declared_mass_kg"]=80
    assert "ROOF_MATERIAL_0_MASS_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row.update(volume_m3=1,declared_mass_kg=7850,
               component_geometry={"type":"RECTANGULAR_SOLID","width_m":-1,"height_m":-1,"length_m":1})
    row["structural_response"]["reviewed_load_kn"]=76982.2025
    assert "ROOF_MATERIAL_0_INVALID_TYPED_COMPONENT_GEOMETRY" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["component_geometry"]={"type":"SOLID_CYLINDER","diameter_m":0,"length_m":1}
    assert "ROOF_MATERIAL_0_INVALID_TYPED_COMPONENT_GEOMETRY" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_m6_roof_covering_load_requires_authoritative_unit_interpretation():
    snapshot=complete_snapshot();rule="IR-M6-1398-ROOF-COVERING-SURFACE-DEAD-LOAD";model_hash="d"*64
    snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    row={"component_id":"FELT-1","covering_code":"BITUMEN_FELT_TWO_LAYER","area_m2":20,
        "declared_mass_kg":300,"included_in_other_dead_load":False,
        "official_unit_interpretation":{"interpretation_id":"M6-U-140","unit":"KG_M2","authority":"OFFICIAL_ERRATA_OR_ENGINEER",
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"b"*64}},
        "structural_response":{"analysis_id":"STRUCT-COVER-1","model_sha256":model_hash,
            "reviewed_load_kn":2.941995,"status":"PASS",
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    snapshot["rule_context"]["roof_covering_surface_loads"]=[row]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["official_unit_interpretation"]["unit"]="KG_M3"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["official_unit_interpretation"].pop("evidence_provenance")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["official_unit_interpretation"]["unit"]="KG_M2"
    row["official_unit_interpretation"]["evidence_provenance"]={"verification_status":"VALID","source_sha256":"b"*64}
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS" and generated["qa"]["checks"]["exact_file_reopened"] is True
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")))
    labels=" ".join(entity.plain_text() for entity in doc.modelspace().query('MTEXT[layer=="RW-SCHEDULE"]'))
    assert "ROOF COVERING LOAD FELT-1" in labels and "M6-U-140:KG_M2" in labels


def test_m6_vertical_rainwater_route_consumes_structural_drift_and_joint_allowance():
    snapshot=complete_snapshot();rule="IR-M6-1398-VERTICAL-RAINWATER-DRIFT-COMPATIBILITY";model_hash="d"*64
    snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    row={"interface_id":"STACK-JOINT-1","storey_height_m":3.2,"selected_joint_allowance_mm":8,
        "seismic_interaction_applicable":False,
        "structural_drift_response":{"analysis_id":"DRIFT-1","model_sha256":model_hash,"reviewed_interface_id":"STACK-JOINT-1",
            "relative_displacement_mm":7.5,"wind_return_period_years":10,"status":"PASS",
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    snapshot["rule_context"]["vertical_rainwater_drift_interfaces"]=[row]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["selected_joint_allowance_mm"]=7
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["selected_joint_allowance_mm"]=8;row["component_damage_limit_mm"]=7
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row.pop("component_damage_limit_mm");row["structural_drift_response"]["model_sha256"]="0"*64
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["structural_drift_response"]["model_sha256"]=model_hash;row["seismic_interaction_applicable"]=True
    row["structural_movement_clearance_mm"]=20
    row["seismic_relative_displacement_response"]={"analysis_id":"EQ-DRIFT-1","model_sha256":model_hash,"reviewed_interface_id":"STACK-JOINT-1",
        "relative_displacement_mm":18,"inelastic_deformation_included":True,"p_delta_included":True,
        "status":"PASS","evidence_provenance":{"verification_status":"VALID","source_sha256":"b"*64}}
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["structural_movement_clearance_mm"]=17
    assert "RAINWATER_DRIFT_0_SEISMIC_MOVEMENT_CLEARANCE_INSUFFICIENT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["structural_movement_clearance_mm"]=20;row["seismic_relative_displacement_response"]["p_delta_included"]=False
    assert "RAINWATER_DRIFT_0_SEISMIC_REQUIRED_EFFECTS_MISSING" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["seismic_relative_displacement_response"]["p_delta_included"]=True
    row["structural_drift_response"]["reviewed_interface_id"]="OTHER"
    assert "RAINWATER_DRIFT_0_INTERFACE_ID_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_m6_exposed_pipe_wind_force_is_recomputed_and_consumed():
    snapshot=complete_snapshot();rule="IR-M6-1398-EXPOSED-RAINWATER-PIPE-WIND-LOAD";model_hash="d"*64
    snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    # d*sqrt(q*Ce)=0.2, so smooth Cf=0.5; l/d=100.5, A=4.02m2 and F=2.01kN.
    row={"pipe_id":"EXT-RW-1","diameter_m":.2,"exposed_length_m":20.1,"surface_roughness":"SMOOTH",
        "q_kn_m2":1,"ce":1,"cg":1,"iw":1,"declared_force_kn":2.01,"vortex_shedding_applicable":True,
        "natural_frequency_hz":1.0,"vortex_reference_width_m":.2,"strouhal_number":.18,"basic_wind_speed_m_s":20,
        "declared_vortex_critical_speed_m_s":1.1111111111111112,"declared_vortex_negligible":False,
        "vortex_dynamic_response":{"analysis_id":"VORTEX-1","model_sha256":model_hash,"reviewed_pipe_id":"EXT-RW-1","status":"PASS",
            "fatigue_checked":True,"resonance_checked":True,"evidence_provenance":{"verification_status":"VALID","source_sha256":"b"*64}},
        "support_structural_response":{"analysis_id":"WIND-SUP-1","model_sha256":model_hash,"reviewed_pipe_id":"EXT-RW-1",
            "reviewed_force_kn":2.01,"status":"PASS",
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    snapshot["rule_context"]["exposed_rainwater_pipe_wind_loads"]=[row]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["declared_force_kn"]=.8
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["declared_force_kn"]=2.01;row["exposed_length_m"]=20
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["exposed_length_m"]=20.1;row["support_structural_response"]["reviewed_force_kn"]=.5
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["support_structural_response"]["reviewed_force_kn"]=2.01
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS" and generated["qa"]["checks"]["exact_file_reopened"] is True
    labels=" ".join(entity.plain_text() for entity in ezdxf.read(StringIO(generated["content"].decode("utf-8"))).modelspace().query('MTEXT[layer=="RW-SCHEDULE"]'))
    assert "VORTEX=True" in labels and "DYNAMIC=VORTEX-1" in labels
    row["declared_vortex_critical_speed_m_s"]=2
    assert "EXPOSED_PIPE_WIND_0_VORTEX_CRITICAL_SPEED_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["declared_vortex_critical_speed_m_s"]=1.1111111111111112
    row["vortex_dynamic_response"]["fatigue_checked"]=False
    assert "EXPOSED_PIPE_WIND_0_VORTEX_DYNAMIC_RESPONSE_NOT_APPROVED" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["vortex_dynamic_response"]["fatigue_checked"]=True;row["vortex_shedding_applicable"]=False
    assert "EXPOSED_PIPE_WIND_0_VORTEX_APPLICABILITY_MUST_BE_DERIVED" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_m4_outdoor_rainwater_equipment_uses_geometry_and_owner_responses():
    snapshot=complete_snapshot();rule="IR-M4-1396-OUTDOOR-RAINWATER-EQUIPMENT-INSTALLATION";model_hash="e"*64
    snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    provenance={"verification_status":"VALID","source_sha256":"a"*64}
    row={"equipment_id":"RW-PUMP-1","space_type":"ROOF",
        "open_space_polygon":[[0,0],[8,0],[8,6],[0,6]],
        "equipment_footprint":[[2,2],[4,2],[4,3],[2,3]],
        "attachment_points":[[2.2,2.2],[3.8,2.8]],
        "architecture_response":{"analysis_id":"ARCH-OUT-1","model_sha256":model_hash,
            "reviewed_equipment_id":"RW-PUMP-1","status":"PASS","evidence_provenance":provenance},
        "anchorage_response":{"analysis_id":"STRUCT-ANCH-1","model_sha256":model_hash,
            "reviewed_equipment_id":"RW-PUMP-1","status":"PASS","evidence_provenance":provenance}}
    snapshot["rule_context"]["outdoor_rainwater_equipment_installations"]=[row]
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="PASS" and "footprint_area_m2=2.000" in " ".join(result["evidence"])
    row["attachment_points"][1]=[7,5]
    assert "OUTDOOR_EQUIPMENT_0_ATTACHMENT_1_OUTSIDE_FOOTPRINT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["attachment_points"][1]=[3.8,2.8];row["architecture_response"]["model_sha256"]="0"*64
    assert "OUTDOOR_EQUIPMENT_0_ARCHITECTURE_RESPONSE_MODEL_HASH_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["architecture_response"]["model_sha256"]=model_hash;row["anchorage_response"].pop("evidence_provenance")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["anchorage_response"]["evidence_provenance"]=provenance
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS" and generated["qa"]["checks"]["exact_file_reopened"] is True
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")))
    labels=" ".join(entity.plain_text() for entity in doc.modelspace().query('MTEXT[layer=="RW-SCHEDULE"]'))
    assert "OUTDOOR RAIN EQUIPMENT RW-PUMP-1" in labels and "ANCHORAGE=STRUCT-ANCH-1" in labels


def test_m4_heavy_equipment_removal_route_geometry_clearance_and_dxf():
    snapshot=complete_snapshot();rule="IR-M4-1396-HEAVY-RAINWATER-EQUIPMENT-REMOVAL-ROUTE"
    row={"equipment_id":"RW-TANK-1","equipment_footprint":[[0,0],[2,0],[2,1],[0,1]],
        "equipment_width_m":1.5,"equipment_height_m":2.2,
        "transport_envelope_model":"TRANSLATING_CAPSULE_NO_ROTATION","equipment_orientation_locked":True,
        "selected_path":[[1,.5],[4,.5],[6,.5]],
        "exit_polygon":[[5,-.5],[7,-.5],[7,1.5],[5,1.5]],
        "clearance_corridor_polygon":[[-.1,-.1],[7.1,-.1],[7.1,1.1],[-.1,1.1]],
        "obstruction_inventory_complete":True,"obstruction_polygons":[],
        "clearance_segments":[
            {"start_distance_m":0,"end_distance_m":2,"clear_width_m":1.5,"clear_height_m":2.2},
            {"start_distance_m":2,"end_distance_m":5,"clear_width_m":1.8,"clear_height_m":2.4}],
        "clearance_samples":[
            {"point":[1,.5],"clear_width_m":1.5,"clear_height_m":2.2},
            {"point":[4,.5],"clear_width_m":1.8,"clear_height_m":2.4},
            {"point":[6,.5],"clear_width_m":2.0,"clear_height_m":2.5}]}
    snapshot["rule_context"]["rainwater_heavy_equipment_removal_routes"]=[row]
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="PASS" and "removal_path_m=5.000" in " ".join(result["evidence"])
    row["clearance_corridor_polygon"]=[[.2,0],[6.8,0],[6.8,1.3],[.2,1.3]]
    assert "HEAVY_EQUIPMENT_ROUTE_0_SWEPT_ENVELOPE_OUTSIDE_CORRIDOR" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["clearance_corridor_polygon"]=[[-.1,-.1],[7.1,-.1],[7.1,1.1],[-.1,1.1]]
    row["obstruction_polygons"]=[[[3,.4],[3.2,.4],[3.2,.6],[3,.6]]]
    assert "HEAVY_EQUIPMENT_ROUTE_0_SWEPT_ENVELOPE_INTERSECTS_OBSTRUCTION_0" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["obstruction_polygons"]=[];row["clearance_segments"][1]["start_distance_m"]=2.1
    assert "HEAVY_EQUIPMENT_ROUTE_0_CLEARANCE_SEGMENT_GAP_BEFORE_1" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["clearance_segments"][1]["start_distance_m"]=2
    row["clearance_segments"][0]["clear_height_m"]=2.19
    assert "HEAVY_EQUIPMENT_ROUTE_0_SEGMENT_0_HEIGHT_INSUFFICIENT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["clearance_segments"][0]["clear_height_m"]=2.2
    row["clearance_samples"][1]["clear_width_m"]=1.49
    assert "HEAVY_EQUIPMENT_ROUTE_0_SAMPLE_1_WIDTH_INSUFFICIENT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["clearance_samples"][1]["clear_width_m"]=1.8;row["clearance_samples"][1]["point"]=[4,2]
    assert "HEAVY_EQUIPMENT_ROUTE_0_SAMPLE_1_NOT_ON_PATH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["clearance_samples"][1]["point"]=[4,.5];row["selected_path"]=[[1,.5],[4,.5]]
    assert "HEAVY_EQUIPMENT_ROUTE_0_PATH_NOT_CONNECTED_TO_EXIT" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["selected_path"]=[[1,.5],[4,.5],[6,.5]];segments=row.pop("clearance_segments")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["clearance_segments"]=segments
    row["selected_path"]=[[1,.5],[4,.5],[4,1.0],[6,1.0]]
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="INPUT_REQUIRED"
    assert any("rectangular_turning_sweep_analysis" in value for value in result["missing_inputs"])
    row["selected_path"]=[[1,.5],[4,.5],[6,.5]]
    row["clearance_samples"]=[
        {"point":[1,.5],"clear_width_m":1.5,"clear_height_m":2.2},
        {"point":[4,.5],"clear_width_m":1.8,"clear_height_m":2.4},
        {"point":[6,.5],"clear_width_m":2.0,"clear_height_m":2.5}]
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS" and generated["qa"]["checks"]["exact_file_reopened"] is True
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")))
    labels=" ".join(entity.plain_text() for entity in doc.modelspace().query('MTEXT[layer=="RW-SCHEDULE"]'))
    assert "HEAVY EQUIPMENT REMOVAL RW-TANK-1" in labels
    assert "PATH=5.000m" in labels and "MIN CONTINUOUS CLEAR=1.5x2.2m" in labels
    assert len(doc.modelspace().query('LWPOLYLINE[layer=="RW-EQUIPMENT-REMOVAL"]'))==3


def test_m6_wind_appendix_scope_rows_do_not_create_blanket_rainwater_approval():
    coverage=json.loads(Path("data/rulebook/modules/mechanical/rainwater/source_coverage.json").read_text())
    rows={row["source_id"]:row for row in coverage["entries"]}
    assert rows["M6-142"]["disposition"]=="GUIDANCE" and not rows["M6-142"]["rule_ids"]
    assert rows["M6-143"]["disposition"]=="DEPENDENCY_CONTEXT" and not rows["M6-143"]["rule_ids"]
    assert rows["M6-146"]["disposition"]=="DEPENDENCY_CONTEXT" and not rows["M6-146"]["rule_ids"]


def test_m4_open_space_and_depressed_court_scope_rows_are_dependencies_not_fake_drainage_rules():
    coverage=json.loads(Path("data/rulebook/modules/mechanical/rainwater/source_coverage.json").read_text())
    rows={row["source_id"]:row for row in coverage["entries"]}
    for source_id in ("M4-114","M4-115","M4-116","M4-117"):
        assert rows[source_id]["disposition"]=="DEPENDENCY_CONTEXT"
        assert not rows[source_id]["rule_ids"] and rows[source_id]["automatic_pass"] is False


def test_m4_transparent_roof_cleaning_uses_path_anchors_and_structural_response():
    rule="IR-M4-1396-TRANSPARENT-ROOF-CLEANING-SAFETY"
    snapshot=complete_snapshot();row=snapshot["rule_context"]["transparent_roof_cleaning_safety_reviews"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["cleaning_anchor_points"][1]=[25,3]
    assert "TRANSPARENT_ROOF_0_CLEANING_ANCHOR_1_NOT_ON_ACCESS_PATH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();row=snapshot["rule_context"]["transparent_roof_cleaning_safety_reviews"][0]
    row["structural_cleaner_load_analysis"]["model_sha256"]="0"*64
    assert "TRANSPARENT_ROOF_0_STRUCTURAL_MODEL_HASH_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot=complete_snapshot();snapshot["rule_context"]["transparent_roof_cleaning_safety_reviews"][0]["structural_cleaner_load_analysis"].pop("evidence_provenance")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_m4_emergency_access_uses_real_geometry_reroute_and_structural_response():
    snapshot=complete_snapshot();rule="IR-M4-1396-EMERGENCY-ACCESS-RAINWATER-INTERFACE";model_hash="e"*64
    snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    row={"interface_id":"EA-1","building_group":6,"pitched_roof":True,
        "rescue_opening_width_m":.9,"rescue_opening_height_m":1.3,"north_lot":True,
        "rescue_area_location":"COURTYARD","rescue_area_polygon":[[0,0],[4,0],[4,4],[0,4]],
        "access_route_polygon":[[4,1],[8,1],[8,3],[4,3]],
        "operational_min_elevation_m":0,"operational_max_elevation_m":4.5,
        "rainwater_routes":[{"route_id":"RW-EA-1","selected_points":[[0,-1,1],[8,-1,1]]}],
        "rainwater_equipment_footprints":[{"equipment_id":"TANK-EA-1","polygon":[[9,0],[10,0],[10,1],[9,1]],"bottom_elevation_m":0,"top_elevation_m":2}],
        "plant_space_below_emergency_route":True,
        "heavy_vehicle_structural_response":{"analysis_id":"STRUCT-EA-1","structural_model_sha256":model_hash,
            "load_case_id":"HEAVY-EMERGENCY-VEHICLE","status":"PASS",
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"f"*64}}}
    snapshot["rule_context"]["emergency_access_rainwater_interfaces"]=[row]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["rainwater_routes"][0]["selected_points"]=[[1,1,1],[3,1,1]]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["rainwater_routes"][0]["selected_points"]=[[1,1,-1],[3,1,-1]]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["rainwater_routes"][0]["selected_points"]=[[1,1,5],[3,1,5]]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["rainwater_routes"][0]["selected_points"]=[[0,-1,1],[8,-1,1]]
    row["heavy_vehicle_structural_response"]["structural_model_sha256"]="0"*64
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row.pop("heavy_vehicle_structural_response")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    assert "M4-108" in by_id(evaluate_rainwater_rules(complete_snapshot()),rule)["source_ids"]
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS" and generated["qa"]["checks"]["rulebook_identity_present"] is True


def test_m4_acoustic_interface_recomputes_3d_level_and_treatment():
    snapshot=complete_snapshot();rule="IR-M4-1396-RAINWATER-ACOUSTIC-INTERFACE";model_hash="e"*64
    snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    row={"interface_id":"AC-1","receiver_id":"BED-1","propagation_model":"FREE_FIELD_POINT_SOURCE",
        "source_point_xyz":[0,0,0],"receiver_point_xyz":[10,0,0],
        "source_sound_power_dba":80,"declared_geometry_correction_dba":0,
        "selected_treatment_insertion_loss_dba":5,"declared_receiver_level_dba":44,
        "m18_acoustic_limit_response":{"response_id":"M18-AC-1","limit_dba":45,"model_sha256":model_hash,"status":"PASS",
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    snapshot["rule_context"]["rainwater_acoustic_interfaces"]=[row]
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="PASS" and any("distance_m=10.000" in value for value in result["evidence"])
    row["selected_treatment_insertion_loss_dba"]=0;row["declared_receiver_level_dba"]=49
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    assert {"M4-107","M4-111"}.issubset(by_id(evaluate_rainwater_rules(complete_snapshot()),rule)["source_ids"])
    row["selected_treatment_insertion_loss_dba"]=5;row["declared_receiver_level_dba"]=43
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["declared_receiver_level_dba"]=44;row["m18_acoustic_limit_response"]["model_sha256"]="b"*64
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["m18_acoustic_limit_response"]["model_sha256"]=model_hash;row["declared_geometry_correction_dba"]=3
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["declared_geometry_correction_dba"]=0;row["propagation_model"]="SHAFT_OR_STRUCTURE_BORNE"
    row.pop("specialist_propagation_response",None)
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["specialist_propagation_response"]={"analysis_id":"AC-SP-1","method":"COUPLED_SHAFT_MODEL",
        "predicted_receiver_level_dba":44,"prediction_basis":"POST_SELECTED_TREATMENT",
        "model_sha256":model_hash,"status":"PASS",
        "evidence_provenance":{"verification_status":"VALID","source_sha256":"c"*64}}
    row["selected_treatment_insertion_loss_dba"]=0;row["declared_receiver_level_dba"]=44
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    second=deepcopy(row);second["interface_id"]="AC-2"
    snapshot["rule_context"]["rainwater_acoustic_interfaces"].append(second)
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    snapshot["rule_context"]["rainwater_acoustic_interfaces"]=[row]
    row["selected_treatment_insertion_loss_dba"]=5
    row["declared_receiver_level_dba"]=44
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="PASS"
    row["propagation_model"]="UNSUPPORTED_BANANA"
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="INPUT_REQUIRED"
    row["propagation_model"]="SHAFT_OR_STRUCTURE_BORNE"
    row["selected_treatment_insertion_loss_dba"]=0
    second=deepcopy(row);second["interface_id"]="AC-2"
    second["m18_acoustic_limit_response"]["limit_dba"]=40
    snapshot["rule_context"]["rainwater_acoustic_interfaces"].append(second)
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert "ACOUSTIC_RECEIVER_BED-1_INCONSISTENT_OWNER_LIMITS" in result["errors"]


def test_m4_installation_space_dispositions_and_pedestrian_qa_semantics_are_explicit():
    module=load_rulebook_module()
    entries={row["source_id"]:row for row in module["coverage"]["entries"]}
    for source_id in ("M4-104","M4-110"):
        assert entries[source_id]["disposition"]=="GUIDANCE"
        assert entries[source_id]["rule_ids"]==[]
    for source_id in ("M4-105","M4-106","M4-112"):
        assert entries[source_id]["disposition"]=="DEPENDENCY_CONTEXT"
        assert entries[source_id]["rule_ids"]==[]
    rules={row["rule_id"]:row for row in module["registry"]["rules"]}
    ramp=rules["IR-M4-1396-PEDESTRIAN-RAMP-RUNOFF-INTERFACE"]
    assert ramp["parameters"]["parking_ramp_limits_do_not_apply"] is True
    assert ramp["parameters"]["qa_policy_is_not_statutory_wording"] is True
    assert ramp["parameters"]["statutory_surface_duty"]=="hard fixed non-slip"


def test_m4_pollution_interface_recomputes_geometry_and_requires_owner_distance():
    snapshot=complete_snapshot();model_hash="e"*64;snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    row={"interface_id":"POLL-1","rainwater_route_points":[[0,0],[5,0]],
         "waste_or_sewage_source_polygons":[[[0,2],[1,2],[1,3],[0,3]]],
         "environmental_health_response":{"response_id":"EH-1","model_sha256":model_hash,"status":"APPROVED","minimum_separation_m":1.5,
             "evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    snapshot["rule_context"]["rainwater_pollution_prevention_interfaces"]=[row]
    rule="IR-M4-1396-RAINWATER-POLLUTION-PREVENTION-INTERFACE"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS",generated
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")));entity=list(doc.modelspace().query('LWPOLYLINE[layer=="RW-POLLUTION-AUDIT"]'))[0]
    entity.set_points([(0,0),(4,1)]);stream=StringIO();doc.write(stream)
    qa=_rainwater_plan_independent_qa(snapshot,generated["result"],stream.getvalue().encode("utf-8"))
    assert qa["status"]=="FAIL" and "POLLUTION_ROUTE_GEOMETRY_MISMATCH" in qa["errors"]
    row["environmental_health_response"]["minimum_separation_m"]=2.1
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    row["environmental_health_response"].pop("evidence_provenance")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_m4_site_projection_checks_property_way_patio_power_and_owner_model():
    snapshot=complete_snapshot();model_hash="e"*64;snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    owner={"response_id":"URBAN-1","model_sha256":model_hash,"status":"APPROVED",
           "evidence_provenance":{"verification_status":"VALID","source_sha256":"b"*64}}
    buried={"interface_id":"BUR-1","interface_kind":"BURIED_COMPONENT_PROPERTY_BOUNDARY",
            "component_polygon":[[1,1],[2,1],[2,2],[1,2]],"property_polygon":[[0,0],[10,0],[10,10],[0,10]],
            "public_way_polygons":[],"public_way_inventory_complete":True,
            "urban_structural_authority_response":{**deepcopy(owner),"interface_id":"BUR-1"}}
    projection={"interface_id":"CAN-1","interface_kind":"ABOVE_GRADE_PROJECTION",
        "projection_polygon":[[0,-.7],[4,-.7],[4,0],[0,0]],"building_limit_line":[[0,0],[4,0]],"outer_edge_line":[[0,-.7],[4,-.7]],
        "building_footprint_polygon":[[0,0],[4,0],[4,4],[0,4]],
        "adjacency_type":"PUBLIC_WAY","underside_elevation_m":3.6,"reference_ground_elevation_m":0,
        "public_way_type":"STREET","public_way_width_m":14,"carriageway_edge_line":[[0,-1.6],[4,-1.6]],
        "public_way_polygon":[[-1,-2],[5,-2],[5,0],[-1,0]],
        "light_vent_patio_polygons":[],"light_vent_patio_inventory_complete":True,
        "power_line_corridor_polygons":[],"power_line_corridor_inventory_complete":True,
        "urban_structural_authority_response":{**owner,"interface_id":"CAN-1"}}
    snapshot["rule_context"]["rainwater_site_projection_interfaces"]=[buried,projection]
    rule="IR-M4-1396-RAINWATER-SITE-PROJECTION-INTERFACE"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS",generated
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")));entity=list(doc.modelspace().query('LWPOLYLINE[layer=="RW-SITE-PROJECTION"]'))[1]
    entity.set_points([(0,-.5),(4,-.5),(4,0),(0,0)]);stream=StringIO();doc.write(stream)
    qa=_rainwater_plan_independent_qa(snapshot,generated["result"],stream.getvalue().encode("utf-8"))
    assert qa["status"]=="FAIL" and "SITE_PROJECTION_GEOMETRY_MISMATCH" in qa["errors"]
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")))
    building=list(doc.modelspace().query('LWPOLYLINE[layer=="RW-BUILDING-FOOTPRINT"]'))[0]
    building.set_points([(0,0),(3,0),(3,3),(0,3)]);stream=StringIO();doc.write(stream)
    qa=_rainwater_plan_independent_qa(snapshot,generated["result"],stream.getvalue().encode("utf-8"))
    assert qa["status"]=="FAIL" and "BUILDING_FOOTPRINT_GEOMETRY_MISMATCH" in qa["errors"]
    snapshot["rule_context"]["rainwater_site_projection_interfaces"][1]["urban_structural_authority_response"]["interface_id"]="BUR-1"
    assert "SITE_PROJECTION_1_OWNER_INTERFACE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot["rule_context"]["rainwater_site_projection_interfaces"][1]["urban_structural_authority_response"]["interface_id"]="CAN-1"
    projection["public_way_width_m"]=11
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    projection["approved_urban_exception"]={"approval_id":"URBAN-EX-1","authority":"CITY","status":"APPROVED","source_sha256":"c"*64,"model_sha256":model_hash,"interface_id":"CAN-1"}
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    projection["power_line_corridor_polygons"]=[[[0,-.7],[1,-.7],[1,0],[0,0]]]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    projection["power_line_corridor_polygons"]=[]
    buried["component_polygon"]=[[9,9],[11,9],[11,11],[9,11]]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="FAIL"
    buried["component_polygon"]=[[1,1],[2,1],[2,2],[1,2]]
    projection["projection_polygon"]=[[0,-.7],[2,-.7],[2,-1.1],[3,-1.1],[3,0],[0,0]]
    projection["building_limit_line"]=[[0,0],[4,0]];projection["outer_edge_line"]=[[0,-.1],[4,-.1]]
    assert "SITE_PROJECTION_1_DEPTH_EXCEEDS_0_80_M" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_atmospheric_ice_load_is_calculated_and_bound_to_structural_response():
    snapshot=complete_snapshot();rule="IR-M6-1398-ATMOSPHERIC-ICE-ON-RAINWATER-COMPONENTS";model_hash="e"*64
    snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    # region 5, z=10 m, Ii=1 -> td=.025 m; Ai=pi*.025*(.1+.025)
    weight=3.141592653589793*.025*.125*10*.9*9.81
    row={"component_id":"RW-ICE-1","exposed_to_atmospheric_icing":True,"wind_load_pipe_id":"RW-WIND-ICE-1","snow_region":5,"height_above_ground_m":10,
         "importance_factor":1,"circumscribed_diameter_m":.1,"exposed_length_m":10,
         "water_unit_weight_kn_m3":9.81,"mountainous_extreme_precipitation":False,
         "flexible_dynamic_ice_effects_required":False,
         "support_structural_response":{"analysis_id":"STRUCT-ICE-1","model_sha256":model_hash,
             "reviewed_ice_weight_kn":weight,"reviewed_iced_diameter_m":.15,"status":"PASS",
             "evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    snapshot["rule_context"]["atmospheric_ice_rainwater_components"]=[row]
    snapshot["rule_context"]["exposed_rainwater_pipe_wind_loads"]=[{
        "pipe_id":"RW-WIND-ICE-1","diameter_m":.15,"exposed_length_m":20,"surface_roughness":"SMOOTH","vortex_shedding_applicable":True,
        "natural_frequency_hz":20,"vortex_reference_width_m":.15,"strouhal_number":.2,"basic_wind_speed_m_s":1,
        "declared_vortex_critical_speed_m_s":15,"declared_vortex_negligible":True,
        "q_kn_m2":1,"ce":1,"cg":1,"iw":1,"declared_force_kn":3.6,
        "support_structural_response":{"analysis_id":"STRUCT-WIND-ICE-1","model_sha256":model_hash,"reviewed_pipe_id":"RW-WIND-ICE-1",
            "reviewed_force_kn":3.6,"status":"PASS",
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"b"*64}}}]
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="PASS" and any("td_m=0.02500" in x for x in result["evidence"])
    row["support_structural_response"]["reviewed_ice_weight_kn"]=0
    assert "ATMOSPHERIC_ICE_0_REVIEWED_WEIGHT_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["support_structural_response"]["reviewed_ice_weight_kn"]=weight
    row["support_structural_response"]["reviewed_iced_diameter_m"]=.1
    assert "ATMOSPHERIC_ICE_0_REVIEWED_DIAMETER_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["support_structural_response"]["reviewed_iced_diameter_m"]=.15
    snapshot["rule_context"]["exposed_rainwater_pipe_wind_loads"][0]["diameter_m"]=.14
    assert "ATMOSPHERIC_ICE_0_ICED_DIAMETER_NOT_CONSUMED_BY_WIND_LOAD" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    snapshot["rule_context"]["exposed_rainwater_pipe_wind_loads"][0]["diameter_m"]=.15
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS" and generated["qa"]["checks"]["exact_file_reopened"] is True
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")))
    labels=" ".join(entity.plain_text() for entity in doc.modelspace().query('MTEXT[layer=="RW-SCHEDULE"]'))
    assert "ATMOSPHERIC ICE RW-ICE-1" in labels and "STRUCT-ICE-1" in labels


def test_atmospheric_ice_local_mountain_data_and_dynamic_study_fail_closed():
    snapshot=complete_snapshot();rule="IR-M6-1398-ATMOSPHERIC-ICE-ON-RAINWATER-COMPONENTS"
    snapshot["rule_context"]["building_geometry_sha256"]="e"*64
    row={"component_id":"RW-ICE-2","exposed_to_atmospheric_icing":True,"snow_region":6,"height_above_ground_m":20,
         "importance_factor":1,"circumscribed_diameter_m":.1,"exposed_length_m":5,
         "water_unit_weight_kn_m3":9.81,"mountainous_extreme_precipitation":True,
         "flexible_dynamic_ice_effects_required":True,"support_structural_response":{}}
    snapshot["rule_context"]["atmospheric_ice_rainwater_components"]=[row]
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="INPUT_REQUIRED"
    assert "atmospheric_ice_rainwater_components[0].official_local_nominal_ice_thickness_mm" in result["missing_inputs"]
    assert "atmospheric_ice_rainwater_components[0].dynamic_ice_response.analysis_id" in result["missing_inputs"]
    row["dynamic_ice_response"]={"analysis_id":"ICE-DYN-1","component_id":"OTHER","model_sha256":"0"*64,"status":"PASS",
        "evidence_provenance":{"verification_status":"VALID","source_sha256":"d"*64}}
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert "ATMOSPHERIC_ICE_0_DYNAMIC_RESPONSE_SCOPE_MISMATCH" in result["errors"]
    assert "ATMOSPHERIC_ICE_0_DYNAMIC_RESPONSE_MODEL_HASH_MISMATCH" in result["errors"]
    snapshot=complete_snapshot()
    snapshot["rule_context"]["atmospheric_ice_rainwater_components"]=[{
        "component_id":"RW-SHELTERED","exposed_to_atmospheric_icing":False}]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="NOT_APPLICABLE"
    snapshot["rule_context"]["atmospheric_ice_rainwater_components"]=[{
        "component_id":"RW-ZERO-ICE","exposed_to_atmospheric_icing":True,"snow_region":2,
        "height_above_ground_m":10,"importance_factor":1,"circumscribed_diameter_m":.1,
        "exposed_length_m":5,"water_unit_weight_kn_m3":9.81}]
    zero=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert zero["status"]=="PASS" and any("td_m=0.00000" in x for x in zero["evidence"])


def test_roof_snow_thermal_factor_is_derived_from_table_6_7_3():
    snapshot=complete_snapshot();rule="IR-M6-1398-ROOF-SNOW-LOAD-BASIS"
    row=snapshot["rule_context"]["roof_snow_load_basis"][0]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["thermal_condition"]="UNHEATED_OR_OPEN_BELOW_ROOF"
    assert "SNOW_0_THERMAL_FACTOR_TABLE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["thermal_factor_ch"]=1.2
    # Ch changes both Cs thresholding and Pr; a stale declared load must fail downstream.
    assert "SNOW_0_PR_FORMULA_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["thermal_condition"]="UNRECOGNIZED"
    assert "SNOW_0_UNKNOWN_THERMAL_CONDITION" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_roof_cladding_wind_zone_geometry_and_pressure_suction_contract():
    snapshot=complete_snapshot();rule="IR-M6-1398-ROOF-CLADDING-WIND-ZONES";model_hash="e"*64
    snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    roof_polygon=snapshot["roof"]["boundary"]
    roof_sha=sha256(json.dumps([[float(x),float(y)] for x,y in roof_polygon],separators=(",",":")).encode()).hexdigest()
    snapshot["rule_context"]["canonical_roof_wind_interfaces"]=[{"roof_interface_id":"ROOF-A:WIND","roof_area_id":"ROOF-A",
        "roof_polygon":roof_polygon,"geometry_model_sha256":model_hash,"source_geometry_id":"ROOF-GEO-A","source_geometry_sha256":roof_sha}]
    row={"roof_area_id":"ROOF-A","roof_interface_id":"ROOF-A:WIND","roof_polygon":roof_polygon,"roof_form":"LOW_SLOPE","roof_slope_degrees":5,
         "smallest_plan_dimension_m":20,"eave_height_m":8,"declared_edge_strip_width_m":2,
         "parapet_height_m":1.1,"declared_corner_cgcp":-4.4,
         "wind_design_basis":{"basis_id":"WIND-BASIS-1","reviewed_roof_interface_id":"ROOF-A:WIND","reviewed_source_geometry_id":"ROOF-GEO-A","source_clause":"M6-115","maximum_regional_wind_speed_m_s":30,
             "terrain_roughness_category":"B","geometry_model_sha256":model_hash,
             "evidence_provenance":{"verification_status":"VALID","source_sha256":"d"*64}},
         "pressure_case_id":"W-POS","suction_case_id":"W-NEG",
         "wind_zone_polygons":[{"zone_id":"EDGE-S","cgcp":-2,"polygon":[[0,0],[5,0],[5,5],[0,5]]}],
         "rainwater_component_attachments":[{"component_id":"RW-SUPPORT-1","roof_interface_id":"ROOF-A:WIND","footprint_polygon":[[1,1],[2,1],[2,2],[1,2]],
             "component_wind_scope":"ROOF_CLADDING_ATTACHMENT","selected_zone_id":"EDGE-S",
             "effective_projected_area_m2":1,"projected_profile_polygon":[[0,0],[1,0],[1,1],[0,1]],"projected_area_direction":"NORMAL_TO_ROOF_SURFACE",
             "component_height_above_ground_m":8,"ce_reference_height_m":8,
             "coefficient_basis":{"source_clause":"M6-122/figure-zone EDGE-S","verification_status":"VALID"},
             "q_kn_m2":1,"ce":1,"cg":1,"iw":1,"declared_support_force_kn":2}],
         "cladding_structural_response":{"analysis_id":"STRUCT-WIND-ZONE-1","model_sha256":model_hash,"reviewed_roof_interface_id":"ROOF-A:WIND","reviewed_source_geometry_id":"ROOF-GEO-A","reviewed_component_ids":["RW-SUPPORT-1"],
             "pressure_case_id":"W-POS","suction_case_id":"W-NEG","status":"PASS",
             "reviewed_attachment_forces_kn":{"RW-SUPPORT-1":2},
             "evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    snapshot["rule_context"]["roof_cladding_wind_zones"]=[row]
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="PASS" and any("edge_width_m=2.000" in x for x in result["evidence"])
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS" and generated["qa"]["checks"]["exact_file_reopened"] is True
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")))
    labels=" ".join(entity.plain_text() for entity in doc.modelspace().query('MTEXT[layer=="RW-SCHEDULE"]'))
    assert "ROOF WIND ZONE ROOF-A" in labels and "RW-SUPPORT-1:Aproj=1m2:2kN" in labels and "STRUCT-WIND-ZONE-1" in labels
    assert [list(entity.get_points("xy")) for entity in doc.modelspace().query('LWPOLYLINE[layer=="RW-WIND-CANONICAL-ROOF"]')]==[[tuple(point) for point in roof_polygon]]
    assert [list(entity.get_points("xy")) for entity in doc.modelspace().query('LWPOLYLINE[layer=="RW-WIND-ROOF"]')]==[[tuple(point) for point in roof_polygon]]
    assert [list(entity.get_points("xy")) for entity in doc.modelspace().query('LWPOLYLINE[layer=="RW-WIND-ATTACHMENT"]')]==[[tuple(point) for point in row["rainwater_component_attachments"][0]["footprint_polygon"]]]
    row["declared_edge_strip_width_m"]=1
    assert "ROOF_WIND_ZONE_0_EDGE_STRIP_WIDTH_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["declared_edge_strip_width_m"]=2;row["declared_corner_cgcp"]=-5.4
    assert "ROOF_WIND_ZONE_0_CORNER_COEFFICIENT_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["declared_corner_cgcp"]=-4.4;row["cladding_structural_response"]["suction_case_id"]="OTHER"
    assert "ROOF_WIND_ZONE_0_PRESSURE_SUCTION_CASE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["cladding_structural_response"]["suction_case_id"]="W-NEG"
    row["rainwater_component_attachments"][0]["declared_support_force_kn"]=1
    assert "ROOF_WIND_ZONE_0_ATTACHMENT_0_SUPPORT_FORCE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["rainwater_component_attachments"][0]["declared_support_force_kn"]=2
    row["rainwater_component_attachments"][0]["footprint_polygon"]=[[6,1],[7,1],[7,2],[6,2]]
    assert "ROOF_WIND_ZONE_0_ATTACHMENT_0_FOOTPRINT_OUTSIDE_SELECTED_ZONE" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["rainwater_component_attachments"][0]["footprint_polygon"]=[[1,1],[2,1],[2,2],[1,2]]
    row["rainwater_component_attachments"][0]["ce_reference_height_m"]=7
    assert "ROOF_WIND_ZONE_0_ATTACHMENT_0_HEIGHT_REFERENCE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["rainwater_component_attachments"][0]["ce_reference_height_m"]=8
    row["wind_zone_polygons"][0]["polygon"]=[[0,0],[1.5,0],[1.5,5],[0,5]]
    row["wind_zone_polygons"].append({"zone_id":"INNER","cgcp":-1,"polygon":[[1.5,0],[5,0],[5,5],[1.5,5]]})
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["rainwater_component_attachments"][0]["segmented_effective_areas_by_zone"]={"EDGE-S":.5,"INNER":.5}
    row["rainwater_component_attachments"][0]["declared_support_force_kn"]=1.5
    row["cladding_structural_response"]["reviewed_attachment_forces_kn"]["RW-SUPPORT-1"]=1.5
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row.pop("roof_form")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["roof_form"]="LOW_SLOPE";row["roof_interface_id"]="NONEXISTENT-ROOF"
    row["wind_design_basis"]["reviewed_roof_interface_id"]="NONEXISTENT-ROOF"
    row["cladding_structural_response"]["reviewed_roof_interface_id"]="NONEXISTENT-ROOF"
    row["rainwater_component_attachments"][0]["roof_interface_id"]="NONEXISTENT-ROOF"
    assert "ROOF_WIND_ZONE_0_UNKNOWN_CANONICAL_ROOF_INTERFACE" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    decoy=[[99,99],[102,99],[102,102],[99,102]]
    snapshot["rule_context"]["canonical_roof_wind_interfaces"]=[{"roof_interface_id":"NONEXISTENT-ROOF","roof_area_id":"ROOF-A",
        "roof_polygon":decoy,"geometry_model_sha256":model_hash,"source_geometry_id":"MADE-UP-GEOMETRY",
        "source_geometry_sha256":sha256(json.dumps([[float(x),float(y)] for x,y in decoy],separators=(",",":")).encode()).hexdigest()}]
    row["roof_polygon"]=decoy;row["wind_zone_polygons"][0]["polygon"]=decoy
    row["rainwater_component_attachments"][0]["footprint_polygon"]=[[100,100],[101,100],[101,101],[100,101]]
    row["wind_design_basis"]["reviewed_source_geometry_id"]="MADE-UP-GEOMETRY"
    row["cladding_structural_response"]["reviewed_source_geometry_id"]="MADE-UP-GEOMETRY"
    assert "ROOF_WIND_ZONE_0_SOURCE_ROOF_GEOMETRY_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_attachment_net_wind_pressure_recomputes_external_internal_and_cstar_corner():
    snapshot=complete_snapshot();rule="IR-M6-1398-RAINWATER-ATTACHMENT-NET-WIND-PRESSURE";model_hash="e"*64
    snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    source_roof=snapshot["roof"]["boundary"]
    roof_sha=sha256(json.dumps([[float(x),float(y)] for x,y in source_roof],separators=(",",":")).encode()).hexdigest()
    snapshot["rule_context"]["canonical_roof_wind_interfaces"]=[{"roof_interface_id":"ROOF-A:C","roof_area_id":"ROOF-A",
        "roof_polygon":source_roof,"geometry_model_sha256":model_hash,"source_geometry_id":"ROOF-GEO-C","source_geometry_sha256":roof_sha}]
    row={"component_id":"RW-ATT-1","component_wind_scope":"ROOF_CLADDING_ATTACHMENT",
         "pressure_sign_convention":"POSITIVE_TOWARD_SURFACE_NEGATIVE_SUCTION","roof_interface_id":"ROOF-A:C",
         "attachment_footprint_polygon":[[1,1],[2,1],[2,2],[1,2]],
         "selected_wind_zone_polygon":[[0,0],[3,0],[3,3],[0,3]],
         "projected_profile_polygon":[[0,0],[2,0],[2,1],[0,1]],
         "wind_zone_response":{"analysis_id":"ZONE-1","model_sha256":model_hash,"reviewed_roof_interface_id":"ROOF-A:C","reviewed_source_geometry_id":"ROOF-GEO-C","reviewed_component_id":"RW-ATT-1",
             "source_clause":"M6-119","evidence_provenance":{"verification_status":"VALID","source_sha256":"c"*64}},
         "corner_zone_intersection_verified":True,"method":"SIMPLIFIED_CSTAR_CORNER","iw":1,"q_kn_m2":1,
         "ce":1,"ct":1,"cg":1,"cp":-2,"cd":1,"parapet_height_m":1.1,
         "internal_pressure_kn_m2":.2,"effective_projected_area_m2":2,
         "declared_external_pressure_kn_m2":-2,"declared_net_pressure_kn_m2":-1.8,
         "declared_net_force_kn":3.6,"support_structural_response":{"analysis_id":"STRUCT-NET-WIND-1",
             "model_sha256":model_hash,"reviewed_roof_interface_id":"ROOF-A:C","reviewed_component_id":"RW-ATT-1","reviewed_net_force_kn":3.6,"status":"PASS",
             "evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    snapshot["rule_context"]["rainwater_attachment_net_wind_pressures"]=[row]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS" and generated["qa"]["checks"]["exact_file_reopened"] is True
    doc=ezdxf.read(StringIO(generated["content"].decode("utf-8")));msp=doc.modelspace()
    labels=" ".join(entity.plain_text() for entity in msp.query('MTEXT[layer=="RW-SCHEDULE"]'))
    assert "NET WIND RW-ATT-1" in labels and "STRUCT-NET-WIND-1" in labels
    assert list(list(msp.query('LWPOLYLINE[layer=="RW-WIND-CANONICAL-ROOF"]'))[0].get_points("xy"))==[tuple(point) for point in source_roof]
    assert list(msp.query('LWPOLYLINE[layer=="RW-WIND-ZONE"]'))[-1].closed
    assert list(list(msp.query('LWPOLYLINE[layer=="RW-WIND-ATTACHMENT"]'))[-1].get_points("xy"))==[tuple(point) for point in row["attachment_footprint_polygon"]]
    row["declared_net_pressure_kn_m2"]=-2.2
    assert "NET_WIND_0_ALGEBRAIC_NET_PRESSURE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["declared_net_pressure_kn_m2"]=-1.8;row["cp"]=-2.3
    assert "NET_WIND_0_CSTAR_CORNER_COEFFICIENT_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["cp"]=-2;row["corner_zone_intersection_verified"]=False
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["corner_zone_intersection_verified"]=True;row["component_wind_scope"]="FREE_PIPE"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["component_wind_scope"]="ROOF_CLADDING_ATTACHMENT"
    row.pop("internal_pressure_kn_m2")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["internal_pressure_kn_m2"]=.2;row["component_id"]="DECOY-COMP"
    assert "NET_WIND_0_ZONE_COMPONENT_ID_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_m6_rainwater_storage_tank_wind_recomputes_force_pressure_and_dxf():
    snapshot=complete_snapshot();rule="IR-M6-1398-RAINWATER-STORAGE-TANK-WIND-LOAD";model_hash="f"*64
    snapshot["rule_context"]["building_geometry_sha256"]=model_hash
    sphere={"tank_id":"RWT-SPH-1","tank_shape":"SPHERICAL","diameter_m":2.0,"surface_roughness":"LOW",
        "iw":1.0,"q_kn_m2":1.0,"ce":1.0,"cg":2.0,"cf":.2,"cp":.7,"cpi":.2,
        "declared_projected_area_m2":3.141592653589793,"declared_force_kn":1.2566370614359172,
        "declared_external_pressure_kn_m2":1.4,"declared_internal_pressure_kn_m2":.4,
        "declared_net_pressure_kn_m2":-1.0,
        "support_structural_response":{"status":"PASS","analysis_id":"STRUCT-TANK-SPH-1","model_sha256":model_hash,
            "reviewed_force_kn":1.2566370614359172,"reviewed_net_pressure_kn_m2":-1.0,
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    cylinder={"tank_id":"RWT-CYL-1","tank_shape":"CYLINDRICAL","diameter_m":2.0,"height_m":3.0,
        "iw":1.0,"q_kn_m2":.8,"ce":1.1,"cg":2.0,"cf":.7,"cp":.8,"cpi":.3,
        "figure_coefficient_basis":{"source_clause":"M6 figure A6-4-7","verification_status":"VALID","cf":.7,"cp":.8,"cpi":.3},
        "declared_projected_area_m2":6.0,"declared_force_kn":7.392,
        "declared_external_pressure_kn_m2":1.408,"declared_internal_pressure_kn_m2":.528,
        "declared_net_pressure_kn_m2":-.88,
        "support_structural_response":{"status":"PASS","analysis_id":"STRUCT-TANK-CYL-1","model_sha256":model_hash,
            "reviewed_force_kn":7.392,"reviewed_net_pressure_kn_m2":-.88,
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"b"*64}}}
    snapshot["rule_context"]["rainwater_storage_tank_wind_loads"]=[sphere,cylinder]
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="PASS" and "force_kn=7.39200" in " ".join(result["evidence"])
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS" and generated["qa"]["checks"]["exact_file_reopened"] is True
    labels=" ".join(entity.plain_text() for entity in ezdxf.read(StringIO(generated["content"].decode("utf-8"))).modelspace().query('MTEXT[layer=="RW-SCHEDULE"]'))
    assert "RAINWATER TANK WIND RWT-SPH-1" in labels and "STRUCT-TANK-CYL-1" in labels
    sphere["declared_force_kn"]=1.0
    assert "RAINWATER_TANK_WIND_0_FORCE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    sphere["declared_force_kn"]=1.2566370614359172;sphere["surface_roughness"]="MEDIUM"
    assert "RAINWATER_TANK_WIND_0_SPHERE_REQUIRES_LOW_ROUGHNESS" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    sphere["surface_roughness"]="LOW";cylinder["figure_coefficient_basis"].pop("source_clause")
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    cylinder["figure_coefficient_basis"]["source_clause"]="M6 figure A6-4-7"
    cylinder["support_structural_response"]["model_sha256"]="0"*64
    assert "RAINWATER_TANK_WIND_1_MODEL_HASH_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]


def test_m6_support_member_wind_recomputes_normal_tangential_forces_and_dxf():
    snapshot=complete_snapshot();rule="IR-M6-1398-RAINWATER-SUPPORT-MEMBER-WIND-LOAD";h="7"*64
    snapshot["rule_context"]["building_geometry_sha256"]=h
    row={"member_id":"RW-SUP-1","member_scope":"RAINWATER_SINGLE_OR_COMBINED_STRUCTURAL_SUPPORT","cross_section_shape":"RECTANGULAR","wind_angle_degrees":0,"length_m":5,"windward_width_m":1,"q_kn_m2":1,"ce":1,"cg":1,"iw":1,
        "k":.6,"cn_infinity":1.2,"ct_infinity":.2,"declared_fn_kn":3.6,"declared_ft_kn":.6,
        "figure_coefficient_basis":{"verification_status":"VALID","source_sha256":"a"*64,"source_clause":"M6 figure A6-4-9","cross_section_shape":"RECTANGULAR","wind_angle_degrees":0,"cn_infinity":1.2,"ct_infinity":.2},
        "structural_response":{"analysis_id":"STRUCT-SUP-WIND-1","model_sha256":h,"status":"PASS","reviewed_fn_kn":3.6,"reviewed_ft_kn":.6,
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"b"*64}}}
    snapshot["rule_context"]["rainwater_support_member_wind_loads"]=[row]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    generated=execute_registered_generator("MECH_ROOF_RAINWATER_PLAN",snapshot)
    assert generated["status"]=="PASS" and generated["qa"]["checks"]["exact_file_reopened"] is True
    labels=" ".join(e.plain_text() for e in ezdxf.read(StringIO(generated["content"].decode())).modelspace().query('MTEXT[layer=="RW-SCHEDULE"]'))
    assert "RAINWATER SUPPORT WIND RW-SUP-1" in labels and "STRUCT-SUP-WIND-1" in labels
    row["k"]=.7
    assert "SUPPORT_MEMBER_WIND_0_K_TABLE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["k"]=.6;row["declared_fn_kn"]=3
    assert "SUPPORT_MEMBER_WIND_0_FN_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["declared_fn_kn"]=3.6;row["structural_response"]["reviewed_ft_kn"]=.5
    assert "SUPPORT_MEMBER_WIND_0_REVIEWED_FT_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["structural_response"]["reviewed_ft_kn"]=.6;row["member_scope"]="FREE_PIPE"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["member_scope"]="RAINWATER_SINGLE_OR_COMBINED_STRUCTURAL_SUPPORT"
    row["figure_coefficient_basis"]["wind_angle_degrees"]=30
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"


def test_m6_site_flood_interface_uses_real_overlap_and_owner_response():
    snapshot=complete_snapshot();rule="IR-M6-1398-RAINWATER-SITE-FLOOD-STRUCTURAL-INTERFACE";h="8"*64
    snapshot["rule_context"]["building_geometry_sha256"]=h
    row={"asset_id":"RWT-EXT-1","asset_footprint_polygon":[[0,0],[2,0],[2,2],[0,2]],
        "flood_hazard_polygon":[[1,1],[3,1],[3,3],[1,3]],"hazard_type":"DEBRIS_IMPACT","project_stage":"DESIGN",
        "declared_intersection_area_m2":1,
        "flood_structural_response":{"analysis_id":"FLOOD-STRUCT-1","model_sha256":h,"reviewed_asset_id":"RWT-EXT-1",
            "reviewed_hazard_type":"DEBRIS_IMPACT","status":"PASS",
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"a"*64}}}
    snapshot["rule_context"]["rainwater_site_flood_structural_interfaces"]=[row]
    result=by_id(evaluate_rainwater_rules(snapshot),rule)
    assert result["status"]=="PASS" and "overlap_m2=1.0000" in " ".join(result["evidence"])
    row["declared_intersection_area_m2"]=.5
    assert "SITE_FLOOD_0_INTERSECTION_AREA_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["declared_intersection_area_m2"]=1;row["flood_structural_response"]["reviewed_asset_id"]="OTHER"
    assert "SITE_FLOOD_0_RESPONSE_SCOPE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["flood_structural_response"]["reviewed_asset_id"]="RWT-EXT-1";row["flood_hazard_polygon"]=[[3,3],[4,3],[4,4],[3,4]];row["declared_intersection_area_m2"]=0
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"


def test_m6_canopy_wind_requires_geometry_cases_coefficients_and_response():
    snapshot=complete_snapshot();rule="IR-M6-1398-RAINWATER-CANOPY-WIND-LOAD";h="6"*64
    snapshot["rule_context"]["building_geometry_sha256"]=h
    row={"canopy_id":"RW-CAN-1","canopy_type":"DUAL_SLOPE","canopy_projection_polygon":[[0,0],[5,0],[5,2],[0,2]],
        "blockage_projection_response":{"wind_direction_id":"WIND-X","projection_plane":"VERTICAL_NORMAL_TO_WIND",
            "geometry_model_sha256":h,"source_figure_id":"M6_A6_4_15","source_printed_page":153,
            "obstruction_projected_area_m2":5,"reference_under_canopy_projected_area_m2":10,
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"c"*64}},"roof_area_m2":10,"blockage_phi":.5,
        "iw":1,"q_kn_m2":1,"ce":1,"ct":1,"cg":1,"cf":.8,"cd":1,"cp_net":.6,"slope_angle_degrees":10,
        "declared_force_kn":8,"declared_pressure_kn_m2":.6,
        "governing_case":"II_ONE_WING",
        "evaluated_cases":["I_BOTH_WINGS","II_BOTH_WINGS","I_ONE_WING","II_ONE_WING"],
        "figure_coefficient_basis":{"verification_status":"VALID","source_sha256":"a"*64,"figure_id":"M6_A6_4_15","printed_page":153,
            "canopy_type":"DUAL_SLOPE","blockage_phi":.5,"slope_angle_degrees":10,"cf":.8,"cp_net":.6,
            "coefficient_semantics":"FIGURE_CF_AND_CPNET_WITH_GENERAL_FACTORS_SEPARATE",
            "evaluated_cases":["I_BOTH_WINGS","II_BOTH_WINGS","I_ONE_WING","II_ONE_WING"],
            "case_coefficients":{"I_BOTH_WINGS":{"cf":.7,"cp_net":.5},"II_BOTH_WINGS":{"cf":.7,"cp_net":.5},
                "I_ONE_WING":{"cf":.7,"cp_net":.5},"II_ONE_WING":{"cf":.8,"cp_net":.6}}},
        "structural_response":{"analysis_id":"CAN-STRUCT-1","model_sha256":h,"status":"PASS","reviewed_force_kn":8,"reviewed_pressure_kn_m2":.6,
            "evidence_provenance":{"verification_status":"VALID","source_sha256":"b"*64}}}
    snapshot["rule_context"]["rainwater_canopy_wind_loads"]=[row]
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="PASS"
    row["evaluated_cases"].remove("II_ONE_WING")
    assert "CANOPY_WIND_0_REQUIRED_CASES_MISSING" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["evaluated_cases"].append("II_ONE_WING");row["declared_force_kn"]=7
    assert "CANOPY_WIND_0_FORCE_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["declared_force_kn"]=8;row["figure_coefficient_basis"]["blockage_phi"]=.4
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["figure_coefficient_basis"]["blockage_phi"]=.5;row["roof_area_m2"]=9
    assert "CANOPY_WIND_0_PROJECTED_AREA_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["roof_area_m2"]=10;row["blockage_phi"]=.4
    assert "CANOPY_WIND_0_BLOCKAGE_PROJECTION_MISMATCH" in by_id(evaluate_rainwater_rules(snapshot),rule)["errors"]
    row["blockage_phi"]=.5;row["figure_coefficient_basis"]["figure_id"]="DECLARED_CUSTOM"
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
    row["figure_coefficient_basis"]["figure_id"]="M6_A6_4_15";row["cf"]=.7
    assert by_id(evaluate_rainwater_rules(snapshot),rule)["status"]=="INPUT_REQUIRED"
