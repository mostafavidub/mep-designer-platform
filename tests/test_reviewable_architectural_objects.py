from cad_engine.architectural_space_engine import _reviewable_architectural_objects


def test_window_and_stair_are_typed_objects_without_design_authority():
    openings={"items":[{
        "opening_evidence_id":"OPEN-W1","kind":"window","view_scope":"PLAN_VIEW",
        "frame_id":"F1","status":"CANDIDATE","geometry":{"bounds":[0,0,1,.2]},
        "source_refs":["A","B"],"evidence":{"detection_path":"STRICT_TWO_FACE_SUPPORT"},
    }]}
    stairs={
        "flight_samples":[{"stair_flight_id":"SF1","source_refs":["C","D"]}],
        "items":[{"stair_assembly_id":"SA1","frame_id":"F1","flight_ids":["SF1"],
                  "geometry":{"bounds":[2,2,4,6]}}],
    }
    result=_reviewable_architectural_objects(openings,stairs)
    assert [(row["object_type"],row["architectural_object_id"]) for row in result["items"]] == [
        ("STAIR","SA1"),("WINDOW","WINDOW-W1")]
    window=result["items"][1]
    assert window["status"]=="SUPPORTED"
    assert window["source_refs"]==["A","B"]
    assert window["authority"]["portal"] is False
    stair=result["items"][0]
    assert stair["source_refs"]==["C","D"]
    assert stair["authority"]["code_compliance"] is False


def test_non_plan_window_is_not_promoted_to_reviewable_plan_object():
    openings={"items":[{"opening_evidence_id":"OPEN-X","kind":"window",
                         "view_scope":"NON_PLAN_VIEW"}]}
    assert _reviewable_architectural_objects(openings,{"items":[],"flight_samples":[]})["items"]==[]
