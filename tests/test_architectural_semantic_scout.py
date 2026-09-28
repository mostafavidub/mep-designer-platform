import json
from types import SimpleNamespace

import pytest

from cad_engine.architectural_semantic_scout import (
    COMPACT_RESPONSE_BUDGET, DeepSeekCompactSemanticScout,
    DeepSeekSemanticScout, SemanticScoutError, adaptive_local_triggers,
    assign_hint_ids, build_mep_preanalysis, build_semantic_map,
    cad_to_normalized, coverage_audit, fuse_semantic_evidence,
    map_hints_to_candidates, normalized_to_cad, reconcile_observations,
    render_clean_whole_floor, render_global_local_semantic_context,
    compact_inventory_schema, compact_localization_schema, compact_semantic_completeness,
    enrich_compact_hints, estimate_compact_response_bytes, plan_compact_calls,
    semantic_output_schema, validate_compact_inventory, validate_compact_localization,
    validate_provider_payload, validate_semantic_item,
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
    assert hint["material_geometry"]=="NONE"
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


def test_compact_schemas_forbid_provider_prose_and_geometry():
    inventory=compact_inventory_schema(); localization=compact_localization_schema({"KITCHEN","BATHROOM"})
    assert set(inventory["properties"])=={"f","types"}
    assert set(localization["properties"]["z"]["items"]["properties"])=={"t","b","c"}
    text=json.dumps(localization)
    assert "observed_text" not in text and "uncertainty" not in text and "polygon" not in text


def test_compact_inventory_and_localization_validate_independently():
    inv=validate_compact_inventory({"f":"F1","types":[{"t":"KITCHEN","n":1,"c":.9}]},frame_id="F1")
    loc=validate_compact_localization({"f":"F1","z":[{"t":"KITCHEN","b":[.1,.2,.4,.5],"c":.8}]},
                                      frame_id="F1",allowed_types={"KITCHEN"})
    assert inv["types"][0]["n"]==1 and loc["z"][0]["b"]==[.1,.2,.4,.5]
    with pytest.raises(SemanticScoutError):
        validate_compact_localization({"f":"F1","z":[{"t":"KITCHEN","b":[.1,.2,.4,.5],"c":.8,"why":"text"}]},
                                      frame_id="F1",allowed_types={"KITCHEN"})


def test_response_budget_and_semantic_group_split_are_deterministic():
    small=estimate_compact_response_bytes(task_type="LOCALIZATION",expected_hints=4)
    large=estimate_compact_response_bytes(task_type="LOCALIZATION",expected_hints=100)
    assert small["within_budget"] and small["estimated_response_bytes"] < COMPACT_RESPONSE_BUDGET
    assert not large["within_budget"]
    inv={"f":"F1","types":[{"t":"KITCHEN","n":1,"c":.9},{"t":"BATHROOM","n":1,"c":.8},
                              {"t":"BEDROOM","n":2,"c":.8}]}
    labels=[{"text":"حمام","normalized_position":[.2,.2]}]
    assert plan_compact_calls(inv,labels)==plan_compact_calls(inv,labels)
    assert [x["group"] for x in plan_compact_calls(inv,labels)]==["WET_SERVICE","HABITABLE"]


def test_compact_enrichment_is_local_and_never_geometry_authority():
    rows=[{"t":"BATHROOM","b":[.1,.1,.4,.4],"c":.9}]
    labels=[{"text":"حمام","normalized_position":[.2,.2]}]
    objects=[{"type":"SHOWER","normalized_position":[.3,.3]}]
    hint=enrich_compact_hints(rows,source_sha256="s",frame_id="F1",source_call_id="C1",
                              labels=labels,objects=objects)[0]
    assert hint["semantic_status"]=="MULTI_EVIDENCE_SUPPORTED"
    assert hint["material_geometry"]=="NONE" and hint["routing_authority"]=="NONE"
    assert hint["engineering_geometry"] is False


def test_compact_enrichment_detects_label_conflict():
    hint=enrich_compact_hints([{"t":"KITCHEN","b":[.1,.1,.4,.4],"c":.9}],source_sha256="s",
        frame_id="F1",source_call_id="C1",labels=[{"text":"اتاق خواب","normalized_position":[.2,.2]}],objects=[])[0]
    assert hint["semantic_status"]=="CONFLICT"


def test_partial_required_set_blocks_semantic_completeness():
    inv={"types":[{"t":"KITCHEN","n":1},{"t":"BATHROOM","n":1}]}
    hints=enrich_compact_hints([{"t":"KITCHEN","b":[.1,.1,.4,.4],"c":.9}],source_sha256="s",
        frame_id="F1",source_call_id="C1",labels=[],objects=[])
    result=compact_semantic_completeness(inv,hints,[])
    assert result["complete_required_set"] is False and result["count_gaps"]=={"BATHROOM":1}


def _compact_response(tool_name,payload,finish_reason="tool_calls"):
    function=SimpleNamespace(name=tool_name,arguments=json.dumps(payload))
    return SimpleNamespace(id="req",choices=[SimpleNamespace(finish_reason=finish_reason,
        message=SimpleNamespace(tool_calls=[SimpleNamespace(function=function)]))],
        usage=SimpleNamespace(prompt_tokens=10,completion_tokens=5,total_tokens=15))


def test_compact_transport_records_complete_observability(tmp_path):
    image=tmp_path/"floor.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    response=_compact_response("submit_compact_semantic_inventory_v2",
        {"f":"F1","types":[{"t":"KITCHEN","n":1,"c":.9}]})
    completions=FakeCompletions(response); client=SimpleNamespace(chat=SimpleNamespace(completions=completions))
    scout=DeepSeekCompactSemanticScout(api_key="secret",client=client)
    result=scout._call(image_path=str(image),frame_id="F1",labels=[],objects=[],task_type="INVENTORY",
                       group="WHOLE_FLOOR",expected_items=10)
    assert result["payload"]["types"]
    meta=scout.call_metadata[0]
    assert meta["finish_reason"]=="tool_calls" and meta["json_validation_status"]=="VALID"
    assert meta["actual_response_bytes"] and meta["total_tokens"]==15



