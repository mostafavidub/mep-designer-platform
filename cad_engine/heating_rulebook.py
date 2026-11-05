"""Source-backed executable M14 heating safety and installation rules."""
from __future__ import annotations

from math import isfinite

from .executable_rulebook import HEATING_ROOT, load_rulebook_module, rule_rows, validate_rulebook_module

PASS, FAIL, INPUT_REQUIRED, NOT_APPLICABLE = "PASS", "FAIL", "INPUT_REQUIRED", "NOT_APPLICABLE"


def _finite(value):
    try:
        return isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _result(rule, status, *, evidence=(), missing=(), errors=()):
    return {
        "rule_id": rule["rule_id"], "rule_version": rule["version"], "status": status,
        "source_ids": sorted({value for source in rule["sources"] for value in source["source_ids"]}),
        "evidence": list(evidence), "missing_inputs": sorted(set(missing)),
        "errors": sorted(set(errors)), "llm_override_allowed": False,
    }


def _surface_guard(rule, snapshot):
    heating = (snapshot or {}).get("heating") or {}
    rows = heating.get("exposed_surfaces")
    complete = heating.get("exposed_surface_inventory_complete")
    if rows is None or complete is None:
        return _result(rule, INPUT_REQUIRED, missing=[
            "heating.exposed_surfaces", "heating.exposed_surface_inventory_complete",
        ])
    if complete is not True:
        return _result(rule, INPUT_REQUIRED, missing=["heating.exposed_surface_inventory_complete"])
    if not rows:
        return _result(rule, NOT_APPLICABLE, evidence=["complete exposed-surface inventory contains zero rows"])

    trigger = float(rule["parameters"]["guard_trigger_temperature_c"])
    missing, errors, evidence, applicable = [], [], [], 0
    for index, row in enumerate(rows):
        occupied = row.get("occupied_or_work_space")
        if occupied is None:
            missing.append(f"heating.exposed_surfaces[{index}].occupied_or_work_space")
            continue
        if occupied is not True:
            evidence.append(f"surface[{index}] outside occupied/residential/work applicability")
            continue
        applicable += 1
        temperature = row.get("maximum_accessible_surface_temperature_c")
        if not _finite(temperature):
            missing.append(f"heating.exposed_surfaces[{index}].maximum_accessible_surface_temperature_c")
            continue
        temperature = float(temperature)
        if temperature < 0:
            missing.append(f"heating.exposed_surfaces[{index}].maximum_accessible_surface_temperature_c")
            continue
        requires_guard = temperature > trigger
        evidence.append(f"surface[{index}] temperature={temperature:g}degC trigger=>{trigger:g}degC")
        if requires_guard:
            guard = row.get("direct_contact_guard")
            if guard is None:
                missing.append(f"heating.exposed_surfaces[{index}].direct_contact_guard")
            elif guard is not True:
                errors.append(f"HEATING_DIRECT_CONTACT_GUARD_MISSING:{index}")
    if missing:
        return _result(rule, INPUT_REQUIRED, evidence=evidence, missing=missing, errors=errors)
    if not applicable:
        return _result(rule, NOT_APPLICABLE, evidence=evidence)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _floor_base(rule, snapshot):
    heating = (snapshot or {}).get("heating") or {}
    rows = heating.get("floor_mounted_equipment")
    complete = heating.get("floor_mounted_equipment_inventory_complete")
    if rows is None or complete is None:
        return _result(rule, INPUT_REQUIRED, missing=[
            "heating.floor_mounted_equipment", "heating.floor_mounted_equipment_inventory_complete",
        ])
    if complete is not True:
        return _result(rule, INPUT_REQUIRED, missing=["heating.floor_mounted_equipment_inventory_complete"])
    if not rows:
        return _result(rule, NOT_APPLICABLE, evidence=["complete floor-mounted-equipment inventory contains zero rows"])

    minimum = float(rule["parameters"]["minimum_base_height_mm"])
    missing, errors, evidence = [], [], []
    for index, row in enumerate(rows):
        height = row.get("base_height_mm")
        if not _finite(height) or float(height) < 0:
            missing.append(f"heating.floor_mounted_equipment[{index}].base_height_mm")
            continue
        height = float(height)
        evidence.append(f"equipment[{index}] base={height:g}mm minimum={minimum:g}mm")
        if height < minimum:
            errors.append(f"HEATING_FLOOR_BASE_HEIGHT_LOW:{index}")
    if missing:
        return _result(rule, INPUT_REQUIRED, evidence=evidence, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _hot_water_expansion_tank(rule, snapshot):
    heating = (snapshot or {}).get("heating") or {}
    systems = heating.get("hot_water_heating_systems")
    complete = heating.get("hot_water_heating_system_inventory_complete")
    if systems is None or complete is None:
        return _result(rule, INPUT_REQUIRED, missing=[
            "heating.hot_water_heating_systems",
            "heating.hot_water_heating_system_inventory_complete",
        ])
    if complete is not True:
        return _result(rule, INPUT_REQUIRED, missing=[
            "heating.hot_water_heating_system_inventory_complete"])
    if not systems:
        return _result(rule, NOT_APPLICABLE, evidence=[
            "complete hot-water-heating-system inventory contains zero rows"])
    missing, errors, evidence = [], [], []
    for index, row in enumerate(systems):
        tank = row.get("expansion_tank")
        if not isinstance(tank, dict):
            errors.append(f"HEATING_EXPANSION_TANK_MISSING:{index}")
            continue
        tank_type = tank.get("type")
        if tank_type not in {"OPEN", "CLOSED"}:
            missing.append(f"heating.hot_water_heating_systems[{index}].expansion_tank.type")
        for field in ("system_water_volume_l", "minimum_operating_temperature_c",
                      "maximum_operating_temperature_c", "maximum_working_pressure_kpa",
                      "selected_capacity_l"):
            value = tank.get(field)
            if not _finite(value) or float(value) <= 0:
                missing.append(
                    f"heating.hot_water_heating_systems[{index}].expansion_tank.{field}")
        if not any(value.startswith(
                f"heating.hot_water_heating_systems[{index}].") for value in missing):
            if float(tank["maximum_operating_temperature_c"]) <= float(
                    tank["minimum_operating_temperature_c"]):
                errors.append(f"HEATING_EXPANSION_TEMPERATURE_RANGE_INVALID:{index}")
            evidence.append(
                f"system[{index}] tank={tank_type} capacity={float(tank['selected_capacity_l']):g}L "
                f"volume={float(tank['system_water_volume_l']):g}L "
                f"temperature={float(tank['minimum_operating_temperature_c']):g}-"
                f"{float(tank['maximum_operating_temperature_c']):g}degC "
                f"pressure={float(tank['maximum_working_pressure_kpa']):g}kPa")
    if missing:
        return _result(rule, INPUT_REQUIRED, evidence=evidence, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _open_expansion_tank_elevation(rule, snapshot):
    systems = ((snapshot or {}).get("heating") or {}).get("hot_water_heating_systems")
    if systems is None:
        return _result(rule, INPUT_REQUIRED, missing=["heating.hot_water_heating_systems"])
    minimum = float(rule["parameters"]["minimum_water_level_above_highest_component_mm"])
    applicable = 0; missing = []; errors = []; evidence = []
    for index, row in enumerate(systems):
        tank = row.get("expansion_tank") or {}
        if tank.get("type") != "OPEN":
            continue
        applicable += 1
        clearance = tank.get("normal_water_level_above_highest_component_mm")
        if not _finite(clearance) or float(clearance) < 0:
            missing.append(
                f"heating.hot_water_heating_systems[{index}].expansion_tank."
                "normal_water_level_above_highest_component_mm")
            continue
        clearance = float(clearance)
        evidence.append(f"system[{index}] open-tank clearance={clearance:g}mm minimum={minimum:g}mm")
        if clearance < minimum:
            errors.append(f"HEATING_OPEN_EXPANSION_TANK_ELEVATION_LOW:{index}")
    if missing:
        return _result(rule, INPUT_REQUIRED, evidence=evidence, missing=missing, errors=errors)
    if not applicable:
        return _result(rule, NOT_APPLICABLE, evidence=["no OPEN expansion tank in supplied systems"])
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _closed_expansion_tank_test_pressure(rule, snapshot):
    systems = ((snapshot or {}).get("heating") or {}).get("hot_water_heating_systems")
    if systems is None:
        return _result(rule, INPUT_REQUIRED, missing=["heating.hot_water_heating_systems"])
    factor = float(rule["parameters"]["minimum_test_to_working_pressure_ratio"])
    applicable = 0; missing = []; errors = []; evidence = []
    for index, row in enumerate(systems):
        tank = row.get("expansion_tank") or {}
        if tank.get("type") != "CLOSED":
            continue
        applicable += 1
        working = tank.get("maximum_working_pressure_kpa")
        tested = tank.get("certified_test_pressure_kpa")
        accredited = tank.get("accredited_test_report")
        if not _finite(working) or float(working) <= 0:
            missing.append(
                f"heating.hot_water_heating_systems[{index}].expansion_tank.maximum_working_pressure_kpa")
        if not _finite(tested) or float(tested) <= 0:
            missing.append(
                f"heating.hot_water_heating_systems[{index}].expansion_tank.certified_test_pressure_kpa")
        if accredited is not True:
            missing.append(
                f"heating.hot_water_heating_systems[{index}].expansion_tank.accredited_test_report")
        if (_finite(working) and float(working) > 0 and _finite(tested)
                and float(tested) > 0 and accredited is True):
            ratio = float(tested) / float(working)
            evidence.append(f"system[{index}] closed-tank test/working ratio={ratio:.6g} minimum={factor:g}")
            if ratio < factor:
                errors.append(f"HEATING_CLOSED_EXPANSION_TANK_TEST_PRESSURE_LOW:{index}")
    if missing:
        return _result(rule, INPUT_REQUIRED, evidence=evidence, missing=missing, errors=errors)
    if not applicable:
        return _result(rule, NOT_APPLICABLE, evidence=["no CLOSED expansion tank in supplied systems"])
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


VALIDATORS = {
    "heating_surface_guard": _surface_guard,
    "floor_mounted_heating_base_height": _floor_base,
    "hot_water_heating_expansion_tank": _hot_water_expansion_tank,
    "open_expansion_tank_elevation": _open_expansion_tank_elevation,
    "closed_expansion_tank_test_pressure": _closed_expansion_tank_test_pressure,
}


def load_heating_rulebook():
    module = load_rulebook_module(HEATING_ROOT)
    integrity = validate_rulebook_module(module)
    if integrity["status"] != "PASS":
        raise ValueError("heating Rulebook integrity failed: " + ",".join(integrity["errors"]))
    return module


def evaluate_heating_rulebook(snapshot):
    module = load_heating_rulebook()
    results = [VALIDATORS[row["validator"]](row, snapshot) for row in rule_rows(module)]
    status = (FAIL if any(row["status"] == FAIL for row in results)
              else INPUT_REQUIRED if any(row["status"] == INPUT_REQUIRED for row in results)
              else PASS)
    return {
        "module_id": module["manifest"]["module_id"],
        "module_version": module["manifest"]["version"],
        "results": results,
        "status": status,
    }


def heating_design_profile():
    module = load_heating_rulebook()
    rows = {row["validator"]: row for row in rule_rows(module)}
    return {
        "module_version": module["manifest"]["version"],
        "surface_guard": rows["heating_surface_guard"]["parameters"],
        "floor_mounted_equipment_base": rows["floor_mounted_heating_base_height"]["parameters"],
        "hot_water_expansion_tank": rows["hot_water_heating_expansion_tank"]["parameters"],
        "open_expansion_tank_elevation": rows["open_expansion_tank_elevation"]["parameters"],
        "closed_expansion_tank_test_pressure": rows["closed_expansion_tank_test_pressure"]["parameters"],
        "authority": "M14-1391",
        "source_ids": ["M14-H-001", "M14-H-002", "M14-H-003", "M14-H-004", "M14-H-005"],
    }
