"""Tests for the authority-separated Mechanical Drawing Set Standard."""

from app.mechanical_drawing_set import approve_drawing_set, predict_drawing_set, requires_approval


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


def test_reference_authority_profile_is_22_deliverable_sheets():
    result = predict_drawing_set(_three_level_scope())
    assert result["total_plans"] == 22
    assert result["deliverable_sheet_count"] == 22
    assert result["count_semantics"] == "authority_separated_customer_deliverables"
    assert result["sheet_families"]["water_supply"]["count"] == 5
    assert result["sheet_families"]["sanitary_vent"]["count"] == 3
    assert result["sheet_families"]["heating"]["count"] == 3
    assert result["sheet_families"]["cooling"]["count"] == 4
    assert result["sheet_families"]["gas"]["count"] == 3
    assert result["sheet_families"]["ventilation_exhaust"]["count"] == 3
    assert result["sheet_families"]["roof_rainwater"]["count"] == 1
    water_types = {x["drawing_type"] for x in result["sheet_families"]["water_supply"]["sheets"]}
    assert "equipment_plan" in water_types
    assert "calculation_sheet" in water_types


def test_duplex_benchmark_manifest_is_exactly_22():
    result = approve_drawing_set(predict_drawing_set(_three_level_scope()))
    manifest = result["approved_manifest"]
    assert manifest["total_sheets"] == 22
    assert len(manifest["sheets"]) == 22
    assert len({x["code"] for x in manifest["sheets"]}) == 22
    assert manifest["manifest_id"] == result["drawing_manifest"]["manifest_id"]
    assert any(x["code"] == "M-W-CALC" and x["drawing_type"] == "calculation_sheet" for x in manifest["sheets"])


def test_afsari_benchmark_manifest_is_exactly_13():
    levels = ["Ground", "First", "Second"]
    result = approve_drawing_set(predict_drawing_set(_three_level_scope(
        all_levels=levels,
        roof_exists=False,
        conditioned_levels=levels,
        heated_levels=levels,
        wet_fixture_levels=levels,
        sanitary_fixture_levels=levels,
        ventilation_required_levels=levels,
        gas_consumer_levels=levels,
        typical_groups=[{"name": "Typical Floors", "levels": ["First", "Second"]}],
    )))
    assert result["approved_manifest"]["total_sheets"] == 13
    assert len(result["approved_manifest"]["sheets"]) == 13


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


def test_five_identical_floors_become_one_plan_per_family():
    levels = ["L1", "L2", "L3", "L4", "L5"]
    result = predict_drawing_set(_three_level_scope(
        all_levels=levels,
        roof_exists=False,
        conditioned_levels=levels,
        heated_levels=levels,
        wet_fixture_levels=levels,
        sanitary_fixture_levels=levels,
        ventilation_required_levels=levels,
        gas_consumer_levels=levels,
        typical_groups=[{"name": "Typical L1-L5", "levels": levels}],
    ))
    for key in ("sanitary_vent", "heating", "cooling", "gas", "ventilation_exhaust"):
        assert result["sheet_families"][key]["count"] == 1
    assert result["sheet_families"]["water_supply"]["count"] == 2


def test_water_calculation_is_only_emitted_when_water_equipment_is_approved():
    plain = predict_drawing_set(_three_level_scope(
        roof_exists=False,
        gas_consumer_levels=["Ground"],
        typical_groups=[{"name": "Typical Floors", "levels": ["Ground", "First Duplex", "Second Duplex"]}],
    ))
    assert not any(x.get("drawing_type") == "calculation_sheet" for x in plain["drawing_manifest"]["sheets"])

    with_equipment = predict_drawing_set(_three_level_scope(central_water_equipment=True))
    calc = [x for x in with_equipment["drawing_manifest"]["sheets"] if x.get("drawing_type") == "calculation_sheet"]
    assert len(calc) == 1
    assert calc[0]["family"] == "water_supply"


def test_approval_gate():
    assert requires_approval({"approved": False}) is True
    assert requires_approval({"approved": True}) is False
