"""Executable M16 cold/hot domestic-water Rulebook module."""
from __future__ import annotations

from math import isfinite

from .executable_rulebook import WATER_ROOT, load_rulebook_module, rule_rows, validate_rulebook_module

PASS, FAIL, INPUT_REQUIRED, NOT_APPLICABLE = "PASS", "FAIL", "INPUT_REQUIRED", "NOT_APPLICABLE"


def _result(rule, status, *, evidence=(), missing=(), errors=()):
    return {
        "rule_id": rule["rule_id"], "rule_version": rule["version"], "status": status,
        "source_ids": sorted({value for source in rule["sources"] for value in source["source_ids"]}),
        "evidence": list(evidence), "missing_inputs": sorted(set(missing)),
        "errors": sorted(set(errors)), "llm_override_allowed": False,
    }


def _finite(value):
    try:
        return isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _hot_cold_backflow(rule, snapshot):
    rows = ((snapshot or {}).get("water") or {}).get("interconnections")
    if rows is None:
        return _result(rule, INPUT_REQUIRED, missing=["water.interconnections"])
    if not rows:
        return _result(rule, NOT_APPLICABLE, evidence=["interconnections=0"])
    missing = [f"water.interconnections[{i}].{key}" for i, row in enumerate(rows)
               for key in ("backflow_prevention", "device_id", "product_evidence_id")
               if row.get(key) in (None, "")]
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing)
    errors = [f"HOT_COLD_BACKFLOW_NOT_PREVENTED:{i}" for i, row in enumerate(rows)
              if row.get("backflow_prevention") is not True]
    return _result(rule, FAIL if errors else PASS, evidence=[f"interconnections={len(rows)}"], errors=errors)


def _manifold_velocity(rule, snapshot):
    rows = ((snapshot or {}).get("water") or {}).get("manifolds")
    if rows is None:
        return _result(rule, INPUT_REQUIRED, missing=["water.manifolds"])
    applicable = [row for row in rows if row.get("independent_fixture_branches") is True]
    unknown = [i for i, row in enumerate(rows) if row.get("independent_fixture_branches") is None]
    if unknown:
        return _result(rule, INPUT_REQUIRED, missing=[f"water.manifolds[{i}].independent_fixture_branches" for i in unknown])
    if not applicable:
        return _result(rule, NOT_APPLICABLE, evidence=["applicable_manifolds=0"])
    missing = [f"water.manifolds[{i}].{key}" for i, row in enumerate(applicable)
               for key in ("velocity_m_s", "hydraulic_calculation_id")
               if (not _finite(row.get(key)) if key == "velocity_m_s" else row.get(key) in (None, ""))]
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing)
    maximum = float(rule["parameters"]["maximum_velocity_m_s"])
    errors = [f"MANIFOLD_VELOCITY_ABOVE_{maximum:g}_M_S:{i}" for i, row in enumerate(applicable)
              if float(row["velocity_m_s"]) > maximum]
    return _result(rule, FAIL if errors else PASS,
                   evidence=[f"velocities_m_s={[float(row['velocity_m_s']) for row in applicable]}"], errors=errors)


