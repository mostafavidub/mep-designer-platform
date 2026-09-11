from pathlib import Path

import ezdxf

from cad_engine import sheet_visual_qa as visual


def _board(code="M-101", family="WATER"):
    return {"code": code, "family": family, "bounds": (0, 0, 21, 29.7),
            "plan_area": (0.5, 2.5, 20.5, 29.2)}


def _issued(path: Path, board=None):
    board = board or _board(); doc = ezdxf.new("R2010"); msp = doc.modelspace()
    doc.layers.add("WALL"); doc.layers.add("ENGITOOLS-M-WATER")
    msp.add_lwpolyline([(1, 3), (19, 3), (19, 25), (1, 25)], close=True, dxfattribs={"layer": "WALL"})
    msp.add_line((2, 5), (18, 5), dxfattribs={"layer": "ENGITOOLS-M-WATER"})
    msp.add_text("CW DN25", dxfattribs={"layer": "ENGITOOLS-M-WATER", "height": .1}).set_placement((5, 5.5))
    doc.saveas(path)
    return {"boards": {"S1": board}, "manifest": [{"old_sheet": "S1", "code": board["code"]}]}


def _fake_render(_doc, _bounds, path, _profile, _sessions=None):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"render" * 300)
    return {"path": str(path), "sha256": "a" * 64, "size_bytes": path.stat().st_size,
            "ink_pixels": 500, "total_pixels": 1000, "ink_ratio": .5, "status": "PASS"}


def test_complete_sheet_set_gets_per_sheet_profiles_scores_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr(visual, "_render_profile", _fake_render)
    path = tmp_path / "issued.dxf"; composition = _issued(path)
    result = visual.validate_all_sheet_visual_qa(path, composition, tmp_path / "previews")
    assert result["status"] == "PASS", result
    assert result["sheet_count"] == result["manifest_sheet_count"] == 1
    assert result["sheets"][0]["score"] == 100
    assert {"color", "monochrome", "overview", "content"}.issubset(result["sheets"][0]["render_profiles"])
    assert Path(result["report_path"]).exists()
    assert result["independent_visual_review"]["status"] == "INPUT_REQUIRED"


def test_manifest_mismatch_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(visual, "_render_profile", _fake_render)
    path = tmp_path / "issued.dxf"; composition = _issued(path)
    composition["manifest"][0]["code"] = "M-999"
    result = visual.validate_all_sheet_visual_qa(path, composition, tmp_path / "previews")
    assert result["status"] == "FAIL"
    assert "manifest_board_identity_mismatch" in result["errors"]


def test_blank_plan_and_missing_architecture_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(visual, "_render_profile", _fake_render)
    path = tmp_path / "blank.dxf"; ezdxf.new("R2010").saveas(path)
    composition = {"boards": {"S1": _board()}, "manifest": [{"code": "M-101"}]}
    result = visual.validate_all_sheet_visual_qa(path, composition, tmp_path / "previews")
    assert result["status"] == "FAIL"
    assert any("no_mechanical_visual_content" in item for item in result["errors"])
    assert any("architecture_underlay_not_visible" in item for item in result["errors"])


def test_service_schematic_does_not_require_architecture_underlay(tmp_path, monkeypatch):
    monkeypatch.setattr(visual, "_render_profile", _fake_render)
    board = _board(code="M-151", family="WATER")
    board["level"] = "SERVICE"
    path = tmp_path / "service.dxf"
    doc = ezdxf.new("R2010"); msp = doc.modelspace()
    doc.layers.add("ENGITOOLS-M-WATER")
    msp.add_line((2, 5), (18, 5), dxfattribs={"layer": "ENGITOOLS-M-WATER"})
    msp.add_text("RISER CW DN25", dxfattribs={"layer": "ENGITOOLS-M-WATER", "height": .1}).set_placement((5, 5.5))
    doc.saveas(path)
    composition = {"boards": {"S1": board}, "manifest": [{"old_sheet": "S1", "code": "M-151"}]}
    result = visual.validate_all_sheet_visual_qa(path, composition, tmp_path / "previews")
    assert result["status"] == "PASS", result
    assert "architecture_underlay_not_visible" not in result["sheets"][0]["errors"]


