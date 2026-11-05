import json

from jsonschema import Draft202012Validator

from cad_engine.executable_rulebook import RULEBOOK_ROOT, SANITARY_ROOT, load_rulebook_module, validate_rulebook_module
from cad_engine.sanitary_vent_rulebook import evaluate_sanitary_vent_rulebook


def _snapshot():
    cleanout_types=["HIGHEST_HORIZONTAL_BRANCH","DIRECTION_CHANGE_OVER_45","STACK_BASE","WATER_TEST_ACCESS","BUILDING_EXIT"]
    return {"sanitary":{"traps":[{"fixture_type":"basin","dn_mm":32}],
                          "fixtures":[{"fixture_type":"private_toilet","count":2,"declared_total_dfu":8}],
                          "sizing_segments":[{"segment_kind":"HORIZONTAL_BRANCH","dn_mm":50,"calculated_dfu":6}],
                          "main_horizontal_segments":[{"dn_mm":100,"slope_percent":1,"calculated_dfu":180}],
                          "cleanout_inventory_complete":True,
                          "cleanouts":[{"location_type":kind,"pipe_dn_mm":100,"cleanout_dn_mm":100,"opposite_wall_clearance_mm":450} for kind in cleanout_types],
                          "horizontal_segments":[{"dn_mm":65,"slope_percent":2.0,"velocity_m_s":0.7,"reverse_slope":False}]},
            "vent":{"terminations":[{"horizontal_to_opening_m":3.0,"vertical_above_opening_m":0.0,
                                      "directly_below_opening":False,"wall_exit":False}],
                    "fixture_connections":[{"waste_dn_mm":50,"waste_slope_percent":2.0,
                                             "trap_weir_to_vent_m":1.8}],
                    "sizing_segments":[{"waste_dn_mm":100,"vent_dn_mm":50,"length_m":12}],
                    "stack_sizing_segments":[{"waste_diameter_in":4,"connected_dfu":320,"vent_diameter_in":3,"developed_length_ft":170}]}}


def _row(result, suffix):
    return next(row for row in result["results"] if row["rule_id"].endswith(suffix))


def test_module_strict_schema_integrity_and_real_design_consumers():
    module=load_rulebook_module(SANITARY_ROOT)
    assert validate_rulebook_module(module)["status"]=="PASS"
    schema=json.loads((RULEBOOK_ROOT/"schema"/"executable_rule.schema.json").read_text())
    assert [e for r in module["registry"]["rules"] for e in Draft202012Validator(schema).iter_errors(r)]==[]
    assert len(module["registry"]["rules"])==10
    basis=__import__("app.mechanical_rulebook",fromlist=["network_design_basis"]).network_design_basis()
    assert basis["systems"]["sanitary"]["source_slope_contract"]["minimum_slope_percent"]["dn_le_65"]==2.0
    assert basis["systems"]["sanitary"]["trap_minimum_dn_mm"]["basin"]==32
    assert basis["systems"]["vent"]["trap_vent_distance_rows"]["50@2"]["maximum_m"]==1.8
    assert basis["systems"]["sanitary"]["source_fixture_dfu"]["private_toilet"]==4
    assert basis["systems"]["sanitary"]["source_branch_stack_capacity"]["100"]["stack_over_3_floors"]==500
    assert basis["systems"]["sanitary"]["source_main_horizontal_capacity"]["375"]["0.5"]==7000
    assert basis["systems"]["vent"]["source_vent_minimum_size"]["minimum_dn_mm"]==32
    assert basis["systems"]["vent"]["source_vent_stack_capacity"]["4@320"]["3"]==170
    assert basis["systems"]["vent"]["source_vent_stack_capacity"]["3@10"]["1.5"]==42


def test_all_four_rules_pass_at_exact_boundaries():
    result=evaluate_sanitary_vent_rulebook(_snapshot())
    assert result["status"]=="PASS"
    assert {r["status"] for r in result["results"]}=={"PASS"}


def test_trap_minimum_dn_and_unknown_fixture_fail_closed():
    snap=_snapshot(); snap["sanitary"]["traps"][0]["dn_mm"]=31.99
    assert _row(evaluate_sanitary_vent_rulebook(snap),"TRAP-MIN-DN")["status"]=="FAIL"
    snap=_snapshot(); snap["sanitary"]["traps"][0]["fixture_type"]="unknown"
    assert _row(evaluate_sanitary_vent_rulebook(snap),"TRAP-MIN-DN")["status"]=="INPUT_REQUIRED"


