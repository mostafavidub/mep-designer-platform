import json
from pathlib import Path
import pytest

from app.mechanical_rulebook import network_design_basis
from cad_engine.executable_rulebook import GAS_ROOT, load_rulebook_module, validate_rulebook_module
from cad_engine.gas_rulebook import evaluate_gas_rulebook

ROOT=Path(__file__).resolve().parents[1]

def _snapshot(height=180,location="NORMAL",wire=10,electric_meter=50,appliance=1):
    return {"gas":{"meter_inventory_complete":True,"meters":[{"location_class":location,
        "replacement_pipe_height_cm":height,"clearance_to_live_electric_wire_cm":wire,
        "clearance_to_electric_meter_cm":electric_meter,"clearance_to_gas_appliance_m":appliance}]}}

def _row(result,suffix):return next(r for r in result["results"] if r["rule_id"].endswith(suffix))

def test_gas_module_integrity_and_strict_schema():
    module=load_rulebook_module(GAS_ROOT);assert validate_rulebook_module(module)["status"]=="PASS"
    validator=pytest.importorskip("jsonschema").Draft202012Validator(json.loads((ROOT/"data/rulebook/schema/executable_rule.schema.json").read_text()))
    assert len(module["registry"]["rules"])==6
    assert all(not list(validator.iter_errors(rule)) for rule in module["registry"]["rules"])

def test_gas_design_consumer_receives_source_geometry_without_new_fake_table():
    gas=network_design_basis()["systems"]["gas"]
    assert gas["source_meter_height"]["normal_minimum_height_cm"]==180
    assert gas["source_meter_clearances"]["minimum_gas_appliance_clearance_m"]==1
    assert gas["source_rulebook_authority"]=="M17-1403"

@pytest.mark.parametrize("height",[180,240])
def test_normal_meter_height_inclusive_boundaries(height):
    assert _row(evaluate_gas_rulebook(_snapshot(height=height)),"GAS-METER-HEIGHT")["status"]=="PASS"

def test_normal_and_parking_height_violations_fail():
    assert _row(evaluate_gas_rulebook(_snapshot(height=179.99)),"GAS-METER-HEIGHT")["status"]=="FAIL"
    assert _row(evaluate_gas_rulebook(_snapshot(height=219.99,location="PARKING_OR_VEHICLE_TRAFFIC")),"GAS-METER-HEIGHT")["status"]=="FAIL"
    assert _row(evaluate_gas_rulebook(_snapshot(height=220,location="PARKING_OR_VEHICLE_TRAFFIC")),"GAS-METER-HEIGHT")["status"]=="PASS"

def test_clearance_exact_boundaries_pass_and_each_below_limit_fails():
    assert _row(evaluate_gas_rulebook(_snapshot()),"GAS-METER-CLEARANCES")["status"]=="PASS"
    for kwargs,code in [({"wire":9.99},"GAS_METER_ELECTRIC_WIRE_CLEARANCE_LOW:0"),
                        ({"electric_meter":49.99},"GAS_METER_ELECTRIC_METER_CLEARANCE_LOW:0"),
                        ({"appliance":.99},"GAS_METER_GAS_APPLIANCE_CLEARANCE_LOW:0")]:
        row=_row(evaluate_gas_rulebook(_snapshot(**kwargs)),"GAS-METER-CLEARANCES")
        assert row["status"]=="FAIL" and code in row["errors"]

def test_missing_nonfinite_unknown_and_incomplete_fail_closed():
    row=_snapshot();row["gas"]["meters"][0].pop("clearance_to_electric_meter_cm")
    assert _row(evaluate_gas_rulebook(row),"GAS-METER-CLEARANCES")["status"]=="INPUT_REQUIRED"
    assert _row(evaluate_gas_rulebook(_snapshot(height=float("nan"))),"GAS-METER-HEIGHT")["status"]=="INPUT_REQUIRED"
    assert _row(evaluate_gas_rulebook(_snapshot(location="UNKNOWN")),"GAS-METER-HEIGHT")["status"]=="INPUT_REQUIRED"
    row=_snapshot();row["gas"]["meter_inventory_complete"]=False
    assert evaluate_gas_rulebook(row)["status"]=="INPUT_REQUIRED"

