from cad_engine.mechanical_execution_sizing import (
    design_sanitary_main_from_rulebook, design_sanitary_branch_stack_from_rulebook,
    design_vent_stack_from_rulebook, validate_sanitary_cleanouts_from_rulebook,
    design_vent_routes_from_rulebook, evaluate_vent_geometry_from_rulebook,
)
from cad_engine.sanitary_vent_rulebook import materialize_vent_plan_riser_schedule
import ezdxf


def test_exact_fixture_dfu_and_slope_row_select_smallest_compliant_main_dn():
    result = design_sanitary_main_from_rulebook(
        [{"id": "S-MAIN", "downstream_fixture_ids": ["WC-1", "B-1"], "slope_percent": 2}],
        [{"id": "WC-1", "fixture_dfu_type": "private_toilet", "count": 10},
         {"id": "B-1", "fixture_dfu_type": "basin", "count": 3}],
    )
    assert result["status"] == "PASS", result
    row = result["segments"][0]
    assert row["calculated_dfu"] == 43
    assert row["selected_dn_mm"] == 100
    assert row["capacity_rule_id"] == "IR-M16-1396-APP3-MAIN-HORIZONTAL-CAPACITY"
    assert row["fixture_dfu_rule_id"] == "IR-M16-1396-APP3-FIXTURE-DFU"


def test_non_tabulated_slope_and_unknown_fixture_are_input_required():
    fixtures = [{"id": "WC-1", "fixture_dfu_type": "private_toilet", "count": 1}]
    slope = design_sanitary_main_from_rulebook(
        [{"id": "S-1", "downstream_fixture_ids": ["WC-1"], "slope_percent": 1.5}], fixtures)
    assert slope["status"] == "INPUT_REQUIRED"
    assert slope["missing_inputs"] == ["S-1:exact_supported_slope_row:1.5"]

    unknown = design_sanitary_main_from_rulebook(
        [{"id": "S-1", "downstream_fixture_ids": ["X"], "slope_percent": 2}],
        [{"id": "X", "fixture_dfu_type": "invented", "count": 1}])
    assert unknown["status"] == "INPUT_REQUIRED"
    assert unknown["missing_inputs"] == ["fixtures[0].supported_fixture_dfu_type"]


def test_overcapacity_and_drawing_dn_mismatch_fail():
    too_large = design_sanitary_main_from_rulebook(
        [{"id": "S-1", "downstream_fixture_ids": ["WC"], "slope_percent": 4}],
        [{"id": "WC", "fixture_dfu_type": "public_toilet", "count": 3000}])
    assert too_large["status"] == "FAIL"
    assert too_large["errors"] == ["S-1:capacity_exceeded"]

    mismatch = design_sanitary_main_from_rulebook(
        [{"id": "S-1", "downstream_fixture_ids": ["WC"], "slope_percent": 2,
          "drawing_dn_mm": 80}],
        [{"id": "WC", "fixture_dfu_type": "private_toilet", "count": 20}])
    assert mismatch["status"] == "FAIL"
    assert mismatch["errors"] == ["S-1:drawing_dn_mismatch"]


def test_branch_and_stack_capacity_select_exact_smallest_dn():
    result = design_sanitary_branch_stack_from_rulebook(
        [{"id":"STACK-1","segment_kind":"STACK_OVER_3_FLOORS","downstream_fixture_ids":["WC"]}],
        [{"id":"WC","fixture_dfu_type":"public_toilet","count":20}])
    assert result["status"] == "PASS"
    assert result["segments"][0]["calculated_dfu"] == 120
    assert result["segments"][0]["selected_dn_mm"] == 100
    assert result["segments"][0]["rule_id"] == "IR-M16-1396-APP3-BRANCH-STACK-CAPACITY"


