import copy
import json
from pathlib import Path

from cad_engine.mechanical_target_design import build_target_design_packages
from cad_engine.mechanical_submission_qa import validate_target_design_packages


SHEET={"official_url":"https://manufacturer.example/synthetic.pdf","revision":"TEST-1","sha256":"a"*64}


def payload():
    heating_basis={"indoor_design_c":20,"outdoor_design_c":-5,"wall_u_w_m2k":0.5,
        "glazing_u_w_m2k":2.4,"floor_u_w_m2k":0.4,"ceiling_u_w_m2k":0.3,
        "air_density_kg_m3":1.2,"air_specific_heat_j_kgk":1006,"supply_c":75,"return_c":65}
    heating_room={"id":"R1","pmm_id":"PMM-ROOM-R1","area_m2":25,"external_wall_area_m2":20,
        "glazing_area_m2":4,"exposed_floor_area_m2":25,"exposed_ceiling_area_m2":25,
        "infiltration_m3h":30,"ventilation_m3h":20}
    radiator={"manufacturer":"Synthetic Official","model":"RAD-500","output_w_per_section":130,
        "height_mm":500,"depth_mm":90,"section_width_mm":80,"rated_supply_c":75,
        "rated_return_c":65,"rated_room_c":20,"datasheet":dict(SHEET)}
    package={"manufacturer":"Synthetic Official","model":"PKG-24","space_heating_capacity_kw":24,
        "dhw_capacity_kw":28,"combined_capacity_kw":32,"gas_consumption_m3h":2.7,
        "dimensions_mm":{"w":400,"h":700,"d":300},"connections":{"gas_mm":20},"datasheet":dict(SHEET)}
    appliance={"id":"A1","pmm_id":"PMM-EQUIPMENT-A1","manufacturer":"Synthetic Official",
        "model":"PKG-24","thermal_input_kw":24,"gas_consumption_m3h":2.7,
        "appliance_valve":{"id":"AV-1"},"flue":{"diameter_mm":100},
        "combustion_air":{"free_area_cm2":150},"datasheet":dict(SHEET)}
    cooling_basis={"indoor_design_c":24,"outdoor_design_c":38,"wall_u_w_m2k":0.5,
        "glazing_u_w_m2k":2.4,"solar_gain_w_m2_by_orientation":{"S":180},
        "people_sensible_w":75,"air_density_kg_m3":1.2,"air_specific_heat_j_kgk":1006,
        "zone_diversity":{"Z1":0.9}}
    cooling_room={"id":"R1","pmm_id":"PMM-ROOM-R1","zone_id":"Z1","area_m2":25,
        "orientation":"S","glazing_area_m2":4,"external_wall_area_m2":18,"occupancy":3,
        "lighting_w":250,"equipment_w":400,"infiltration_m3h":40,"ventilation_m3h":60}
    idu={"manufacturer":"Synthetic Official","model":"IDU-12","capacity_btu_h":12000,
        "airflow_cfm":400,"liquid_size_mm":6.35,"gas_size_mm":12.7,"max_pipe_length_m":25,
        "max_elevation_m":10,"service_clearance_mm":300,"datasheet":dict(SHEET)}
    odu={"manufacturer":"Synthetic Official","model":"ODU-12","nominal_capacity_btu_h":12000,
        "airflow_cfm":1200,"min_connected_ratio":0.8,"max_connected_ratio":1.3,
        "max_total_pipe_length_m":30,"max_elevation_m":12,"service_clearance_mm":500,"datasheet":dict(SHEET)}
    fan={"manufacturer":"Synthetic Official","model":"EF-120","airflow_cfm":120,
        "esp_pa":100,"dimensions_mm":{"w":300,"h":300,"d":200},"sound_db":35,
        "service_clearance_mm":300,"fan_curve":{"points":[[120,100]]},"datasheet":dict(SHEET)}
    roof={"roof_id":"ROOF-1","boundary":[[0,0],[20,0],[20,10],[0,10]],
        "stacks":[{"id":"RW-1","point":[10,5]}],"catchments":[{"id":"C1",
        "polygon":[[0,0],[10,0],[10,10],[0,10]],"low_point":[5,5],
        "drain":{"id":"RD-1","point":[5,5]},"stack_id":"RW-1","slope_percent":2,
        "emergency_overflow":{"id":"OF-1","point":[0,5]}}]}
    rain_basis={"rainfall_intensity_mm_h":100,"runoff_coefficient":1.0,"minimum_slope_percent":2,
        "drain_capacity_table":[{"dn_mm":75,"max_flow_lps":3}],
        "downpipe_capacity_table":[{"dn_mm":90,"max_flow_lps":4}]}
    riser_graph={"graph_id":"MEP-GRAPH-1","levels":[{"id":"GROUND","type":"GROUND"},
        {"id":"ROOF","type":"ROOF"}],"nodes":[{"id":"N1","level":"GROUND"},{"id":"N2","level":"ROOF"}],
        "edges":[{"id":"RW-E1","from":"N1","to":"N2","system":"rainwater","size":"DN90",
        "material":"uPVC","levels":["GROUND","ROOF"],"calc_id":"CALC-RW-RISER-1",
        "plan_id":"CALC-RW-RISER-1","riser_id":"CALC-RW-RISER-1","schedule_id":"CALC-RW-RISER-1"}]}
    def db_record(model,equipment_type):
        return {"manufacturer":"Synthetic Official","model":model,"equipment_type":equipment_type,
          "capacity":{"declared":True},"dimensions_mm":{"declared":True},"weight_kg":1,
          "connections":{"declared":True},"electrical":{"declared":True},"water_flow":{"not_applicable":True},
          "gas_consumption":{"declared":True},"refrigerant":{"declared":True},
          "piping_limits":{"declared":True},"clearances_mm":{"declared":True},"sound":{"declared":True},
          "pressure":{"declared":True},"pump_curve":{"declared":True},"fan_curve":{"declared":True},
          "official_document":{"source_type":"OFFICIAL_MANUFACTURER",
          "official_url":SHEET["official_url"],"revision":SHEET["revision"],"sha256":SHEET["sha256"],
          "retrieved_at":"2026-09-09"}}
    return {
      "heating":{"rooms":[heating_room],"design_basis":heating_basis,
        "radiator_catalogue":[radiator],"segments":[{"id":"H1","system":"heating_supply",
        "downstream_radiator_ids":["RAD-R1"]}],"network_basis":{"design_delta_t_k":10,
        "fluid_density_kg_m3":983,"fluid_specific_heat_j_kgk":4180,
        "candidate_diameters_mm":[10,16,20,25],"max_velocity_m_s":1.0},
        "package_requirements":{"space_heating_kw":10,"dhw_kw":20,"simultaneous_factor":0.5},
        "package_catalogue":[package]},
      "gas":{"appliances":[appliance],"segments":[{"id":"G1","downstream_appliance_ids":["A1"],
        "equivalent_length_m":12}],"design_basis":{"service_pressure_mbar":21,
        "allowable_pressure_drop_mbar":2,"capacity_table":[{"max_equivalent_length_m":20,
        "dn_mm":20,"max_flow_m3h":4}],"meter":{"id":"GM-1"},"regulator":{"id":"GR-1"},
        "service_shutoff":{"id":"SV-1"},"riser":{"id":"GRS-1"},"fittings":{"schedule":"GF-1"},
        "sleeves":{"detail":"GS-1"}}},
      "split_ac":{"rooms":[cooling_room],"design_basis":cooling_basis,"idu_catalogue":[idu],
        "odu_catalogue":[odu],"routes":[{"room_id":"R1","length_m":18,"elevation_m":6,
        "condensate_drain":True,"service_clearance_mm":400}],"odu_site":{"service_clearance_mm":700}},
      "exhaust":{"rooms":[{"id":"WC-1","pmm_id":"PMM-WC-1","level_id":"GROUND",
        "room_type":"toilet","volume_m3":20,"duct_path":{"duct_friction_pa":30,
        "fitting_loss_pa":20,"terminal_loss_pa":10}}],"criteria":{"toilet":{"minimum_cfm":100,"ach":10}},
        "fan_catalogue":[fan]},
      "rainwater":{"roof":roof,"design_basis":rain_basis},
      "riser":{"network_graph":riser_graph},
      "manufacturer_database":{"records":[db_record("RAD-500","radiator"),db_record("PKG-24","package"),
        db_record("IDU-12","split_idu"),db_record("ODU-12","split_odu"),db_record("EF-120","exhaust_fan")]}
    }


