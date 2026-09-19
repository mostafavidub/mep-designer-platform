from cad_engine.mechanical_cad_preservation import _validate_matched_topology


def _wall(box):
    return {"semantic_class": "WALL", "bbox": box}


def test_exact_entity_correspondence_resolves_only_quantization_false_negative():
    before = {"entities": [
        _wall((-1, 0, 0.00005, 0)),
        _wall((0.00005, 0, 1, 0)),
    ]}
    # A sub-micron inverse-transform residual crosses the endpoint bucket.
    after = {"entities": [
        _wall((-1, 0, 0.000049999999, 0)),
        _wall((0.000050000001, 0, 1, 0)),
    ]}
    match = {
        "pass": True,
        "strategy": "exact_transformed_geometry",
        "protected_source_count": 2,
        "matched_count": 2,
        "missing": [],
        "extra_protected": [],
        "matches": [{"bbox_error": 0.0}, {"bbox_error": 0.0}],
    }
    result = _validate_matched_topology(before, after, match)
    assert result["pass"] is True
    assert result["quantized_graph_pass"] is False
    assert result["evidence"] == "EXACT_ENTITY_CORRESPONDENCE"


def test_extra_or_approximate_architecture_cannot_override_topology_failure():
    before = {"entities": [_wall((0, 0, 1, 0))]}
    after = {"entities": [_wall((0, 0, 1, 0)), _wall((2, 0, 3, 0))]}
    match = {
        "pass": True,
        "strategy": "preserved_copy_order",
        "protected_source_count": 1,
        "matched_count": 1,
        "missing": [],
        "extra_protected": [{"key": "extra"}],
        "matches": [{"bbox_error": 0.0}],
    }
    assert _validate_matched_topology(before, after, match)["pass"] is False


def test_material_bbox_error_cannot_override_topology_failure():
    before = {"entities": [_wall((0, 0, 1, 0)), _wall((1, 0, 2, 0))]}
    after = {"entities": [_wall((0, 0, 1, 0)), _wall((1.1, 0, 2.1, 0))]}
    match = {
        "pass": True,
        "strategy": "preserved_copy_order",
        "protected_source_count": 2,
        "matched_count": 2,
        "missing": [],
        "extra_protected": [],
        "matches": [{"bbox_error": 0.0}, {"bbox_error": 0.01}],
    }
    assert _validate_matched_topology(before, after, match)["pass"] is False