class SequenceCompletions:
    def __init__(self, responses):
        self.responses=list(responses); self.calls=[]
    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise RuntimeError("unexpected extra provider call")
        return self.responses.pop(0)


def test_exact_anchor_fusion_treats_stair_and_duct_as_composition_not_conflict():
    from cad_engine.architectural_semantic_scout import build_exact_semantic_anchors, fuse_semantic_anchors
    hints=enrich_compact_hints([{"t":"STAIR","b":[.1,.1,.7,.7],"c":.85}],
        source_sha256="s",frame_id="F1",source_call_id="C1",labels=[],objects=[])
    labels=[{"text":"داکت","normalized_position":[.3,.3]}]
    anchors=build_exact_semantic_anchors(labels,source_sha256="s",frame_id="F1")
    fused=fuse_semantic_anchors(hints,anchors)
    assert fused["conflicts"]==[]
    assert fused["compositions"]
    assert fused["hints"][0]["semantic_status"]=="COMPOSED_WITH_EXACT_ANCHOR"


def test_exact_anchor_can_seed_mep_preanalysis_without_vision():
    from cad_engine.architectural_semantic_scout import build_compact_mep_preanalysis
    labels=[{"text":"توالت","normalized_position":[.2,.2]},
            {"text":"داکت","normalized_position":[.3,.3]},
            {"text":"انبار","normalized_position":[.5,.5]}]
    result=build_compact_mep_preanalysis([],labels,[],source_sha256="s",frame_id="F1")
    assert result["qualification_status"]=="QUALIFIED_FOR_PREANALYSIS"
    types={row["semantic_type"] for row in result["search_targets"]}
    assert {"TOILET","DUCT","STORAGE"} <= types
    assert result["engineering_authority"] is False


def test_incompatible_exact_anchor_still_blocks_vision_hint():
    from cad_engine.architectural_semantic_scout import build_exact_semantic_anchors, fuse_semantic_anchors
    hints=enrich_compact_hints([{"t":"KITCHEN","b":[.1,.1,.5,.5],"c":.9}],
        source_sha256="s",frame_id="F1",source_call_id="C1",labels=[],objects=[])
    anchors=build_exact_semantic_anchors([{"text":"اتاق خواب","normalized_position":[.3,.3]}],
        source_sha256="s",frame_id="F1")
    fused=fuse_semantic_anchors(hints,anchors)
    assert fused["conflicts"]
    assert fused["hints"][0]["semantic_status"]=="CONFLICT"


