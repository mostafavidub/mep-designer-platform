import json
from pathlib import Path

import pytest

from app.mechanical_rulebook import VENTILATION, network_design_basis
from cad_engine.executable_rulebook import VENTILATION_ROOT, load_rulebook_module, validate_rulebook_module
from cad_engine.ventilation_rulebook import evaluate_ventilation_rulebook

ROOT=Path(__file__).resolve().parents[1]

def _snapshot(kitchen=50, bath=25):
    return {"ventilation":{"space_inventory_complete":True,"spaces":[
        {"space_id":"K-1","usage":"RESIDENTIAL_KITCHEN","design_exhaust_lps":kitchen},
        {"space_id":"B-1","usage":"RESIDENTIAL_BATHROOM_OR_TOILET","design_exhaust_lps":bath}],
        "outside_air_intake_inventory_complete":True,"outside_air_intakes":[
        {"nearest_exhaust_class":"HAZARDOUS_OR_CONTAMINATED","horizontal_distance_m":3,"intake_below_exhaust_m":0}]}}

def _row(result, suffix): return next(r for r in result["results"] if r["rule_id"].endswith(suffix))

def test_module_integrity_and_strict_schema():
    module=load_rulebook_module(VENTILATION_ROOT); assert validate_rulebook_module(module)["status"]=="PASS"
    assert len(module["registry"]["rules"])==5
    validator=pytest.importorskip("jsonschema").Draft202012Validator(json.loads((ROOT/"data/rulebook/schema/executable_rule.schema.json").read_text()))
    assert all(not list(validator.iter_errors(rule)) for rule in module["registry"]["rules"])

def test_kitchen_si_conversion_is_source_correct_and_consumed():
    assert VENTILATION["kitchen_m3h_each"]==180.0
    assert VENTILATION["toilet_m3h_each"]==90.0
    basis=network_design_basis()["systems"]["exhaust_ventilation"]
    assert basis["endpoint_load_by_type"]["residential_kitchen"]==50.0
    assert basis["size_table"]==[]

def test_residential_exhaust_exact_boundaries_pass_and_below_fails():
    assert _row(evaluate_ventilation_rulebook(_snapshot()),"RESIDENTIAL-EXHAUST-RATES")["status"]=="PASS"
    failed=_row(evaluate_ventilation_rulebook(_snapshot(kitchen=49.99)),"RESIDENTIAL-EXHAUST-RATES")
    assert failed["status"]=="FAIL" and failed["errors"]==["VENTILATION_EXHAUST_FLOW_LOW:K-1"]

def test_missing_nonfinite_and_incomplete_inventory_fail_closed():
    row=_snapshot(); row["ventilation"]["spaces"][0].pop("design_exhaust_lps")
    assert _row(evaluate_ventilation_rulebook(row),"RESIDENTIAL-EXHAUST-RATES")["status"]=="INPUT_REQUIRED"
    assert _row(evaluate_ventilation_rulebook(_snapshot(kitchen=float("nan"))),"RESIDENTIAL-EXHAUST-RATES")["status"]=="INPUT_REQUIRED"
    row=_snapshot(); row["ventilation"]["space_inventory_complete"]=False
    assert _row(evaluate_ventilation_rulebook(row),"RESIDENTIAL-EXHAUST-RATES")["status"]=="INPUT_REQUIRED"

def test_intake_separation_or_condition_exact_boundaries():
    assert _row(evaluate_ventilation_rulebook(_snapshot()),"OUTSIDE-AIR-INTAKE-SEPARATION")["status"]=="PASS"
    row=_snapshot(); row["ventilation"]["outside_air_intakes"][0].update(horizontal_distance_m=2.99,intake_below_exhaust_m=1)
    assert _row(evaluate_ventilation_rulebook(row),"OUTSIDE-AIR-INTAKE-SEPARATION")["status"]=="PASS"
    row["ventilation"]["outside_air_intakes"][0]["intake_below_exhaust_m"]=0.99
    assert _row(evaluate_ventilation_rulebook(row),"OUTSIDE-AIR-INTAKE-SEPARATION")["status"]=="FAIL"

def test_residential_kitchen_bath_exhaust_exception_is_not_false_hazard():
    row=_snapshot(); row["ventilation"]["outside_air_intakes"]=[{"nearest_exhaust_class":"RESIDENTIAL_KITCHEN_OR_BATH_EXHAUST","horizontal_distance_m":0,"intake_below_exhaust_m":0}]
    result=_row(evaluate_ventilation_rulebook(row),"OUTSIDE-AIR-INTAKE-SEPARATION")
    assert result["status"]=="NOT_APPLICABLE"

def test_empty_complete_scope_is_not_applicable_but_missing_scope_is_unknown():
    empty={"ventilation":{"space_inventory_complete":True,"spaces":[],"outside_air_intake_inventory_complete":True,"outside_air_intakes":[]}}
    assert {r["status"] for r in evaluate_ventilation_rulebook(empty)["results"]}=={"NOT_APPLICABLE"}
    assert evaluate_ventilation_rulebook({"ventilation":{}})["status"]=="INPUT_REQUIRED"

