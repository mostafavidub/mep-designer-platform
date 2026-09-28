import json
from pathlib import Path
from types import SimpleNamespace

import ezdxf
import pytest

from cad_engine.architectural_space_engine import reconstruct_architecture
from cad_engine.architectural_vision_recovery import (
    DEEPSEEK_SHELL_BOUNDARIES_TOOL_SCHEMA, DEEPSEEK_V1_TOOL_NAME, PROVIDER_CAPABILITY_MATRIX,
    DeepSeekVisionAdapter, GLOBAL_JSON_SCHEMA, OpenAIVisionAdapter, RENDER_VERSION, RenderTransform,
    SHELL_BOUNDARIES_JSON_SCHEMA,
    VisionRecoveryError, VisionTask, VisionTransport, _raw_source_context, _validate_payload,
    architectural_qa_shell_boundaries, configured_vision_adapter,
    reconcile_and_repair, render_source_frame, select_vision_viewport, validate_shell_boundaries_payload,
)
from cad_engine.engineering_runner import run_engineering_pipeline


def _drawing(path):
    doc = ezdxf.new("R2013"); doc.header["$INSUNITS"] = 6
    msp = doc.modelspace(); doc.layers.add("WALL")
    for a, b in [((0, 0), (10, 0)), ((10, 0), (10, 6)), ((10, 6), (0, 6)), ((0, 6), (0, 0))]:
        msp.add_line(a, b, dxfattribs={"layer": "WALL"})
    doc.saveas(path)
    return path


class FakeAdapter:
    model = "fake-multimodal"
    def __init__(self): self.calls = []
    def analyze(self, *, image_path, frame_id, regions, context=None):
        self.calls.append((image_path, frame_id, regions))
        spaces=[]
        for index,row in enumerate(regions):
            x1,y1,x2,y2=row["pixel_bounds"]
            spaces.append({"vision_space_id":f"V{index}","polygon_px":[[x1,y1],[x2,y1],[x2,y2],[x1,y2]],
                           "semantic_candidates":[{"type":"living","confidence":.98}],
                           "objects_seen":["sofa"],"labels_seen":[],"boundary_evidence":["enclosure"],"uncertainties":[]})
        return {"frame_id":frame_id,"physical_spaces":spaces,"functional_zones":[],"doors":[],"windows":[],
                "open_passages":[],"stairs":[],"shafts":[],"suspected_false_boundaries":[],
                "suspected_missing_boundaries":[],"unresolved_regions":[]}


def test_coordinate_transform_round_trip_and_y_axis():
    transform = RenderTransform(10, 20, 110, 70, 1200, 700, 40)
    point = (42.25, 31.75)
    pixel = transform.cad_to_pixel(point)
    restored = transform.pixel_to_cad(pixel)
    assert restored == pytest.approx(point)
    assert transform.cad_to_pixel((10, 70))[1] < transform.cad_to_pixel((10, 20))[1]


def test_strict_schema_rejects_unknown_region_and_extra_fields():
    with pytest.raises(VisionRecoveryError, match="Unknown or duplicate"):
        _validate_payload({"schema": "architectural-vision-evidence/1.0", "regions": [
            {"region_id": "BAD", "semantic_type": "living", "confidence": .9,
             "evidence": [], "uncertainty": ""}]}, {"EXPECTED"})
    with pytest.raises(VisionRecoveryError, match="Invalid region response fields"):
        _validate_payload({"schema": "architectural-vision-evidence/1.0", "regions": [
            {"region_id": "EXPECTED", "semantic_type": "living", "confidence": .9,
             "evidence": [], "uncertainty": "", "release_allowed": True}]}, {"EXPECTED"})


def test_every_array_item_has_explicit_deepseek_compatible_schema():
    def visit(node):
        if not isinstance(node,dict): return
        if node.get("type") == "array":
            items=node.get("items")
            assert isinstance(items,dict) and any(key in items for key in ("type","anyOf","$ref"))
        for value in node.values():
            if isinstance(value,dict): visit(value)
            elif isinstance(value,list):
                for item in value: visit(item)
    visit(GLOBAL_JSON_SCHEMA)


def test_source_renderer_is_cached_and_transform_manifest_is_exact(tmp_path):
    extracted = {"primitives": [{"start": (0, 0), "end": (10, 6)}], "texts": []}
    frame = {"frame_id": "F1", "bounds": [0, 0, 10, 6]}
    first = render_source_frame(extracted=extracted, frame=frame, source_hash="abc", cache_dir=tmp_path)
    second = render_source_frame(extracted=extracted, frame=frame, source_hash="abc", cache_dir=tmp_path)
    assert first == second
    assert first["cache_key"] == second["cache_key"]
    assert first["transform"]["y_axis_inverted"] is True


