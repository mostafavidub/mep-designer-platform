import json
from types import SimpleNamespace

import pytest

from cad_engine.architectural_semantic_scout import (
    DeepSeekSemanticScout, SemanticScoutError, adaptive_local_triggers,
    assign_hint_ids, build_mep_preanalysis, build_semantic_map,
    cad_to_normalized, coverage_audit, fuse_semantic_evidence,
    map_hints_to_candidates, normalized_to_cad, reconcile_observations,
    render_clean_whole_floor, render_global_local_semantic_context,
    semantic_output_schema, validate_provider_payload, validate_semantic_item,
)


def item(kind="KITCHEN", bbox=None, center=None, confidence=.8, evidence=None):
    bbox=bbox or [.1,.1,.4,.4]; center=center or [.25,.25]
    return {"semantic_type":kind,"confidence":confidence,"approx_center_norm":center,
        "approx_bbox_norm":bbox,"evidence_classes":evidence or ["SPATIAL_LAYOUT"],
        "observed_text":[],"objects_seen":[],"uncertainty":[]}


def graph():
    return {"frame_id":"F1","source_sha256":"source","frame_bounds":[0,0,100,100],
        "regions":[
            {"region_id":"R1","polygon":[[0,0],[50,0],[50,50],[0,50],[0,0]],"centroid":[25,25],
             "exact_text_evidence":[{"source_handle":"L1","text":"آشپزخانه"}],"object_evidence":[]},
            {"region_id":"R2","polygon":[[50,0],[100,0],[100,50],[50,50],[50,0]],"centroid":[75,25],
             "exact_text_evidence":[],"object_evidence":[{"source_handle":"O1","type":"SINK","confidence":.9}]},
        ],"preauthority":{"label_host_diagnostics":[{"label_id":"L1","point":[25,75],"text":"آشپزخانه"}]}}


def payload(zones=None):
    return {"frame_id":"F1","semantic_zones":zones or [item()],"unclassified_areas":[],"overall_confidence":.8}


def test_normalized_bbox_validation_and_unknown_fields():
    assert validate_semantic_item(item())["semantic_type"]=="KITCHEN"
    for bad in ([-.1,0,.5,.5],[.5,.2,.4,.8],[0,0,0,.5]):
        with pytest.raises(SemanticScoutError): validate_semantic_item(item(bbox=bad))
    with pytest.raises(SemanticScoutError): validate_semantic_item({**item(),"polygon":[[0,0]]})


def test_normalized_cad_transform_is_reversible():
    point=[23.5,81.25]; bounds=[10,20,110,220]
    restored=normalized_to_cad(cad_to_normalized(point,bounds),bounds)
    assert restored==pytest.approx(point)


def test_hint_authority_can_never_be_engineering_geometry():
    hint=assign_hint_ids([item()],source_sha256="s",frame_id="f",call_hash="c")[0]
    assert hint["authority"]=="VISION_SEMANTIC_HINT"
    assert hint["material_geometry"] is None
    assert hint["routing_authority"]=="NONE"
    assert hint["engineering_geometry"] is False


def test_hint_id_is_deterministic_and_provider_does_not_supply_it():
    left=assign_hint_ids([item()],source_sha256="s",frame_id="f",call_hash="c")
    right=assign_hint_ids([item()],source_sha256="s",frame_id="f",call_hash="c")
    assert left[0]["semantic_hint_id"]==right[0]["semantic_hint_id"]
    assert "semantic_hint_id" not in semantic_output_schema()["properties"]["semantic_zones"]["items"]["properties"]


def test_global_local_same_type_deduplicates_but_open_plan_types_do_not():
    local=item("KITCHEN",bbox=[.12,.12,.42,.42],center=[.27,.27])
    living=item("LIVING",bbox=[.15,.15,.6,.6],center=[.35,.35])
    result=reconcile_observations([item()], [local,living], source_sha256="s",frame_id="f",call_hash="c")
    assert [x["semantic_type"] for x in result["semantic_zones"]]==["KITCHEN","LIVING"]
    assert result["semantic_zones"][0]["cross_pass_agreement"] is True


def test_coverage_gap_and_unexplained_label_trigger_local_zoom():
    hints=assign_hint_ids([item()],source_sha256="s",frame_id="f",call_hash="c")
    labels=[{"text":"حمام","normalized_position":[.8,.8]}]
    audit=coverage_audit(hints,labels)
    assert audit["coverage_gaps"] and audit["exact_labels_unexplained"]==["حمام"]
    assert adaptive_local_triggers(audit,hints,labels)[0]["reason"]=="UNEXPLAINED_EXACT_LABEL"


