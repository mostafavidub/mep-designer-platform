from pathlib import Path
from types import SimpleNamespace

import ezdxf
from ezdxf.entities.dimstyleoverride import DimStyleOverride

from cad_engine.mechanical_dimensioning import (
    APPID, LAYERS, apply_mechanical_dimensions, validate_exact_mechanical_dimensions,
)


def _fixture(tmp_path, *, unit=1.0, family="WATER", targets=None):
    doc = ezdxf.new("R2010")
    if unit is None:
        doc.header["$INSUNITS"] = 0
    # An architectural dimension proves preservation and namespace isolation.
    source_dim = doc.modelspace().add_linear_dim(base=(0, 2), p1=(0, 0), p2=(2, 0))
    source_dim.render()
    board = SimpleNamespace(code="M-101", bounds=(0, 0, 21, 29.7), plan_area=(1, 4, 20, 29), title_area=(0, 0, 21, 3.1))
    manifest = [{"old_sheet": "S", "code": "M-101", "family": family,
                 "source_plan_id": "PLAN-1", "source_bounds": [0, 0, 10, 10],
                 "uniform_transform": {"scale_x": 1.8, "scale_y": 1.8, "offset_x": 1.5, "offset_y": 5.0}}]
    targets = targets if targets is not None else [
        {"owner_id": "EQ-1", "kind": "equipment", "source_point": (5, 6), "paper_point": (10.5, 15.8)},
        {"owner_id": "ROUTE-1", "kind": "route_terminal", "source_point": (8, 3), "paper_point": (15.9, 10.4)},
    ]
    reports = [{"sheet": "M-101", "dimension_targets": targets}]
    answers = {"_plan_analysis": {"architectural_auto": {"effective_unit_to_m": unit}}} if unit else {}
    result = apply_mechanical_dimensions(doc, manifest, {"S": board}, reports, answers)
    path = tmp_path / "dimensions.dxf"
    doc.saveas(path)
    return path, result, {"S": board}


def test_generates_scaled_owner_linked_dimensions_and_preserves_architecture(tmp_path):
    path, report, boards = _fixture(tmp_path)
    assert report["status"] == "PASS"
    assert report["dimension_count"] == 4
    exact = validate_exact_mechanical_dimensions(path, report, boards)
    assert exact["status"] == "PASS"
    doc = ezdxf.readfile(path)
    assert len(doc.modelspace().query("DIMENSION")) == 5
    generated = [e for e in doc.modelspace().query("DIMENSION") if e.dxf.layer in LAYERS.values()]
    assert {e.get_xdata(APPID)[1].value for e in generated} == {"EQ-1", "ROUTE-1"}
    assert sorted(round(float(row["measured_mm"])) for row in exact["records"]) == [3000, 5000, 6000, 8000]


def test_unknown_units_and_missing_targets_are_explicit_input_blockers(tmp_path):
    path, report, _ = _fixture(tmp_path, unit=None)
    assert report["status"] == "INPUT_REQUIRED"
    assert report["dimension_count"] == 0
    assert "CALIBRATED_UNIT_AND_UNIFORM_SCALE_REQUIRED" in report["blockers"][0]
    _, missing, _ = _fixture(tmp_path, targets=[])
    assert missing["status"] == "INPUT_REQUIRED"
    assert "NO_TRACEABLE_MECHANICAL_DIMENSION_TARGET" in missing["blockers"][0]


def test_non_plan_families_are_not_dimensioned(tmp_path):
    _, report, _ = _fixture(tmp_path, family="COVER")
    assert report["status"] == "NOT_APPLICABLE"
    assert report["dimension_count"] == 0


def test_zero_axis_is_omitted_without_zero_dimension(tmp_path):
    targets = [{"owner_id": "EQ-ORIGIN-X", "kind": "equipment", "source_point": (0, 4), "paper_point": (1.5, 12.2)}]
    path, report, boards = _fixture(tmp_path, targets=targets)
    assert report["dimension_count"] == 1
    assert report["records"][0]["axis"] == "Y"
    assert validate_exact_mechanical_dimensions(path, report, boards)["status"] == "PASS"


