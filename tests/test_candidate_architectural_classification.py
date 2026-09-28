import pytest

from cad_engine.candidate_architectural_classification import (
    CandidateClassificationError,
    build_candidate_graph,
    candidate_classification_schema,
    derive_shell_candidates,
    fuse_region_classifications,
    validate_candidate_classification,
)
from cad_engine.preauthority_candidate_graph import (
    EXCLUDED, HARD, SOFT, atomic_faces, build_preauthority_graph, source_segments,
)


def _model(*, weak=False):
    regions=[] if weak else [
        {"region_id":"OLD-I","candidate_id":"C-I","frame_id":"F1",
         "geometry":[[0,0],[6,0],[6,6],[0,6],[0,0]],"area":36},
        {"region_id":"OLD-Y","candidate_id":"C-Y","frame_id":"F1",
         "geometry":[[6,0],[10,0],[10,6],[6,6],[6,0]],"area":24},
    ]
    return {"source":{"source_sha256":"a"*64},
        "frames":[{"frame_id":"F1","bounds":[0,0,10,6]}],
        "plan_regions":{"regions":regions},
        "canonical_walls":[{"wall_id":"W1","frame_id":"F1","centerline":[[6,0],[6,6]],
                            "source_handles":["H1"]}],
        "all_texts":[{"text":"اتاق خواب","point":[3,3],"handle":"T1"},
                     {"text":"حیاط","point":[8,3],"handle":"T2"}],
        "architectural_objects":[],"diagnostics":{"adaptive_tolerance":.001}}


def _payload(graph, interior="BUILDING_INTERIOR"):
    left=min(graph["regions"],key=lambda row:row["centroid"][0])
    right=max(graph["regions"],key=lambda row:row["centroid"][0])
    return {"frame_id":"F1","regions":[
        {"region_id":left["region_id"],"role":interior,"confidence":.95,
         "evidence":["room label"],"uncertainty":""},
        {"region_id":right["region_id"],"role":"YARD","confidence":.96,
         "evidence":["yard label"],"uncertainty":""}],
        "boundaries":[],"bridge_decisions":[]}


def test_candidate_graph_is_id_only_bounded_and_hosts_exact_source_labels():
    graph=build_candidate_graph(_model(),frame_id="F1")
    assert graph["provider_eligible"] is True
    assert len(graph["regions"])==2
    assert len(graph["boundaries"])<=160
    assert {item["text"] for row in graph["regions"] for item in row["exact_text_evidence"]}=={"اتاق خواب","حیاط"}
    schema=candidate_classification_schema(region_ids=[r["region_id"] for r in graph["regions"]],
        boundary_ids=[r["boundary_id"] for r in graph["boundaries"]],ambiguity_options={})
    serialized=str(schema)
    assert "polygon" not in serialized and "geometry" not in serialized and "pixel" not in serialized


def test_unknown_region_and_vision_geometry_are_rejected():
    graph=build_candidate_graph(_model(),frame_id="F1")
    payload=_payload(graph); payload["regions"][0]["region_id"]="R-INVENTED"
    with pytest.raises(CandidateClassificationError,match="Unknown or duplicate"):
        validate_candidate_classification(payload,graph)
    payload=_payload(graph); payload["regions"][0]["polygon"]=[[0,0],[1,0],[1,1]]
    with pytest.raises(CandidateClassificationError,match="invalid fields"):
        validate_candidate_classification(payload,graph)


def test_region_roles_derive_existing_shared_boundary_without_redrawing_shell():
    graph=build_candidate_graph(_model(),frame_id="F1")
    fusion=fuse_region_classifications(graph,_payload(graph))
    result=derive_shell_candidates(graph,fusion)
    assert result["status"]=="INPUT_REQUIRED"  # unsupported exterior edges still fail closed
    assert len(result["shell_boundaries"])==1
    edge=result["shell_boundaries"][0]
    assert edge["geometry"] in [row["geometry"] for row in graph["boundaries"]]
    assert edge["material_geometry"]=="PHYSICAL_WALL"


def test_exact_label_contradiction_blocks_single_wrong_classification():
    graph=build_candidate_graph(_model(),frame_id="F1")
    payload=_payload(graph)
    right=max(graph["regions"],key=lambda row:row["centroid"][0])
    for row in payload["regions"]:
        if row["region_id"]==right["region_id"]: row["role"]="BUILDING_INTERIOR"
    fusion=fuse_region_classifications(graph,payload)
    assert fusion["status"]=="CONFLICT"
    assert any(row["region_id"]==right["region_id"] for row in fusion["conflicts"])
    assert derive_shell_candidates(graph,fusion)["shell_boundaries"]==[]


def test_missing_cad_shared_boundary_never_becomes_wall_material():
    model=_model(); model["canonical_walls"]=[]
    graph=build_candidate_graph(model,frame_id="F1")
    result=derive_shell_candidates(graph,fuse_region_classifications(graph,_payload(graph)))
    assert result["shell_boundaries"][0]["material_geometry"]=="NONE"


def test_unusable_candidate_geometry_fails_before_provider():
    graph=build_candidate_graph(_model(weak=True),frame_id="F1")
    assert graph["provider_eligible"] is False
    assert graph["status"]=="FASIHI_CANDIDATE_GRAPH_INSUFFICIENT"
    assert "TOO_FEW_REGION_CANDIDATES" in graph["blocking_reasons"]


