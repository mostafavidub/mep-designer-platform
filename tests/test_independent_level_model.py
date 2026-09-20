from pathlib import Path

import ezdxf

from cad_engine.independent_level_model_gate import build_independent_level_model, normalize_level_identity


def _source(tmp_path, plan_specs):
    path = tmp_path / "architecture.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for index, spec in enumerate(plan_specs):
        x1, y1, x2, y2 = spec["bounds"]
        msp.add_line((x1+1, y1+1), (x2-1, y1+1), dxfattribs={"layer": "A-WALL"})
        msp.add_line((x1+1, y1+1), (x1+1, y2-1-index*.2), dxfattribs={"layer": "A-WALL"})
        if spec.get("roof"):
            msp.add_circle(((x1+x2)/2, (y1+y2)/2), .4, dxfattribs={"layer": "A-ROOF-DRAIN"})
    doc.saveas(path)
    return path


def _architecture(specs):
    plans=[];rooms=[];shafts=[];detections=[]
    for index,spec in enumerate(specs,1):
        pid=f"PLAN-{index:02d}";roof=bool(spec.get("roof"));bounds=spec["bounds"]
        plans.append({"plan_id":pid,"bounds":bounds,"content_bounds":bounds,
                      "drawing_type":"ROOF_PLAN" if roof else "ARCH_FLOOR_PLAN",
                      "mechanical_role":"ROOF_SUPPORT" if roof else "PRIMARY_FLOOR",
                      "level":spec.get("level"),"represented_levels":spec.get("represented_levels",[])})
        point=(bounds[0]+2,bounds[1]+2)
        if not roof:
            rooms.append({"id":f"ROOM-{index}","plan_id":pid,"label_point":point})
            detections.append({"id":f"EQ-{index}","plan_id":pid,"point":point})
        shafts.append({"id":f"SHAFT-{index}","plan_id":pid,"point":point})
    return {"plans":plans,"rooms":rooms,"shafts":shafts,
            "level_ownership_contract":{"status":"PASS"}},{"detections":detections}


def test_failed_architectural_ownership_contract_cannot_report_pass(tmp_path):
    path=tmp_path/"source.dxf";doc=ezdxf.new("R2013");doc.modelspace().add_line((0,0),(10,10));doc.saveas(path)
    architecture={"plans":[{"plan_id":"P1","bounds":[0,0,10,10],"content_bounds":[0,0,10,10],
                            "drawing_type":"ARCH_FLOOR_PLAN","mechanical_role":"PRIMARY_FLOOR","level":"GROUND"}],
                  "rooms":[],"shafts":[],"level_ownership_contract":{"status":"FAIL"}}
    result=build_independent_level_model(Path(path),architecture,{"detections":[]},unit_to_m=.001)
    assert result["status"]=="FAIL"
    assert "ARCHITECTURAL_LEVEL_OWNERSHIP_UNRESOLVED" in result["errors"]
    assert result["checks"]["authoritative_ownership_contract"] is False


def test_level_identity_normalizes_persian_english_and_roof():
    assert normalize_level_identity("طبقه سوم") == "LEVEL-03"
    assert normalize_level_identity("Level 04") == "LEVEL-04"
    assert normalize_level_identity("زیرزمین ۲") == "BASEMENT-02"
    assert normalize_level_identity("همکف") == "GROUND"
    assert normalize_level_identity("ignored", roof=True) == "ROOF"


def test_builds_independent_floor_and_roof_models_with_vertical_graph(tmp_path):
    specs=[{"bounds":[0,0,20,20],"level":"همکف"},
           {"bounds":[30,0,52,20],"level":"طبقه اول"},
           {"bounds":[60,0,84,20],"level":"بام","roof":True}]
    path=_source(tmp_path,specs);architecture,recognition=_architecture(specs)
    result=build_independent_level_model(path,architecture,recognition,unit_to_m=.001)
    assert result["status"] == "PASS"
    assert result["score"] == 100
    assert len(result["models"]) == 3
    assert result["roof"]["status"] == "CONFIRMED"
    assert result["roof"]["features"]["drain_evidence"]
    assert all(model["entities"] and model["source_transform"]["inverse_required"] for model in result["models"])
    assert len(result["entity_ownership"]) == len(set(result["entity_ownership"]))
    assert result["vertical_graph"]["nodes"]