def test_all_target_design_packages_pass_with_complete_traceable_evidence():
    result=build_target_design_packages(payload())
    assert result["status"]=="PASS",result
    packages=result["packages"]
    assert packages["heating"]["radiator_selection"]["radiators"][0]["selection_type"]=="MANUFACTURER_MODEL"
    gas=packages["gas"]["gas_network"]
    assert all(all(row.get(key) is not None for key in ("flow_m3h","equivalent_length_m","selected_dn_mm","calc_id")) for row in gas["segments"])
    idu=packages["split_ac"]["selection"]["idus"][0]
    assert all(idu.get(key) is not None for key in ("calculated_load_btu_h","selected_capacity_btu_h",
        "selection_margin_percent","manufacturer","model","route_length_m","elevation_m","status"))


def test_missing_manufacturer_and_engineering_values_fail_closed():
    value=payload(); value["heating"]["radiator_catalogue"][0]["datasheet"].pop("sha256")
    assert build_target_design_packages(value)["status"]=="INPUT_REQUIRED"
    value=payload(); value["gas"]["design_basis"].pop("sleeves")
    assert build_target_design_packages(value)["status"]=="INPUT_REQUIRED"
    value=payload(); value["split_ac"]["rooms"][0].pop("orientation")
    assert build_target_design_packages(value)["status"]=="INPUT_REQUIRED"


