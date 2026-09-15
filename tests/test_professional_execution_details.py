from copy import deepcopy

from cad_engine.professional_execution_details import build_execution_detail, evaluate_execution_details


def _context():
    identity={"source_plan_id":"PLAN-L1","source_pmm_id":"PMM-FIX-1","source_calc_id":"CALC-1","owner_id":"EDGE-1","schedule_row_id":"SCH-1"}
    detail={
        "detail_id":"DT-1","family":"sanitary_connection","system":"sanitary","identity":identity,
        "parameters":{"pipe_dn_mm":75,"slope_percent":2,"trap":"P-TRAP","vent":"CONNECTED","cleanout":"ACCESSIBLE"},
        "geometry":{"entity_count":12,"primitives":["LINE","ARC","DIMENSION","LEADER"]},
        "dimensions":[{"parameter":"pipe_dn_mm","value":75,"unit":"mm"},{"parameter":"slope_percent","value":2,"unit":"percent"}],
        "installation_components":["pipe","trap","cleanout","vent","sleeve"],"assembly_sequence":["sleeve","pipe","trap","test"],
        "constructability":{"supports":"SPACING_CALCULATED","anchors":"HOST_VERIFIED","penetration":"LOCATED","sleeve":"SIZED","firestop":"RATED","insulation":"NOT_APPLICABLE","corrosion_protection":"SPECIFIED","service_clearance_mm":450,"access_path":"SHOWN","flow_direction":"SHOWN","slope_status":"SHOWN","coordination_status":"PASS","clashes":[]},
        "callout":{"detail_id":"DT-1","source_plan_id":"PLAN-L1","bidirectional":True},
        "standards":[{"standard":"PROJECT_RULE_BOOK","revision":"CURRENT","clause":"SANITARY_CONNECTION"}],
        "print_qa":{"status":"PASS","minimum_text_height_mm":2.5,"clipped":False,"overlaps":False},
    }
    return {"requirements":[{"system":"sanitary","family":"sanitary_connection","required_ids":["DT-1"]}],"details":[detail],
            "calculation_rows":[{"calc_id":"CALC-1","pipe_dn_mm":75,"slope_percent":2}],
            "schedule_rows":[{"schedule_row_id":"SCH-1","pipe_dn_mm":75,"slope_percent":2}],
            "plan_callouts":[detail["callout"]]}


def test_complete_execution_detail_scores_100_only_with_exact_entities():
    report=evaluate_execution_details(_context(),{"reopened":True,"immutable":True,"executable_detail_ids":["DT-1"]})
    assert report["status"] == "PASS" and report["score"] == 100 and report["release_allowed"] is True


def test_builder_refuses_to_invent_missing_project_parameters():
    result=build_execution_detail({"family":"sanitary_connection","identity":{},"parameters":{}})
    assert result["status"] == "INPUT_REQUIRED" and "parameters.pipe_dn_mm" in result["missing_inputs"]


def test_label_only_exact_output_cannot_pass():
    report=evaluate_execution_details(_context(),{"reopened":True,"immutable":True,"executable_detail_ids":[]})
    assert report["status"] == "FAIL" and report["release_allowed"] is False


def test_parameter_tamper_and_orphan_callout_are_detected_independently():
    context=deepcopy(_context()); context["details"][0]["parameters"]["pipe_dn_mm"]=90
    context["plan_callouts"][0]["bidirectional"]=False
    report=evaluate_execution_details(context,{"reopened":True,"immutable":True,"executable_detail_ids":["DT-1"]})
    assert "DT-1:pipe_dn_mm" in report["errors"]
    assert "DT-1:CALLOUT_MISMATCH" in report["errors"]


def test_constructability_and_print_self_assertions_are_destructively_checked():
    context=deepcopy(_context()); detail=context["details"][0]
    detail["constructability"]["service_clearance_mm"]=0
    detail["constructability"]["clashes"]=["BEAM-1"]
    detail["print_qa"]["overlaps"]=True
    report=evaluate_execution_details(context,{"reopened":True,"immutable":True,"executable_detail_ids":["DT-1"]})
    assert report["status"] == "FAIL" and report["score"] < 100