def test_complete_empty_inventory_is_not_applicable_missing_is_unknown():
    result=evaluate_gas_rulebook({"gas":{"meter_inventory_complete":True,"meters":[],
        "combustion_air_space_inventory_complete":True,"combustion_air_spaces":[],
        "flue_design_inventory_complete":True,"flue_designs":[],
        "combustion_air_opening_inventory_complete":True,"combustion_air_openings":[],
        "combustion_air_duct_inventory_complete":True,"combustion_air_ducts":[]}})
    assert {r["status"] for r in result["results"]}=={"NOT_APPLICABLE"}
    assert evaluate_gas_rulebook({"gas":{}})["status"]=="INPUT_REQUIRED"

def _full_snapshot(**combustion):
    row=_snapshot(); row["gas"].update({
        "combustion_air_space_inventory_complete":True,
        "combustion_air_spaces":[{"selected_method":"KNOWN_ACH_ROOM_VOLUME",
            "room_volume_m3":6.716666667,"ach":0.6,"nonfan_input_kcal_h":1000,
            "fan_input_kcal_h":1000,**combustion}],
        "flue_design_inventory_complete":True,
        "flue_designs":[{"appliance_id":"BOILER-1","diameter_mm":150,"material":"approved metal",
            "route_polyline":[[0,0],[0,3]],"capacity_calculation_id":"FLUE-CALC-1",
            "capacity_calculation_status":"ENGINEER_APPROVED"}],
        "combustion_air_opening_inventory_complete":True,
        "combustion_air_openings":[{"grille_material":"METAL_GRILLE","gross_area_mm2":20000,
            "declared_free_area_mm2":15000,"required_free_area_mm2":15000,
            "louver_min_dimension_mm":7,"takes_air_directly_from_outdoors":True,
            "outdoor_inlet_bottom_above_ground_mm":300}],
        "combustion_air_duct_inventory_complete":True,
        "combustion_air_ducts":[{"shape":"RECTANGULAR","free_area_mm2":15000,
            "connected_opening_free_area_mm2":15000,"minimum_side_mm":80,
            "served_room_ids":["ROOM-1"],"served_opening_roles":["LOW"]}]})
    return row

def test_combustion_air_formula_exact_boundary_and_mixed_load_consumed():
    result=_row(evaluate_gas_rulebook(_full_snapshot()),"COMBUSTION-AIR-KNOWN-ACH")
    assert result["status"]=="PASS"
    gas=network_design_basis()["systems"]["gas"]
    assert gas["source_combustion_air_known_ach"]["nonfan_m3_per_1000_kcal_h"]==2.35
    assert gas["source_combustion_air_known_ach"]["fan_m3_per_1000_kcal_h"]==1.68

def test_combustion_air_below_volume_or_ach_fails_and_missing_is_unknown():
    assert _row(evaluate_gas_rulebook(_full_snapshot(room_volume_m3=6.70)),
                "COMBUSTION-AIR-KNOWN-ACH")["status"]=="FAIL"
    assert _row(evaluate_gas_rulebook(_full_snapshot(ach=.59)),
                "COMBUSTION-AIR-KNOWN-ACH")["status"]=="FAIL"
    row=_full_snapshot();row["gas"]["combustion_air_spaces"][0].pop("fan_input_kcal_h")
    assert _row(evaluate_gas_rulebook(row),"COMBUSTION-AIR-KNOWN-ACH")["status"]=="INPUT_REQUIRED"

def test_alternate_combustion_air_method_requires_bound_evidence():
    row=_full_snapshot();space=row["gas"]["combustion_air_spaces"][0]
    space["selected_method"]="OTHER_M17_COMBUSTION_AIR_METHOD";space["alternate_method_evidence_id"]="M17-METHOD-2-CALC"
    assert _row(evaluate_gas_rulebook(row),"COMBUSTION-AIR-KNOWN-ACH")["status"]=="NOT_APPLICABLE"
    space.pop("alternate_method_evidence_id")
    assert _row(evaluate_gas_rulebook(row),"COMBUSTION-AIR-KNOWN-ACH")["status"]=="INPUT_REQUIRED"

