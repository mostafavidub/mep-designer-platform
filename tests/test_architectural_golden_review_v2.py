from copy import deepcopy

from tools.architectural_golden_review import (
    METHOD, SECTORS, approval_errors, export_proposals, new_golden,
    refresh_approval_gate, regenerate_topology,
)
from tools.architectural_golden_validate import validate


FRAME = "FRAME-C7C5B4F856993D8A"


def _model():
    return {
        "building_envelopes": [{"envelope_id": "E1", "frame_id": FRAME, "status": "HIGH_CONFIDENCE",
                                "outer_ring": [[0, 0], [4, 0], [4, 2], [0, 2], [0, 0]]}],
        "physical_spaces": [
            {"physical_space_id": "S1", "frame_id": FRAME, "status": "VERIFIED", "category": "bedroom",
             "polygon": [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]], "evidence": ["CAD"]},
            {"physical_space_id": "S2", "frame_id": FRAME, "status": "INPUT_REQUIRED", "category": "kitchen",
             "polygon": [[2, 0], [4, 0], [4, 2], [2, 2], [2, 0]], "evidence": ["CAD"]},
        ],
        "openings": [{"opening_id": "O1", "frame_id": FRAME, "status": "VERIFIED", "kind": "door",
                      "opening_segment": [[2, .8], [2, 1.2]], "point": [2, 1], "space_a": "S1", "space_b": "S2"},
                     {"opening_id": "O2", "frame_id": FRAME, "status": "VERIFIED", "kind": "window",
                      "opening_segment": [[0, .8], [0, 1.2]], "point": [0, 1], "space_a": "S1", "space_b": "EXTERIOR"}],
        "frames": [{"frame_id": FRAME, "bounds": [0, 0, 4, 2]}],
        "label_bindings": [{"host_space_id": "S1", "point": [1, 1], "text": "BEDROOM"}],
    }


def _golden():
    proposals = export_proposals(_model(), FRAME)
    return new_golden(case_id="case", source_sha256="0" * 64, frame_id=FRAME,
                      level="GROUND", bounds=[0, 0, 4, 2], proposals=proposals)


def test_export_is_read_only_stable_and_preserves_source_identity():
    model = _model(); before = deepcopy(model)
    first = export_proposals(model, FRAME); second = export_proposals(model, FRAME)
    assert model == before and first == second
    assert first["authority"] == "REVIEW_INPUT_ONLY"
    assert first["generated_without_new_inference"] is True
    assert first["spaces"][0]["source_id"] == "S1"
    assert first["spaces"][0]["review_item_id"].startswith("SPACE-PROP-")
    assert first["spaces"][0]["original_geometry"] == first["spaces"][0]["polygon"]
    assert first["spaces"][0]["disposition"] == "UNREVIEWED"
    assert first["label_bindings"][0]["text"] == "BEDROOM"


def test_approval_fails_closed_until_all_proposals_and_both_source_passes_complete():
    golden = _golden()
    assert "proposal_review_incomplete" in approval_errors(golden)
    for row in [golden["proposals"]["building_envelope"], *golden["proposals"]["spaces"], *golden["proposals"]["portals"]]:
        row["disposition"] = "CORRECT"
    golden["review"].update({"annotator": "A", "reviewer": "A"})
    golden["spaces"] = [{"golden_space_id": "G1", "status": "VERIFIED", "category": "bedroom",
                         "polygon": [[0, 0], [4, 0], [4, 2], [0, 2], [0, 0]], "interior_rings": []}]
    assert "independent_reviewer_required" in approval_errors(golden)
    golden["review"]["reviewer"] = "B"
    golden["completeness"].update({"mode_completed": True, "sectors": dict.fromkeys(SECTORS, True),
                                    "questions": {"missing_spaces": False, "missing_portals": False,
                                                  "missing_voids": False, "source_labels_checked": False}})
    golden["reviewer_completeness"].update({"completed": True, "sectors": dict.fromkeys(SECTORS, True)})
    assert approval_errors(golden) == []
    assert refresh_approval_gate(golden)["approval_gate"]["eligible"] is True


def test_adjacency_and_access_are_derived_and_windows_never_create_access():
    golden = _golden()
    golden["spaces"] = [
        {"golden_space_id": "G1", "polygon": [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]], "interior_rings": []},
        {"golden_space_id": "G2", "polygon": [[2, 0], [4, 0], [4, 2], [2, 2], [2, 0]], "interior_rings": []},
    ]
    golden["portals"] = [
        {"golden_portal_id": "P1", "kind": "door", "status": "VERIFIED", "space_a": "G1", "space_b": "G2"},
        {"golden_portal_id": "P2", "kind": "window", "status": "VERIFIED", "space_a": "G1", "space_b": "EXTERIOR"},
    ]
    regenerate_topology(golden)
    assert golden["geometric_adjacency"] == [["G1", "G2"]]
    assert golden["access_connectivity"] == [{"space_a": "G1", "space_b": "G2", "portal_id": "P1"}]


def test_approved_v2_validator_rejects_stale_derived_topology():
    golden = _golden()
    for row in [golden["proposals"]["building_envelope"], *golden["proposals"]["spaces"], *golden["proposals"]["portals"]]: row["disposition"] = "WRONG"
    golden["review"].update({"annotator": "A", "annotation_date": "2026-09-30", "reviewer": "B",
                             "reviewed_at": "2026-09-30", "approved_at": "2026-09-30"})
    golden["review_status"] = "APPROVED"
    golden["building_envelope"] = {"status": "VERIFIED", "outer_ring": [[0, 0], [4, 0], [4, 2], [0, 2], [0, 0]], "interior_voids": []}
    golden["spaces"] = [
        {"golden_space_id": "G1", "status": "VERIFIED", "category": "a", "polygon": [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]], "interior_rings": []},
        {"golden_space_id": "G2", "status": "VERIFIED", "category": "b", "polygon": [[2, 0], [4, 0], [4, 2], [2, 2], [2, 0]], "interior_rings": []},
    ]
    golden["completeness"].update({"mode_completed": True, "sectors": dict.fromkeys(SECTORS, True),
                                    "questions": dict.fromkeys(golden["completeness"]["questions"], False)})
    golden["reviewer_completeness"].update({"completed": True, "sectors": dict.fromkeys(SECTORS, True)})
    report = validate(golden)
    assert "stale_geometric_adjacency" in report["errors"]


def test_method_identity_is_explicit_and_legacy_schema_identity_is_preserved():
    golden = _golden()
    assert golden["schema"] == "architectural-topology-golden/1.0"
    assert golden["annotation_method"] == golden["review"]["method"] == METHOD
    assert golden["golden_id"].startswith("GOLDEN-") and golden["human_added_items"] == []
    assert set(golden["completeness"]["sectors"]) == set(SECTORS)
