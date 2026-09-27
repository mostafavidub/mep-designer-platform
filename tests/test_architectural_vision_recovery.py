import json
from types import SimpleNamespace

import ezdxf
import pytest

from cad_engine.architectural_space_engine import reconstruct_architecture
from cad_engine.architectural_vision_recovery import (
    OpenAIVisionAdapter, RenderTransform, VisionRecoveryError, _validate_payload,
    reconcile_and_repair, render_source_frame,
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
    def analyze(self, *, image_path, frame_id, regions):
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
