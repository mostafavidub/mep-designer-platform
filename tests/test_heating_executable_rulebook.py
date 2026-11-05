import json
from pathlib import Path

import pytest

from app.mechanical_rulebook import network_design_basis
from cad_engine.executable_rulebook import HEATING_ROOT, load_rulebook_module, validate_rulebook_module
from cad_engine.heating_rulebook import evaluate_heating_rulebook, heating_design_profile


ROOT = Path(__file__).resolve().parents[1]


def _snapshot(*, temperature=90.0, guard=None, base=80.0, tank_type="CLOSED"):
    surface = {
        "occupied_or_work_space": True,
        "maximum_accessible_surface_temperature_c": temperature,
    }
    if guard is not None:
        surface["direct_contact_guard"] = guard
    return {"heating": {
        "exposed_surface_inventory_complete": True,
        "exposed_surfaces": [surface],
        "floor_mounted_equipment_inventory_complete": True,
        "floor_mounted_equipment": [{"base_height_mm": base}],
        "hot_water_heating_system_inventory_complete": True,
        "hot_water_heating_systems": [{"expansion_tank": {
            "type": tank_type, "system_water_volume_l": 180,
            "minimum_operating_temperature_c": 10,
            "maximum_operating_temperature_c": 80,
            "maximum_working_pressure_kpa": 300,
            "selected_capacity_l": 24,
            "normal_water_level_above_highest_component_mm": 1200,
            "certified_test_pressure_kpa": 450,
            "accredited_test_report": True,
        }}],
    }}


def _by_id(result, suffix):
    return next(row for row in result["results"] if row["rule_id"].endswith(suffix))


def test_heating_module_integrity_and_strict_schema():
    module = load_rulebook_module(HEATING_ROOT)
    assert validate_rulebook_module(module)["status"] == "PASS"
    assert len(module["registry"]["rules"]) == 5
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "data/rulebook/schema/executable_rule.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    for rule in module["registry"]["rules"]:
        assert list(validator.iter_errors(rule)) == []


def test_design_consumer_exposes_source_backed_contracts_without_sizes():
    profile = heating_design_profile()
    systems = network_design_basis()["systems"]
    for name in ("heating_supply", "heating_return"):
        assert systems[name]["source_surface_guard"]["guard_trigger_temperature_c"] == 90
        assert systems[name]["source_floor_mounted_equipment_base"]["minimum_base_height_mm"] == 80
        assert systems[name]["source_open_expansion_tank_elevation"][
            "minimum_water_level_above_highest_component_mm"] == 1200
        assert systems[name]["source_closed_expansion_tank_test_pressure"][
            "minimum_test_to_working_pressure_ratio"] == 1.5
        assert systems[name]["source_rule_ids"] == profile["source_ids"]
        assert systems[name]["size_table"] == []


def test_surface_guard_threshold_is_strictly_above_90():
    at_limit = evaluate_heating_rulebook(_snapshot(temperature=90.0, guard=False))
    assert _by_id(at_limit, "HEATING-SURFACE-GUARD")["status"] == "PASS"
    above_without_guard = evaluate_heating_rulebook(_snapshot(temperature=90.01, guard=False))
    assert _by_id(above_without_guard, "HEATING-SURFACE-GUARD")["status"] == "FAIL"
    above_with_guard = evaluate_heating_rulebook(_snapshot(temperature=90.01, guard=True))
    assert _by_id(above_with_guard, "HEATING-SURFACE-GUARD")["status"] == "PASS"


def test_missing_guard_and_invalid_temperature_fail_closed():
    missing_guard = evaluate_heating_rulebook(_snapshot(temperature=91.0))
    assert _by_id(missing_guard, "HEATING-SURFACE-GUARD")["status"] == "INPUT_REQUIRED"
    invalid = evaluate_heating_rulebook(_snapshot(temperature=float("nan"), guard=True))
    assert _by_id(invalid, "HEATING-SURFACE-GUARD")["status"] == "INPUT_REQUIRED"