def test_mapping_is_many_to_many_and_never_geometry_authority():
    wide=assign_hint_ids([item(bbox=[.1,.5,.9,.95],center=[.5,.7])],source_sha256="s",frame_id="F1",call_hash="c")
    mapped=map_hints_to_candidates(wide,graph())[0]
    assert len(mapped["overlapping_candidates"])==2
    assert mapped["mapping_status"]=="MULTIPLE_CANDIDATES"
    assert mapped["engineering_geometry"] is False


def test_label_and_object_support_strengthen_semantics_without_geometry():
    hints=assign_hint_ids([item(bbox=[.1,.1,.4,.4],center=[.25,.25])],source_sha256="s",frame_id="F1",call_hash="c")
    labels=[{"text":"آشپزخانه","normalized_position":[.2,.2]}]
    objects=[{"type":"SINK","normalized_position":[.3,.3]}]
    fused=fuse_semantic_evidence(hints,labels,objects)
    assert fused[0]["semantic_status"]=="STRONGLY_SUPPORTED"
    assert fused[0]["geometry_status"]=="INPUT_REQUIRED"


def test_mep_preanalysis_is_bounded_and_not_final_design():
    hints=assign_hint_ids([item("BATHROOM")],source_sha256="s",frame_id="f",call_hash="c")
    fused=[{"semantic_hint_id":hints[0]["semantic_hint_id"],"semantic_type":"BATHROOM"}]
    result=build_mep_preanalysis(hints,fused)
    assert result["mode"]=="MEP_PREANALYSIS" and result["engineering_authority"] is False
    assert "FINAL_ROUTING" in result["forbidden_uses"]


def test_semantic_map_keeps_semantic_and_geometry_status_separate():
    result=build_semantic_map(graph=graph(),provider_payload=payload(),provider="deepseek",model="deepseek-flash",
                              render_hash="r",call_hash="c")
    assert result["schema"]=="architectural-semantic-map/1.0"
    assert result["engineering_geometry"] is False
    assert result["semantic_fusion"][0]["geometry_status"]=="INPUT_REQUIRED"


def test_wrong_frame_and_provider_geometry_are_rejected():
    with pytest.raises(SemanticScoutError): validate_provider_payload({**payload(),"frame_id":"BAD"},frame_id="F1")
    wrong=payload(); wrong["semantic_zones"][0]["polygon"]=[[0,0]]
    with pytest.raises(SemanticScoutError): validate_provider_payload(wrong,frame_id="F1")


class FakeCompletions:
    def __init__(self,response): self.response=response; self.calls=[]
    def create(self,**kwargs): self.calls.append(kwargs); return self.response


def test_deepseek_semantic_call_is_strict_and_single(tmp_path):
    image=tmp_path/"floor.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    raw=json.dumps(payload())
    function=SimpleNamespace(name="submit_architectural_semantic_map_v1",arguments=raw)
    response=SimpleNamespace(id="req",choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[SimpleNamespace(function=function)]))],
                             usage=SimpleNamespace(prompt_tokens=10,completion_tokens=5,total_tokens=15))
    completions=FakeCompletions(response); client=SimpleNamespace(chat=SimpleNamespace(completions=completions))
    adapter=DeepSeekSemanticScout(api_key="secret",client=client)
    assert adapter.analyze(image_paths=[str(image)],frame_id="F1",labels=[],objects=[])["semantic_zones"]
    assert len(completions.calls)==1
    assert completions.calls[0]["tools"][0]["function"]["strict"] is True
    assert "secret" not in json.dumps(adapter.last_call_metadata)


def test_malformed_deepseek_semantic_response_is_rejected_atomically(tmp_path):
    image=tmp_path/"floor.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    function=SimpleNamespace(name="submit_architectural_semantic_map_v1",arguments='{"frame_id":"F1"')
    response=SimpleNamespace(id="req",choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[SimpleNamespace(function=function)]))],usage=None)
    client=SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(response)))
    adapter=DeepSeekSemanticScout(api_key="secret",client=client)
    with pytest.raises(SemanticScoutError) as error:
        adapter.analyze(image_paths=[str(image)],frame_id="F1",labels=[],objects=[])
    assert error.value.code=="SEMANTIC_JSON_INVALID"


def test_private_source_path_is_not_in_semantic_map():
    rendered=build_semantic_map(graph=graph(),provider_payload=payload(),provider="deepseek",model="deepseek-flash",
                                render_hash="r",call_hash="c")
    text=json.dumps(rendered,ensure_ascii=False)
    assert "/Users/" not in text and ".dxf" not in text


def test_clean_and_local_render_have_no_candidate_overlay(tmp_path):
    source=tmp_path/"source.png"
    info=render_clean_whole_floor(graph(),source,width=300,height=300)
    assert info["candidate_overlay"] is False and info["debug_overlay"] is False
    local=render_global_local_semantic_context(source,[.1,.1,.4,.4],tmp_path/"local.png")
    assert local["global_context"] and local["local_detail"]
