from copy import deepcopy
from pathlib import Path
import tempfile

import ezdxf

from cad_engine.architecture_space_equipment_gate import (
    CONTROL_WEIGHTS, evaluate_architecture_space_equipment,
    exact_architecture_source_evidence,
)


HASH = "a" * 64


def context():
    return {
        "source_identity": {"sha256": HASH, "approved_revision": "A-7", "mechanical_reference_used": False},
        "calibration": {"units": "mm", "scale": 1, "north": 0, "origin": [0, 0], "valid_bounds": [0, 0, 10, 10]},
        "frames": [{"id": "P1", "type": "PLAN", "level_id": "L1", "view_id": "V1", "ambiguous": False}],
        "geometry": {"wall_ids": ["W1"], "open_wall_chains": [], "opening_ids": [], "door_ids": ["D1"],
                     "window_ids": [], "column_ids": [], "stair_ids": [], "elevator_ids": [], "obstruction_ids": []},
        "spaces": [{"id": "R1", "level_id": "L1", "closed_boundary": True,
                    "polygon": [[0, 0], [5, 0], [5, 5], [0, 5]], "label": "آشپزخانه",
                    "label_source": "CAD_TEXT", "label_inside": True, "use": "kitchen",
                    "classification_confidence": .99, "area_m2": 25, "height_m": 3,
                    "centroid": [2.5, 2.5], "entrance_ids": ["D1"], "adjacent_space_ids": []}],
        "vertical_spaces": [{"id": "S1", "kind": "SHAFT", "level_ids": ["L1"], "evidence": ["geometry", "text"]}],
        "object_inventory_complete": True,
        "objects": [{"id": "F1", "status": "EXISTING", "confidence": .98, "type": "sink", "orientation": 0,
                     "level_id": "L1", "space_id": "R1", "inside_host": True, "point": [2, 2],
                     "ports": ["cold_water", "hot_water", "sanitary"], "evidence": ["block", "spatial_relation"]}],
        "deduplication": {"status": "PASS", "false_merges": 0, "remaining_duplicates": 0},
        "semantic_consistency": {"status": "PASS", "outside_space": 0, "inside_wall": 0, "wrong_level": 0},
        "visual_overlay_qa": {"status": "PASS", "frame_ids": ["P1"], "critical_defects": []},
    }


def exact():
    return {"reopened": True, "sha256": HASH, "hash_matches": True, "modelspace_entities": 1}


def test_all_eighteen_controls_total_100_and_release():
    assert len(CONTROL_WEIGHTS) == 18 and sum(CONTROL_WEIGHTS.values()) == 100
    report = evaluate_architecture_space_equipment(context(), exact())
    assert report["status"] == "PASS" and report["score"] == 100
    assert report["all_controls_pass"] and report["release_allowed"]


def test_missing_input_is_never_guessed_or_scored_as_pass():
    report = evaluate_architecture_space_equipment({})
    assert report["status"] == "INPUT_REQUIRED" and not report["release_allowed"]
    assert report["score"] < 100


def test_open_room_ambiguous_frame_and_wrong_host_fail_closed():
    value = deepcopy(context())
    value["frames"][0]["ambiguous"] = True
    value["spaces"][0]["closed_boundary"] = False
    value["objects"][0]["inside_host"] = False
    report = evaluate_architecture_space_equipment(value, exact())
    assert report["status"] == "FAIL"
    assert any("UNCLASSIFIED_OR_AMBIGUOUS_FRAME" in item for item in report["errors"])


def test_reference_contamination_and_duplicate_false_merge_block():
    value = deepcopy(context())
    value["source_identity"]["mechanical_reference_used"] = True
    value["deduplication"]["false_merges"] = 1
    report = evaluate_architecture_space_equipment(value, exact())
    assert report["status"] == "FAIL"
    assert "MECHANICAL_REFERENCE_INPUT_FORBIDDEN" in report["errors"]


def test_exact_source_is_reopened_and_hash_verified():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "architecture.dxf"
        doc = ezdxf.new("R2010"); doc.modelspace().add_line((0, 0), (1, 1)); doc.saveas(path)
        measured = exact_architecture_source_evidence(path)
        assert measured["reopened"] and measured["modelspace_entities"] == 1
        assert exact_architecture_source_evidence(path, measured["sha256"])["hash_matches"]
        assert not exact_architecture_source_evidence(path, "0" * 64)["hash_matches"]


def test_every_space_and_equipment_field_is_required():
    value = deepcopy(context())
    value["spaces"][0].pop("height_m")
    value["objects"][0].pop("orientation")
    report = evaluate_architecture_space_equipment(value, exact())
    assert report["status"] in {"FAIL", "INPUT_REQUIRED"}
    assert not report["release_allowed"]