def _viewport_source():
    primitives=[]
    def line(a,b,layer="0"):
        primitives.append({"entity_type":"LINE","start":a,"end":b,"layer":layer,"handle":str(len(primitives))})
    # Whole-sheet border must not become the plan viewport.
    for a,b in [((0,0),(100,0)),((100,0),(100,100)),((100,100),(0,100)),((0,100),(0,0))]: line(a,b)
    # Dense Layer-0 plan plus an attached balcony/exterior edge.
    for a,b in [((20,20),(60,20)),((60,20),(60,60)),((60,60),(20,60)),((20,60),(20,20)),
                ((40,20),(40,60)),((20,40),(60,40)),((60,30),(70,30)),((70,30),(70,50)),((70,50),(60,50))]: line(a,b)
    # A sparse title box must not win over the plan.
    for a,b in [((76,2),(98,2)),((98,2),(98,14)),((98,14),(76,14)),((76,14),(76,2))]: line(a,b,"TITLE")
    texts=[{"text":"اتاق خواب","point":[22,62],"layer":"0"},{"text":"PROJECT TITLE","point":[78,8],"layer":"TITLE"}]
    return {"primitives":primitives,"texts":texts,"objects":[],"dimensions":[]}


def test_raw_viewport_excludes_sheet_border_title_and_whitespace_but_retains_plan_edges():
    viewport=select_vision_viewport(extracted=_viewport_source(),frame={"frame_id":"F","bounds":[0,0,100,100]})
    x1,y1,x2,y2=viewport["vision_bounds"]
    assert x1>0 and y1>0 and x2<90 and y2<80
    assert x1<20 and y1<20 and x2>=70 and y2>60
    assert viewport["metrics"]["vision_to_frame_ratio"]<.55
    assert viewport["selection_evidence"]["excluded_long_frame_geometry"]==4


def test_focused_and_full_frame_transforms_are_independent_and_cache_is_versioned(tmp_path):
    source=_viewport_source(); frame={"frame_id":"F","bounds":[0,0,100,100]}
    viewport=select_vision_viewport(extracted=source,frame=frame)
    full=render_source_frame(extracted=source,frame=frame,source_hash="abc",cache_dir=tmp_path,
                             width_px=600,render_role="CONTEXT_FULL_FRAME")
    focused=render_source_frame(extracted=source,frame=frame,source_hash="abc",cache_dir=tmp_path,
                                width_px=600,viewport=viewport,render_role="FOCUSED_PLAN")
    assert full["cache_key"]!=focused["cache_key"]
    assert full["transform"]["cad_bounds"]!=focused["transform"]["cad_bounds"]
    assert full["render_version"]==focused["render_version"]==RENDER_VERSION
    focus_transform=RenderTransform(*focused["transform"]["cad_bounds"],*focused["transform"]["pixel_size"],
                                    focused["transform"]["padding_px"])
    assert focus_transform.pixel_to_cad(focus_transform.cad_to_pixel((40,40)))==pytest.approx((40,40))


def test_persian_source_label_is_preserved_as_structured_context(tmp_path):
    source=_viewport_source(); frame={"frame_id":"F","bounds":[0,0,100,100]}
    viewport=select_vision_viewport(extracted=source,frame=frame)
    manifest=render_source_frame(extracted=source,frame=frame,source_hash="abc",cache_dir=tmp_path,
                                 viewport=viewport,render_role="FOCUSED_PLAN")
    context=_raw_source_context(source,manifest)
    assert any(row["text"]=="اتاق خواب" for row in context["raw_texts"])
    assert all(len(row["pixel_point"])==2 for row in context["raw_texts"])


def test_openai_request_uses_configured_model_and_parses_strict_json(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCH_VISION_CACHE_DIR", str(tmp_path / "cache"))
    image = tmp_path / "frame.png"
    from PIL import Image
    Image.new("RGB", (8, 8), "white").save(image)
    captured = {}
    class Responses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text=json.dumps({
                "frame_id":"F1","physical_spaces":[{"vision_space_id":"V1","polygon_px":[[0,0],[8,0],[8,8],[0,8]],
                "semantic_candidates":[{"type":"kitchen","confidence":.97}],"objects_seen":["sink"],"labels_seen":[],
                "boundary_evidence":["enclosure"],"uncertainties":[]}],"functional_zones":[],"doors":[],"windows":[],
                "open_passages":[],"stairs":[],"shafts":[],"suspected_false_boundaries":[],
                "suspected_missing_boundaries":[],"unresolved_regions":[]
            }))
    adapter = OpenAIVisionAdapter(model="configured-model", api_key="test", client=SimpleNamespace(responses=Responses()))
    result = adapter.analyze(image_path=str(image), frame_id="F1",
                             regions=[{"region_id": "S1", "bounds": [0, 0, 1, 1], "pixel_bounds": [0, 0, 8, 8]}])
    assert captured["model"] == "configured-model"
    assert result["physical_spaces"][0]["semantic_candidates"][0]["type"] == "kitchen"
    assert "data:image/png;base64," in captured["input"][0]["content"][1]["image_url"]
    assert captured["input"][0]["content"][1]["detail"] == "original"


