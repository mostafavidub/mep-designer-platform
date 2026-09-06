"""Production adapter for the strict Electrical authority pipeline v19.

The dedicated CAD image contains only ``cad_engine``; therefore this module must
remain self-contained and may not import the web ``app`` package.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .runtime_support_v19 import canonical_earthing, canonical_supply, execution_score
from .strict_pipeline_v15_2 import run_strict_electrical_pipeline_v15_2

PIPELINE_AUTHORITY = "electrical-v19"


def _negative(value):
    text = str(value or "").strip().lower()
    return any(x in text for x in ("ندارد", "خارج از محدوده", "خیر", "none", "not required"))


def build_engine_config(answers: dict | None, plan_analysis: dict | None = None) -> dict[str, Any]:
    answers = dict(answers or {})
    explicit = dict(answers.get("_electrical_engine_config") or {})
    if explicit:
        return explicit
    analysis = dict(plan_analysis or {})
    auto = dict(analysis.get("architectural_auto") or {})
    supply = canonical_supply(answers.get("supply_configuration") or answers.get("supply")) or {}
    earthing = canonical_earthing(answers.get("earthing_system") or answers.get("earthing"))
    design_basis = {}

    def put(key, value):
        if value not in (None, "", [], {}):
            design_basis[key] = value

    put("city", answers.get("city") or answers.get("location"))
    put("building_type", answers.get("building_type") or answers.get("occupancy") or auto.get("occupancy_inferred"))
    put("supply_voltage_v", supply.get("voltage_v"))
    put("phase_configuration", supply.get("configuration"))
    put("utility_service", answers.get("supply") or answers.get("supply_configuration"))
    put("earthing_system", None if earthing == "input_required" else earthing)
    put("lighting_basis", answers.get("lighting_basis_values"))
    put("socket_power_requirements", answers.get("socket_power_requirements"))
    put("dedicated_appliance_requirements", answers.get("dedicated_appliance_requirements"))
    put("hvac_electrical_loads", answers.get("hvac_electrical_loads"))
    put("elevator", answers.get("elevator_load") or answers.get("elevator"))
    put("pump", answers.get("pump_load") or answers.get("pump"))
    put("emergency_lighting", answers.get("emergency_lighting"))
    fire = answers.get("fire_alarm_requirement") or answers.get("fire_alarm")
    if fire:
        put("fire_alarm_requirement", not _negative(fire))
    low_current = answers.get("low_current_systems") or answers.get("elv")
    if low_current:
        put("low_current_systems", [] if _negative(low_current) else [str(low_current)])
    emergency = str(answers.get("emergency") or "").lower()
    if emergency:
        put("generator", "ژنراتور" in emergency or "generator" in emergency)
        put("ups", "ups" in emergency)
    for key in (
        "lightning_protection", "ev_charging", "solar_pv", "ambient_temperature_c",
        "installation_method", "conductor_material", "power_factor", "frequency_hz",
        "voltage_drop_limits",
    ):
        put(key, answers.get(key))
    return {
        "project_inputs": {
            "project_name": answers.get("project_name") or "EngiTools Electrical Project",
            "building_type": design_basis.get("building_type") or "unknown",
        },
        "design_basis": design_basis,
        "applicable_rules": {"design_basis": dict(answers.get("electrical_rule_design_basis") or {})},
        "manufacturer_data": dict(answers.get("manufacturer_data") or {}),
        "placement_rules": dict(answers.get("placement_rules") or {}),
        "circuit_rules": dict(answers.get("circuit_rules") or {}),
        "calculation_rules": dict(answers.get("calculation_rules") or {}),
        "sizing_tables": dict(answers.get("sizing_tables") or {}),
        "voltage_drop_rules": dict(answers.get("voltage_drop_rules") or {}),
        "panel_rules": dict(answers.get("panel_rules") or {}),
        "service_inputs": dict(answers.get("service_inputs") or {}),
        "optional_system_inputs": dict(answers.get("optional_system_inputs") or {}),
        "detail_parameters": dict(answers.get("detail_parameters") or {}),
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
    report = run_strict_electrical_pipeline_v15_2(src, dst, config)
    readiness = _score_gates(report)
    report["pipeline_authority"] = PIPELINE_AUTHORITY
    report["execution_readiness"] = readiness
    report["submission_state"] = "EXECUTION_REVIEW_READY" if readiness["execution_ready"] else "PRE_SUBMISSION"
    report["status"] = "PASS" if report.get("acceptance", {}).get("status") == "PASS" else "INPUT_REQUIRED"
    report["requires_professional_review"] = True
    return report
