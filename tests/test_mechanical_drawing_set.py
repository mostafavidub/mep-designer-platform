"""Tests for Mechanical Drawing Set Planning Standard.

These tests define the expected behavior before CAD generation:
- drawing set must be calculated first
- systems are counted by effective levels
- approval is required before generation
"""

from app.mechanical_drawing_set import predict_drawing_set, requires_approval


def test_reference_project_21_sheets():
    result = predict_drawing_set({
        "cooling_levels": 4,
        "heating_levels": 3,
        "water_levels": 4,
        "sanitary_levels": 3,
        "ventilation_levels": 3,
        "gas_levels": 3,
        "roof_drainage": True,
        "riser": True,
    })
    assert result["total"] == 25


def test_approval_gate():
    assert requires_approval({"approved": False}) is True
    assert requires_approval({"approved": True}) is False