def test_flue_documentation_requires_real_route_and_approved_calculation():
    assert _row(evaluate_gas_rulebook(_full_snapshot()),"FLUE-DESIGN-DOCUMENTATION")["status"]=="PASS"
    row=_full_snapshot();row["gas"]["flue_designs"][0]["route_polyline"]=[[0,0]]
    assert _row(evaluate_gas_rulebook(row),"FLUE-DESIGN-DOCUMENTATION")["status"]=="INPUT_REQUIRED"

def test_combustion_air_opening_exact_geometry_boundaries_and_consumer():
    assert _row(evaluate_gas_rulebook(_full_snapshot()),"COMBUSTION-AIR-OPENING-GEOMETRY")["status"]=="PASS"
    gas=network_design_basis()["systems"]["gas"]
    assert gas["source_combustion_air_openings"]["metal_max_free_area_fraction"]==.75
    assert gas["source_combustion_air_openings"]["minimum_outdoor_inlet_bottom_above_ground_mm"]==300

def test_combustion_air_opening_rejects_overstated_or_insufficient_free_area():
    row=_full_snapshot();row["gas"]["combustion_air_openings"][0]["declared_free_area_mm2"]=15001
    assert _row(evaluate_gas_rulebook(row),"COMBUSTION-AIR-OPENING-GEOMETRY")["status"]=="FAIL"
    row=_full_snapshot();row["gas"]["combustion_air_openings"][0].update(declared_free_area_mm2=14999,required_free_area_mm2=15000)
    assert _row(evaluate_gas_rulebook(row),"COMBUSTION-AIR-OPENING-GEOMETRY")["status"]=="FAIL"

def test_combustion_air_opening_louver_and_outdoor_height_boundaries():
    row=_full_snapshot();opening=row["gas"]["combustion_air_openings"][0];opening["louver_min_dimension_mm"]=6.99
    assert _row(evaluate_gas_rulebook(row),"COMBUSTION-AIR-OPENING-GEOMETRY")["status"]=="FAIL"
    row=_full_snapshot();row["gas"]["combustion_air_openings"][0]["outdoor_inlet_bottom_above_ground_mm"]=299.99
    assert _row(evaluate_gas_rulebook(row),"COMBUSTION-AIR-OPENING-GEOMETRY")["status"]=="FAIL"

def test_combustion_air_duct_exact_boundaries_and_dedicated_scope():
    assert _row(evaluate_gas_rulebook(_full_snapshot()),"COMBUSTION-AIR-DUCT-GEOMETRY")["status"]=="PASS"
    row=_full_snapshot();row["gas"]["combustion_air_ducts"][0]["free_area_mm2"]=9999
    assert _row(evaluate_gas_rulebook(row),"COMBUSTION-AIR-DUCT-GEOMETRY")["status"]=="FAIL"
    row=_full_snapshot();row["gas"]["combustion_air_ducts"][0]["minimum_side_mm"]=79.99
    assert _row(evaluate_gas_rulebook(row),"COMBUSTION-AIR-DUCT-GEOMETRY")["status"]=="FAIL"
    row=_full_snapshot();row["gas"]["combustion_air_ducts"][0]["served_opening_roles"]=["HIGH","LOW"]
    assert _row(evaluate_gas_rulebook(row),"COMBUSTION-AIR-DUCT-GEOMETRY")["status"]=="FAIL"

def test_combustion_air_opening_and_duct_missing_data_fail_closed():
    row=_full_snapshot();row["gas"]["combustion_air_openings"][0].pop("grille_material")
    assert _row(evaluate_gas_rulebook(row),"COMBUSTION-AIR-OPENING-GEOMETRY")["status"]=="INPUT_REQUIRED"
    row=_full_snapshot();row["gas"]["combustion_air_ducts"][0].pop("connected_opening_free_area_mm2")
    assert _row(evaluate_gas_rulebook(row),"COMBUSTION-AIR-DUCT-GEOMETRY")["status"]=="INPUT_REQUIRED"
    row=_full_snapshot();row["gas"]["flue_designs"][0]["capacity_calculation_status"]="DRAFT"
    assert _row(evaluate_gas_rulebook(row),"FLUE-DESIGN-DOCUMENTATION")["status"]=="INPUT_REQUIRED"