def _v2_model(segments, texts=(), objects=()):
    return {"source":{"source_sha256":"b"*64},"frames":[{"frame_id":"F2","bounds":[0,0,10,10]}],
        "architectural_segments":segments,"boundary_extraction_rejections":[],
        "canonical_walls":[],"all_texts":list(texts),"architectural_objects":list(objects),
        "diagnostics":{"adaptive_tolerance":.01}}


def _segment(handle,a,b,status="REJECTED",semantic="UNKNOWN_GEOMETRY"):
    return {"segment_id":handle,"source_handle":handle,"frame_id":"F2","geometry":[a,b],
        "semantic_class":semantic,"wall_evidence_state":"CONFIRMED_WALL" if status=="ACCEPTED" else "WEAK_WALL_CANDIDATE",
        "status":status,"source_context":{"layer":"0","entity_type":"LINE"}}


def test_unknown_source_line_is_retained_as_soft_candidate():
    model=_v2_model([_segment("S1",[1,1],[9,1])])
    rows=source_segments(model,model["frames"][0],.01)
    assert rows[0]["authority_tier"]==SOFT


def test_annotation_and_furniture_geometry_are_hard_excluded():
    rows=[_segment("A",[1,1],[2,1],semantic="ANNOTATION"),
          _segment("F",[2,2],[3,2],semantic="FURNITURE")]
    result=source_segments(_v2_model(rows),{"frame_id":"F2","bounds":[0,0,10,10]},.01)
    assert {row["authority_tier"] for row in result}=={EXCLUDED}


def test_atomic_face_uses_hard_and_soft_boundaries_with_stable_id():
    rows=[_segment("A",[1,1],[5,1],"ACCEPTED"),_segment("B",[5,1],[5,5]),
          _segment("C",[5,5],[1,5],"ACCEPTED"),_segment("D",[1,5],[1,1])]
    model=_v2_model(rows); frame=model["frames"][0]; segments=source_segments(model,frame,.01)
    first,_=atomic_faces(segments,.01,frame); second,_=atomic_faces(segments,.01,frame)
    assert len(first)==1 and first[0]["face_id"]==second[0]["face_id"]
    assert first[0]["hard_boundary_fraction"]>0 and first[0]["soft_boundary_fraction"]>0


def test_label_hosted_and_unhosted_have_explicit_status():
    rows=[_segment("A",[1,1],[5,1],"ACCEPTED"),_segment("B",[5,1],[5,5],"ACCEPTED"),
          _segment("C",[5,5],[1,5],"ACCEPTED"),_segment("D",[1,5],[1,1],"ACCEPTED")]
    texts=[{"handle":"T1","text":"ROOM","point":[3,3]},{"handle":"T2","text":"OUT","point":[8,8]}]
    graph=build_preauthority_graph(_v2_model(rows,texts),{"frame_id":"F2","bounds":[0,0,10,10]},tolerance=.01)
    states={row["label_id"]:row for row in graph["label_host_diagnostics"]}
    assert states["T1"]["status"]=="HOSTED"
    assert states["T2"]["reason"]=="LABEL_OUTSIDE_PLAN"


def test_virtual_opening_closure_is_candidate_only_not_material_wall():
    rows=[_segment("A",[1,1],[4,1],"ACCEPTED"),_segment("B",[4.5,1],[8,1],"ACCEPTED"),
          _segment("C",[8,1],[8,5],"ACCEPTED"),_segment("D",[8,5],[1,5],"ACCEPTED"),
          _segment("E",[1,5],[1,1],"ACCEPTED")]
    graph=build_preauthority_graph(_v2_model(rows),{"frame_id":"F2","bounds":[0,0,10,10]},tolerance=.01)
    assert graph["virtual_closure_candidates"]
    closure=graph["virtual_closure_candidates"][0]
    assert closure["material_geometry"]=="NONE" and closure["authority"]=="CANDIDATE_ONLY"
    assert graph["atomic_faces"]


def test_site_cycle_is_candidate_not_automatic_building_interior():
    rows=[_segment("A",[1,1],[9,1]),_segment("B",[9,1],[9,9]),
          _segment("C",[9,9],[1,9]),_segment("D",[1,9],[1,1])]
    graph=build_candidate_graph(_v2_model(rows),frame_id="F2")
    assert graph["regions"] and all(row.get("authority")=="CANDIDATE_ONLY" for row in graph["regions"])
    assert all("role" not in row for row in graph["regions"])


def test_v2_provider_gate_can_pass_only_with_real_faces_and_hosted_label():
    rows=[_segment("A",[1,1],[9,1],"ACCEPTED"),_segment("B",[9,1],[9,9],"ACCEPTED"),
          _segment("C",[9,9],[1,9],"ACCEPTED"),_segment("D",[1,9],[1,1],"ACCEPTED"),
          _segment("E",[5,1],[5,9],"ACCEPTED")]
    graph=build_candidate_graph(_v2_model(rows,[{"handle":"T","text":"ROOM","point":[3,3]}]),frame_id="F2")
    assert graph["provider_eligible"] is True
    schema=candidate_classification_schema(region_ids=[r["region_id"] for r in graph["regions"]],
        boundary_ids=[b["boundary_id"] for b in graph["boundaries"]],ambiguity_options={})
    assert "geometry" not in str(schema) and "polygon" not in str(schema)
