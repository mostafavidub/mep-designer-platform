import json
from pathlib import Path

import pytest

from app.mechanical_rulebook import network_design_basis
from cad_engine.cooling_rulebook import evaluate_cooling_rulebook, cooling_design_profile
from cad_engine.executable_rulebook import COOLING_ROOT, load_rulebook_module, validate_rulebook_module


ROOT = Path(__file__).resolve().parents[1]


def _snapshot(*, provided=600, required=600, temperature_control=True, fan_selector=True):
    return {"cooling": {"split_and_window_unit_inventory_complete": True,
        "split_and_window_units": [{
            "manufacturer_instruction_id": "OFFICIAL-MANUAL-SHA256",
            "manufacturer_required_service_clearances_mm": {"front": required, "left": 100},
            "provided_service_clearances_mm": {"front": provided, "left": 100},
            "automatic_temperature_controller": temperature_control,
            "fan_speed_selector": fan_selector,
        }]}}


def _by_suffix(result, suffix):
    return next(row for row in result["results"] if row["rule_id"].endswith(suffix))


def test_cooling_module_integrity_and_strict_schema():
    module = load_rulebook_module(COOLING_ROOT)
    assert validate_rulebook_module(module)["status"] == "PASS"
    assert len(module["registry"]["rules"]) == 2
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "data/rulebook/schema/executable_rule.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    for rule in module["registry"]["rules"]:
        assert list(validator.iter_errors(rule)) == []


def test_cooling_consumer_receives_source_rules_without_fake_size_table():
    profile = cooling_design_profile()
    cooling = network_design_basis()["systems"]["cooling"]
    assert cooling["source_rule_ids"] == profile["source_ids"]
    assert cooling["source_manufacturer_installation_and_access"][
        "all_declared_sides_required"] is True
    assert cooling["source_temperature_and_fan_controls"]["fan_speed_selector_required"] is True
    assert cooling["size_table"] == []


def test_service_clearance_exact_boundary_passes_and_below_fails():
    at_limit = _by_suffix(evaluate_cooling_rulebook(_snapshot()), "COOLING-INSTALLATION-ACCESS")
    assert at_limit["status"] == "PASS"
    below = _by_suffix(evaluate_cooling_rulebook(_snapshot(provided=599.99)),
                       "COOLING-INSTALLATION-ACCESS")
    assert below["status"] == "FAIL"
    assert below["errors"] == ["COOLING_SERVICE_CLEARANCE_LOW:0:front"]


def test_missing_or_invalid_clearance_fails_closed():
    missing = _snapshot()
    missing["cooling"]["split_and_window_units"][0]["provided_service_clearances_mm"].pop("front")
    assert _by_suffix(evaluate_cooling_rulebook(missing),
                      "COOLING-INSTALLATION-ACCESS")["status"] == "INPUT_REQUIRED"
    invalid = _snapshot(provided=float("nan"))
    assert _by_suffix(evaluate_cooling_rulebook(invalid),
                      "COOLING-INSTALLATION-ACCESS")["status"] == "INPUT_REQUIRED"


def test_product_controls_are_both_required_and_unknown_is_distinct():
    passing = _by_suffix(evaluate_cooling_rulebook(_snapshot()), "COOLING-CONTROLS")
    assert passing["status"] == "PASS"
    absent = _by_suffix(evaluate_cooling_rulebook(_snapshot(fan_selector=False)),
                        "COOLING-CONTROLS")
    assert absent["status"] == "FAIL"
    unknown = _snapshot()
    unknown["cooling"]["split_and_window_units"][0].pop("automatic_temperature_controller")
    assert _by_suffix(evaluate_cooling_rulebook(unknown),
                      "COOLING-CONTROLS")["status"] == "INPUT_REQUIRED"


def test_complete_empty_inventory_is_not_applicable_but_missing_inventory_is_unknown():
    empty = evaluate_cooling_rulebook({"cooling": {
        "split_and_window_unit_inventory_complete": True, "split_and_window_units": []}})
    assert empty["status"] == "PASS"
    assert {row["status"] for row in empty["results"]} == {"NOT_APPLICABLE"}
    assert evaluate_cooling_rulebook({"cooling": {}})["status"] == "INPUT_REQUIRED"