def test_nonzero_source_origin_maps_datum_inside_plan_not_titleblock(tmp_path):
    doc=ezdxf.new("R2010")
    board=SimpleNamespace(code="M-131",bounds=(0,0,21,29.7),plan_area=(1,4,20,29),title_area=(0,0,21,3.1))
    source_bounds=[7700,-3960,7710,-3950];scale=1.5;offset_x=1.5-source_bounds[0]*scale;offset_y=5-source_bounds[1]*scale
    source_point=(7705,-3954);paper_point=(source_point[0]*scale+offset_x,source_point[1]*scale+offset_y)
    manifest=[{"old_sheet":"S","code":"M-131","family":"HEATING","source_plan_id":"P1",
               "source_bounds":source_bounds,"uniform_transform":{"scale_x":scale,"scale_y":scale,"offset_x":offset_x,"offset_y":offset_y}}]
    reports=[{"sheet":"M-131","dimension_targets":[{"owner_id":"RAD-1","kind":"equipment","source_point":source_point,"paper_point":paper_point}]}]
    answers={"_plan_analysis":{"architectural_auto":{"effective_unit_to_m":1.0}}}
    result=apply_mechanical_dimensions(doc,manifest,{"S":board},reports,answers)
    path=tmp_path/"nonzero-origin.dxf";doc.saveas(path)
    assert result["status"]=="PASS"
    assert validate_exact_mechanical_dimensions(path,result,{"S":board})["status"]=="PASS"
    for entity in doc.modelspace().query("DIMENSION"):
        assert all(point.y>=board.plan_area[1]+.44 for point in (entity.dxf.defpoint,entity.dxf.defpoint2,entity.dxf.defpoint3))


def test_exact_qa_rejects_mismatch_orphan_duplicate_and_outside_board(tmp_path):
    path, report, boards = _fixture(tmp_path)
    doc = ezdxf.readfile(path)
    generated = [e for e in doc.modelspace().query("DIMENSION") if e.dxf.layer in LAYERS.values()]
    # Numeric mismatch.
    tags = list(generated[0].get_xdata(APPID)); tags[-1] = (1000, "999999")
    generated[0].set_xdata(APPID, tags)
    # Orphan owner.
    tags = list(generated[1].get_xdata(APPID)); tags[1] = (1000, "UNKNOWN-OWNER")
    generated[1].set_xdata(APPID, tags)
    # Out of board.
    generated[2].dxf.defpoint2 = (999, 999, 0)
    corrupted_override = DimStyleOverride(generated[2])
    corrupted_override.update({"dimlfac": 12.0})
    corrupted_override.commit()
    # Duplicate semantic identity.
    duplicate = generated[3].copy(); doc.modelspace().add_entity(duplicate)
    doc.saveas(path)
    exact = validate_exact_mechanical_dimensions(path, report, boards)
    assert exact["status"] == "FAIL"
    joined = "|".join(exact["errors"])
    assert "dimension_measurement_mismatch" in joined
    assert "orphan_dimension" in joined
    assert "dimension_outside_board" in joined
    assert "dimension_scale_override_mismatch" in joined
    assert "duplicate_dimension_identity" in joined


def test_generation_is_deterministic_and_owner_deduplicated(tmp_path):
    duplicate_owner = [
        {"owner_id": "EQ-1", "kind": "route_terminal", "source_point": (1, 1), "paper_point": (3.3, 6.8)},
        {"owner_id": "EQ-1", "kind": "equipment", "source_point": (5, 6), "paper_point": (10.5, 15.8)},
    ]
    _, first, _ = _fixture(tmp_path, targets=duplicate_owner)
    _, second, _ = _fixture(tmp_path, targets=duplicate_owner)
    assert [r["semantic_id"] for r in first["records"]] == [r["semantic_id"] for r in second["records"]]
    assert len({r["owner_id"] for r in first["records"]}) == 1