def test_deepseek_request_uses_same_contract_and_provider_separated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCH_VISION_CACHE_DIR", str(tmp_path / "cache"))
    image = tmp_path / "frame.png"
    from PIL import Image
    Image.new("RGB", (8, 8), "white").save(image)
    calls = []
    payload = {"frame_id":"F1","physical_spaces":[],"functional_zones":[],"doors":[],"windows":[],
               "open_passages":[],"stairs":[],"shafts":[],"suspected_false_boundaries":[],
               "suspected_missing_boundaries":[],"unresolved_regions":[]}
    class Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(id="resp-1", output_text=json.dumps(payload),
                                   usage=SimpleNamespace(input_tokens=12, output_tokens=3, total_tokens=15))
    client = SimpleNamespace(responses=Responses())
    deepseek = DeepSeekVisionAdapter(model="deepseek-flash", api_key="secret", client=client)
    openai = OpenAIVisionAdapter(model="deepseek-flash", api_key="secret", client=client)
    context={"source_sha256":"a"*64,"render_cache_key":"render-1","scope":"GLOBAL"}
    deepseek.analyze(image_path=str(image), frame_id="F1", regions=[], context=context)
    openai.analyze(image_path=str(image), frame_id="F1", regions=[], context=context)
    assert len(calls) == 2
    assert deepseek.last_call_metadata["provider"] == "deepseek"
    assert deepseek.last_call_metadata["usage"]["total_tokens"] == 15
    assert deepseek.last_call_metadata["cache_key"] != openai.last_call_metadata["cache_key"]


def test_deepseek_cache_hit_avoids_duplicate_request(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCH_VISION_CACHE_DIR",str(tmp_path/"cache"))
    image=tmp_path/"frame.png"
    from PIL import Image
    Image.new("RGB",(8,8),"white").save(image)
    payload={"frame_id":"F1","physical_spaces":[],"functional_zones":[],"doors":[],"windows":[],
             "open_passages":[],"stairs":[],"shafts":[],"suspected_false_boundaries":[],
             "suspected_missing_boundaries":[],"unresolved_regions":[]}
    class Responses:
        calls=0
        def create(self,**kwargs):
            self.calls+=1
            return SimpleNamespace(output_text=json.dumps(payload))
    responses=Responses()
    adapter=DeepSeekVisionAdapter(model="deepseek-flash",api_key="secret",
                                  client=SimpleNamespace(responses=responses))
    kwargs={"image_path":str(image),"frame_id":"F1","regions":[],
            "context":{"source_sha256":"a"*64,"render_cache_key":"r","scope":"GLOBAL"}}
    adapter.analyze(**kwargs); adapter.analyze(**kwargs)
    assert responses.calls == 1
    assert adapter.last_call_metadata["cache_hit"] is True


def _v1_payload(frame_id="F1"):
    return {"frame_id":frame_id,
            "building_shells":[{"shell_id":"S1","polygon_px":[[0,0],[10,0],[10,10],[0,10]],
                                "confidence":.9,"evidence":["continuous exterior"],"uncertainties":[]}],
            "boundary_segments":[{"boundary_id":"B1","geometry_px":[[0,0],[10,0]],
                                  "role":"BUILDING_SHELL","confidence":.95,"evidence":["strong line"]}],
            "exterior_regions":[],"uncertainties":[]}


def _strict_response(payload=None, *, tool_name=DEEPSEEK_V1_TOOL_NAME, arguments=None):
    raw=arguments if arguments is not None else json.dumps(payload or _v1_payload())
    function=SimpleNamespace(name=tool_name,arguments=raw)
    message=SimpleNamespace(tool_calls=[SimpleNamespace(function=function)])
    return SimpleNamespace(id="strict-v1",choices=[SimpleNamespace(message=message)],
                           usage=SimpleNamespace(prompt_tokens=10,completion_tokens=20,total_tokens=30))


def _deepseek_client(*, strict_response=None, strict_error=None, json_response=None, json_error=None):
    class Completions:
        def __init__(self): self.calls=[]
        def create(self,**kwargs):
            self.calls.append(kwargs)
            if kwargs.get("response_format"):
                if json_error: raise json_error
                if json_response is None: raise AssertionError("unexpected JSON_OBJECT fallback")
                return json_response
            if strict_error: raise strict_error
            return strict_response or _strict_response()
    completions=Completions()
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)),completions


