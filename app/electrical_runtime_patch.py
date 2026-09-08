"""Install active Electrical evidence rules on the public/panel analyzer.

This keeps Mechanical behavior untouched while replacing unsafe Electrical
auto-answers with preliminary analysis evidence and injecting only unresolved
fail-closed basis questions.
"""
from __future__ import annotations

from types import SimpleNamespace

from .electrical_basis_contract import normalize_answers
from .electrical_workflow import question_payload, required_basis_questions

UNSAFE_AUTO_PROJECT_FACTS = {
    "design_load_kw",
    "cable_length_m",
    "power_factor",
    "max_voltage_drop_pct",
}

ALIASES = {
    "city": ("city", "location"),
    "supply_configuration": ("supply_configuration", "supply"),
    "service_panel_location": ("service_panel_location", "main_panel"),
    "earthing_system": ("earthing_system", "earthing"),
    "dedicated_load_schedule": ("dedicated_load_schedule", "special_loads", "loads"),
    "fire_alarm_requirement": ("fire_alarm_requirement", "fire_alarm"),
    "low_current_systems": ("low_current_systems", "elv"),
    "lighting_design_basis": ("lighting_design_basis", "lighting"),
    "local_electrical_code": ("local_electrical_code", "codes"),
    "ceiling_and_mounting": ("ceiling_and_mounting", "heights"),
}


def _has_answer(answers, key):
    return any(str((answers or {}).get(alias) or "").strip() for alias in ALIASES.get(key, (key,)))


def install(main_auto):
    if getattr(main_auto, "_electrical_runtime_installed", False):
        return
    original = main_auto.build_unified_questionnaire

    def build_unified_questionnaire(analysis, discipline, supplied_answers=None):
        auto, answers, unresolved = original(analysis, discipline, supplied_answers)
        if discipline != "electrical":
            return auto, answers, unresolved

        preliminary = {}
        for key, source_key in (
            ("estimated_connected_load_kw", "estimated_electrical_load_kw"),
            ("representative_route_m", "estimated_cable_route_m"),
        ):
            if auto.get(source_key) is not None:
                preliminary[key] = {
                    "value": auto[source_key], "status": "PRELIMINARY",
                    "source": "architectural_evidence_proxy",
                    "final_for_sizing": False,
                }
        analysis["electrical_preliminary_evidence"] = preliminary
        for key in UNSAFE_AUTO_PROJECT_FACTS:
            answers.pop(key, None)

        for key, value in dict(supplied_answers or {}).items():
            if value is not None and str(value).strip():
                answers[str(key)] = value
        answers = normalize_answers(answers)

        p = SimpleNamespace(answers=answers, analysis=analysis)
        missing = required_basis_questions(p)
        final_questions = []
        seen = set()
        superseded = {alias for key in missing for alias in ALIASES.get(key, (key,))}
        for key, prompt in unresolved:
            if key in superseded or _has_answer(answers, key):
                continue
            final_questions.append((key, prompt)); seen.add(key)
        for key in missing:
            if _has_answer(answers, key):
                continue
            payload = question_payload(key)
            if key not in seen:
                final_questions.append((key, payload["question"])); seen.add(key)
        analysis["electrical_basis_preflight"] = {
            "status": "INPUT_REQUIRED" if missing else "PASS",
            "missing": missing,
            "contract_revision": "electrical-design-basis/1",
        }
        return auto, answers, final_questions

    main_auto.build_unified_questionnaire = build_unified_questionnaire
    main_auto._electrical_runtime_installed = True
