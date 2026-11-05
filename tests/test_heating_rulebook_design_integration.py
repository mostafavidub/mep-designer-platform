from cad_engine.mechanical_execution_sizing import design_heating_installation_from_rulebook


def _inventory(tank_type="CLOSED"):
    return {
        "exposed_surface_inventory_complete": True,
        "exposed_surfaces": [{"surface_id":"RAD-1","occupied_or_work_space":True,
                              "maximum_accessible_surface_temperature_c":91,"direct_contact_guard":True}],
        "floor_mounted_equipment_inventory_complete": True,
        "floor_mounted_equipment": [{"equipment_id":"BOILER-1","base_height_mm":80}],
        "hot_water_heating_system_inventory_complete": True,
        "hot_water_heating_systems": [{"system_id":"HTG-1","expansion_tank":{
            "type":tank_type,"system_water_volume_l":180,"minimum_operating_temperature_c":10,
            "maximum_operating_temperature_c":80,"maximum_working_pressure_kpa":300,
            "selected_capacity_l":24,"normal_water_level_above_highest_component_mm":1200,
            "certified_test_pressure_kpa":450,"accredited_test_report":True}}],
    }


def test_closed_tank_design_consumer_carries_basis_identity_without_sizing_formula():
    result=design_heating_installation_from_rulebook(_inventory())
    assert result["status"] == "PASS"
    row=result["expansion_tank_schedule"][0]
    assert row["selected_capacity_l"] == 24
    assert row["capacity_basis"]["system_water_volume_l"] == 180
    assert row["calc_id"].startswith("CALC-HEATING-TANK-")
    assert row["selection_authority"] == "EXPLICIT_PROJECT_OR_ENGINEER_SELECTION"
    assert result["release_allowed"] is False
    assert result["coverage_limit"].endswith("NO_CAPACITY_FORMULA")


def test_open_tank_exact_elevation_and_closed_certificate_failures_propagate():
    open_inventory=_inventory("OPEN")
    open_inventory["hot_water_heating_systems"][0]["expansion_tank"]["normal_water_level_above_highest_component_mm"]=1199.99
    assert design_heating_installation_from_rulebook(open_inventory)["status"] == "FAIL"
    closed=_inventory();closed["hot_water_heating_systems"][0]["expansion_tank"]["certified_test_pressure_kpa"]=449.99
    assert design_heating_installation_from_rulebook(closed)["status"] == "FAIL"


def test_missing_capacity_basis_and_incomplete_inventories_remain_input_required():
    inventory=_inventory();inventory["hot_water_heating_systems"][0]["expansion_tank"].pop("system_water_volume_l")
    assert design_heating_installation_from_rulebook(inventory)["status"] == "INPUT_REQUIRED"
    inventory=_inventory();inventory["exposed_surface_inventory_complete"]=False
    assert design_heating_installation_from_rulebook(inventory)["status"] == "INPUT_REQUIRED"