def _component_rating(rule, snapshot):
    rows = ((snapshot or {}).get("water") or {}).get("components")
    if not rows:
        return _result(rule, INPUT_REQUIRED, missing=["water.components"])
    required = ("system", "rated_pressure_bar", "rated_temperature_c", "maximum_operating_pressure_bar",
                "manufacturer_evidence_id")
    missing = [f"water.components[{i}].{key}" for i, row in enumerate(rows) for key in required
               if row.get(key) in (None, "")]
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing)
    errors, evidence = [], []
    for i, row in enumerate(rows):
        if any(not _finite(row.get(key)) for key in required[1:4]):
            return _result(rule, INPUT_REQUIRED, missing=[f"water.components[{i}].numeric_rating"])
        system = str(row["system"]).upper()
        if system not in {"COLD_WATER", "HOT_WATER"}:
            errors.append(f"COMPONENT_SYSTEM_INVALID:{i}"); continue
        minimum_temperature = float(rule["parameters"]["hot_temperature_c" if system == "HOT_WATER" else "cold_temperature_c"])
        minimum_pressure = max(float(rule["parameters"]["minimum_pressure_bar"]),
                               float(row["maximum_operating_pressure_bar"]))
        evidence.append(f"component[{i}] required={minimum_pressure:g}bar/{minimum_temperature:g}C")
        if float(row["rated_pressure_bar"]) < minimum_pressure:
            errors.append(f"COMPONENT_PRESSURE_RATING_LOW:{i}")
        if float(row["rated_temperature_c"]) < minimum_temperature:
            errors.append(f"COMPONENT_TEMPERATURE_RATING_LOW:{i}")
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _fixture_minimum_dn(rule, snapshot):
    rows = ((snapshot or {}).get("water") or {}).get("fixture_branches")
    if not rows:
        return _result(rule, INPUT_REQUIRED, missing=["water.fixture_branches"])
    table = rule["parameters"]["minimum_dn_mm"]
    missing, errors, evidence = [], [], []
    for i, row in enumerate(rows):
        fixture, dn = str(row.get("fixture_type") or ""), row.get("dn_mm")
        if fixture not in table:
            missing.append(f"water.fixture_branches[{i}].supported_fixture_type")
        elif not _finite(dn) or float(dn) <= 0:
            missing.append(f"water.fixture_branches[{i}].dn_mm")
        else:
            minimum = float(table[fixture]); evidence.append(f"branch[{i}] DN{float(dn):g} min=DN{minimum:g}")
            if float(dn) < minimum: errors.append(f"FIXTURE_BRANCH_DN_LOW:{i}")
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _fixture_pressure(rule, snapshot):
    rows = ((snapshot or {}).get("water") or {}).get("fixture_outlets")
    if not rows:
        return _result(rule, INPUT_REQUIRED, missing=["water.fixture_outlets"])
    table = rule["parameters"]["minimum_flowing_pressure_mwc"]
    maximum = float(rule["parameters"]["maximum_static_pressure_bar"])
    missing, errors, evidence = [], [], []
    for i, row in enumerate(rows):
        fixture = str(row.get("fixture_type") or "")
        static, flowing = row.get("static_pressure_bar"), row.get("flowing_pressure_mwc")
        if fixture not in table: missing.append(f"water.fixture_outlets[{i}].supported_pressure_fixture_type")
        if not _finite(static): missing.append(f"water.fixture_outlets[{i}].static_pressure_bar")
        if not _finite(flowing): missing.append(f"water.fixture_outlets[{i}].flowing_pressure_mwc")
        if fixture in table and _finite(static) and _finite(flowing):
            minimum = float(table[fixture]); evidence.append(
                f"outlet[{i}] static={float(static):g}bar flowing={float(flowing):g}mH2O min={minimum:g}")
            if float(static) > maximum: errors.append(f"FIXTURE_STATIC_PRESSURE_ABOVE_4_BAR:{i}")
            if float(flowing) < minimum: errors.append(f"FIXTURE_FLOWING_PRESSURE_LOW:{i}")
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _fixture_consumption(rule, snapshot):
    rows = ((snapshot or {}).get("water") or {}).get("fixture_outlets")
    if not rows:
        return _result(rule, INPUT_REQUIRED, missing=["water.fixture_outlets"])
    table = rule["parameters"]["maximum_consumption"]
    missing, errors, evidence = [], [], []
    for i, row in enumerate(rows):
        fixture = str(row.get("flow_fixture_type") or row.get("fixture_type") or "")
        value, unit = row.get("rated_consumption"), row.get("rated_consumption_unit")
        product = row.get("flow_control_product_id")
        if fixture not in table: missing.append(f"water.fixture_outlets[{i}].supported_flow_fixture_type"); continue
        expected = table[fixture]
        if not _finite(value): missing.append(f"water.fixture_outlets[{i}].rated_consumption")
        if unit != expected["unit"]: missing.append(f"water.fixture_outlets[{i}].rated_consumption_unit")
        if not product: missing.append(f"water.fixture_outlets[{i}].flow_control_product_id")
        if _finite(value) and unit == expected["unit"] and product:
            evidence.append(f"outlet[{i}]={float(value):g}{unit} max={float(expected['value']):g}{unit}")
            if float(value) > float(expected["value"]): errors.append(f"FIXTURE_CONSUMPTION_HIGH:{i}")
            if fixture == "dual_flush_toilet" and row.get("secondary_rated_consumption") != expected["secondary_value"]:
                errors.append(f"DUAL_FLUSH_SECONDARY_VALUE_INVALID:{i}")
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _water_hammer(rule, snapshot):
    rows = ((snapshot or {}).get("water") or {}).get("quick_closing_valves")
    if rows is None:
        return _result(rule, INPUT_REQUIRED, missing=["water.quick_closing_valves"])
    if not rows:
        return _result(rule, NOT_APPLICABLE, evidence=["quick_closing_valves=0"])
    missing, errors = [], []
    for i, row in enumerate(rows):
        point = row.get("point")
        if not isinstance(point, (list, tuple)) or len(point) != 2 or not all(_finite(v) for v in point):
            missing.append(f"water.quick_closing_valves[{i}].point")
        for key in ("arrestor_product_id", "arrestor_standard", "accessible"):
            if row.get(key) in (None, ""): missing.append(f"water.quick_closing_valves[{i}].{key}")
        if row.get("accessible") is False: errors.append(f"WATER_HAMMER_ARRESTOR_NOT_ACCESSIBLE:{i}")
        standard = str(row.get("arrestor_standard") or "").upper()
        if standard and standard != "ASSE 1010" and row.get("equivalent_approval_id") in (None, ""):
            missing.append(f"water.quick_closing_valves[{i}].equivalent_approval_id")
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=[f"quick_closing_valves={len(rows)}"], errors=errors)


