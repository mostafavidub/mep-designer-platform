"""Tests for Mechanical Drawing Set Planning Standard."""

from app.mechanical_drawing_set import predict_drawing_set, requires_approval


def test_reference_project_21_sheets():
    result = predict_drawing_set({
        "conditioned_levels": ["G", "1", "2", "3"],
        "heated_levels": ["G", "1", "2"],
        "wet_fixture_levels": ["B", "G", "1", "2"],
        "sanitary_fixture_levels": ["G", "1", "2"],
        "ventilation_required_levels": ["B", "G", "1"],
        "gas_consumer_levels": ["G", "1", "2"],
        "roof_exists": True,
        "vertical_systems": False,
    })
    assert result["total_plans"] == 21


def test_approval_gate():
    assert requires_approval({"approved": False}) is True
    assert requires_approval({"approved": True}) is False