def test_tiny_text_overlap_density_and_empty_render_are_destructive_failures(tmp_path, monkeypatch):
    def empty_render(_doc, _bounds, path, _profile, _sessions=None):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"x")
        return {"path": str(path), "size_bytes": 1, "ink_pixels": 0, "total_pixels": 1,
                "ink_ratio": 0, "status": "FAIL"}
    monkeypatch.setattr(visual, "_render_profile", empty_render)
    path = tmp_path / "issued.dxf"; composition = _issued(path)
    doc = ezdxf.readfile(path); msp = doc.modelspace()
    for _ in range(3):
        msp.add_text("OVERLAP", dxfattribs={"layer": "ENGITOOLS-M-WATER", "height": .01}).set_placement((5, 5.5))
    doc.saveas(path)
    result = visual.validate_all_sheet_visual_qa(path, composition, tmp_path / "previews")
    assert result["status"] == "FAIL"
    assert any("plotted_text_below_minimum" in item for item in result["errors"])
    assert any("annotation_overlap" in item for item in result["errors"])
    assert any("render_empty" in item for item in result["errors"])


def test_baseline_regression_and_review_coverage_are_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(visual, "_render_profile", _fake_render)
    path = tmp_path / "issued.dxf"; composition = _issued(path)
    result = visual.validate_all_sheet_visual_qa(
        path, composition, tmp_path / "previews",
        baseline={"M-101": {"mechanical_entities": 99, "architecture_entities": 1, "annotation_count": 1}},
        release_context={"independent_visual_review": {"reviewer_id": "reviewer-1", "evidence_sha256": "b" * 64,
                                                        "reviewed_sheet_codes": ["M-999"]}})
    assert result["status"] == "FAIL"
    assert any("baseline_regression" in item for item in result["errors"])
    assert "independent_visual_review_sheet_coverage_mismatch" in result["errors"]


def test_real_renderer_reuses_two_sessions_for_all_sheet_crops(tmp_path, monkeypatch):
    created = []
    class Figure:
        def savefig(self, path, **_kwargs):
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"render" * 300)
    class Axis:
        def set_xlim(self, *_args): pass
        def set_ylim(self, *_args): pass
        def set_aspect(self, *_args, **_kwargs): pass
    class Canvas:
        def draw(self): pass
        def buffer_rgba(self):
            import numpy as np
            return np.zeros((20, 20, 4), dtype="uint8")
    class Plot:
        @staticmethod
        def close(fig): created.append(("closed", id(fig)))
    # Verify the explicit closer, which is the resource boundary used after all
    # board crops. Functional crop coverage is exercised by the tests above.
    sessions = {"color": (Figure(), Axis(), Plot, None), "monochrome": (Figure(), Axis(), Plot, None)}
    visual._close_render_sessions(sessions)
    assert sessions == {}
    assert len(created) == 2


def test_render_inventory_never_keeps_color_and_monochrome_sessions_together(tmp_path, monkeypatch):
    active = set(); maximum = []
    def render(_doc, _bounds, path, profile, sessions):
        sessions.setdefault(profile, (object(), object(), object(), object()))
        active.add(profile); maximum.append(len(active))
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"render" * 300)
        return {"path": str(path), "size_bytes": path.stat().st_size, "ink_pixels": 500,
                "total_pixels": 1000, "ink_ratio": .5, "status": "PASS"}
    def close(sessions):
        active.difference_update(sessions); sessions.clear()
    monkeypatch.setattr(visual, "_render_profile", render)
    monkeypatch.setattr(visual, "_close_render_sessions", close)
    inventory, failures = visual._render_board_inventory(object(), {"S1": _board()}, tmp_path)
    assert failures == {}
    assert maximum and max(maximum) == 1
    assert {"color", "monochrome", "overview", "content"} == set(inventory["M-101"])
