"""Electrical standards registry v19.

This registry identifies the standards families the engine can use as
``applicable_rule`` evidence.  It deliberately contains no project-specific
loads, quantities, breaker sizes, cable sizes, mounting heights or utility
service assumptions.  Local/jurisdictional editions remain explicit project
inputs unless a verified rule package is installed.
"""
from __future__ import annotations

REGISTRY_VERSION = "electrical-standards-registry-v19.0"

STANDARDS = {
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
        "source": "IEC official catalogue / 2026 series pack",
        "status": "VERIFIED_REFERENCE",
        "may_supply_project_facts": False,
    },
    "LOCAL_IRAN_MABHATH_13": {
        "title": "مبحث سیزدهم مقررات ملی ساختمان - طرح و اجرای تأسیسات برقی ساختمان‌ها",
        "scope": "local building electrical requirements",
        "source": "project/jurisdiction rule package",
        "status": "EDITION_MUST_BE_CONFIRMED_FOR_PROJECT",
        "may_supply_project_facts": False,
    },
    "LOCAL_UTILITY_REQUIREMENTS": {
        "title": "ضوابط شرکت توزیع/برق منطقه‌ای محل پروژه",
        "scope": "service, metering and utility connection requirements",
        "source": "project-specific utility",
        "status": "INPUT_REQUIRED",
        "may_supply_project_facts": False,
    },
    "LOCAL_FIRE_AUTHORITY": {
        "title": "ضوابط مرجع آتش‌نشانی محل پروژه",
        "scope": "fire-alarm and emergency electrical requirements when applicable",
        "source": "project-specific authority",
        "status": "INPUT_REQUIRED",
        "may_supply_project_facts": False,
    },
}


def verified_rule_ids():
    return [key for key, value in STANDARDS.items() if value["status"] == "VERIFIED_REFERENCE"]


def project_rule_requirements():
    return [key for key, value in STANDARDS.items() if value["status"] in {"INPUT_REQUIRED", "EDITION_MUST_BE_CONFIRMED_FOR_PROJECT"}]


def validate_registry():
    forbidden = ("breaker_size", "cable_size", "mounting_height", "service_capacity", "fixture_count")
    errors = []
    for key, value in STANDARDS.items():
        if value.get("may_supply_project_facts"):
            errors.append(f"standard_may_not_supply_project_fact:{key}")
        if any(name in value for name in forbidden):
            errors.append(f"hardcoded_project_value_in_registry:{key}")
    return {"version": REGISTRY_VERSION, "status": "PASS" if not errors else "FAIL", "errors": errors, "standards": STANDARDS}