def test_preliminary_only_radiator_and_missing_segment_identity_are_rejected():
    result=build_target_design_packages(payload()); packages=result["packages"]
    packages["heating"]["radiator_selection"]["radiators"][0]["selection_type"]="DESIGN_ENVELOPE"
    packages["gas"]["gas_network"]["segments"][0]["calc_id"]=None
    gate=validate_target_design_packages(packages)
    assert gate["status"]=="INPUT_REQUIRED"
    assert "heating:PRELIMINARY_OR_INVALID_RADIATOR" in gate["errors"]


def test_steps_7_9_semantic_golden_contract():
    result=build_target_design_packages(payload())
    baseline=json.loads(Path("standards/golden/mechanical-steps-7-9.baseline.json").read_text())
    actual={"sheets":{key:value for key,value in result["gate"]["sheets"].items()
                       if key in {"M-131","M-132","M-141","M-142","M-161","M-162"}},
            "heating_radiator_fields":sorted(result["packages"]["heating"]["radiator_selection"]["radiators"][0]),
            "gas_segment_fields":sorted(result["packages"]["gas"]["gas_network"]["segments"][0]),
            "split_idu_fields":sorted(result["packages"]["split_ac"]["selection"]["idus"][0])}
    assert actual==baseline


def test_steps_10_13_final_evidence_and_semantic_golden_contract():
    result=build_target_design_packages(payload()); packages=result["packages"]
    baseline=json.loads(Path("standards/golden/mechanical-steps-10-13.baseline.json").read_text())
    actual={"sheets":{key:value for key,value in result["gate"]["sheets"].items()
                       if key in {"M-171","M-172","M-R-01","M-151","M-181"}},
      "exhaust_fan_fields":sorted(packages["exhaust"]["fan_selection"]["fans"][0]),
      "rainwater_catchment_fields":sorted(packages["rainwater"]["rainwater_design"]["catchments"][0]),
      "rainwater_segment_fields":sorted(packages["rainwater"]["rainwater_design"]["segments"][0]),
      "riser_claim":packages["riser"]["riser_design"]["claim"],
      "riser_level_policy":packages["riser"]["riser_design"]["level_policy"],
      "manufacturer_policy":packages["manufacturer_database"]["database"]["policy"],
      "manufacturer_record_count":packages["manufacturer_database"]["database"]["record_count"],
      "private_documents_stored":packages["manufacturer_database"]["database"]["private_documents_stored"]}
    assert actual==baseline


def test_steps_10_13_destructive_inputs_fail_closed():
    value=payload(); value["exhaust"]["fan_catalogue"][0].pop("fan_curve")
    assert build_target_design_packages(value)["status"]=="INPUT_REQUIRED"
    value=payload(); value["rainwater"]["roof"]["catchments"]=[]
    assert build_target_design_packages(value)["status"]=="INPUT_REQUIRED"
    value=payload(); value["riser"]["network_graph"]["levels"].append({"id":"DETAIL-1","type":"DETAIL"})
    assert build_target_design_packages(value)["status"]=="FAIL"
    value=payload(); value["manufacturer_database"]["records"][0]["official_document"]["source_type"]="RESELLER"
    assert build_target_design_packages(value)["status"]=="FAIL"
    value=payload(); value["manufacturer_database"]["records"]=value["manufacturer_database"]["records"][1:]
    result=build_target_design_packages(value)
    assert result["status"]=="FAIL"
    assert any("UNREGISTERED_SELECTION" in error for error in result["gate"]["errors"])
