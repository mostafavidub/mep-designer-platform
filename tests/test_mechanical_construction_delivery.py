import json
from pathlib import Path

from cad_engine.mechanical_pipeline_construction_delivery import build_construction_delivery


def payload():
    catalogue_id="MFR-OFFICIAL-1"
    detail={"status":"PASS","detail":{"detail_id":"DT-RAD-1","family":"radiator_connection",
      "identity":{"source_plan_id":"M-131","source_pmm_id":"PMM-RAD-1","source_calc_id":"CALC-RAD-1",
                  "manufacturer_catalogue_id":catalogue_id}},
      "qa":{"label_only":False,"source_identity_complete":True,"manufacturer_confirmed":True}}
    required=["BLOCK","DIMENSION","HATCH","LEADER","CALLOUT","SECTION_MARKER","DETAIL_MARKER",
              "EQUIPMENT_SYMBOL","FITTING_SYMBOL","REDUCER_SYMBOL"]
    return {"details":[detail],"plan_detail_references":[{"detail_id":"DT-RAD-1","source_plan_id":"M-131"}],
      "manufacturer_database":{"records":[{"catalogue_id":catalogue_id}]},
      "required_cad_entity_types":required,"cad_inventory":{key:1 for key in required},
      "manifest_sheets":[{"code":"M-001","title":"DRAWING INDEX","revision":"R1","status":"FINAL"},
                         {"code":"M-131","title":"HEATING PLAN","revision":"R1","status":"FINAL"}],
      "dxf_layouts":["M-001","M-131"],
      "equipment_schedule":[{"tag":"RAD-1","level":"طبقه اول","room":"اتاق ۱","type":"Radiator",
        "manufacturer":"Official","model":"R500","capacity":"1950 W","flow":"0.047 L/s",
        "power":"N/A","connection_size":"DN16","status":"PASS"}],
      "annotation_solver":{"plan":{"plan_id":"M-131","bounds":[0,0,500,300],"print_scale":10,"obstacles":[]},
        "requests":[{"id":"A1","text":"RAD-1 DN16","target":[100,100],"priority":10,"source_id":"RAD-1"}],
        "config":{"minimum_text_height_mm":2.5,"clearance_model_units":5,"candidate_offsets":[[10,10]],
                  "auto_enlarge":True,"enlarged_scale":"1:20"}}}


def test_steps_14_19_construction_delivery_passes_as_one_final_package():
    result=build_construction_delivery(payload())
    assert result["status"]=="PASS",result
    assert result["release_allowed"]
    assert result["phases"]["drawing_index"]["identity"]=="manifest sheets == index sheets == DXF layouts"
    assert result["phases"]["annotations"]["quality"]["unreadable"]==0
    assert result["phases"]["annotations"]["quality"]["leader_crossings"]==0


def test_steps_14_19_semantic_golden_regression():
    result=build_construction_delivery(payload())
    actual={"schema":"mechanical-construction-delivery/1","status":result["status"],
      "release_allowed":result["release_allowed"],
      "phase_statuses":{key:value["status"] for key,value in sorted(result["phases"].items())},
      "drawing_index_identity":result["phases"]["drawing_index"]["identity"],
      "required_schedule_columns":result["phases"]["equipment_schedule"]["columns"],
      "submission_policy":"all required evidence is explicit; missing evidence is never assumed zero"}
    expected=json.loads((Path(__file__).parents[1]/"standards/golden/mechanical-steps-14-19.baseline.json").read_text())
    assert actual==expected


def test_missing_cad_primitive_and_unreferenced_detail_fail_closed():
    value=payload(); value["cad_inventory"]["DIMENSION"]=0
    assert build_construction_delivery(value)["status"]=="INPUT_REQUIRED"
    value=payload(); value["plan_detail_references"]=[]
    assert build_construction_delivery(value)["status"]=="FAIL"


def test_manifest_layout_mismatch_and_internal_schedule_level_fail():
    value=payload(); value["dxf_layouts"].append("M-999")
    assert build_construction_delivery(value)["status"]=="FAIL"
    value=payload(); value["equipment_schedule"][0]["level"]="LEVEL-ID-01"
    assert build_construction_delivery(value)["status"]=="FAIL"


def test_dense_annotations_create_source_bound_enlarged_view():
    value=payload(); value["annotation_solver"]["plan"]["obstacles"]=[[0,0,500,300]]
    result=build_construction_delivery(value)
    assert result["status"]=="PASS",result
    view=result["phases"]["annotations"]["enlarged_plans"][0]
    assert view["source_plan_id"]=="M-131"


def test_missing_schedule_field_and_unknown_catalogue_identity_do_not_pass():
    value=payload(); value["equipment_schedule"][0].pop("power")
    assert build_construction_delivery(value)["status"]=="INPUT_REQUIRED"
    value=payload(); value["details"][0]["detail"]["identity"]["manufacturer_catalogue_id"]="UNKNOWN"
    assert build_construction_delivery(value)["status"]=="FAIL"
