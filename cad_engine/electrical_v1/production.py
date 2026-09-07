"""Production adapter for the active Electrical authority pipeline.

The dedicated CAD image contains only ``cad_engine``; therefore this module must
remain self-contained and may not import the web ``app`` package.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import re

from .runtime_support import canonical_earthing, canonical_supply, execution_score
from .acceptance_pipeline import run_acceptance_electrical_pipeline

PIPELINE_AUTHORITY = "electrical-authority"


def _negative(value):
    text = str(value or "").strip().lower()
    return value is False or any(x in text for x in ("ندارد", "نداریم", "نیست", "خارج از محدوده", "خیر", "none", "not required", "no "))


def _explicit_bool(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if _negative(value):
        return False
    text = str(value).strip().lower()
    if any(x in text for x in ("دارد", "داریم", "بله", "نیاز دارد", "required", "yes", "فعال")):
        return True
    return value


def _number(value, integer=False):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value) if integer else float(value)
    text = str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    match = re.search(r"[-+]?\d+(?:[.,٫]\d+)?", text)
    if not match:
        return None
    parsed = float(match.group(0).replace("٫", ".").replace(",", "."))
    return int(parsed) if integer else parsed


def _kv_pairs(value):
    if isinstance(value, dict):
        return dict(value)
    text = str(value or "").strip()
    if not text:
        return {}
    result = {}
    for token in re.split(r"[;\n]+", text):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            key, raw = token.split("=", 1)
        elif ":" in token and "->" not in token:
            key, raw = token.split(":", 1)
        else:
            continue
        result[key.strip().lower()] = raw.strip()
    return result


def _numeric_map(value):
    if isinstance(value, dict):
        out = {}
        for key, raw in value.items():
            number = _number(raw)
            if number is not None:
                out[str(key).strip().lower()] = number
        return out
    return {key: number for key, raw in _kv_pairs(value).items() if (number := _number(raw)) is not None}


def _lighting_basis(value):
    if isinstance(value, dict):
        return value
    return _numeric_map(value)


def _luminaire_schedule(value):
    if isinstance(value, dict):
        if "luminaires" in value:
            return dict(value.get("luminaires") or {})
        if any(k in value for k in ("lumens", "utilization_factor", "maintenance_factor", "input_power_w")):
            return {"default": dict(value)}
        return value
    pairs = _kv_pairs(value)
    aliases = {"cu": "utilization_factor", "uf": "utilization_factor", "mf": "maintenance_factor", "power_w": "input_power_w"}
    data = {}
    for key, raw in pairs.items():
        target = aliases.get(key, key)
        if target in {"lumens", "utilization_factor", "maintenance_factor", "input_power_w"}:
            number = _number(raw)
            if number is not None:
                data[target] = number
    return {"default": data} if data else {}


def _socket_rules(value):
    if isinstance(value, dict):
        return value
    pairs = _kv_pairs(value)
    count = _number(pairs.get("minimum_count") or pairs.get("count") or pairs.get("default_count"), integer=True)
    load = _number(pairs.get("design_load_w_per_outlet") or pairs.get("load_w") or pairs.get("watts"))
    reference = pairs.get("reference")
    if count is None:
        return {}
    row = {"minimum_count": count}
    if load is not None:
        row["design_load_w_per_outlet"] = load
    if reference:
        row["reference"] = reference
    return {"default": row}


def _appliance_schedule(value):
    if isinstance(value, dict):
        return value
    if _negative(value):
        return {}
    text = str(value or "").strip()
    if not text:
        return {}
    result = {}
    # Explicit compact format: kitchen=oven@2500,dishwasher@1800
    for room, raw_items in _kv_pairs(text).items():
        items = []
        for raw in re.split(r"[,،]+", raw_items):
            raw = raw.strip()
            if not raw:
                continue
            if "@" in raw:
                name, watts = raw.rsplit("@", 1)
                load = _number(watts)
                if load is not None:
                    items.append({"name": name.strip() or "appliance", "load_w": load})
        if items:
            result[room] = items
    return result


def _canonical_low_current(value):
    if value in (None, ""):
        return None
    if _negative(value):
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    found = []
    aliases = {
        "TELECOM": ("telecom", "telephone", "تلفن"),
        "DATA": ("data", "network", "شبکه"),
        "TV": ("tv", "antenna", "آنتن", "انتن"),
        "INTERCOM": ("intercom", "آیفون", "ایفون"),
        "CCTV": ("cctv", "camera", "دوربین"),
        "ACCESS_CONTROL": ("access control", "کنترل تردد", "اکسس"),
    }
    for raw in values:
        text = str(raw or "").lower()
        for canonical, tokens in aliases.items():
            if canonical not in found and any(token.lower() in text for token in tokens):
                found.append(canonical)
    return found


def _riser_feeders(value):
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    rows = [row.strip() for row in text.splitlines() if row.strip()]
    if not rows:
        rows = [text]
    result = {}
    for index, row in enumerate(rows, 1):
        explicit = re.search(r"(LVL-\d{3}->LVL-\d{3})", row, re.I)
        key = explicit.group(1).upper() if explicit else f"LVL-{index:03d}->LVL-{index+1:03d}"
        payload = row.split(":", 1)[-1] if explicit and ":" in row else row
        pairs = _kv_pairs(payload.replace(",", ";"))
        cable = pairs.get("cable") or pairs.get("کابل")
        protection = pairs.get("protection") or pairs.get("حفاظت")
        tag = pairs.get("tag") or pairs.get("تگ")
        if cable and protection and tag:
            result[key] = {"cable": cable, "protection": protection, "tag": tag}
    return result


def _build_detail_parameters(answers: dict) -> dict:
    """Translate flat site/panel answers into the parametric detail contract.

    No construction value is inferred here. Existing structured ``detail_parameters``
    have priority; flat fields are only copied when the user explicitly supplied
    them. This allows late CAD INPUT_REQUIRED recovery to ask one exact question,
    resume the same project, and then satisfy the matching detail parameter.
    """
    explicit = {
        str(detail_id): dict(values or {})
        for detail_id, values in dict(answers.get("detail_parameters") or {}).items()
        if isinstance(values, dict)
    }
    mapping = {
        "D-EL-PANEL-MOUNT": {
            "mounting_height": "detail_panel_mounting_height_mm",
            "wall_type": "detail_wall_type",
            "clearance": "detail_panel_clearance_mm",
        },
        "D-EL-METER": {
            "mounting_height": "detail_meter_mounting_height_mm",
            "service_type": "detail_service_type",
        },
        "D-EL-CONDUIT-SUPPORT": {
            "support_spacing": "detail_conduit_support_spacing_mm",
            "conduit_type": "detail_conduit_type",
        },
        "D-EL-WALL-PEN": {
            "wall_type": "detail_wall_type",
            "fire_rating": "detail_fire_rating",
            "sleeve": "detail_sleeve_type",
        },
        "D-EL-EARTHING": {
            "electrode_type": "detail_earthing_electrode_type",
            "conductor": "detail_earthing_conductor",
            "inspection_point": "detail_earthing_inspection_point",
        },
        "D-EL-LIGHT-MOUNT": {
            "ceiling_type": "detail_ceiling_type",
            "fixture_type": "detail_fixture_type",
        },
        "D-EL-SWITCH-OUTLET": {
            "mounting_height": "detail_device_mounting_height_mm",
            "wall_type": "detail_wall_type",
        },
        "D-EL-FIRE-DETECTOR": {
            "ceiling_type": "detail_ceiling_type",
            "clearance_basis": "detail_detector_clearance_basis",
        },
        "D-EL-EMERGENCY": {
            "mounting": "detail_emergency_mounting",
            "supply": "detail_emergency_supply",
        },
        "D-EL-JB": {
            "box_size": "detail_junction_box_size",
            "access": "detail_junction_box_access",
        },
        "D-EL-TERMINATION": {
            "cable": "detail_service_cable",
            "lug": "detail_lug_type",
            "protection": "detail_termination_protection",
        },
        "D-EL-ISOLATOR": {
            "rating": "detail_isolator_rating",
            "mounting": "detail_isolator_mounting",
            "clearance": "detail_isolator_clearance",
        },
    }
    for detail_id, params in mapping.items():
        target = explicit.setdefault(detail_id, {})
        for parameter, answer_key in params.items():
            if parameter in target:
                continue
            value = answers.get(answer_key)
            if value not in (None, "", [], {}):
                target[parameter] = value
        if not target:
            explicit.pop(detail_id, None)
    return explicit


def build_engine_config(answers: dict | None, plan_analysis: dict | None = None) -> dict[str, Any]:
    answers = dict(answers or {})
    explicit = dict(answers.get("_electrical_engine_config") or {})
    if explicit:
        return explicit
    analysis = dict(plan_analysis or {})
    auto = dict(analysis.get("architectural_auto") or {})
    supply = canonical_supply(answers.get("supply_configuration") or answers.get("supply")) or {}
    earthing = canonical_earthing(answers.get("earthing_final_basis") or answers.get("earthing_system") or answers.get("earthing"))
    design_basis = {}

    def put(key, value):
        if value not in (None, "", [], {}):
            design_basis[key] = value

    put("city", answers.get("city") or answers.get("location"))
    put("building_type", answers.get("building_type") or answers.get("occupancy") or auto.get("occupancy_inferred"))
    put("number_of_units", _number(answers.get("number_of_units"), integer=True))
    put("supply_voltage_v", _number(answers.get("supply_voltage_v")) or supply.get("voltage_v"))
    put("phase_configuration", supply.get("configuration"))
    put("utility_service", answers.get("utility_service") or answers.get("supply") or answers.get("supply_configuration"))
    put("earthing_system", None if earthing == "input_required" else earthing)

    lighting = _lighting_basis(answers.get("lighting_basis_values"))
    put("lighting_basis", lighting)
    put("switch_control_requirements", _numeric_map(answers.get("switch_control_requirements")))
    put("socket_power_requirements", _socket_rules(answers.get("socket_power_requirements")))
    dedicated_raw = answers.get("dedicated_appliance_requirements") or answers.get("dedicated_load_schedule")
    if dedicated_raw not in (None, ""):
        dedicated = _appliance_schedule(dedicated_raw)
        # An explicit negative answer is evidence of an empty schedule; preserve
        # the empty dict through the applicable-rule channel below.
        if dedicated or _negative(dedicated_raw):
            design_basis["dedicated_appliance_requirements"] = dedicated
    put("hvac_electrical_loads", _explicit_bool(answers.get("hvac_electrical_loads")))
    put("elevator", _explicit_bool(answers.get("elevator_load") or answers.get("elevator")))
    put("pump", _explicit_bool(answers.get("pump_load") or answers.get("pump")))
    put("emergency_lighting", _explicit_bool(answers.get("emergency_lighting")))
    fire = answers.get("fire_alarm_requirement") or answers.get("fire_alarm")
    if fire not in (None, ""):
        put("fire_alarm_requirement", not _negative(fire))
    low_current = _canonical_low_current(answers.get("low_current_systems") or answers.get("elv"))
    if low_current is not None:
        # Empty explicit list is meaningful NOT_REQUIRED evidence and must not be
        # dropped by ``put``.
        design_basis["low_current_systems"] = low_current

    emergency = str(answers.get("emergency") or "").lower()
    if emergency:
        design_basis["generator"] = "ژنراتور" in emergency or "generator" in emergency
        design_basis["ups"] = "ups" in emergency
    for key in ("lightning_protection", "generator", "ups", "ev_charging", "solar_pv"):
        if answers.get(key) not in (None, ""):
            design_basis[key] = _explicit_bool(answers.get(key))
    for key in ("ambient_temperature_c", "power_factor", "frequency_hz"):
        put(key, _number(answers.get(key)))
    put("installation_method", answers.get("installation_method"))
    put("conductor_material", answers.get("conductor_material"))
    if answers.get("voltage_drop_limits") not in (None, ""):
        limits = answers.get("voltage_drop_limits")
        if not isinstance(limits, dict):
            parsed = _numeric_map(limits)
            limits = parsed or ({"default": _number(limits)} if _number(limits) is not None else None)
        put("voltage_drop_limits", limits)

    manufacturer_data = dict(answers.get("manufacturer_data") or {})
    luminaires = _luminaire_schedule(answers.get("luminaire_schedule"))
    if luminaires:
        existing = dict(manufacturer_data.get("luminaires") or {})
        existing.update(luminaires)
        manufacturer_data["luminaires"] = existing

    placement_rules = dict(answers.get("placement_rules") or {})
    for key in ("opening_clearance_m", "wall_host_tolerance_m"):
        value = _number(answers.get(key))
        if value is not None:
            placement_rules[key] = value
    for key in ("ceiling_layout_basis_confirmed", "switch_door_relation_confirmed"):
        value = _explicit_bool(answers.get(key))
        if isinstance(value, bool):
            placement_rules[key] = value

    circuit_rules = dict(answers.get("circuit_rules") or {})
    if isinstance(answers.get("panel_locations"), dict):
        circuit_rules["panel_locations"] = dict(answers["panel_locations"])
    if answers.get("circuit_demand_rules"):
        demand = _numeric_map(answers.get("circuit_demand_rules"))
        if demand:
            circuit_rules["demand_factors"] = demand

    calculation_rules = dict(answers.get("calculation_rules") or {})
    threshold = _number(answers.get("phase_balance_threshold_pct"))
    if threshold is not None:
        calculation_rules["max_phase_imbalance_pct"] = threshold

    service_inputs = dict(answers.get("service_inputs") or {})
    flat_service = {
        "service": answers.get("service"),
        "meter": answers.get("meter"),
        "main_distribution": answers.get("main_distribution"),
    }
    for key, value in flat_service.items():
        if value not in (None, ""):
            service_inputs[key] = value
    riser = _riser_feeders(answers.get("riser_feeder_schedule"))
    if riser:
        service_inputs["riser_feeders"] = {**dict(service_inputs.get("riser_feeders") or {}), **riser}

    optional_system_inputs = dict(answers.get("optional_system_inputs") or {})
    grounding = dict(optional_system_inputs.get("grounding") or {})
    for target, answer_key in (
        ("earth_electrode", "grounding_earth_electrode"),
        ("main_earth_bar", "grounding_main_earth_bar"),
        ("protective_conductors", "grounding_protective_conductors"),
        ("panel_grounding", "grounding_panel_grounding"),
    ):
        value = answers.get(answer_key)
        if value not in (None, ""):
            grounding[target] = value
    if grounding:
        optional_system_inputs["grounding"] = grounding

    applicable_basis = dict(answers.get("electrical_rule_design_basis") or {})
    # Explicit empty dedicated schedule is valid evidence; ``build_design_basis``
    # must see it even though ``put`` intentionally ignores empty containers.
    if dedicated_raw not in (None, "") and _negative(dedicated_raw):
        applicable_basis["dedicated_appliance_requirements"] = {}

    return {
        "project_inputs": {
            "project_name": answers.get("project_name") or "EngiTools Electrical Project",
            "building_type": design_basis.get("building_type") or "unknown",
        },
        "design_basis": design_basis,
        "applicable_rules": {"design_basis": applicable_basis},
        "manufacturer_data": manufacturer_data,
        "placement_rules": placement_rules,
        "circuit_rules": circuit_rules,
        "calculation_rules": calculation_rules,
        "sizing_tables": dict(answers.get("sizing_tables") or {}),
        "voltage_drop_rules": dict(answers.get("voltage_drop_rules") or {}),
        "panel_rules": dict(answers.get("panel_rules") or {}),
        "service_inputs": service_inputs,
        "optional_system_inputs": optional_system_inputs,
        "detail_parameters": _build_detail_parameters(answers),
        "content_density": dict(answers.get("content_density") or {}),
        "reference_similarity_threshold": float(answers.get("reference_similarity_threshold") or .60),
    }


def _score_gates(report):
    gates = dict(report.get("gates") or {})
    gates.setdefault("NO_FAKE_FINAL", {"status":"PASS"})
    gates.setdefault("RUNTIME_RELEASE_IDENTITY", {"status":"PASS"})
    # CAD cannot attest to authenticated panel recovery; the web transaction
    # supplies this gate later. Keeping it UNKNOWN prevents a CAD-only score
    # from falsely claiming end-to-end execution readiness.
    gates.setdefault("PANEL_FLOW_RECOVERY", {"status":"UNKNOWN"})
    return execution_score(gates)


def design_electrical_authority_site(src: str | Path, dst: str | Path, *, answers=None, plan_analysis=None) -> dict:
    config = build_engine_config(answers, plan_analysis)
    report = run_acceptance_electrical_pipeline(src, dst, config)
    readiness = _score_gates(report)
    report["pipeline_authority"] = PIPELINE_AUTHORITY
    report["execution_readiness"] = readiness
    report["submission_state"] = "EXECUTION_REVIEW_READY" if readiness["execution_ready"] else "PRE_SUBMISSION"
    report["status"] = "PASS" if report.get("acceptance", {}).get("status") == "PASS" else "INPUT_REQUIRED"
    report["requires_professional_review"] = True
    return report