def test_v1_shell_boundary_contract_is_small_strict_and_valid():
    payload=_v1_payload()
    assert validate_shell_boundaries_payload(payload,frame_id="F1") is payload
    assert set(SHELL_BOUNDARIES_JSON_SCHEMA["properties"]) == {
        "frame_id","building_shells","boundary_segments","exterior_regions","uncertainties"}
    malformed={**payload,"doors":[]}
    with pytest.raises(VisionRecoveryError) as caught:
        validate_shell_boundaries_payload(malformed,frame_id="F1")
    assert caught.value.code=="VISION_SCHEMA_INVALID"


def test_v1_architectural_qa_rejects_exterior_region_inside_shell():
    payload=_v1_payload(); payload["exterior_regions"]=[{
        "region_id":"E1","polygon_px":[[1,1],[4,1],[4,4],[1,4]],"role":"YARD","confidence":.9}]
    with pytest.raises(VisionRecoveryError) as caught:
        architectural_qa_shell_boundaries(payload,image_size=(20,20))
    assert caught.value.code=="VISION_ARCHITECTURAL_QA_FAILED"
    assert caught.value.details["conflicts"][0]["shell_overlap_ratio"]==1.0


def test_v1_request_has_independent_cache_and_metrics(tmp_path,monkeypatch):
    monkeypatch.setenv("ARCH_VISION_CACHE_DIR",str(tmp_path/"cache"))
    image=tmp_path/"frame.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    client,calls=_deepseek_client(strict_response=_strict_response(_v1_payload()))
    adapter=DeepSeekVisionAdapter(model="deepseek-flash",api_key="secret",
                                  client=client,max_retries=1)
    first=adapter.analyze_shell_boundaries(image_path=str(image),frame_id="F1",
                                           context={"source_sha256":"a"*64})
    second=adapter.analyze_shell_boundaries(image_path=str(image),frame_id="F1",
                                            context={"source_sha256":"a"*64})
    assert first==second and len(calls.calls)==1
    assert adapter.last_call_metadata["cache_hit"] is True
    assert adapter.last_call_metadata["task_type"]=="SHELL_BOUNDARIES_V1"
    function=calls.calls[0]["tools"][0]["function"]
    assert function["strict"] is True and function["name"]==DEEPSEEK_V1_TOOL_NAME
    assert function["parameters"]==DEEPSEEK_SHELL_BOUNDARIES_TOOL_SCHEMA
    assert calls.calls[0]["tool_choice"]["function"]["name"]==DEEPSEEK_V1_TOOL_NAME
    assert adapter.last_call_metadata["transport"]==VisionTransport.STRICT_TOOL_CALL.value


def test_v1_timeout_has_no_blind_retry(tmp_path):
    image=tmp_path/"frame.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    class APITimeoutError(Exception): pass
    client,calls=_deepseek_client(strict_error=APITimeoutError("private body"),
                                  json_error=APITimeoutError("private body"))
    adapter=DeepSeekVisionAdapter(model="deepseek-flash",api_key="secret",
                                  client=client,max_retries=1)
    with pytest.raises(VisionRecoveryError) as caught:
        adapter.analyze_shell_boundaries(image_path=str(image),frame_id="F1")
    assert caught.value.code=="VISION_TIMEOUT" and len(calls.calls)==2
    assert calls.calls[0].get("response_format") is None
    assert calls.calls[1]["response_format"]=={"type":"json_object"}


def test_v1_invalid_provider_payload_is_diagnosed_outside_success_cache(tmp_path,monkeypatch):
    monkeypatch.setenv("ARCH_VISION_CACHE_DIR",str(tmp_path/"cache"))
    monkeypatch.setenv("ARCH_VISION_DIAGNOSTIC_DIR",str(tmp_path/"diagnostics"))
    image=tmp_path/"frame.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    invalid=_v1_payload(); invalid["exterior_regions"]=[{
        "region_id":"E1","polygon_px":[[0,0],[2,0],[2,2]],"role":"YARD","confidence":.8,
        "unexpected":"must not be accepted"}]
    response=_strict_response(invalid)
    client,_calls=_deepseek_client(strict_response=response)
    adapter=DeepSeekVisionAdapter(model="deepseek-flash",api_key="secret",
        client=client,max_retries=0)
    with pytest.raises(VisionRecoveryError) as caught:
        adapter.analyze_shell_boundaries(image_path=str(image),frame_id="F1",
                                         context={"source_sha256":"a"*64})
    assert caught.value.details["validation_path"]=="$.exterior_regions[0]"
    assert caught.value.details["extra_keys"]==["unexpected"]
    diagnostic=json.loads(Path(adapter.last_call_metadata["diagnostic_path"]).read_text())
    assert diagnostic["raw_response_json"]["exterior_regions"][0]["unexpected"]=="must not be accepted"
    assert not list((tmp_path/"cache").glob("vision-*.json"))