def _probable_demand(rule, snapshot):
    """Recompute selected source-table SFU totals and exact probable-demand rows.

    The printed table is discrete.  This implementation intentionally does not
    interpolate between rows or extrapolate beyond the visually verified set.
    """
    rows = ((snapshot or {}).get("water") or {}).get("sizing_segments")
    if not rows:
        return _result(rule, INPUT_REQUIRED, missing=["water.sizing_segments"])
    fixture_sfu = rule["parameters"]["fixture_sfu"]
    demand = rule["parameters"]["probable_flow_l_s"]
    missing, errors, evidence = [], [], []
    for i, row in enumerate(rows):
        scope = str(row.get("supply_scope") or "")
        mode = str(row.get("system_mode") or "")
        fixtures = row.get("fixtures")
        if scope not in {"cold", "hot", "total"}:
            missing.append(f"water.sizing_segments[{i}].supply_scope")
        if mode not in demand:
            missing.append(f"water.sizing_segments[{i}].system_mode")
        if not isinstance(fixtures, list) or not fixtures:
            missing.append(f"water.sizing_segments[{i}].fixtures")
            continue
        total = 0.0
        valid = True
        for j, fixture in enumerate(fixtures):
            key, count = str(fixture.get("fixture_sfu_type") or ""), fixture.get("count")
            if key not in fixture_sfu:
                missing.append(f"water.sizing_segments[{i}].fixtures[{j}].supported_fixture_sfu_type")
                valid = False
            if not _finite(count) or float(count) <= 0 or not float(count).is_integer():
                missing.append(f"water.sizing_segments[{i}].fixtures[{j}].count")
                valid = False
            if valid:
                total += float(fixture_sfu[key][scope]) * int(float(count))
        if not valid or scope not in {"cold", "hot", "total"} or mode not in demand:
            continue
        declared = row.get("declared_total_sfu")
        probable = row.get("probable_flow_l_s")
        if not _finite(declared):
            missing.append(f"water.sizing_segments[{i}].declared_total_sfu")
        elif abs(float(declared) - total) > 1e-9:
            errors.append(f"SEGMENT_SFU_TOTAL_MISMATCH:{i}")
        key = f"{total:g}"
        expected = demand[mode].get(key)
        if expected is None:
            missing.append(f"water.sizing_segments[{i}].verified_probable_demand_row[{key}]")
        elif not _finite(probable):
            missing.append(f"water.sizing_segments[{i}].probable_flow_l_s")
        elif abs(float(probable) - float(expected)) > 1e-9:
            errors.append(f"SEGMENT_PROBABLE_FLOW_MISMATCH:{i}")
        else:
            evidence.append(f"segment[{i}] scope={scope} SFU={key} mode={mode} flow={float(expected):g}L/s")
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _galvanized_equivalent_length(rule, snapshot):
    rows = ((snapshot or {}).get("water") or {}).get("sizing_segments")
    if not rows:
        return _result(rule, INPUT_REQUIRED, missing=["water.sizing_segments"])
    table = rule["parameters"]["equivalent_length_m"]
    missing, errors, evidence = [], [], []
    applicable = 0
    for i, row in enumerate(rows):
        if row.get("pipe_material") != "GALVANIZED_STEEL":
            continue
        applicable += 1
        dn, fittings = row.get("dn_mm"), row.get("fittings")
        declared = row.get("declared_fitting_equivalent_length_m")
        dn_key = f"{float(dn):g}" if _finite(dn) and float(dn) > 0 else ""
        if dn_key not in table:
            missing.append(f"water.sizing_segments[{i}].supported_galvanized_dn_mm")
        if not isinstance(fittings, list):
            missing.append(f"water.sizing_segments[{i}].fittings")
            continue
        total, valid = 0.0, True
        for j, fitting in enumerate(fittings):
            kind, quantity = str(fitting.get("type") or ""), fitting.get("quantity")
            if dn_key not in table or kind not in (table.get(dn_key) or {}):
                missing.append(f"water.sizing_segments[{i}].fittings[{j}].supported_type")
                valid = False
            if not _finite(quantity) or float(quantity) < 0 or not float(quantity).is_integer():
                missing.append(f"water.sizing_segments[{i}].fittings[{j}].quantity")
                valid = False
            if valid:
                total += float(table[dn_key][kind]) * int(float(quantity))
        if not _finite(declared):
            missing.append(f"water.sizing_segments[{i}].declared_fitting_equivalent_length_m")
        elif valid and abs(float(declared) - total) > 1e-9:
            errors.append(f"FITTING_EQUIVALENT_LENGTH_MISMATCH:{i}")
        elif valid:
            evidence.append(f"segment[{i}] DN{dn_key} fitting_equivalent_length={total:g}m")
    if not applicable:
        return _result(rule, NOT_APPLICABLE, evidence=["galvanized_steel_segments=0"])
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing, errors=errors)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _outlet_temperature(rule, snapshot):
    water = (snapshot or {}).get("water") or {}
    special = water.get("special_building_temperature_basis")
    if special is None:
        return _result(rule, INPUT_REQUIRED, missing=["water.special_building_temperature_basis"])
    if special is True:
        return _result(rule, INPUT_REQUIRED, missing=["water.approved_special_temperature_limits"])
    rows = water.get("hot_outlets")
    if not rows:
        return _result(rule, NOT_APPLICABLE, evidence=["hot_outlets=0"])
    limits = rule["parameters"]["maximum_c"]
    missing, errors, evidence = [], [], []
    for i, row in enumerate(rows):
        fixture = str(row.get("fixture_type") or "")
        value = row.get("design_temperature_c")
        if fixture not in limits:
            missing.append(f"water.hot_outlets[{i}].supported_fixture_type")
        elif not _finite(value):
            missing.append(f"water.hot_outlets[{i}].design_temperature_c")
        else:
            evidence.append(f"outlet[{i}]={float(value):g}C limit={float(limits[fixture]):g}C")
            if float(value) > float(limits[fixture]): errors.append(f"HOT_OUTLET_TEMPERATURE_HIGH:{i}")
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing)
    return _result(rule, FAIL if errors else PASS, evidence=evidence, errors=errors)


