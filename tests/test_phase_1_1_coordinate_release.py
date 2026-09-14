from pathlib import Path

import ezdxf
import pytest

from cad_engine.coordinate_integrity import uniform_fit, map_point, inverse_point, transform_evidence
from cad_engine.mechanical_network_materializer import materialize_authoritative_network
from cad_engine.post_materialization_release import validate_coordinate_evidence
from cad_engine.mechanical_authority import _has_collapsed_plan_path


def test_uniform_fit_never_stretches_x_and_y_independently():
    transform = uniform_fit((100, 200, 300, 300), (1, 2, 19, 25))
    assert transform["scale_x"] == transform["scale_y"]
    assert transform["scale"] == pytest.approx(.09)
    mapped = map_point((300, 300), transform)
    assert inverse_point(mapped, transform) == pytest.approx((300, 300), abs=1e-9)


def test_transform_evidence_rejects_missing_and_accepts_roundtrip():
    assert validate_coordinate_evidence({})["status"] == "FAIL"
    transform = uniform_fit((0, 0, 100, 50), (1, 1, 19, 25))
    evidence = transform_evidence(transform, [(0, 0), (20, 10), (100, 50)])
    assert validate_coordinate_evidence({"coordinate_transforms": [{"edge_id": "E1", **evidence}]})["status"] == "PASS"


def _fixture_files(tmp_path: Path):
    src = tmp_path / "source.dxf"
    doc = ezdxf.new("R2010"); doc.modelspace().add_line((0, 0), (100, 50)); doc.saveas(src)
    dst = tmp_path / "issued.dxf"
    out = ezdxf.new("R2010"); out.modelspace().add_line((0, 0), (1, 1)); out.saveas(dst)
    report = {"composition": {"manifest": [{"old_sheet": "B1", "code": "M-101", "family": "WATER", "level": "GROUND", "purpose": "PLAN"}],
                              "boards": {"B1": {"plan_area": [1, 2, 19, 25]}}}}
    network = {"levels": [{"id": "L1", "name": "GROUND", "type": "GROUND", "region_bounds": [0, 0, 100, 50]}],
               "edges": [{"id": "E1", "system": "cold_water", "levels": ["L1"], "draw_on_plan": True,
                           "plan_path": [(0, 0), (100, 50)], "size": 25, "size_mm": 25,
                           "material": "PPR", "calc_id": "C1"}]}
    return src, dst, report, network


def test_materializer_records_uniform_reversible_transform_on_exact_file(tmp_path):
    src, dst, report, network = _fixture_files(tmp_path)
    result = materialize_authoritative_network(src, dst, report, network)
    assert result["status"] == "PASS"
    assert result["exact_file_reopened"] is True
    assert validate_coordinate_evidence(result)["status"] == "PASS"
    row = result["coordinate_transforms"][0]
    assert row["scale_x"] == row["scale_y"]
    assert row["anisotropy"] == pytest.approx(0)


def test_materializer_fails_closed_when_route_is_degenerate(tmp_path):
    src, dst, report, network = _fixture_files(tmp_path)
    network["edges"][0]["plan_path"] = [(10, 10), (10, 10)]
    result = materialize_authoritative_network(src, dst, report, network)
    assert result["status"] == "FAIL"
    assert any("MATERIALIZED_SEGMENT_DEGENERATE" in item for item in result["errors"])


def test_persisted_collapsed_path_is_detected_for_authoritative_rebuild():
    network = {"edges": [{"id": "E1", "draw_on_plan": True,
                           "plan_path": [(2, 2), (2, 2), (2, 2)]}]}
    assert _has_collapsed_plan_path(network) is True
    network["edges"][0]["plan_path"][-1] = (2.1, 2)
    assert _has_collapsed_plan_path(network) is False