def test_deepseek_provider_schema_is_strict_supported_projection():
    def walk(node):
        if isinstance(node,dict):
            assert not ({"minimum","maximum","minItems","maxItems","maxLength"} & set(node))
            if node.get("type")=="object":
                assert node["additionalProperties"] is False
                assert set(node["required"])==set(node["properties"])
            for value in node.values(): walk(value)
        elif isinstance(node,list):
            for value in node: walk(value)
    walk(DEEPSEEK_SHELL_BOUNDARIES_TOOL_SCHEMA)
    assert set(DEEPSEEK_SHELL_BOUNDARIES_TOOL_SCHEMA["properties"])=={
        "frame_id","building_shells","boundary_segments","exterior_regions","uncertainties"}
    assert set(DEEPSEEK_SHELL_BOUNDARIES_TOOL_SCHEMA["properties"]["building_shells"]["items"]["properties"])=={
        "shell_id","polygon_px","confidence","evidence","uncertainties"}
    assert len(json.dumps(DEEPSEEK_SHELL_BOUNDARIES_TOOL_SCHEMA))>1500
    assert SHELL_BOUNDARIES_JSON_SCHEMA["properties"]["building_shells"]["maxItems"]==3


@pytest.mark.parametrize("response,code",[
    (_strict_response(tool_name="wrong_tool"),"VISION_TOOL_NAME_INVALID"),
    (SimpleNamespace(id="none",choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[]))],usage=None),
     "VISION_TOOL_CALL_MISSING"),
    (_strict_response(arguments="not-json"),"VISION_JSON_INVALID"),
])
def test_strict_tool_failures_are_explicit_and_never_fallback(tmp_path,monkeypatch,response,code):
    monkeypatch.setenv("ARCH_VISION_CACHE_DIR",str(tmp_path/"cache"))
    monkeypatch.setenv("ARCH_VISION_DIAGNOSTIC_DIR",str(tmp_path/"diagnostics"))
    image=tmp_path/"frame.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    client,calls=_deepseek_client(strict_response=response)
    adapter=DeepSeekVisionAdapter(model="deepseek-flash",api_key="secret",client=client)
    with pytest.raises(VisionRecoveryError) as caught:
        adapter.analyze_shell_boundaries(image_path=str(image),frame_id="F1")
    assert caught.value.code==code and len(calls.calls)==1
    assert not list((tmp_path/"cache").glob("vision-*.json"))


@pytest.mark.parametrize("mutate",[
    lambda payload: payload["building_shells"][0].update({"extra":True}),
    lambda payload: payload["building_shells"][0].pop("shell_id"),
    lambda payload: payload["building_shells"][0].update({"polygon_px":[[0,0],[1,1]]}),
])
def test_strict_tool_cannot_bypass_canonical_contract(tmp_path,monkeypatch,mutate):
    monkeypatch.setenv("ARCH_VISION_CACHE_DIR",str(tmp_path/"cache"))
    image=tmp_path/"frame.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    payload=_v1_payload(); mutate(payload)
    client,_calls=_deepseek_client(strict_response=_strict_response(payload))
    adapter=DeepSeekVisionAdapter(model="deepseek-flash",api_key="secret",client=client)
    with pytest.raises(VisionRecoveryError):
        adapter.analyze_shell_boundaries(image_path=str(image),frame_id="F1")
    assert not list((tmp_path/"cache").glob("vision-*.json"))


def test_transport_cache_identity_and_capability_routing(tmp_path):
    image=tmp_path/"frame.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    client,_calls=_deepseek_client()
    adapter=DeepSeekVisionAdapter(model="deepseek-flash",api_key="secret",client=client)
    strict=adapter._v1_material(image_path=str(image),frame_id="F1",context={},
                                transport=VisionTransport.STRICT_TOOL_CALL)
    fallback=adapter._v1_material(image_path=str(image),frame_id="F1",context={},
                                  transport=VisionTransport.JSON_OBJECT)
    assert strict["cache_key"]!=fallback["cache_key"]
    capability=PROVIDER_CAPABILITY_MATRIX[("deepseek","deepseek-flash",VisionTask.SHELL_BOUNDARIES_V1.value)]
    assert capability["preferred_transport"]==VisionTransport.STRICT_TOOL_CALL.value
    assert VisionTransport.RESPONSES_JSON_SCHEMA.value in capability["unsupported_transports"]
    assert capability["status"]=="TRANSPORT_QUALIFIED_FREEFORM_GEOMETRY_UNQUALIFIED"
    assert capability["reliability_state"]=="ARCHITECTURAL_QA_FAILED"


