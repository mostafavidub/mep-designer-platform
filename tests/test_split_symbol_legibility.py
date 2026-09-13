import ezdxf

from cad_engine.mechanical_design_core import _boards, _ensure_ac_blocks
from cad_engine.mechanical_release_hardening import validate_split_ac_visual_legibility


def test_canonical_idu_survives_visual_gate_in_both_orientations(tmp_path):
    row = {
        "old_sheet": "S1",
        "code": "M-C-01",
        "family": "SPLIT_AC",
        "level": "GROUND",
        "title_fa": "Split AC plan",
    }
    board = _boards([row])["S1"]
    doc = ezdxf.new("R2013")
    _ensure_ac_blocks(doc)
    msp = doc.modelspace()
    x1, y1, x2, y2 = board.plan_area
    msp.add_blockref(
        "ENGI_AC_INDOOR", (x1 + 3, y1 + 4),
        dxfattribs={"layer": "0", "rotation": 0},
    )
    msp.add_blockref(
        "ENGI_AC_INDOOR", (min(x1 + 8, x2 - 3), y1 + 4),
        dxfattribs={"layer": "0", "rotation": 90},
    )
    path = tmp_path / "split-orientations.dxf"
    doc.saveas(path)

    result = validate_split_ac_visual_legibility(
        path, {"boards": {board.sheet: vars(board)}}, tmp_path / "previews"
    )

    assert result["status"] == "PASS", result
    units = result["boards"][0]["units"]
    assert len(units) == 2
    assert all(unit["pixel_long_side"] >= 28 for unit in units)
    assert all(unit["pixel_short_side"] >= 14 for unit in units)


def test_split_visual_threshold_remains_fail_closed_for_undersized_idu(tmp_path):
    row = {
        "old_sheet": "S1",
        "code": "M-C-01",
        "family": "SPLIT_AC",
        "level": "GROUND",
        "title_fa": "Split AC plan",
    }
    board = _boards([row])["S1"]
    doc = ezdxf.new("R2013")
    block = doc.blocks.new("ENGI_AC_INDOOR")
    block.add_lwpolyline(
        [(-0.05, -0.02), (0.05, -0.02), (0.05, 0.02), (-0.05, 0.02)],
        close=True,
    )
    x1, y1, _, _ = board.plan_area
    doc.modelspace().add_blockref("ENGI_AC_INDOOR", (x1 + 3, y1 + 4))
    path = tmp_path / "undersized-split.dxf"
    doc.saveas(path)

    result = validate_split_ac_visual_legibility(
        path, {"boards": {board.sheet: vars(board)}}
    )

    assert result["status"] == "FAIL"
    assert any(error.startswith("split_symbol_too_small:S1:") for error in result["errors"])
