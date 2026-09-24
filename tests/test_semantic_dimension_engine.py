import shutil
from pathlib import Path

import ezdxf

from cad_engine.semantic_dimension_engine import (
    _override_status,
    apply_semantic_dimension_engine,
    extract_source_dimension_registry,
    select_minimal_dimension_set,
)


def _architectural_source(path: Path):
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "WALL"})
    msp.add_line((10, 0), (10, 10), dxfattribs={"layer": "WALL"})
    d = msp.add_linear_dim(base=(0, -1), p1=(0, 0), p2=(10, 0), angle=0)
    d.dimension.dxf.layer = "GRID"
    d.render()
    doc.saveas(path)


def test_override_conflict_distinguishes_minor_rounding_from_material_conflict():
    assert _override_status(2.97657, "3.00") == "MINOR_OVERRIDE"
    assert _override_status(3.23749, "3.25") == "MINOR_OVERRIDE"
    assert _override_status(5.95, "7.00") == "CONFLICT"
    assert _override_status(2.0, "20-30") == "NON_NUMERIC_OVERRIDE"


def test_source_dimension_registry_preserves_geometry_text_and_semantic_binding(tmp_path):
    src = tmp_path / "source.dxf"
    _architectural_source(src)
    registry = extract_source_dimension_registry(src)
    assert registry["dimension_count"] == 1
    row = registry["records"][0]
    assert row["raw_measurement"] == 10.0
    assert row["purpose"] == "GRID"
    assert row["preservation_policy"] == "KEEP_VISIBLE"
    assert row["reference_point_a"] == (0.0, 0.0)
    assert row["reference_point_b"] == (10.0, 0.0)


def test_minimal_dimension_set_removes_exact_duplicate_reference_definition():
    row = {
        "id": "D1", "board_id": "B", "orientation": "HORIZONTAL", "purpose": "SETOUT",
        "reference_a": {"element_id": "A"}, "reference_b": {"element_id": "B"}, "mandatory": True,
    }
    duplicate = {**row, "id": "D2"}
    assert [x["id"] for x in select_minimal_dimension_set([row, duplicate])] == ["D1"]


def test_engine_generates_reference_bound_mechanical_setout_and_reopens_exact_file(tmp_path):
    src = tmp_path / "source.dxf"; out = tmp_path / "out.dxf"
    _architectural_source(src); shutil.copy2(src, out)
    network = {
        "levels": [{"id": "L1", "name": "Ground", "type": "GROUND", "region_bounds": [0, 0, 10, 10]}],
        "nodes": [
            {"id": "S1", "kind": "shaft", "category": "vertical_core", "point": (4, 3), "level": "L1"},
            {"id": "F1", "kind": "basin", "category": "fixture", "point": (8, 7), "level": "L1"},
        ],
        "edges": [{
            "id": "E1", "system": "cold_water", "from": "S1", "to": "F1", "levels": ["L1"],
            "draw_on_plan": True, "plan_path": [(4, 3), (8, 3), (8, 7)],
        }],
    }
    report = {"composition": {
        "manifest": [{"family": "WATER", "purpose": "PLAN", "level": "GROUND", "old_sheet": "B1", "code": "M-W-01"}],
        "boards": {"B1": {"plan_area": [20, 20, 120, 120]}},
    }}
    preservation = {"status": "PASS", "critical_missing_count": 0, "important_missing_count": 0}
    result = apply_semantic_dimension_engine(src, out, report, network, architecture_preservation=preservation)
    assert result["status"] == "PASS"
    assert result["generated_dimension_count"] == 2
    assert result["source_preservation_proven"] is True
    reopened = ezdxf.readfile(out)
    generated = []
    for entity in reopened.modelspace().query("DIMENSION"):
        try:
            data = entity.get_xdata("PLANHA_DIMENSION")
        except Exception:
            continue
        if any(code == 1000 and value == "SEMANTIC_DIMENSION" for code, value in data):
            generated.append(entity)
    assert len(generated) == 2


def test_source_material_override_requires_review_not_silent_deletion(tmp_path):
    src = tmp_path / "conflict.dxf"
    doc = ezdxf.new("R2010"); msp = doc.modelspace()
    d = msp.add_linear_dim(base=(0, -1), p1=(0, 0), p2=(5.95, 0), angle=0, text="7.00")
    d.render(); doc.saveas(src)
    registry = extract_source_dimension_registry(src)
    assert registry["override_conflict_count"] == 1
    assert registry["records"][0]["preservation_policy"] == "FLAG_CONFLICT"