def test_compact_semantic_scout_retries_exactly_once_after_malformed_json(tmp_path):
    image=tmp_path/"floor.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    bad_function=SimpleNamespace(name="submit_compact_semantic_inventory_v2",arguments='{"f":"F1"')
    bad=SimpleNamespace(id="bad",choices=[SimpleNamespace(finish_reason="tool_calls",
        message=SimpleNamespace(tool_calls=[SimpleNamespace(function=bad_function)]))],usage=None)
    good=_compact_response("submit_compact_semantic_inventory_v2",
        {"f":"F1","types":[{"t":"KITCHEN","n":1,"c":.9}]})
    completions=SequenceCompletions([bad,good])
    scout=DeepSeekCompactSemanticScout(api_key="secret",
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    result=scout._call(image_path=str(image),frame_id="F1",labels=[],objects=[],
        task_type="INVENTORY",group="WHOLE_FLOOR",expected_items=10)
    assert result["payload"]["types"]
    assert len(completions.calls)==2
    assert scout.call_metadata[0]["retry_scheduled"] is True
    assert scout.call_metadata[1]["attempt_number"]==2


def test_compact_semantic_scout_never_retries_more_than_once(tmp_path):
    image=tmp_path/"floor.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    def malformed(identifier):
        function=SimpleNamespace(name="submit_compact_semantic_inventory_v2",arguments='{"f":"F1"')
        return SimpleNamespace(id=identifier,choices=[SimpleNamespace(finish_reason="tool_calls",
            message=SimpleNamespace(tool_calls=[SimpleNamespace(function=function)]))],usage=None)
    completions=SequenceCompletions([malformed("one"),malformed("two")])
    scout=DeepSeekCompactSemanticScout(api_key="secret",
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    with pytest.raises(SemanticScoutError) as error:
        scout._call(image_path=str(image),frame_id="F1",labels=[],objects=[],
            task_type="INVENTORY",group="WHOLE_FLOOR",expected_items=10)
    assert error.value.code=="COMPACT_JSON_INVALID"
    assert len(completions.calls)==2


def test_compact_semantic_scout_does_not_retry_valid_response(tmp_path):
    image=tmp_path/"floor.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    completions=SequenceCompletions([_compact_response("submit_compact_semantic_inventory_v2",
        {"f":"F1","types":[{"t":"LIVING","n":1,"c":.8}]})])
    scout=DeepSeekCompactSemanticScout(api_key="secret",
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    scout._call(image_path=str(image),frame_id="F1",labels=[],objects=[],
        task_type="INVENTORY",group="WHOLE_FLOOR",expected_items=10)
    assert len(completions.calls)==1
    assert scout.call_metadata[0]["retry_scheduled"] is False
    assert scout.call_metadata[0]["retry_reason"] is None
    assert scout.call_metadata[0]["attempt_result"]=="SUCCESS"


@pytest.mark.parametrize("left,right", [
    ("STAIR", "SHAFT"), ("BATHROOM", "DUCT"), ("TOILET", "SHAFT"),
    ("KITCHEN", "LIVING"),
])
def test_required_functional_compositions_are_not_conflicts(left, right):
    from cad_engine.architectural_semantic_scout import build_exact_semantic_anchors, fuse_semantic_anchors
    label = {"SHAFT":"شفت", "DUCT":"داکت", "LIVING":"پذیرایی"}[right]
    hints=enrich_compact_hints([{"t":left,"b":[.1,.1,.6,.6],"c":.8}],source_sha256="s",
        frame_id="F1",source_call_id="C1",labels=[],objects=[])
    anchors=build_exact_semantic_anchors([{"text":label,"normalized_position":[.3,.3]}],
        source_sha256="s",frame_id="F1")
    result=fuse_semantic_anchors(hints,anchors)
    assert result["conflicts"]==[]
    assert result["compositions"][0]["relation"]=="COLOCATED_FUNCTIONAL_COMPOSITION"


def test_exact_anchor_rejects_invalid_normalized_position():
    from cad_engine.architectural_semantic_scout import build_exact_semantic_anchors
    with pytest.raises(SemanticScoutError) as error:
        build_exact_semantic_anchors([{"text":"توالت","normalized_position":[1.2,.2]}],
                                     source_sha256="s",frame_id="F1")
    assert error.value.code=="SEMANTIC_LOCATION_INVALID"


def test_mep_preanalysis_hard_safety_gate_is_explicit():
    from cad_engine.architectural_semantic_scout import build_compact_mep_preanalysis
    hint=enrich_compact_hints([{"t":"KITCHEN","b":[.1,.1,.4,.4],"c":.9}],source_sha256="s",
        frame_id="F1",source_call_id="C1",labels=[],objects=[])
    result=build_compact_mep_preanalysis(hint,[],[],source_sha256="s",frame_id="F1")
    forbidden={"FINAL_FIXTURE_PLACEMENT","FINAL_PIPE_ROUTE","FINAL_DRAIN_ROUTE","FINAL_VENT_ROUTE",
        "FINAL_DUCT_ROUTE","FINAL_CABLE_ROUTE","FINAL_ELECTRICAL_EQUIPMENT_PLACEMENT",
        "ROOM_AREA_LOAD_CALCULATION","WALL_PENETRATION","SLEEVE","ROUTING_OBSTACLE",
        "ENGINEER_READY_OUTPUT"}
    assert forbidden <= set(result["forbidden_uses"])
    assert result["investigation_priorities"]
    assert all(row["authority"]=="PREANALYSIS_ONLY" for row in result["investigation_priorities"])
    assert all(target["location_kind"] in {"APPROXIMATE_BBOX","EXACT_DXF_TEXT_POINT"}
               for target in result["search_targets"])
    assert "route" not in result and "equipment" not in result and "loads" not in result


def test_functional_label_audit_excludes_drafting_annotations():
    inv={"types":[{"t":"TOILET","n":1}]}
    labels=[{"text":"توالت","normalized_position":[.2,.2]},
            {"text":"SC:1/100","normalized_position":[.5,.9]}]
    hints=enrich_compact_hints([{"t":"TOILET","b":[.1,.1,.3,.3],"c":.9}],source_sha256="s",
        frame_id="F1",source_call_id="C1",labels=labels,objects=[])
    result=compact_semantic_completeness(inv,hints,labels)
    assert result["functional_labels_explained"]==["توالت"]
    assert result["functional_labels_unexplained"]==[]
    assert result["non_semantic_annotation_count"]==1


def test_invalid_compact_values_are_schema_failures_not_provider_failures():
    with pytest.raises(SemanticScoutError) as inv:
        validate_compact_inventory({"f":"F1","types":[{"t":"KITCHEN","n":"bad","c":.9}]},frame_id="F1")
    assert inv.value.code=="COMPACT_INVENTORY_INVALID"
    with pytest.raises(SemanticScoutError) as loc:
        validate_compact_localization({"f":"F1","z":[{"t":"KITCHEN","b":[.1,.2,"bad",.5],"c":.8}]},
                                      frame_id="F1",allowed_types={"KITCHEN"})
    assert loc.value.code=="COMPACT_LOCALIZATION_INVALID"


def test_storage_inventory_is_not_silently_dropped_by_planner():
    planned=plan_compact_calls({"f":"F1","types":[{"t":"STORAGE","n":1,"c":.8}]},[])
    assert any("STORAGE" in row["types"] for row in planned)


def test_provider_transport_failure_retries_once_and_records_terminal_result(tmp_path):
    image=tmp_path/"floor.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    good=_compact_response("submit_compact_semantic_inventory_v2",
        {"f":"F1","types":[{"t":"UNKNOWN","n":1,"c":.1}]})
    completions=SequenceCompletions([RuntimeError("network"),good])
    original_create=completions.create
    def create(**kwargs):
        item=completions.responses[0]
        if isinstance(item,Exception):
            completions.calls.append(kwargs); completions.responses.pop(0); raise item
        return original_create(**kwargs)
    completions.create=create
    scout=DeepSeekCompactSemanticScout(api_key="secret",
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    scout._call(image_path=str(image),frame_id="F1",labels=[],objects=[],task_type="INVENTORY",
                group="WHOLE_FLOOR",expected_items=10)
    assert len(completions.calls)==2
    assert scout.call_metadata[0]["retry_reason"]=="SEMANTIC_PROVIDER_FAILED"
    assert scout.call_metadata[1]["retry_result"]=="SUCCESS"


def test_valid_unknown_semantics_do_not_trigger_retry(tmp_path):
    image=tmp_path/"floor.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    completions=SequenceCompletions([_compact_response("submit_compact_semantic_inventory_v2",
        {"f":"F1","types":[{"t":"UNKNOWN","n":1,"c":.05}]})])
    scout=DeepSeekCompactSemanticScout(api_key="secret",
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)))
    scout._call(image_path=str(image),frame_id="F1",labels=[],objects=[],task_type="INVENTORY",
                group="WHOLE_FLOOR",expected_items=10)
    assert len(completions.calls)==1