def _hot_water_return(rule, snapshot):
    hot = (((snapshot or {}).get("water") or {}).get("hot_water") or {})
    length = hot.get("heater_to_farthest_outlet_length_m")
    if not _finite(length) or float(length) < 0:
        return _result(rule, INPUT_REQUIRED, missing=["water.hot_water.heater_to_farthest_outlet_length_m"])
    trigger = float(rule["parameters"]["trigger_length_m"])
    if float(length) <= trigger:
        return _result(rule, NOT_APPLICABLE, evidence=[f"length_m={float(length):g}"])
    method = hot.get("temperature_maintenance_method")
    if not method:
        return _result(rule, INPUT_REQUIRED, missing=["water.hot_water.temperature_maintenance_method"])
    if not hot.get("temperature_maintenance_evidence_id"):
        return _result(rule, INPUT_REQUIRED, missing=["water.hot_water.temperature_maintenance_evidence_id"])
    if method not in {"RETURN_LOOP", "AUTOMATIC_HEAT_TRACE"}:
        return _result(rule, FAIL, evidence=[f"method={method}"], errors=["TEMPERATURE_MAINTENANCE_METHOD_INVALID"])
    return _result(rule, PASS, evidence=[f"length_m={float(length):g}", f"method={method}"])


def _pressure_test(rule, snapshot):
    stage = (snapshot or {}).get("duty_stage")
    if stage is None:
        return _result(rule, INPUT_REQUIRED, missing=["duty_stage"])
    if stage == "DESIGN_AND_LATER":
        note = (((snapshot or {}).get("water") or {}).get("construction_pressure_test_note"))
        return _result(rule, PASS if note else INPUT_REQUIRED,
                       evidence=["construction requirement carried"] if note else (),
                       missing=[] if note else ["water.construction_pressure_test_note"])
    if stage != "CONSTRUCTION_AND_FINAL_INSPECTION":
        return _result(rule, INPUT_REQUIRED, missing=["supported_duty_stage"])
    record = (((snapshot or {}).get("water") or {}).get("construction_pressure_test") or {})
    required = ("test_pressure_bar", "maximum_operating_pressure_bar", "duration_h", "result", "supervisor_approval_id")
    missing = [f"water.construction_pressure_test.{key}" for key in required if record.get(key) in (None, "")]
    if missing:
        return _result(rule, INPUT_REQUIRED, missing=missing)
    if not _finite(record["duration_h"]) or float(record["duration_h"]) < float(rule["parameters"]["minimum_duration_h"]):
        return _result(rule, FAIL, errors=["PRESSURE_TEST_DURATION_LOW"])
    if not _finite(record["test_pressure_bar"]) or not _finite(record["maximum_operating_pressure_bar"]):
        return _result(rule, INPUT_REQUIRED, missing=["water.construction_pressure_test.numeric_pressure"])
    required_pressure = max(10.0, float(record["maximum_operating_pressure_bar"]))
    if float(record["test_pressure_bar"]) < required_pressure:
        return _result(rule, FAIL, errors=["PRESSURE_TEST_PRESSURE_LOW"],
                       evidence=[f"required_pressure_bar={required_pressure:g}"])
    return _result(rule, PASS if record["result"] == "PASS" else FAIL,
                   evidence=[f"duration_h={record['duration_h']}", f"pressure_bar={record['test_pressure_bar']}"],
                   errors=[] if record["result"] == "PASS" else ["PRESSURE_TEST_FAILED"])