def test_overlapping_frames_fail_multiple_entity_ownership(tmp_path):
    specs=[{"bounds":[0,0,20,20],"level":"همکف"},{"bounds":[10,0,30,20],"level":"طبقه اول"}]
    path=_source(tmp_path,specs);architecture,recognition=_architecture(specs)
    result=build_independent_level_model(path,architecture,recognition,unit_to_m=.001)
    assert result["status"] == "FAIL"
    assert any(error.startswith("MULTIPLE_ENTITY_OWNER") for error in result["errors"])
    assert result["checks"]["unique_entity_ownership"] is False


def test_non_typical_duplicate_geometry_fails_closed(tmp_path):
    specs=[{"bounds":[0,0,20,20],"level":"همکف"},{"bounds":[30,0,50,20],"level":"طبقه اول"}]
    path=_source(tmp_path,specs);architecture,recognition=_architecture(specs)
    # Make normalized geometry exactly identical by removing the per-index variation.
    doc=ezdxf.new("R2010");msp=doc.modelspace()
    for x in (0,30):
        msp.add_line((x+1,1),(x+19,1),dxfattribs={"layer":"A-WALL"})
        msp.add_line((x+1,1),(x+1,19),dxfattribs={"layer":"A-WALL"})
    doc.saveas(path)
    result=build_independent_level_model(path,architecture,recognition,unit_to_m=.001)
    assert result["status"] == "FAIL"
    assert any(error.startswith("UNAPPROVED_DUPLICATE_LEVEL_GEOMETRY") for error in result["errors"])


def test_explicit_single_typical_model_represents_multiple_levels(tmp_path):
    specs=[{"bounds":[0,0,20,20],"level":"طبقه اول","represented_levels":["طبقه اول","طبقه دوم","طبقه سوم"]}]
    path=_source(tmp_path,specs);architecture,recognition=_architecture(specs)
    result=build_independent_level_model(path,architecture,recognition,unit_to_m=.001)
    assert result["status"] == "PASS"
    assert result["models"][0]["kind"] == "TYPICAL_FLOOR"
    assert result["models"][0]["represented_level_ids"] == ["LEVEL-01","LEVEL-02","LEVEL-03"]


def test_unknown_unit_or_level_is_input_required_not_guessed(tmp_path):
    specs=[{"bounds":[0,0,20,20],"level":None}]
    path=_source(tmp_path,specs);architecture,recognition=_architecture(specs)
    result=build_independent_level_model(path,architecture,recognition,unit_to_m=None)
    assert result["status"] == "INPUT_REQUIRED"
    assert "CALIBRATED_ARCHITECTURAL_UNIT_REQUIRED" in result["missing_inputs"]
    assert any(item.startswith("LEVEL_ID_REQUIRED") for item in result["missing_inputs"])


def test_roof_role_cannot_fabricate_roof_from_floor_drawing(tmp_path):
    specs=[{"bounds":[0,0,20,20],"level":"بام"}]
    path=_source(tmp_path,specs);architecture,recognition=_architecture(specs)
    architecture["plans"][0]["mechanical_role"]="ROOF_SUPPORT"
    architecture["plans"][0]["drawing_type"]="ARCH_FLOOR_PLAN"
    result=build_independent_level_model(path,architecture,recognition,unit_to_m=.001)
    assert result["status"] == "FAIL"
    assert "FABRICATED_OR_UNCONFIRMED_ROOF_MODEL" in result["errors"]


def test_fingerprints_and_ownership_are_deterministic(tmp_path):
    specs=[{"bounds":[0,0,20,20],"level":"همکف"}]
    path=_source(tmp_path,specs);architecture,recognition=_architecture(specs)
    first=build_independent_level_model(path,architecture,recognition,unit_to_m=.001)
    second=build_independent_level_model(path,architecture,recognition,unit_to_m=.001)
    assert first["source_sha256"] == second["source_sha256"]
    assert first["models"] == second["models"]
    assert first["entity_ownership"] == second["entity_ownership"]


def test_objects_on_explicitly_excluded_views_do_not_pollute_floor_models(tmp_path):
    specs=[{"bounds":[0,0,20,20],"level":"همکف"}]
    path=_source(tmp_path,specs);architecture,recognition=_architecture(specs)
    architecture["plans"].append({"plan_id":"SECTION-01","bounds":[30,0,50,20],
                                  "drawing_type":"SECTION","mechanical_role":"EXCLUDE"})
    architecture["shafts"].append({"id":"SECTION-SHAFT","plan_id":"SECTION-01","point":(35,5)})
    result=build_independent_level_model(path,architecture,recognition,unit_to_m=.001)
    assert result["status"] == "PASS"
    assert result["checks"]["shaft_level_binding"] is True
    assert result["excluded_source_plan_ids"] == ["SECTION-01"]
    assert "SECTION-SHAFT" not in result["models"][0]["shaft_ids"]
