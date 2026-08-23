"""Tests for the authority-separated Mechanical Drawing Set Standard."""

from app.mechanical_drawing_set import predict_drawing_set, requires_approval


def _three_level_scope(**overrides):
    levels = ["Ground", "First Duplex", "Second Duplex"]
    scope = {
        "all_levels": levels + ["Roof"],
        "conditioned_levels": levels,
        "heated_levels": levels,
        "wet_fixture_levels": levels,
        "sanitary_fixture_levels": levels,
        "ventilation_required_levels": levels,
        "gas_consumer_levels": levels,
        "roof_exists": True,
        "roof_level_name": "Roof",
        "vertical_systems": True,
        "typical_groups": [],
    }
    scope.update(overrides)
    return scope


def test_reference_authority_profile_is_21_deliverable_sheets():
    result = predict_drawing_set(_three_level_scope())
    assert result["total_plans"] == 21
    assert result["deliverable_sheet_count"] == 21
    assert result["count_semantics"] == "authority_separated_customer_deliverables"
    assert result["sheet_families"]["water_supply"]["count"] == 4
    assert result["sheet_families"]["sanitary_vent"]["count"] == 3
    assert result["sheet_families"]["heating"]["count"] == 3
    assert result["sheet_families"]["cooling"]["count"] == 4
    assert result["sheet_families"]["gas"]["count"] == 3
    assert result["sheet_families"]["ventilation_exhaust"]["count"] == 3
    assert result["sheet_families"]["roof_rainwater"]["count"] == 1


def test_no_cross_system_combination_in_authority_profile():
    result = predict_drawing_set(_three_level_scope())
    for key in ("water_supply", "sanitary_vent", "heating", "cooling", "gas", "ventilation_exhaust"):
        assert len(result["sheet_families"][key]["systems"]) == 1
    assert "plumbing_gas" not in result["sheet_families"]
    assert "heating_cooling_condensate" not in result["sheet_families"]
    assert "riser_calc" not in result["sheet_families"]


def test_typical_floors_consolidate_only_inside_each_system():
    levels = ["Ground", "First Duplex", "Second Duplex"]
    result = predict_drawing_set(_three_level_scope(
        typical_groups=[{"name": "Typical Floors", "levels": levels}]
    ))
    # Six system families collapse to one level-pattern sheet each. Water and
    # cooling keep their authority special sheets, plus one roof/rainwater sheet.
    assert result["deliverable_sheet_count"] == 9
    assert result["sheet_families"]["water_supply"]["count"] == 2
    assert result["sheet_families"]["cooling"]["count"] == 2
    for key in ("sanitary_vent", "heating", "gas", "ventilation_exhaust"):
        assert result["sheet_families"][key]["count"] == 1
        assert result["sheet_families"][key]["sheets"][0]["typical"] is True
    assert result["sheet_families"]["roof_rainwater"]["count"] == 1


def test_gas_scope_off_removes_only_gas_deliverables():
    result = predict_drawing_set(_three_level_scope(gas_consumer_levels=[]))
    assert result["systems"]["gas"]["count"] == 0
    assert result["sheet_families"]["gas"]["count"] == 0
    assert result["deliverable_sheet_count"] == 18


def test_approval_gate():
    assert requires_approval({"approved": False}) is True
    assert requires_approval({"approved": True}) is False
