from cad_engine.mechanical_cad_preservation import _canonical_architecture_identity


def _answers(model):
    return {"_canonical_input_contract": {"architecture_evidence": model}}


def test_sealed_room_and_wet_core_identity_can_complete_flattened_dxf_evidence():
    model = {"version": "architecture-reconstruction-v1", "topology_version": "architecture-topology-v1", "levels": [{
        "name": "Ground",
        "rooms": [
            {"id": "L01-R001", "type": "kitchen", "bounds": [0, 0, 4, 4]},
            {"id": "L01-R002", "type": "bath", "bounds": [4, 0, 7, 4]},
        ],
        "shafts": [],
        "wet_cores": [{"id": "L01-WC01", "room_ids": ["L01-R001", "L01-R002"], "center": [4, 2]}],
    }]}
    result = _canonical_architecture_identity(_answers(model))
    assert result["room_identity_complete"] is True
    assert result["shaft_wet_core_evidence_complete"] is True


def test_incomplete_or_orphaned_sealed_identity_fails_closed():
    model = {"levels": [{
        "name": "Ground",
        "rooms": [{"id": "L01-R001", "type": "kitchen"}],
        "shafts": [{"id": "L01-S001"}],
        "wet_cores": [{"id": "L01-WC01", "room_ids": ["UNKNOWN"], "center": [1, 1]}],
    }]}
    result = _canonical_architecture_identity(_answers(model))
    assert result["room_identity_complete"] is False
    assert result["shaft_wet_core_evidence_complete"] is False


def test_unbounded_outlier_label_does_not_invalidate_real_closed_rooms():
    model = {"levels": [{
        "name": "Ground",
        "rooms": [
            {"id": "L01-R001", "type": "living", "bounds": [0, 0, 8, 8]},
            {"id": "L01-R002", "type": "kitchen", "bounds": None, "polygon": None},
        ],
        "shafts": [], "wet_cores": [],
    }]}
    result = _canonical_architecture_identity(_answers(model))
    assert result["room_identity_complete"] is True
    assert result["closed_room_count"] == 1
    assert result["unbounded_room_label_count"] == 1