def test_vent_stack_selects_exact_row_and_rejects_unknown_or_overlength():
    result=design_vent_stack_from_rulebook([{"id":"V-1","waste_diameter_in":4,"connected_dfu":320,"developed_length_ft":170}])
    assert result["status"] == "PASS"
    assert result["segments"][0]["selected_vent_diameter_in"] == 3
    unknown=design_vent_stack_from_rulebook([{"id":"V-X","waste_diameter_in":4,"connected_dfu":321,"developed_length_ft":10}])
    assert unknown["status"] == "INPUT_REQUIRED"
    over=design_vent_stack_from_rulebook([{"id":"V-2","waste_diameter_in":2,"connected_dfu":20,"developed_length_ft":151}])
    assert over["status"] == "FAIL"


def test_cleanout_complete_inventory_positive_and_destructive_cases():
    required=["HIGHEST_HORIZONTAL_BRANCH","DIRECTION_CHANGE_OVER_45","STACK_BASE","WATER_TEST_ACCESS","BUILDING_EXIT"]
    rows=[{"location_type":kind,"pipe_dn_mm":100,"cleanout_dn_mm":100,"opposite_wall_clearance_mm":450} for kind in required]
    rows.append({"location_type":"MAIN_HORIZONTAL_INTERVAL","pipe_dn_mm":150,"cleanout_dn_mm":100,"opposite_wall_clearance_mm":500,"distance_from_previous_m":30})
    passed=validate_sanitary_cleanouts_from_rulebook(rows,True)
    assert passed["status"] == "PASS" and passed["calc_id"].startswith("CALC-CLEANOUT-")
    rows[-1]["distance_from_previous_m"]=30.01
    failed=validate_sanitary_cleanouts_from_rulebook(rows,True)
    assert failed["status"] == "FAIL" and "CLEANOUT_SPACING_HIGH:5" in failed["errors"]
    assert validate_sanitary_cleanouts_from_rulebook(rows,False)["status"] == "FAIL"


def test_vent_minimum_dn_length_step_and_exact_geometry_rules():
    sized=design_vent_routes_from_rulebook([{"id":"VR-1","waste_dn_mm":100,"length_m":12.01,"plan_path":[[0,0],[2,0]],"riser_levels":[0,3,6]}])
    assert sized["status"] == "PASS" and sized["routes"][0]["selected_vent_dn_mm"] == 65
    geometry=evaluate_vent_geometry_from_rulebook(
        [{"waste_dn_mm":50,"waste_slope_percent":2,"trap_to_vent_path":[[0,0],[1,0],[1,0.8]]}],
        [{"point_xyz":[0,0,4],"opening_points_xyz":[[2,0,2.5]],"wall_exit":False}])
    assert geometry["status"] == "PASS",geometry
    too_far=evaluate_vent_geometry_from_rulebook(
        [{"waste_dn_mm":50,"waste_slope_percent":2,"trap_to_vent_path":[[0,0],[1.81,0]]}],
        [{"point_xyz":[0,0,4],"opening_points_xyz":[[3,0,4]],"wall_exit":False}])
    assert too_far["status"] == "FAIL" and "TRAP_VENT_DISTANCE_HIGH:0" in too_far["errors"]


def test_vent_plan_riser_schedule_exact_dxf_reopen(tmp_path):
    sized=design_vent_routes_from_rulebook([{"id":"VR-1","waste_dn_mm":100,"length_m":12,"plan_path":[[0,0],[2,0],[2,3]],"riser_levels":[0,3,6]}])
    doc=ezdxf.new("R2010");materialized=materialize_vent_plan_riser_schedule(doc,sized)
    assert materialized["status"] == "PASS"
    path=tmp_path/"vent-rulebook.dxf";doc.saveas(path);reopened=ezdxf.readfile(path);msp=reopened.modelspace()
    assert len(list(msp.query('LWPOLYLINE[layer=="PLANHA-M-VENT-PLAN"]')))==1
    assert len(list(msp.query('LINE[layer=="PLANHA-M-VENT-RISER"]')))==1
    labels=[e.dxf.text for e in msp.query('TEXT[layer=="PLANHA-M-VENT-SCHEDULE"]')]
    assert sized["routes"][0]["calc_id"] in labels[0] and "DN50" in labels[0]