def test_slope_velocity_boundaries_reverse_and_unsupported_dn():
    for field,value in (("slope_percent",1.999),("slope_percent",4.001),("velocity_m_s",0.699)):
        snap=_snapshot(); snap["sanitary"]["horizontal_segments"][0][field]=value
        assert _row(evaluate_sanitary_vent_rulebook(snap),"HORIZONTAL-SLOPE")["status"]=="FAIL"
    snap=_snapshot(); snap["sanitary"]["horizontal_segments"][0]["reverse_slope"]=True
    assert _row(evaluate_sanitary_vent_rulebook(snap),"HORIZONTAL-SLOPE")["status"]=="FAIL"
    snap=_snapshot(); snap["sanitary"]["horizontal_segments"][0]["dn_mm"]=70
    assert _row(evaluate_sanitary_vent_rulebook(snap),"HORIZONTAL-SLOPE")["status"]=="INPUT_REQUIRED"


def test_vent_termination_opening_alternative_and_wall_exit_constraints():
    snap=_snapshot(); term=snap["vent"]["terminations"][0]; term.update({"horizontal_to_opening_m":2.99,"vertical_above_opening_m":1.0})
    assert _row(evaluate_sanitary_vent_rulebook(snap),"VENT-TERMINATION")["status"]=="PASS"
    term["vertical_above_opening_m"]=0.999
    assert _row(evaluate_sanitary_vent_rulebook(snap),"VENT-TERMINATION")["status"]=="FAIL"
    snap=_snapshot(); term=snap["vent"]["terminations"][0]; term.update({"wall_exit":True,"horizontal_to_property_m":3.0,"height_above_ground_m":3.0,"under_balcony_or_canopy":False})
    assert _row(evaluate_sanitary_vent_rulebook(snap),"VENT-TERMINATION")["status"]=="PASS"
    term["under_balcony_or_canopy"]=True
    assert _row(evaluate_sanitary_vent_rulebook(snap),"VENT-TERMINATION")["status"]=="FAIL"


def test_trap_vent_distance_exact_table_only():
    snap=_snapshot(); snap["vent"]["fixture_connections"][0]["trap_weir_to_vent_m"]=1.801
    assert _row(evaluate_sanitary_vent_rulebook(snap),"TRAP-VENT-DISTANCE")["status"]=="FAIL"
    snap=_snapshot(); snap["vent"]["fixture_connections"][0]["waste_slope_percent"]=1.99
    assert _row(evaluate_sanitary_vent_rulebook(snap),"TRAP-VENT-DISTANCE")["status"]=="INPUT_REQUIRED"


def test_fixture_dfu_and_branch_stack_capacity_boundaries():
    snap=_snapshot(); assert _row(evaluate_sanitary_vent_rulebook(snap),"FIXTURE-DFU")["status"]=="PASS"
    snap["sanitary"]["fixtures"][0]["declared_total_dfu"]=7.99
    assert _row(evaluate_sanitary_vent_rulebook(snap),"FIXTURE-DFU")["status"]=="FAIL"
    snap=_snapshot(); assert _row(evaluate_sanitary_vent_rulebook(snap),"BRANCH-STACK-CAPACITY")["status"]=="PASS"
    snap["sanitary"]["sizing_segments"][0]["calculated_dfu"]=6.01
    assert _row(evaluate_sanitary_vent_rulebook(snap),"BRANCH-STACK-CAPACITY")["status"]=="FAIL"
    snap=_snapshot(); snap["sanitary"]["sizing_segments"][0].update({"segment_kind":"HORIZONTAL_BRANCH","dn_mm":125})
    assert _row(evaluate_sanitary_vent_rulebook(snap),"BRANCH-STACK-CAPACITY")["status"]=="INPUT_REQUIRED"


