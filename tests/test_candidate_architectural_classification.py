import pytest

from cad_engine.candidate_architectural_classification import (
    CandidateClassificationError,
    build_candidate_graph,
    candidate_classification_schema,
    derive_shell_candidates,
    fuse_region_classifications,
    validate_candidate_classification,
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
