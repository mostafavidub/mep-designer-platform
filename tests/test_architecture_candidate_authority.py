"""Independent fail-closed checks for candidate roles and invalid inner rings."""
from copy import deepcopy

import pytest

from cad_engine.architecture_contract import assign_canonical_model_hash
from cad_engine.architecture_validator import validate_architecture
from test_architecture_input_foundation_v2 import contract


def _errors(model):
    assign_canonical_model_hash(model)
    before = deepcopy(model)
    report = validate_architecture(model)
    assert model == before
    return {row["code"] for row in report["hard_errors"]}


@pytest.mark.parametrize("role", ["PARENT_CONTAINER", "BUILDING_ENVELOPE", "INVALID_DIAGNOSTIC",
                                  "OVERLAPPING_UNRESOLVED", "REPEATED_CELL_ARRAY", "MATERIAL_INTERIOR_CONFLICT", "WALL_MATERIAL_CONFLICT"])
@pytest.mark.parametrize("location", ["space", "geometry_evidence"])
def test_nonphysical_candidate_cannot_receive_material_authority(role, location):
    model = contract()
    space = model["physical_spaces"][0]
    target = space if location == "space" else space.setdefault("geometry_evidence", {})
    target["candidate_role"] = role
    assert "NON_PHYSICAL_CANDIDATE_AUTHORITY_FORBIDDEN" in _errors(model)


@pytest.mark.parametrize("role", ["PARENT_CONTAINER", "BUILDING_ENVELOPE", "INVALID_DIAGNOSTIC",
                                  "OVERLAPPING_UNRESOLVED", "REPEATED_CELL_ARRAY", "MATERIAL_INTERIOR_CONFLICT", "WALL_MATERIAL_CONFLICT"])
def test_valid_unresolved_candidate_is_retained_without_material_authority(role):
    model = contract()
    space = model["physical_spaces"][0]
    space.update(candidate_role=role, status="INPUT_REQUIRED", geometry_status="INPUT_REQUIRED")
    space["authority"].update(status="INPUT_REQUIRED", material_geometry=False)
    assert "NON_PHYSICAL_CANDIDATE_AUTHORITY_FORBIDDEN" not in _errors(model)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_hole_cannot_hide_behind_finite_exterior(value):
    model = contract()
    model["physical_spaces"][0]["interior_rings"] = [[[1, 1], [2, 1], [2, value], [1, 2]]]
    assert "PHYSICAL_SPACE_POLYGON_INVALID" in _errors(model)


def test_precision_collapsed_inner_ring_fails_closed():
    model = contract()
    model["physical_spaces"][0]["interior_rings"] = [[[1, 1], [1, 1], [2, 1], [2, 1]]]
    assert "PHYSICAL_SPACE_POLYGON_INVALID" in _errors(model)


def test_supported_physical_cell_role_retains_existing_authority():
    model = contract()
    model["physical_spaces"][0]["candidate_role"] = "PHYSICAL_SPACE_CANDIDATE"
    assert _errors(model) == set()
