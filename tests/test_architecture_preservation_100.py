import copy

import ezdxf

from cad_engine.architecture_preservation_gate import (
    ARCHITECTURE_100_RUBRIC,
    diff_snapshots,
    evaluate_eighteen_step_contract,
    snapshot_architecture,
)


CONTROL_NAMES = (
    "immutable_snapshot", "coordinate_calibration", "drawing_separation", "level_binding",
    "wall_reconstruction", "typed_openings_and_verticals", "closed_room_identity", "shaft_wet_core_evidence",
    "safe_deduplication", "mutation_prohibition", "work_copy_only", "atomic_rollback",
    "exact_entity_diff", "topology_preservation", "per_sheet_visibility", "graphical_sheet_qa",
    "destructive_regression", "exact_file_reopen",
)


def architectural_doc():
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    for name in ("A-WALL", "A-DOOR", "A-TEXT"):
        doc.layers.add(name)
    model = doc.modelspace()
    model.add_line((0, 0), (10, 0), dxfattribs={"layer": "A-WALL"})
    model.add_line((4, 0), (5, 0), dxfattribs={"layer": "A-DOOR"})
    model.add_text("ROOM 101", dxfattribs={"layer": "A-TEXT", "height": .2}).set_placement((2, 2))
    return doc


def test_snapshot_seals_entities_and_document_structure():
    snapshot = snapshot_architecture(architectural_doc(), plan_id="GROUND")
    assert snapshot["document"]["units"] == 4
    assert "Model" in {layout["name"] for layout in snapshot["document"]["layouts"]}
    assert "A-WALL" in snapshot["document"]["layers"]
    assert len(snapshot["document"]["metadata_hash"]) == 64
    assert len(snapshot["snapshot_hash"]) == 64


def test_exact_diff_rejects_protected_geometry_text_and_layer_mutation():
    before = snapshot_architecture(architectural_doc(), plan_id="GROUND")
    for field, value in (("bbox", (0, 0, 9, 0)), ("text", "CHANGED"), ("layer", "0")):
        after = copy.deepcopy(before)
        target = next(item for item in after["entities"] if item["criticality"] == "CRITICAL")
        target[field] = value
        result = diff_snapshots(before, after)
        assert result["pass"] is False
        assert result["protected_changed"]


def test_all_eighteen_controls_are_required_for_100_and_release():
    passed = evaluate_eighteen_step_contract(checks={name: True for name in CONTROL_NAMES})
    assert passed["status"] == "PASS"
    assert passed["score"] == 100
    assert sum(ARCHITECTURE_100_RUBRIC.values()) == 100

    for control in CONTROL_NAMES:
        checks = {name: True for name in CONTROL_NAMES}
        checks[control] = False
        failed = evaluate_eighteen_step_contract(checks=checks)
        assert failed["status"] == "FAIL"
        assert failed["score"] < 100
        assert control in failed["failures"]
        assert failed["action"] == "ROLLBACK_AND_BLOCK_DELIVERY"


def test_missing_and_unknown_controls_fail_closed():
    assert evaluate_eighteen_step_contract(checks={})["status"] == "FAIL"
    checks = {name: True for name in CONTROL_NAMES}
    checks["exact_file_reopen"] = "UNKNOWN"
    result = evaluate_eighteen_step_contract(checks=checks)
    assert result["status"] == "FAIL"
    assert "exact_file_reopen" in result["failures"]