def test_floor_base_boundary_and_negative_case():
    assert _by_id(evaluate_heating_rulebook(_snapshot(base=80.0)), "FLOOR-BASE-HEIGHT")["status"] == "PASS"
    assert _by_id(evaluate_heating_rulebook(_snapshot(base=79.99)), "FLOOR-BASE-HEIGHT")["status"] == "FAIL"
    assert _by_id(evaluate_heating_rulebook(_snapshot(base=float("inf"))), "FLOOR-BASE-HEIGHT")["status"] == "INPUT_REQUIRED"


def test_inventory_completeness_and_not_applicable_are_distinct():
    missing = {"heating": {}}
    assert evaluate_heating_rulebook(missing)["status"] == "INPUT_REQUIRED"
    empty_complete = {"heating": {
        "exposed_surface_inventory_complete": True, "exposed_surfaces": [],
        "floor_mounted_equipment_inventory_complete": True, "floor_mounted_equipment": [],
        "hot_water_heating_system_inventory_complete": True,
        "hot_water_heating_systems": [],
    }}
    result = evaluate_heating_rulebook(empty_complete)
    assert result["status"] == "PASS"
    assert {row["status"] for row in result["results"]} == {"NOT_APPLICABLE"}


def test_non_applicable_space_does_not_require_guard():
    snapshot = _snapshot(temperature=120.0)
    snapshot["heating"]["exposed_surfaces"][0]["occupied_or_work_space"] = False
    result = evaluate_heating_rulebook(snapshot)
    assert _by_id(result, "HEATING-SURFACE-GUARD")["status"] == "NOT_APPLICABLE"


def test_hot_water_system_requires_source_bound_expansion_tank_and_capacity_basis():
    passing = evaluate_heating_rulebook(_snapshot())
    assert _by_id(passing, "HOT-WATER-EXPANSION-TANK")["status"] == "PASS"
    missing = _snapshot()
    missing["heating"]["hot_water_heating_systems"][0].pop("expansion_tank")
    failed = _by_id(evaluate_heating_rulebook(missing), "HOT-WATER-EXPANSION-TANK")
    assert failed["status"] == "FAIL"
    assert failed["errors"] == ["HEATING_EXPANSION_TANK_MISSING:0"]
    incomplete = _snapshot()
    incomplete["heating"]["hot_water_heating_systems"][0]["expansion_tank"].pop(
        "system_water_volume_l")
    assert _by_id(evaluate_heating_rulebook(incomplete),
                  "HOT-WATER-EXPANSION-TANK")["status"] == "INPUT_REQUIRED"


def test_open_expansion_tank_elevation_includes_exact_1200_mm_boundary():
    at_limit = _snapshot(tank_type="OPEN")
    assert _by_id(evaluate_heating_rulebook(at_limit), "OPEN-TANK-ELEVATION")["status"] == "PASS"
    below = _snapshot(tank_type="OPEN")
    below["heating"]["hot_water_heating_systems"][0]["expansion_tank"][
        "normal_water_level_above_highest_component_mm"] = 1199.99
    assert _by_id(evaluate_heating_rulebook(below), "OPEN-TANK-ELEVATION")["status"] == "FAIL"
    unknown = _snapshot(tank_type="OPEN")
    unknown["heating"]["hot_water_heating_systems"][0]["expansion_tank"][
        "normal_water_level_above_highest_component_mm"] = float("nan")
    assert _by_id(evaluate_heating_rulebook(unknown),
                  "OPEN-TANK-ELEVATION")["status"] == "INPUT_REQUIRED"


def test_closed_tank_certificate_pressure_ratio_boundary_and_missing_report():
    at_limit = _snapshot()
    assert _by_id(evaluate_heating_rulebook(at_limit),
                  "CLOSED-TANK-TEST-PRESSURE")["status"] == "PASS"
    below = _snapshot()
    below["heating"]["hot_water_heating_systems"][0]["expansion_tank"][
        "certified_test_pressure_kpa"] = 449.99
    assert _by_id(evaluate_heating_rulebook(below),
                  "CLOSED-TANK-TEST-PRESSURE")["status"] == "FAIL"
    no_report = _snapshot()
    no_report["heating"]["hot_water_heating_systems"][0]["expansion_tank"][
        "accredited_test_report"] = False
    assert _by_id(evaluate_heating_rulebook(no_report),
                  "CLOSED-TANK-TEST-PRESSURE")["status"] == "INPUT_REQUIRED"
