import json
from types import SimpleNamespace

import ezdxf
import pytest

from cad_engine.architectural_space_engine import reconstruct_architecture
from cad_engine.architectural_vision_recovery import (
    DeepSeekVisionAdapter, GLOBAL_JSON_SCHEMA, OpenAIVisionAdapter, RenderTransform, VisionRecoveryError, _validate_payload,
    configured_vision_adapter, reconcile_and_repair, render_source_frame,
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


def test_provider_routing_and_deepseek_base_url(monkeypatch):
    captured={}
    class FakeOpenAI:
        def __init__(self, **kwargs): captured.update(kwargs)
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    monkeypatch.setenv("ARCH_VISION_PROVIDER", "deepseek")
    monkeypatch.setenv("ARCH_VISION_MODEL", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-logged")
    adapter, error = configured_vision_adapter()
    assert error is None and isinstance(adapter, DeepSeekVisionAdapter)
    assert str(captured["base_url"]).rstrip("/") == "https://api.deepseek.com"
    assert captured["api_key"] == "not-logged"


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
