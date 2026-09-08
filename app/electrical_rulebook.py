"""Machine-readable Electrical Rule Book.

The Rule Book owns engineering rules and reference constraints, not project
facts. Project facts must come from traceable drawing evidence, explicit user
answers, verified authority inputs, or calculated results with provenance.
Unresolved project facts remain unresolved and must not be silently defaulted.
"""
from __future__ import annotations

RULEBOOK_REVISION = "electrical-rulebook/1"
REQUIRED_PROVENANCE = (
    "Detected", "Calculated", "Rule-based Proposed", "User-confirmed",
    "Authority-confirmed", "Manufacturer-confirmed",
)

REFERENCE_RULES = {
    "IEC_60364_1_2025": {
        "title": "IEC 60364-1:2025 Low-voltage electrical installations - Part 1",
        "scope": "fundamental principles, general characteristics and definitions",
        "source": "IEC official catalogue",
        "status": "VERIFIED_REFERENCE",
        "may_supply_project_facts": False,
    },
    "IEC_60364_5_53_2024_CSV": {
        "title": "IEC 60364-5-53:2019+AMD1:2020+AMD2:2024 CSV",
        "scope": "selection/erection of protection, isolation, switching, control and monitoring devices",
        "source": "IEC official catalogue",
        "status": "VERIFIED_REFERENCE",
        "may_supply_project_facts": False,
    },
    "IEC_61439_1_2020": {
        "title": "IEC 61439-1:2020 Low-voltage switchgear and controlgear assemblies - General rules",
        "scope": "LV assembly definitions, service conditions, construction, characteristics and verification",
        "source": "IEC official catalogue",
        "status": "VERIFIED_REFERENCE",
        "may_supply_project_facts": False,
    },
    "IEC_62305_SERIES_2024": {
        "title": "IEC 62305 Parts 1-4:2024, Protection against lightning",
        "scope": "lightning protection when project applicability is established",
        "source": "IEC official catalogue",
        "status": "VERIFIED_REFERENCE",
        "may_supply_project_facts": False,
    },
    "LOCAL_IRAN_MABHATH_13": {
        "title": "مبحث سیزدهم مقررات ملی ساختمان - طرح و اجرای تأسیسات برقی ساختمان‌ها",
        "scope": "local building electrical requirements",
        "source": "project/jurisdiction rule package",
        "status": "PROJECT_EDITION_REQUIRED",
        "may_supply_project_facts": False,
    },
    "LOCAL_UTILITY_REQUIREMENTS": {
        "title": "ضوابط شرکت توزیع/برق منطقه‌ای محل پروژه",
        "scope": "service, metering and utility connection requirements",
        "source": "project-specific utility",
        "status": "PROJECT_INPUT_REQUIRED",
        "may_supply_project_facts": False,
    },
    "LOCAL_FIRE_AUTHORITY": {
        "title": "ضوابط مرجع آتش‌نشانی محل پروژه",
        "scope": "fire-alarm and emergency electrical requirements when applicable",
        "source": "project-specific authority",
        "status": "PROJECT_INPUT_REQUIRED",
        "may_supply_project_facts": False,
    },
}

PROJECT_EVIDENCE_STANDARD = (
    "location", "occupancy", "utility_service", "supply_configuration",
    "supply_voltage_v", "service_capacity", "earthing_system",
    "panel_location", "lighting_basis", "socket_power_requirements",
    "dedicated_appliance_requirements", "hvac_electrical_loads",
    "elevator_load", "pump_load", "emergency_power", "fire_alarm_scope",
    "low_current_scope", "lightning_protection_scope", "local_electrical_code",
    "local_utility_requirements", "local_fire_authority_requirements",
)


def verified_rule_ids():
    return [key for key, value in REFERENCE_RULES.items() if value["status"] == "VERIFIED_REFERENCE"]


def project_rule_requirements():
    return [key for key, value in REFERENCE_RULES.items() if value["status"] in {"PROJECT_INPUT_REQUIRED", "PROJECT_EDITION_REQUIRED"}]


def validate_rulebook():
    forbidden = ("breaker_size", "cable_size", "mounting_height", "service_capacity", "fixture_count")
    errors = []
    for key, value in REFERENCE_RULES.items():
        if value.get("may_supply_project_facts"):
            errors.append(f"rule_may_not_supply_project_fact:{key}")
        if any(name in value for name in forbidden):
            errors.append(f"hardcoded_project_value_in_rulebook:{key}")
    return {
        "rulebook_revision": RULEBOOK_REVISION,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "rules": REFERENCE_RULES,
        "required_provenance": REQUIRED_PROVENANCE,
    }