VALIDATORS = {
    "hot_cold_backflow_prevention": _hot_cold_backflow,
    "manifold_velocity": _manifold_velocity,
    "component_pressure_temperature_rating": _component_rating,
    "fixture_minimum_dn": _fixture_minimum_dn,
    "fixture_pressure": _fixture_pressure,
    "fixture_maximum_consumption": _fixture_consumption,
    "water_hammer_arrestor": _water_hammer,
    "probable_demand_from_sfu": _probable_demand,
    "galvanized_fitting_equivalent_length": _galvanized_equivalent_length,
    "hot_water_outlet_temperature": _outlet_temperature,
    "hot_water_return_length": _hot_water_return,
    "construction_pressure_test_dependency": _pressure_test,
}


def load_water_rulebook():
    module = load_rulebook_module(WATER_ROOT)
    integrity = validate_rulebook_module(module)
    if integrity["status"] != "PASS":
        raise ValueError("water Rulebook integrity failed: " + ",".join(integrity["errors"]))
    return module


def evaluate_water_rulebook(snapshot):
    module = load_water_rulebook()
    results = []
    for rule in rule_rows(module):
        validator = VALIDATORS.get(rule["validator"])
        results.append(validator(rule, snapshot) if validator else _result(
            rule, INPUT_REQUIRED, missing=[f"validator:{rule['validator']}"]))
    return {"module_id": module["manifest"]["module_id"],
            "module_version": module["manifest"]["version"], "results": results,
            "status": FAIL if any(row["status"] == FAIL for row in results) else
                      INPUT_REQUIRED if any(row["status"] == INPUT_REQUIRED for row in results) else PASS}


def water_design_profile():
    """Return designer inputs while preserving each value's governing authority."""
    module = load_water_rulebook()
    branch_rule = next(row for row in rule_rows(module) if row["validator"] == "fixture_minimum_dn")
    demand_rule = next(row for row in rule_rows(module) if row["validator"] == "probable_demand_from_sfu")
    equivalent_rule = next(row for row in rule_rows(module)
                           if row["validator"] == "galvanized_fitting_equivalent_length")
    return {"material": "PPR", "hazen_williams_c": 150,
            "target_velocity_mps": 1.5, "maximum_friction_loss_kpa_per_100m": 20,
            "minimum_fixture_branch_dn_mm": branch_rule["parameters"]["minimum_dn_mm"],
            "minimum_fixture_branch_dn_provenance": {
                "authority": "STATUTORY_MANDATORY",
                "rule_id": branch_rule["rule_id"],
                "module_version": module["manifest"]["version"],
                "source_ids": list(branch_rule["sources"][0]["source_ids"]),
            },
            "probable_demand_method": {
                "method": "M16_APPENDIX_1_EXACT_VERIFIED_ROWS_NO_INTERPOLATION",
                "rule_id": demand_rule["rule_id"],
                "fixture_sfu": demand_rule["parameters"]["fixture_sfu"],
                "probable_flow_l_s": demand_rule["parameters"]["probable_flow_l_s"],
            },
            "galvanized_fitting_equivalent_length_method": {
                "method": "M16_APPENDIX_1_TABLE_P1_4_5_3_EXACT_DN_AND_FITTING",
                "rule_id": equivalent_rule["rule_id"],
                "equivalent_length_m": equivalent_rule["parameters"]["equivalent_length_m"],
            },
            "authority": "PLANHA_INTERNAL", "source_id": "MEP-SIZE-001"}