def test_timeout_allows_one_json_object_fallback_and_canonical_validation(tmp_path,monkeypatch):
    monkeypatch.setenv("ARCH_VISION_CACHE_DIR",str(tmp_path/"cache"))
    image=tmp_path/"frame.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    class APITimeoutError(Exception): pass
    json_response=SimpleNamespace(id="json-v1",choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps(_v1_payload())))],
        usage=SimpleNamespace(prompt_tokens=11,completion_tokens=12,total_tokens=23))
    client,calls=_deepseek_client(strict_error=APITimeoutError("timeout"),json_response=json_response)
    adapter=DeepSeekVisionAdapter(model="deepseek-flash",api_key="secret",client=client)
    assert adapter.analyze_shell_boundaries(image_path=str(image),frame_id="F1")==_v1_payload()
    assert len(calls.calls)==2
    assert adapter.last_call_metadata["transport"]==VisionTransport.JSON_OBJECT.value


@pytest.mark.parametrize("content,code",[("not-json","VISION_JSON_INVALID"),
    (json.dumps({"frame_id":"F1"}),"VISION_SCHEMA_INVALID")])
def test_json_object_fallback_still_fails_closed(tmp_path,content,code):
    image=tmp_path/"frame.png"
    from PIL import Image
    Image.new("RGB",(20,20),"white").save(image)
    class APITimeoutError(Exception): pass
    response=SimpleNamespace(id="json-bad",choices=[SimpleNamespace(message=SimpleNamespace(content=content))],usage=None)
    client,_calls=_deepseek_client(strict_error=APITimeoutError("timeout"),json_response=response)
    adapter=DeepSeekVisionAdapter(model="deepseek-flash",api_key="secret",client=client)
    with pytest.raises(VisionRecoveryError) as caught:
        adapter.analyze_shell_boundaries(image_path=str(image),frame_id="F1")
    assert caught.value.code==code