def test_cleanout_completeness_size_clearance_and_spacing():
    snap=_snapshot(); assert _row(evaluate_sanitary_vent_rulebook(snap),"CLEANOUT")["status"]=="PASS"
    snap["sanitary"]["cleanouts"][0]["cleanout_dn_mm"]=99.9
    assert _row(evaluate_sanitary_vent_rulebook(snap),"CLEANOUT")["status"]=="FAIL"
    snap=_snapshot(); snap["sanitary"]["cleanouts"][0]["opposite_wall_clearance_mm"]=449.9
    assert _row(evaluate_sanitary_vent_rulebook(snap),"CLEANOUT")["status"]=="FAIL"
    snap=_snapshot(); snap["sanitary"]["cleanouts"].append({"location_type":"MAIN_HORIZONTAL_INTERVAL","pipe_dn_mm":100,"cleanout_dn_mm":100,"opposite_wall_clearance_mm":450,"distance_from_previous_m":30.01})
    assert _row(evaluate_sanitary_vent_rulebook(snap),"CLEANOUT")["status"]=="FAIL"
    snap=_snapshot(); snap["sanitary"]["cleanout_inventory_complete"]=False
    assert _row(evaluate_sanitary_vent_rulebook(snap),"CLEANOUT")["status"]=="FAIL"


def test_vent_minimum_size_half_waste_minimum_and_length_size_up():
    snap=_snapshot(); assert _row(evaluate_sanitary_vent_rulebook(snap),"VENT-MIN-SIZE")["status"]=="PASS"
    snap["vent"]["sizing_segments"][0]["vent_dn_mm"]=49.9
    assert _row(evaluate_sanitary_vent_rulebook(snap),"VENT-MIN-SIZE")["status"]=="FAIL"
    snap=_snapshot(); snap["vent"]["sizing_segments"][0].update({"length_m":12.01,"vent_dn_mm":65})
    assert _row(evaluate_sanitary_vent_rulebook(snap),"VENT-MIN-SIZE")["status"]=="PASS"
    snap["vent"]["sizing_segments"][0]["vent_dn_mm"]=50
    assert _row(evaluate_sanitary_vent_rulebook(snap),"VENT-MIN-SIZE")["status"]=="FAIL"


def test_main_horizontal_capacity_exact_rows_boundaries_and_unknowns():
    snap=_snapshot(); assert _row(evaluate_sanitary_vent_rulebook(snap),"MAIN-HORIZONTAL-CAPACITY")["status"]=="PASS"
    snap["sanitary"]["main_horizontal_segments"][0]["calculated_dfu"]=180.01
    assert _row(evaluate_sanitary_vent_rulebook(snap),"MAIN-HORIZONTAL-CAPACITY")["status"]=="FAIL"
    snap=_snapshot(); snap["sanitary"]["main_horizontal_segments"][0]["slope_percent"]=1.5
    assert _row(evaluate_sanitary_vent_rulebook(snap),"MAIN-HORIZONTAL-CAPACITY")["status"]=="INPUT_REQUIRED"
    snap=_snapshot(); snap["sanitary"]["main_horizontal_segments"][0]["dn_mm"]=50; snap["sanitary"]["main_horizontal_segments"][0]["slope_percent"]=2
    assert _row(evaluate_sanitary_vent_rulebook(snap),"MAIN-HORIZONTAL-CAPACITY")["status"]=="INPUT_REQUIRED"


def test_vent_stack_capacity_exact_rows_boundaries_and_unknowns():
    snap=_snapshot(); assert _row(evaluate_sanitary_vent_rulebook(snap),"VENT-STACK-CAPACITY")["status"]=="PASS"
    snap["vent"]["stack_sizing_segments"][0]["developed_length_ft"]=170.01
    assert _row(evaluate_sanitary_vent_rulebook(snap),"VENT-STACK-CAPACITY")["status"]=="FAIL"
    snap=_snapshot(); snap["vent"]["stack_sizing_segments"][0]["connected_dfu"]=321
    assert _row(evaluate_sanitary_vent_rulebook(snap),"VENT-STACK-CAPACITY")["status"]=="INPUT_REQUIRED"
    snap=_snapshot(); snap["vent"]["stack_sizing_segments"][0]["developed_length_ft"]=float("nan")
    assert _row(evaluate_sanitary_vent_rulebook(snap),"VENT-STACK-CAPACITY")["status"]=="INPUT_REQUIRED"
    snap=_snapshot(); snap["vent"]["stack_sizing_segments"][0].update({"waste_diameter_in":3,"connected_dfu":10,"vent_diameter_in":1.5,"developed_length_ft":42})
    assert _row(evaluate_sanitary_vent_rulebook(snap),"VENT-STACK-CAPACITY")["status"]=="PASS"
