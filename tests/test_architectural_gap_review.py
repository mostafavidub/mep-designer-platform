from copy import deepcopy

from cad_engine.architectural_gap_review import apply_review_decisions, build_review_manifest, validate_review_decisions


def _inputs(geometry=((1,2),(3,4))):
    gaps=[{"gap_id":"G1","closure_id":"C1","host_wall_ids":["W1"],"geometry":geometry,
           "gap_width":.2,"local_wall_thickness":.1,"classification":"AMBIGUOUS_GAP",
           "status":"INPUT_REQUIRED","source_handles":["A"],"portal_evidence_ids":[]}]
    walls=[{"wall_id":"W1","status":"SUPPORTED_PARTITION","representation":"SINGLE_LINE",
            "source_handles":["A"]}]
    return gaps,walls


def _manifest(geometry=((1,2),(3,4))):
    gaps,walls=_inputs(geometry)
    return build_review_manifest(source_sha256="a"*64,frame_id="F1",dependency_engine_sha="b"*40,
                                 gaps=gaps,walls=walls)


def _decision(question,answer="DOOR"):
    keys=("question_id","source_sha256","frame_id","dependency_engine_sha","gap_id","closure_id",
          "host_wall_ids","gap_geometry_hash","evidence_hash","question_version")
    return {**{key:question[key] for key in keys},"decision":answer}


def test_review_identity_is_deterministic_and_geometry_reversal_invariant():
    assert _manifest()["review_fingerprint"]==_manifest(((3,4),(1,2)))["review_fingerprint"]


def test_valid_decision_replays_without_material_or_access_authority():
    current=_manifest();supplied=deepcopy(current)
    supplied["decisions"]=[_decision(current["questions"][0],"WINDOW")]
    result=validate_review_decisions(supplied,current)
    assert len(result["accepted_review_decisions"])==1
    assert current["questions"][0]["material_geometry"]=="NONE"
    assert current["questions"][0]["access_authority"]=="NONE"
    assert result["review_application_status"]=="PASS"


def test_source_or_geometry_change_makes_only_that_decision_stale():
    current=_manifest();supplied=deepcopy(current);row=_decision(current["questions"][0])
    row["source_sha256"]="c"*64;supplied["decisions"]=[row]
    result=validate_review_decisions(supplied,current)
    assert not result["accepted_review_decisions"]
    assert result["stale_review_decisions"][0]["reason"]=="MATERIAL_IDENTITY_CHANGED"


def test_unknown_question_and_invalid_answer_fail_closed():
    current=_manifest();supplied=deepcopy(current);row=_decision(current["questions"][0])
    row["question_id"]="GAPQ-OTHER";bad=_decision(current["questions"][0],"CUT_NEW_WALL")
    supplied["decisions"]=[row,bad];result=validate_review_decisions(supplied,current)
    assert len(result["stale_review_decisions"])==1
    assert {row["reason"] for row in result["rejected_review_decisions"]}=={"DECISION_INVALID","INCOMPLETE_REVIEW_SET"}


def test_conflicting_duplicate_decision_is_rejected_but_first_remains_valid():
    current=_manifest();supplied=deepcopy(current);question=current["questions"][0]
    supplied["decisions"]=[_decision(question,"DOOR"),_decision(question,"CONTINUOUS_WALL")]
    result=validate_review_decisions(supplied,current)
    assert len(result["accepted_review_decisions"])==1
    assert result["rejected_review_decisions"][0]["reason"]=="DECISION_CONFLICT"
    assert result["review_application_status"]=="INPUT_REQUIRED"


def test_unknown_answer_is_valid_but_grants_only_interpretation_authority():
    current=_manifest();supplied=deepcopy(current)
    supplied["decisions"]=[_decision(current["questions"][0],"UNKNOWN")]
    accepted=validate_review_decisions(supplied,current)["accepted_review_decisions"][0]
    assert accepted["review_scope"]=="TOPOLOGY_CLASSIFICATION_ONLY"


def test_continuous_wall_applies_only_as_nonmaterial_closure():
    current=_manifest();supplied=deepcopy(current);question=current["questions"][0]
    supplied["decisions"]=[_decision(question,"CONTINUOUS_WALL")]
    validation=validate_review_decisions(supplied,current)
    gaps,walls=_inputs();closures=[{"closure_id":"C1","gap_classification":"AMBIGUOUS_GAP",
                                    "gap_status":"INPUT_REQUIRED","material_geometry":"NONE"}]
    applied=apply_review_decisions(gaps,closures,validation)
    assert applied[0]["classification"]=="HUMAN_CONFIRMED_CONTINUITY"
    assert closures[0]["material_geometry"]=="NONE"
    assert closures[0]["roles"]==["ENCLOSURE_BARRIER"]
    assert {closures[0][key] for key in ("wall_authority","routing_authority","portal_authority","access_authority")}=={"NONE"}


def test_incomplete_review_set_has_zero_application_authority():
    gaps,walls=_inputs();g2=deepcopy(gaps[0]);g2.update(gap_id="G2",closure_id="C2",geometry=((5,2),(6,2)))
    current=build_review_manifest(source_sha256="a"*64,frame_id="F1",dependency_engine_sha="b"*40,
                                  gaps=gaps+[g2],walls=walls)
    supplied=deepcopy(current);supplied["decisions"]=[_decision(current["questions"][0],"CONTINUOUS_WALL")]
    validation=validate_review_decisions(supplied,current)
    closures=[{"closure_id":"C1","gap_status":"INPUT_REQUIRED"},{"closure_id":"C2","gap_status":"INPUT_REQUIRED"}]
    assert validation["review_application_status"]=="INPUT_REQUIRED"
    assert apply_review_decisions(gaps+[g2],closures,validation)==[]
    assert all(row["gap_status"]=="INPUT_REQUIRED" for row in closures)


def test_review_fingerprint_change_blocks_all_replay():
    current=_manifest();supplied=deepcopy(current);supplied["review_fingerprint"]="0"*64
    supplied["decisions"]=[_decision(current["questions"][0],"CONTINUOUS_WALL")]
    result=validate_review_decisions(supplied,current)
    assert result["review_application_status"]=="INPUT_REQUIRED"
    assert result["rejected_review_decisions"][0]["reason"]=="REVIEW_SET_IDENTITY_CHANGED"