def test_unknown_space_or_exhaust_class_cannot_be_treated_as_out_of_scope():
    row=_snapshot(); row["ventilation"]["spaces"][0]["usage"]="KITCHEN_UNKNOWN"
    assert _row(evaluate_ventilation_rulebook(row),"RESIDENTIAL-EXHAUST-RATES")["status"]=="INPUT_REQUIRED"
    row=_snapshot(); row["ventilation"]["outside_air_intakes"][0]["nearest_exhaust_class"]="UNKNOWN"
    assert _row(evaluate_ventilation_rulebook(row),"OUTSIDE-AIR-INTAKE-SEPARATION")["status"]=="INPUT_REQUIRED"

def _parking_snapshot(private_flow=100, common_flow=750, full=750, minimum=25, co=24.9):
    return {"ventilation":{"space_inventory_complete":True,"spaces":[
        {"space_id":"P-PRIVATE","usage":"PRIVATE_PARKING","vehicle_count":2,
         "floor_area_m2":40,"enclosure":"OPEN","design_ventilation_lps":private_flow},
        {"space_id":"P-COMMON","usage":"COMMON_PARKING","floor_area_m2":100,
         "enclosure":"ENCLOSED","design_ventilation_lps":common_flow,
         "full_system_capacity_lps":full,"minimum_controlled_capacity_lps":minimum,
         "co_control_setpoint_ppm":co,"automatic_operation_enabled":True,
         "pollutant_control_enabled":True}],"outside_air_intake_inventory_complete":True,
         "outside_air_intakes":[]}}

def test_parking_table_exact_bases_pass_and_below_boundary_fails():
    passed=evaluate_ventilation_rulebook(_parking_snapshot())
    assert _row(passed,"PARKING-VENTILATION-RATES")["status"]=="PASS"
    assert _row(passed,"ENCLOSED-PARKING-CO-CONTROL")["status"]=="PASS"
    failed=evaluate_ventilation_rulebook(_parking_snapshot(private_flow=99.99,common_flow=749.99))
    assert _row(failed,"PARKING-VENTILATION-RATES")["errors"]==[
        "VENTILATION_PARKING_FLOW_LOW:P-COMMON","VENTILATION_PARKING_FLOW_LOW:P-PRIVATE"]

def test_enclosed_parking_capacity_co_and_automatic_controls_fail_closed():
    assert _row(evaluate_ventilation_rulebook(_parking_snapshot(full=749.99)),
                "ENCLOSED-PARKING-CO-CONTROL")["status"]=="FAIL"
    assert _row(evaluate_ventilation_rulebook(_parking_snapshot(minimum=24.99)),
                "ENCLOSED-PARKING-CO-CONTROL")["status"]=="FAIL"
    assert _row(evaluate_ventilation_rulebook(_parking_snapshot(co=25)),
                "ENCLOSED-PARKING-CO-CONTROL")["status"]=="FAIL"
    missing=_parking_snapshot();missing["ventilation"]["spaces"][1]["automatic_operation_enabled"]=False
    assert _row(evaluate_ventilation_rulebook(missing),"ENCLOSED-PARKING-CO-CONTROL")["status"]=="INPUT_REQUIRED"

def _outside_air_snapshot(office=75, pool=250, corridor=25):
    return {"ventilation":{"space_inventory_complete":True,"spaces":[
        {"space_id":"OFFICE","usage":"OFFICE_ROOM","occupant_count":10,"design_outside_air_lps":office},
        {"space_id":"POOL","usage":"INDOOR_POOL","floor_area_m2":100,"design_outside_air_lps":pool},
        {"space_id":"CORRIDOR","usage":"CORRIDOR","floor_area_m2":100,"design_outside_air_lps":corridor}],
        "outside_air_intake_inventory_complete":True,"outside_air_intakes":[]}}

def test_single_basis_outside_air_rows_preserve_person_and_area_columns():
    passed=_row(evaluate_ventilation_rulebook(_outside_air_snapshot()),"OUTSIDE-AIR-RATES")
    assert passed["status"]=="PASS"
    failed=_row(evaluate_ventilation_rulebook(_outside_air_snapshot(office=74.99,pool=249.99,corridor=24.99)),
                "OUTSIDE-AIR-RATES")
    assert failed["errors"]==["VENTILATION_OUTSIDE_AIR_FLOW_LOW:CORRIDOR",
                              "VENTILATION_OUTSIDE_AIR_FLOW_LOW:OFFICE",
                              "VENTILATION_OUTSIDE_AIR_FLOW_LOW:POOL"]

def test_unregistered_multi_basis_row_and_missing_basis_fail_closed():
    unknown=_outside_air_snapshot();unknown["ventilation"]["spaces"][0]["usage"]="DORMITORY_MULTI_OCCUPANT"
    assert _row(evaluate_ventilation_rulebook(unknown),"OUTSIDE-AIR-RATES")["status"]=="INPUT_REQUIRED"
    missing=_outside_air_snapshot();missing["ventilation"]["spaces"][1].pop("floor_area_m2")
    assert _row(evaluate_ventilation_rulebook(missing),"OUTSIDE-AIR-RATES")["status"]=="INPUT_REQUIRED"
