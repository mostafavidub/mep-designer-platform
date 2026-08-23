"""Tests for Mechanical Drawing Set Planning Standard."""

from app.mechanical_drawing_set import predict_drawing_set, requires_approval


def _three_level_scope(**overrides):
    levels = ["Ground", "First Duplex", "Second Duplex"]
    scope = {
        "all_levels": levels,
        "conditioned_levels": levels,
        "heated_levels": levels,
        "wet_fixture_levels": levels,
        "sanitary_fixture_levels": levels,
        "ventilation_required_levels": levels,
        "gas_consumer_levels": levels,
        "roof_exists": True,
        "roof_requires_dedicated_plan": False,
        "vertical_systems": True,
        "typical_groups": [],
    }
    scope.update(overrides)
    return scope


def test_three_level_deliverable_matches_13_sheet_cad_composition():
    result = predict_drawing_set(_three_level_scope())
    assert result["total_plans"] == 13
    assert result["deliverable_sheet_count"] == 13
    assert result["count_semantics"] == "customer_deliverable_sheets"
    assert result["sheet_families"]["plumbing_gas"]["count"] == 3
    assert result["sheet_families"]["sanitary_vent_rain"]["count"] == 3
    assert result["sheet_families"]["heating_cooling_condensate"]["count"] == 3
    assert result["sheet_families"]["ventilation_exhaust"]["count"] == 3
    assert result["sheet_families"]["riser_calc"]["count"] == 1


def test_internal_system_scope_is_not_customer_sheet_count():
    result = predict_drawing_set({
        "all_levels": ["B", "G", "1", "2", "3"],
        "conditioned_levels": ["G", "1", "2", "3"],
        "heated_levels": ["G", "1", "2"],
        "wet_fixture_levels": ["B", "G", "1", "2"],
        "sanitary_fixture_levels": ["G", "1", "2"],
        "ventilation_required_levels": ["B", "G", "1"],
        "gas_consumer_levels": ["G", "1", "2"],
        "roof_exists": True,
        "vertical_systems": False,
    })
    assert result["system_scope_count"] == 21
    assert result["deliverable_sheet_count"] == 14
    assert result["total_plans"] == 14


def test_typical_floors_are_consolidated_before_customer_count():
    result = predict_drawing_set(_three_level_scope(
        typical_groups=[{"name": "Typical Duplex Floors", "levels": ["Ground", "First Duplex", "Second Duplex"]}]
    ))
    # Four combined plan families collapse to one Typical sheet each, plus one
    # combined riser/calculation sheet.
    assert result["deliverable_sheet_count"] == 5
    for key in (
        "plumbing_gas", "sanitary_vent_rain",
        "heating_cooling_condensate", "ventilation_exhaust",
    ):
        family = result["sheet_families"][key]
        assert family["count"] == 1
        assert family["sheets"][0]["typical"] is True
        assert len(family["sheets"][0]["levels"]) == 3


def test_gas_scope_can_be_off_without_removing_plumbing_sheet():
    result = predict_drawing_set(_three_level_scope(gas_consumer_levels=[]))
    assert result["systems"]["gas"]["count"] == 0
    assert result["sheet_families"]["plumbing_gas"]["count"] == 3
    assert result["deliverable_sheet_count"] == 13


def test_approval_gate():
    assert requires_approval({"approved": False}) is True
    assert requires_approval({"approved": True}) is False
