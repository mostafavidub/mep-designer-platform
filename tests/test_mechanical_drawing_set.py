"""Tests for the project-driven Mechanical Drawing Set Standard."""

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


def _types(result, family):
    return [x.get("drawing_type") for x in result["drawing_manifest"]["sheets"] if x.get("family") == family]


def test_reference_scope_manifest_is_structurally_consistent_and_project_driven():
    result = predict_drawing_set(_three_level_scope())
    manifest = result["drawing_manifest"]
    assert manifest["total_sheets"] == len(manifest["sheets"])
    assert manifest["total_sheets"] == result["deliverable_sheet_count"]
    assert len({x["code"] for x in manifest["sheets"]}) == len(manifest["sheets"])
    assert result["count_semantics"] == "authority_separated_customer_deliverables"

    for family in ("water_supply", "sanitary_vent", "heating", "cooling", "gas", "ventilation_exhaust"):
        primary = [x for x in manifest["sheets"] if x.get("family") == family and x.get("drawing_type") == "floor_plan"]
        assert len(primary) == 3

    water_types = _types(result, "water_supply")
    assert "equipment_plan" in water_types
    assert "calculation_sheet" in water_types
    assert _types(result, "roof_rainwater") == ["roof_plan"]


def test_approval_freezes_the_exact_current_manifest():
    result = approve_drawing_set(predict_drawing_set(_three_level_scope()))
    manifest = result["approved_manifest"]
    assert manifest == result["drawing_manifest"]
    assert manifest["total_sheets"] == len(manifest["sheets"])
    assert len({x["code"] for x in manifest["sheets"]}) == len(manifest["sheets"])


def test_typical_floors_consolidate_only_primary_plans_not_required_water_service_docs():
    levels = ["Ground", "First Duplex", "Second Duplex"]
    result = predict_drawing_set(_three_level_scope(
        typical_groups=[{"name": "Typical Floors", "levels": levels}]
    ))
    for family in ("water_supply", "sanitary_vent", "heating", "cooling", "gas", "ventilation_exhaust"):
        primary = [x for x in result["drawing_manifest"]["sheets"] if x.get("family") == family and x.get("drawing_type") == "floor_plan"]
        assert len(primary) == 1
        assert primary[0]["typical"] is True

    # The project still has three real wet levels, so service equipment and its
    # calculation remain necessary even though the floor plans consolidate.
    water_types = _types(result, "water_supply")
    assert "equipment_plan" in water_types
    assert "calculation_sheet" in water_types


def test_gas_scope_off_removes_all_gas_deliverables_without_affecting_other_primary_families():
    result = predict_drawing_set(_three_level_scope(gas_consumer_levels=[]))
    assert result["systems"]["gas"]["count"] == 0
    assert not [x for x in result["drawing_manifest"]["sheets"] if x.get("family") == "gas"]
    for family in ("water_supply", "sanitary_vent", "heating", "cooling", "ventilation_exhaust"):
        assert [x for x in result["drawing_manifest"]["sheets"] if x.get("family") == family and x.get("drawing_type") == "floor_plan"]


def test_single_level_direct_water_does_not_invent_pump_or_calculation_sheet():
    level = ["Ground"]
    result = predict_drawing_set(_three_level_scope(
        all_levels=level,
        wet_fixture_levels=level,
        sanitary_fixture_levels=level,
        conditioned_levels=level,
        heated_levels=level,
        ventilation_required_levels=level,
        gas_consumer_levels=level,
        roof_exists=False,
        typical_groups=[],
        central_water_equipment=False,
    ))
    water_types = _types(result, "water_supply")
    assert "equipment_plan" not in water_types
    assert "calculation_sheet" not in water_types


def test_explicit_direct_water_scope_suppresses_equipment_and_calculation_deliverables():
    levels = ["Ground", "First"]
    result = predict_drawing_set(_three_level_scope(
        all_levels=levels,
        wet_fixture_levels=levels,
        sanitary_fixture_levels=levels,
        conditioned_levels=levels,
        heated_levels=levels,
        ventilation_required_levels=levels,
        gas_consumer_levels=[],
        roof_exists=False,
        typical_groups=[],
        central_water_equipment=False,
    ))
    water = [x for x in result["drawing_manifest"]["sheets"] if x.get("family") == "water_supply"]
    assert not [x for x in water if x.get("drawing_type") == "equipment_plan"]
    assert not [x for x in water if x.get("drawing_type") == "calculation_sheet"]


def test_explicit_central_water_equipment_requires_calc_even_on_one_level():
    level = ["Ground"]
    result = predict_drawing_set(_three_level_scope(
        all_levels=level,
        wet_fixture_levels=level,
        sanitary_fixture_levels=level,
        conditioned_levels=level,
        heated_levels=level,
        ventilation_required_levels=level,
        gas_consumer_levels=[],
        roof_exists=False,
        typical_groups=[],
        central_water_equipment=True,
    ))
    water_types = _types(result, "water_supply")
    assert "equipment_plan" in water_types
    assert "calculation_sheet" in water_types


def test_no_cross_system_combination_in_system_family_metadata():
    result = predict_drawing_set(_three_level_scope())
    for key in ("water_supply", "sanitary_vent", "heating", "cooling", "gas", "ventilation_exhaust"):
        assert len(result["sheet_families"][key]["systems"]) == 1


def test_approval_gate():
    assert requires_approval({"approved": False}) is True
    assert requires_approval({"approved": True}) is False
