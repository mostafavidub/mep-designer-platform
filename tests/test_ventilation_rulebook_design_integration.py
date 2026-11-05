from cad_engine.ventilation_rulebook import design_residential_ventilation_from_rulebook, design_ventilation_from_rulebook


def _basis(): return {"max_duct_velocity_m_s":3,"candidate_round_duct_diameters_mm":[100,125,160,200]}


def test_exact_m14_residential_rates_drive_duct_design_and_identity():
    result=design_residential_ventilation_from_rulebook(
        [{"space_id":"K-1","usage":"RESIDENTIAL_KITCHEN"},{"space_id":"B-1","usage":"RESIDENTIAL_BATHROOM_OR_TOILET"}],
        [{"intake_id":"OA-1","point_xyz":[0,0,0],"nearest_exhaust_point_xyz":[3,0,0],"nearest_exhaust_class":"HAZARDOUS_OR_CONTAMINATED"}],_basis())
    assert result["status"] == "PASS",result
    by={x["space_id"]:x for x in result["spaces"]}
    assert (by["K-1"]["required_exhaust_lps"],by["K-1"]["required_exhaust_m3h"])==(50,180)
    assert (by["B-1"]["required_exhaust_lps"],by["B-1"]["required_exhaust_m3h"])==(25,90)
    assert all(x["duct_sizing"]["calc_id"].startswith("CALC-DUCT-") for x in result["spaces"])
    assert result["coverage_limit"].endswith("ONLY")


def test_intake_geometry_or_condition_and_unknown_scope_fail_closed():
    failed=design_residential_ventilation_from_rulebook(
        [{"space_id":"K","usage":"RESIDENTIAL_KITCHEN"}],
        [{"intake_id":"OA","point_xyz":[0,0,0],"nearest_exhaust_point_xyz":[2.99,0,.99],"nearest_exhaust_class":"HAZARDOUS_OR_CONTAMINATED"}],_basis())
    assert failed["status"] == "FAIL"
    assert "VENTILATION_OUTSIDE_AIR_INTAKE_SEPARATION_LOW:0" in failed["errors"]
    unknown=design_residential_ventilation_from_rulebook([{"space_id":"P","usage":"PARKING"}],[],_basis())
    assert unknown["status"] == "INPUT_REQUIRED"


def test_missing_duct_basis_or_no_compliant_candidate_does_not_invent_size():
    missing=design_residential_ventilation_from_rulebook([{"space_id":"K","usage":"RESIDENTIAL_KITCHEN"}],[],{})
    assert missing["status"] == "INPUT_REQUIRED"
    failed=design_residential_ventilation_from_rulebook([{"space_id":"K","usage":"RESIDENTIAL_KITCHEN"}],[],{"max_duct_velocity_m_s":.1,"candidate_round_duct_diameters_mm":[100]})
    assert failed["status"] == "FAIL" and failed["spaces"][0]["duct_sizing"]["selected"] is None

def test_parking_rates_and_enclosed_control_drive_duct_design_without_guessing():
    result=design_ventilation_from_rulebook([
        {"space_id":"PRIVATE","usage":"PRIVATE_PARKING","vehicle_count":2,
         "floor_area_m2":40,"enclosure":"OPEN"},
        {"space_id":"COMMON","usage":"COMMON_PARKING","floor_area_m2":100,
         "enclosure":"ENCLOSED","automatic_operation_enabled":True,
         "pollutant_control_enabled":True,"co_control_setpoint_ppm":24.9}],[],
        {"max_duct_velocity_m_s":8,"candidate_round_duct_diameters_mm":[200,250,315,400]})
    assert result["status"]=="PASS",result
    by={row["space_id"]:row for row in result["spaces"]}
    assert by["PRIVATE"]["required_exhaust_lps"]==100
    assert by["COMMON"]["required_exhaust_lps"]==750
    assert by["COMMON"]["rule_id"].endswith("PARKING-VENTILATION-RATES")

def test_enclosed_parking_missing_co_basis_remains_input_required():
    result=design_ventilation_from_rulebook([
        {"space_id":"COMMON","usage":"COMMON_PARKING","floor_area_m2":100,
         "enclosure":"ENCLOSED","automatic_operation_enabled":True,
         "pollutant_control_enabled":True}],[],
        {"max_duct_velocity_m_s":8,"candidate_round_duct_diameters_mm":[200,250,315,400]})
    assert result["status"]=="INPUT_REQUIRED"
    assert any("co_control_setpoint_ppm" in item for item in result["missing_inputs"])

def test_single_basis_outside_air_rows_drive_exact_duct_duties():
    result=design_ventilation_from_rulebook([
        {"space_id":"OFFICE","usage":"OFFICE_ROOM","occupant_count":10},
        {"space_id":"POOL","usage":"INDOOR_POOL","floor_area_m2":100},
        {"space_id":"CORRIDOR","usage":"CORRIDOR","floor_area_m2":100}],[],
        {"max_duct_velocity_m_s":6,"candidate_round_duct_diameters_mm":[125,160,200,250,315]})
    assert result["status"]=="PASS",result
    by={row["space_id"]:row for row in result["spaces"]}
    assert by["OFFICE"]["required_exhaust_lps"]==75
    assert by["POOL"]["required_exhaust_lps"]==250
    assert by["CORRIDOR"]["required_exhaust_lps"]==25
    assert all(row["rule_id"].endswith("OUTSIDE-AIR-RATES") for row in by.values())
