"""Source-backed executable M14 split/window air-conditioner rules."""
from __future__ import annotations

from math import isfinite

from .executable_rulebook import COOLING_ROOT, load_rulebook_module, rule_rows, validate_rulebook_module

PASS, FAIL, INPUT_REQUIRED, NOT_APPLICABLE = "PASS", "FAIL", "INPUT_REQUIRED", "NOT_APPLICABLE"


def _finite(value):
    try:
        return isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _result(rule, status, *, evidence=(), missing=(), errors=()):
    return {"rule_id": rule["rule_id"], "rule_version": rule["version"], "status": status,
            "source_ids": sorted({value for source in rule["sources"] for value in source["source_ids"]}),
            "evidence": list(evidence), "missing_inputs": sorted(set(missing)),
            "errors": sorted(set(errors)), "llm_override_allowed": False}


def _split_inventory(snapshot):
    cooling = (snapshot or {}).get("cooling") or {}
    return cooling.get("split_and_window_units"), cooling.get("split_and_window_unit_inventory_complete")


def _manufacturer_installation_and_access(rule, snapshot):
    rows, complete = _split_inventory(snapshot)
    if rows is None or complete is None:
        return _result(rule, INPUT_REQUIRED, missing=[
            "cooling.split_and_window_units", "cooling.split_and_window_unit_inventory_complete"])
    if complete is not True:
        return _result(rule, INPUT_REQUIRED, missing=["cooling.split_and_window_unit_inventory_complete"])
    if not rows:
        return _result(rule, NOT_APPLICABLE, evidence=["complete split/window unit inventory contains zero rows"])
    missing, errors, evidence = [], [], []
    for index, row in enumerate(rows):
        instruction = row.get("manufacturer_instruction_id")
        required = row.get("manufacturer_required_service_clearances_mm")
        provided = row.get("provided_service_clearances_mm")
        if not instruction:
            missing.append(f"cooling.split_and_window_units[{index}].manufacturer_instruction_id")
        if not isinstance(required, dict) or not required:
            missing.append(
                f"cooling.split_and_window_units[{index}].manufacturer_required_service_clearances_mm")
            continue
        if not isinstance(provided, dict):
            missing.append(f"cooling.split_and_window_units[{index}].provided_service_clearances_mm")
            continue
        for side, required_value in sorted(required.items()):
            if not _finite(required_value) or float(required_value) < 0:
                missing.append(
                    f"cooling.split_and_window_units[{index}].manufacturer_required_service_clearances_mm.{side}")
                continue
            provided_value = provided.get(side)
            if not _finite(provided_value) or float(provided_value) < 0:
                missing.append(
                    f"cooling.split_and_window_units[{index}].provided_service_clearances_mm.{side}")
                continue
            evidence.append(
                f"unit[{index}] {side} clearance={float(provided_value):g}mm "
                f"manufacturer-minimum={float(required_value):g}mm")
            if float(provided_value) < float(required_value):
                errors.append(f"COOLING_SERVICE_CLEARANCE_LOW:{index}:{side}")
    if missing:
        return _result(rule, INPUT_REQUIRED, evidence=evidence, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _temperature_and_fan_controls(rule, snapshot):
    rows, complete = _split_inventory(snapshot)
    if rows is None or complete is None:
        return _result(rule, INPUT_REQUIRED, missing=[
            "cooling.split_and_window_units", "cooling.split_and_window_unit_inventory_complete"])
    if complete is not True:
        return _result(rule, INPUT_REQUIRED, missing=["cooling.split_and_window_unit_inventory_complete"])
    if not rows:
        return _result(rule, NOT_APPLICABLE, evidence=["complete split/window unit inventory contains zero rows"])
    missing, errors, evidence = [], [], []
    for index, row in enumerate(rows):
        for field, code in (("automatic_temperature_controller", "TEMPERATURE_CONTROLLER"),
                            ("fan_speed_selector", "FAN_SPEED_SELECTOR")):
            value = row.get(field)
            if value is None:
                missing.append(f"cooling.split_and_window_units[{index}].{field}")
            elif value is not True:
                errors.append(f"COOLING_{code}_MISSING:{index}")
            else:
                evidence.append(f"unit[{index}] {field}=present")
    if missing:
        return _result(rule, INPUT_REQUIRED, evidence=evidence, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


VALIDATORS = {
    "cooling_manufacturer_installation_and_access": _manufacturer_installation_and_access,
    "cooling_temperature_and_fan_controls": _temperature_and_fan_controls,
}


def load_cooling_rulebook():
    module = load_rulebook_module(COOLING_ROOT)
    integrity = validate_rulebook_module(module)
    if integrity["status"] != "PASS":
        raise ValueError("cooling Rulebook integrity failed: " + ",".join(integrity["errors"]))
    return module


def evaluate_cooling_rulebook(snapshot):
    module = load_cooling_rulebook()
    results = [VALIDATORS[row["validator"]](row, snapshot) for row in rule_rows(module)]
    status = (FAIL if any(row["status"] == FAIL for row in results)
              else INPUT_REQUIRED if any(row["status"] == INPUT_REQUIRED for row in results)
              else PASS)
    return {"module_id": module["manifest"]["module_id"],
            "module_version": module["manifest"]["version"],
            "results": results, "status": status}


def cooling_design_profile():
    module = load_cooling_rulebook()
    rows = {row["validator"]: row for row in rule_rows(module)}
    return {"module_version": module["manifest"]["version"],
            "manufacturer_installation_and_access":
                rows["cooling_manufacturer_installation_and_access"]["parameters"],
            "temperature_and_fan_controls":
                rows["cooling_temperature_and_fan_controls"]["parameters"],
            "authority": "M14-1391", "source_ids": ["M14-C-001", "M14-C-002"]}
