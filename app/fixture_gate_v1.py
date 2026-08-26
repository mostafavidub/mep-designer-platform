"""Pre-design fixture evidence gate.

This module turns unresolved wet-level fixture evidence into an explicit
questionnaire requirement and prevents mechanical design approval from being
considered ready until the evidence is resolved by either high-confidence CAD
detections or a quantified user-confirmed fixture schedule.

It is intentionally narrow: it does not change sheet composition, routing,
sizing, or any electrical workflow.
"""
import re


_DIAGNOSTIC_PREFIX = "wet_level_without_detected_fixture:"


def unresolved_wet_levels(auto):
    levels = []
    for item in (auto or {}).get("evidence_diagnostics") or []:
        text = str(item or "")
        if not text.startswith(_DIAGNOSTIC_PREFIX):
            continue
        level = text[len(_DIAGNOSTIC_PREFIX):].strip()
        if level and level not in levels:
            levels.append(level)
    return levels


def fixture_schedule_quantified(value):
    text = str(value or "").strip().translate(
        str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    )
    low = text.lower()
    aliases = (
        "sink", "basin", "lav", "toilet", "wc", "bath", "shower", "urinal",
        "dishwasher", "washing machine", "floor drain",
        "سینک", "روشویی", "روشويی", "توالت", "دوش", "وان", "کفشور",
        "کف شور", "یورینال", "ظرفشویی", "لباسشویی",
    )
    return bool(re.search(r"\d+", text)) and any(alias in low for alias in aliases)


def fixture_evidence_resolved(auto, answers=None):
    missing = unresolved_wet_levels(auto)
    if not missing:
        return True
    return fixture_schedule_quantified((answers or {}).get("fixture_schedule"))


def _fixture_question(auto):
    levels = unresolved_wet_levels(auto)
    if not levels:
        return None
    label = "، ".join(levels)
    return (
        "fixture_schedule",
        "برای جلوگیری از طراحی ناقص، تجهیزات بهداشتی/مکانیکی این ترازها با اطمینان کافی از DXF تشخیص داده نشد: "
        f"{label}. تعداد واقعی تجهیزات را به‌صورت عددی وارد کنید؛ مثال: «سینک ۲، روشویی ۳، توالت ۳، دوش ۲»."
    )


def install(main_auto_module, workflow_module):
    """Install questionnaire + approval gates without touching design engines."""
    if getattr(main_auto_module, "_fixture_gate_v1_installed", False):
        return

    base_dynamic_questions = main_auto_module.dynamic_questions

    def dynamic_questions_with_fixture_gate(analysis, discipline, auto):
        questions = list(base_dynamic_questions(analysis, discipline, auto))
        if discipline != "mechanical":
            return questions
        required = _fixture_question(auto)
        if required and not any(key == "fixture_schedule" for key, _ in questions):
            questions.append(required)
        return questions

    main_auto_module.dynamic_questions = dynamic_questions_with_fixture_gate

    base_is_approved = workflow_module.is_approved

    def is_approved_with_fixture_gate(project):
        if not base_is_approved(project):
            return False
        if (project.answers or {}).get("discipline", (project.analysis or {}).get("discipline", "mechanical")) != "mechanical":
            return True
        auto = (project.analysis or {}).get("architectural_auto") or {}
        return fixture_evidence_resolved(auto, project.answers or {})

    workflow_module.is_approved = is_approved_with_fixture_gate
    main_auto_module._fixture_gate_v1_installed = True