def test_provider_routing_and_deepseek_base_url(monkeypatch):
    captured=[]
    class FakeOpenAI:
        def __init__(self, **kwargs): captured.append(kwargs)
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    monkeypatch.setenv("ARCH_VISION_PROVIDER", "deepseek")
    monkeypatch.setenv("ARCH_VISION_MODEL", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-logged")
    adapter, error = configured_vision_adapter()
    assert error is None and isinstance(adapter, DeepSeekVisionAdapter)
    assert [str(row["base_url"]).rstrip("/") for row in captured] == [
        "https://api.deepseek.com","https://api.deepseek.com/beta"]
    assert all(row["api_key"]=="not-logged" for row in captured)


def test_normal_engineering_entrypoint_routes_to_deepseek(monkeypatch,tmp_path):
    monkeypatch.setenv("ARCH_VISION_PROVIDER","deepseek")
    monkeypatch.setenv("ARCH_VISION_MODEL","deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_API_KEY","secret")
    monkeypatch.setenv("ARCH_VISION_CACHE_DIR",str(tmp_path/"cache"))
    calls=[]
    class Responses:
        def create(self,**kwargs):
            calls.append(kwargs)
            prompt=kwargs["input"][0]["content"][0]["text"]
            frame_id=json.loads(prompt.split("FRAME_ID=",1)[1].split(". Return JSON",1)[0])
            return SimpleNamespace(output_text=json.dumps({"frame_id":frame_id,"physical_spaces":[],
                "functional_zones":[],"doors":[],"windows":[],"open_passages":[],"stairs":[],"shafts":[],
                "suspected_false_boundaries":[],"suspected_missing_boundaries":[],"unresolved_regions":[]}))
    class FakeOpenAI:
        def __init__(self,**kwargs): self.responses=Responses()
    monkeypatch.setattr("openai.OpenAI",FakeOpenAI)
    drawing=_drawing(tmp_path/"deepseek-entrypoint.dxf")
    result=run_engineering_pipeline(drawing,design_basis={})
    assert calls
    assert result["architecture"]["vision_reconciliation"]["provider"] == "deepseek"
    assert result["architecture"]["completeness"]["downstream_engineering_allowed"] is False


@pytest.mark.parametrize("provider,credential", [("deepseek", "DEEPSEEK_API_KEY"), ("openai", "OPENAI_API_KEY")])
def test_missing_provider_secret_fails_closed(monkeypatch, provider, credential):
    monkeypatch.setenv("ARCH_VISION_PROVIDER", provider)
    monkeypatch.setenv("ARCH_VISION_MODEL", "configured-model")
    monkeypatch.delenv(credential, raising=False)
    adapter, error = configured_vision_adapter()
    assert adapter is None
    assert error["error_code"] == "VISION_CREDENTIAL_NOT_CONFIGURED"


def test_transient_provider_failure_has_one_bounded_retry(tmp_path):
    image=tmp_path/"frame.png"
    from PIL import Image
    Image.new("RGB",(8,8),"white").save(image)
    class APITimeoutError(Exception): pass
    class Responses:
        def __init__(self): self.calls=0
        def create(self, **kwargs): self.calls += 1; raise APITimeoutError("secret request payload")
    responses=Responses()
    adapter=DeepSeekVisionAdapter(model="deepseek-flash",api_key="secret",
                                  client=SimpleNamespace(responses=responses),max_retries=1)
    with pytest.raises(VisionRecoveryError) as caught:
        adapter.analyze(image_path=str(image),frame_id="F1",regions=[])
    assert caught.value.code == "VISION_TIMEOUT"
    assert "secret" not in str(caught.value)
    assert responses.calls == 2


@pytest.mark.parametrize("status,expected", [(401,"VISION_AUTH_ERROR"),(402,"VISION_BUDGET_LIMIT"),
                                               (413,"VISION_IMAGE_TOO_LARGE"),(429,"VISION_RATE_LIMIT"),
                                               (503,"VISION_PROVIDER_UNAVAILABLE")])
def test_provider_http_failures_are_explicit_and_sanitized(tmp_path, status, expected):
    image=tmp_path/f"frame-{status}.png"
    from PIL import Image
    Image.new("RGB",(8,8),"white").save(image)
    class ProviderFailure(Exception):
        status_code=status
    class Responses:
        def create(self, **kwargs): raise ProviderFailure("Authorization: Bearer forbidden-secret")
    adapter=DeepSeekVisionAdapter(model="deepseek-flash",api_key="forbidden-secret",
                                  client=SimpleNamespace(responses=Responses()),max_retries=0)
    with pytest.raises(VisionRecoveryError) as caught:
        adapter.analyze(image_path=str(image),frame_id="F1",regions=[])
    assert caught.value.code == expected
    assert "secret" not in str(caught.value)


def test_incomplete_and_malformed_responses_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCH_VISION_CACHE_DIR",str(tmp_path/"cache"))
    image=tmp_path/"frame.png"
    from PIL import Image
    Image.new("RGB",(8,8),"white").save(image)
    for response,code in [(SimpleNamespace(status="incomplete",output_text=None),"VISION_RESPONSE_INCOMPLETE"),
                          (SimpleNamespace(status="completed",output_text="not-json"),"VISION_JSON_INVALID")]:
        adapter=DeepSeekVisionAdapter(model="deepseek-flash",api_key="secret",
                                      client=SimpleNamespace(responses=SimpleNamespace(create=lambda **_:response)),
                                      max_retries=0)
        with pytest.raises(VisionRecoveryError) as caught:
            adapter.analyze(image_path=str(image),frame_id="F1",regions=[])
        assert caught.value.code == code


def test_oversized_inline_image_is_rejected_before_provider_call(tmp_path,monkeypatch):
    image=tmp_path/"frame.png"; image.write_bytes(b"12345")
    monkeypatch.setattr("cad_engine.architectural_vision_recovery.MAX_INLINE_IMAGE_BYTES",4)
    responses=SimpleNamespace(create=lambda **_:pytest.fail("provider must not be called"))
    adapter=DeepSeekVisionAdapter(model="deepseek-flash",api_key="secret",
                                  client=SimpleNamespace(responses=responses))
    with pytest.raises(VisionRecoveryError) as caught:
        adapter.analyze(image_path=str(image),frame_id="F1",regions=[])
    assert caught.value.code == "VISION_IMAGE_TOO_LARGE"


def test_unknown_provider_and_missing_model_are_explicit(monkeypatch):
    monkeypatch.setenv("ARCH_VISION_PROVIDER","unknown")
    adapter,error=configured_vision_adapter()
    assert adapter is None and error["error_code"]=="VISION_PROVIDER_UNSUPPORTED"
    monkeypatch.setenv("ARCH_VISION_PROVIDER","deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY","secret")
    monkeypatch.delenv("ARCH_VISION_MODEL",raising=False)
    adapter,error=configured_vision_adapter()
    assert adapter is None and error["error_code"]=="VISION_MODEL_NOT_CONFIGURED"


def test_provider_failure_cannot_release_downstream_engineering(tmp_path):
    class FailingAdapter:
        provider="deepseek"; model="deepseek-flash"
        def analyze(self,**kwargs):
            raise VisionRecoveryError("VISION_PROVIDER_UNAVAILABLE","Vision provider is temporarily unavailable")
    model=reconstruct_architecture(_drawing(tmp_path/"provider-failure.dxf"),vision_adapter=FailingAdapter())
    assert model["vision_reconciliation"]["status"] == "FAILED"
    assert model["completeness"]["downstream_engineering_allowed"] is False


def _space(identity, polygon):
    return {"physical_space_id":identity,"space_id":identity,"frame_id":"F1","polygon":polygon,
            "interior_rings":[],"category":"unknown","use":"unknown","status":"INPUT_REQUIRED",
            "confidence":0.0,"evidence":[],"source_handles":[],"functional_zones":[]}


def _merge_analysis():
    return {"frame_id":"F1","physical_spaces":[{"vision_space_id":"V1",
            "polygon_px":[[0,100],[100,100],[100,40],[0,40]],
            "semantic_candidates":[{"type":"living","confidence":.98}],"objects_seen":["sofa"],
            "labels_seen":[],"boundary_evidence":["single enclosure"],"uncertainties":[]}],
            "functional_zones":[],"doors":[],"windows":[],"open_passages":[],"stairs":[],"shafts":[],
            "suspected_false_boundaries":[],"suspected_missing_boundaries":[],"unresolved_regions":[]}


def test_vision_merge_requires_weak_cad_boundary():
    transform=RenderTransform(0,0,10,10,100,100,0)
    spaces=[_space("A",[[0,0],[5,0],[5,6],[0,6]]),_space("B",[[5,0],[10,0],[10,6],[5,6]])]
    result=reconcile_and_repair(analysis=_merge_analysis(),spaces=spaces,transform=transform,
                                segments=[],source_hash="abc",tolerance=.01)
    assert result["accepted_repairs"]==1
    assert len(spaces)==1 and spaces[0]["category"]=="living"


def test_vision_cannot_merge_across_strong_cad_wall():
    transform=RenderTransform(0,0,10,10,100,100,0)
    spaces=[_space("A",[[0,0],[5,0],[5,6],[0,6]]),_space("B",[[5,0],[10,0],[10,6],[5,6]])]
    segment={"segment_id":"SEG1","source_handle":"H1","geometry":[[5,0],[5,6]],"status":"ACCEPTED"}
    result=reconcile_and_repair(analysis=_merge_analysis(),spaces=spaces,transform=transform,
                                segments=[segment],source_hash="abc",tolerance=.01)
    assert result["accepted_repairs"]==0
    assert len(spaces)==2
    assert result["repairs"][0]["reason"]=="STRONG_WALL_OR_GEOMETRY_CONFLICT"


def test_portal_search_tolerates_pixel_error_but_continuous_strong_wall_still_blocks():
    transform=RenderTransform(0,0,10,10,1000,1000,0)
    analysis={"frame_id":"F1","physical_spaces":[],"functional_zones":[],"doors":[{
        "geometry_px":[[498,400],[498,600]],"connects":["A","B"],"evidence":["door-like"],"confidence":.99}],
        "windows":[],"open_passages":[],"stairs":[],"shafts":[],"suspected_false_boundaries":[],
        "suspected_missing_boundaries":[],"unresolved_regions":[]}
    segment={"segment_id":"SEG1","source_handle":"H1","geometry":[[5,0],[5,10]],"status":"ACCEPTED"}
    result=reconcile_and_repair(analysis=analysis,spaces=[],transform=transform,segments=[segment],
                                source_hash="abc",tolerance=.001)
    repair=result["repairs"][0]
    assert repair["cad_evidence"]["near_wall_segment_ids"]==["SEG1"]
    assert repair["accepted"] is False
    assert repair["reason"]=="NO_WALL_GAP"


def test_bounded_global_recovery_fuses_semantics_and_recomputes_gate(tmp_path):
    adapter = FakeAdapter()
    model = reconstruct_architecture(_drawing(tmp_path / "vision.dxf"), vision_adapter=adapter)
    assert model["physical_spaces"][0]["category"] == "living"
    assert model["physical_spaces"][0]["status"] == "HIGH_CONFIDENCE"
    assert model["completeness"]["downstream_engineering_allowed"] is True
    assert model["vision_reconciliation"]["calls"] == 1
    assert len(adapter.calls) == 1
    assert model["diagnostics"]["dxf_parse_count"] == 1


def test_actual_engineering_entrypoint_uses_configured_adapter(monkeypatch, tmp_path):
    adapter = FakeAdapter()
    monkeypatch.setattr("cad_engine.architectural_vision_recovery.configured_vision_adapter",
                        lambda: (adapter, None))
    result = run_engineering_pipeline(_drawing(tmp_path / "entrypoint.dxf"), design_basis={})
    assert adapter.calls
    assert result["architecture"]["vision_reconciliation"]["status"] == "COMPLETE"
    assert result.get("blocked_at") != "architecture_completeness"


def test_actual_upload_analysis_path_invokes_vision_before_human_review(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CAD_OUTPUT_DIR", str(tmp_path / "cad"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'upload.db'}")
    adapter=FakeAdapter()
    monkeypatch.setattr("cad_engine.architectural_vision_recovery.configured_vision_adapter",lambda:(adapter,None))
    from app.main_health import main_auto
    result=main_auto.analyze_dxf_enhanced(_drawing(tmp_path/"upload.dxf"))
    canonical=result["canonical_architecture_model"]
    assert adapter.calls
    assert canonical["vision_reconciliation"]["status"]=="COMPLETE"
    assert canonical["completeness"]["downstream_engineering_allowed"] is True
