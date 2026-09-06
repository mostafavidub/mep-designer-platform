"""Electrical project preflight, scope resolver and fail-closed questionnaire.

Mirrors the mature Mechanical workflow contracts while keeping electrical
engineering decisions discipline-specific.  Architecture may establish rooms,
levels and equipment candidates, but service/protection/system decisions remain
INPUT_REQUIRED until supported by evidence or explicit user approval.
"""
from __future__ import annotations

from pathlib import Path
import re

from .electrical_basis_contract import (
    canonical_city, canonical_earthing, canonical_panel_strategy,
    canonical_supply, normalize_answers, numeric, panel_location_approval,
)

SYSTEM_LABELS = {
    "lighting": "روشنایی", "power": "پریز و قدرت", "dedicated_power": "بارهای اختصاصی",
    "hvac_power": "برق تجهیزات مکانیکی", "elevator_power": "آسانسور",
    "emergency": "برق اضطراری", "fire_alarm": "اعلام حریق", "low_current": "جریان ضعیف",
    "grounding": "ارت و هم‌بندی", "lightning": "حفاظت صاعقه",
}

REQUIRED_BASIS_QUESTION_SPECS = {
    "city": {
        "question": "شهر پروژه را مشخص کنید؛ انتخاب ضوابط محلی و شرایط طراحی برق بدون شهر قطعی نمی‌شود.",
        "input_type": "text", "options": [], "unit": None,
    },
    "supply_configuration": {
        "question": "مشخصات انشعاب برق را تأیید کنید: تک‌فاز/سه‌فاز یا ترکیب واحدها و مشاعات، و در صورت مشخص بودن ولتاژ نامی.",
        "input_type": "radio",
        "options": ["همه واحدها تک‌فاز", "واحدها تک‌فاز و مشاعات سه‌فاز", "همه انشعاب‌ها سه‌فاز", "ترکیبی بر اساس نوع مصرف"],
        "unit": None,
    },
    "earthing_system": {
        "question": "سیستم ارت/هم‌بندی مورد تأیید پروژه چیست؟ اگر هنوز تعیین نشده، گزینه «طبق گزارش خاک/نظر مشاور تعیین شود» را انتخاب کنید تا Final نشود.",
        "input_type": "radio",
        "options": ["ارت فونداسیون", "چاه ارت / الکترود زمین", "TN-S", "TN-C-S", "TT", "طبق گزارش خاک و نظر مشاور تعیین شود"],
        "unit": None,
    },
    "service_panel_location": {
        "question": "محل سرویس، کنتورها و تابلو اصلی را تأیید کنید. اگر در معماری قطعی نیست، اجازه پیشنهاد مهندسی بدهید.",
        "input_type": "radio",
        "options": ["محل در پلان مشخص شده است", "همکف نزدیک ورودی اصلی", "پارکینگ یا زیرزمین", "اتاق برق مستقل", "اجازه پیشنهاد محل مناسب را دارید"],
        "unit": None,
    },
    "dedicated_load_schedule": {
        "question": "بارهای اختصاصی و تجهیزات برقی پروژه را با توان/فاز یا مشخصات سازنده اعلام کنید؛ اگر موردی ندارید صریحاً «ندارد» ثبت کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "fire_alarm_requirement": {
        "question": "Scope اعلام حریق پروژه را تأیید کنید: خارج از محدوده، متعارف، آدرس‌پذیر، یا طبق الزام مرجع آتش‌نشانی تعیین شود.",
        "input_type": "radio",
        "options": ["خارج از محدوده این پروژه", "سیستم متعارف", "سیستم آدرس‌پذیر", "طبق الزام مرجع آتش‌نشانی تعیین شود"],
        "unit": None,
    },
    "low_current_systems": {
        "question": "سیستم‌های جریان ضعیف موردنیاز پروژه را مشخص کنید؛ فقط سیستم‌های تأییدشده وارد نقشه می‌شوند.",
        "input_type": "radio",
        "options": ["آنتن، تلفن و شبکه", "آنتن، تلفن، شبکه و آیفون", "جریان ضعیف + دوربین مداربسته", "فقط زیرساخت/لوله‌گذاری", "خارج از محدوده"],
        "unit": None,
    },
    "lighting_design_basis": {
        "question": "مبنای روشنایی را تأیید کنید: الزامات Rule Book/استاندارد پروژه، Lighting Schedule مشاور، یا مقادیر سازنده. بدون مبنای معتبر تعداد چراغ Final نمی‌شود.",
        "input_type": "radio",
        "options": ["Rule Book و استاندارد مصوب پروژه", "Lighting Schedule مشاور", "طبق مشخصات سازنده چراغ‌ها", "فعلاً Preliminary بماند"],
        "unit": None,
    },
    "local_electrical_code": {
        "question": "مرجع/ضابطه برق قابل استناد پروژه را مشخص کنید (مثلاً ضابطه محلی، مشاور یا مجموعه استاندارد قراردادی).",
        "input_type": "text", "options": [], "unit": None,
    },
    "ceiling_and_mounting": {
        "question": "وضعیت سقف کاذب و محدودیت‌های نصب چراغ/دتکتور/تجهیزات سقفی را تأیید کنید؛ اگر در معماری مشخص است همان را اعلام کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
}


def _discipline(p):
    return (p.answers or {}).get("discipline", (p.analysis or {}).get("discipline", "electrical"))


def _negative(value):
    text = str(value or "").strip().lower()
    return any(x in text for x in ("ندارد", "خیر", "نیست", "بدون", "none", "not required", "out of scope"))


def _level_profiles(p):
    return list(((p.analysis or {}).get("architectural_auto") or {}).get("level_profiles") or [])


def _level_names(p):
    profiles = _level_profiles(p)
    if profiles:
        return [str(x.get("name")) for x in profiles if x.get("name")]
    auto = (p.analysis or {}).get("architectural_auto") or {}
    levels = [str(x.get("name") if isinstance(x, dict) else x) for x in auto.get("levels") or []]
    levels = [x for x in levels if x]
    if levels:
        return list(dict.fromkeys(levels))
    for f in (p.analysis or {}).get("files") or []:
        for text in f.get("texts") or []:
            value = str(text)
            if "پلان معماری" in value or "architectural plan" in value.lower():
                levels.append(value)
    return list(dict.fromkeys(levels)) or ["پلان معماری"]


def build_scope(p):
    answers = normalize_answers(p.answers or {})
    profiles = _level_profiles(p)
    levels = _level_names(p)
    auto = (p.analysis or {}).get("architectural_auto") or {}
    room_counts = dict(auto.get("room_counts") or {})
    if profiles:
        non_roof = [str(x.get("name")) for x in profiles if x.get("name") and not x.get("roof")]
        wet_levels = [str(x.get("name")) for x in profiles if x.get("name") and not x.get("roof") and any(int((x.get("room_counts") or {}).get(k) or 0) for k in ("kitchen", "bath", "toilet"))]
        occupied_levels = [str(x.get("name")) for x in profiles if x.get("name") and not x.get("roof") and int(x.get("recognized_room_labels") or 0) > 0]
        roof = [str(x.get("name")) for x in profiles if x.get("name") and x.get("roof")]
    else:
        non_roof = [x for x in levels if "بام" not in x and "roof" not in x.lower()]
        wet_levels = list(non_roof) if any(room_counts.get(k) for k in ("kitchen", "bath", "toilet")) else []
        occupied_levels = list(non_roof)
        roof = [x for x in levels if "بام" in x or "roof" in x.lower()]
    elevator = bool(auto.get("detected_elevator") or room_counts.get("elevator"))
    parking = bool(auto.get("detected_parking") or room_counts.get("parking"))
    kitchen = bool(room_counts.get("kitchen"))
    vertical = len(occupied_levels) > 1
    fire_answer = answers.get("fire_alarm_requirement") or answers.get("fire_alarm")
    low_current_answer = answers.get("low_current_systems") or answers.get("elv")
    emergency_answer = answers.get("emergency")
    return {
        "all_levels": levels,
        "electrical_plan_levels": occupied_levels or non_roof,
        "wet_area_levels": wet_levels,
        "roof_levels": roof,
        "vertical_systems": vertical,
        "elevator_present": elevator,
        "parking_present": parking,
        "kitchen_present": kitchen,
        "lighting_required": bool(occupied_levels or non_roof),
        "power_required": bool(occupied_levels or non_roof),
        "dedicated_power_candidate": bool(kitchen or elevator or parking),
        "elevator_power_required": elevator,
        "fire_alarm_scope_known": bool(str(fire_answer or "").strip()),
        "fire_alarm_required": False if _negative(fire_answer) else (True if fire_answer else None),
        "low_current_scope_known": bool(str(low_current_answer or "").strip()),
        "low_current_required": False if _negative(low_current_answer) else (True if low_current_answer else None),
        "emergency_scope_known": bool(str(emergency_answer or "").strip()),
        "emergency_required": False if _negative(emergency_answer) else (True if emergency_answer else None),
        "effective_level_source": "architecture-level-profiles" if profiles else "fallback-detected-levels",
    }


def required_basis_questions(p):
    if _discipline(p) != "electrical":
        return []
    answers = normalize_answers(p.answers or {})
    scope = build_scope(p)
    missing = []
    if not canonical_city(answers):
        missing.append("city")
    if not canonical_supply(answers.get("supply_configuration") or answers.get("supply")):
        missing.append("supply_configuration")
    if not panel_location_approval(answers):
        missing.append("service_panel_location")
    if not canonical_earthing(answers.get("earthing_system") or answers.get("earthing")):
        missing.append("earthing_system")
    if scope.get("dedicated_power_candidate") and not str(answers.get("dedicated_load_schedule") or answers.get("special_loads") or answers.get("loads") or "").strip():
        missing.append("dedicated_load_schedule")
    if not scope.get("fire_alarm_scope_known"):
        missing.append("fire_alarm_requirement")
    if not scope.get("low_current_scope_known"):
        missing.append("low_current_systems")
    if scope.get("lighting_required") and not str(answers.get("lighting_design_basis") or "").strip():
        missing.append("lighting_design_basis")
    if not str(answers.get("local_electrical_code") or answers.get("codes") or "").strip():
        missing.append("local_electrical_code")
    if not str(answers.get("ceiling_and_mounting") or answers.get("heights") or "").strip():
        missing.append("ceiling_and_mounting")
    return list(dict.fromkeys(missing))


def question_payload(key):
    spec = REQUIRED_BASIS_QUESTION_SPECS[key]
    payload = {
        "key": key, "question": spec["question"], "input_type": spec["input_type"],
        "options": list(spec.get("options") or []), "unit": spec.get("unit"),
        "required": True, "source": "electrical_basis_preflight_v19",
    }
    if spec["input_type"] == "number":
        payload.update({"min": 0.1, "step": 0.1})
    return payload


def ensure_required_basis_questions(p):
    missing = required_basis_questions(p)
    if not missing:
        return False
    existing = [dict(x) for x in (p.questions or []) if isinstance(x, dict)]
    by_key = {q.get("key"): i for i, q in enumerate(existing) if q.get("key")}
    for key in missing:
        replacement = question_payload(key)
        if key in by_key:
            existing[by_key[key]] = replacement
        else:
            by_key[key] = len(existing)
            existing.append(replacement)
    p.questions = existing
    p.current_question = min(by_key[key] for key in missing if key in by_key)
    p.status = "asking"
    analysis = dict(p.analysis or {})
    analysis["electrical_basis_preflight"] = {"status": "INPUT_REQUIRED", "missing": missing, "contract": "electrical-design-basis-v19.0"}
    p.analysis = analysis
    return True


def reopen_basis_questions(p, missing):
    allowed = [key for key in missing if key in REQUIRED_BASIS_QUESTION_SPECS]
    answers = dict(p.answers or {})
    aliases = {
        "city": ("city", "location"), "supply_configuration": ("supply_configuration", "supply"),
        "service_panel_location": ("service_panel_location", "service_panel_location_approval", "main_panel"),
        "earthing_system": ("earthing_system", "earthing"),
        "dedicated_load_schedule": ("dedicated_load_schedule", "special_loads", "loads"),
        "fire_alarm_requirement": ("fire_alarm_requirement", "fire_alarm"),
        "low_current_systems": ("low_current_systems", "elv"),
        "lighting_design_basis": ("lighting_design_basis",),
        "local_electrical_code": ("local_electrical_code", "codes"),
        "ceiling_and_mounting": ("ceiling_and_mounting", "heights"),
    }
    for key in allowed:
        for alias in aliases.get(key, (key,)):
            answers.pop(alias, None)
    p.answers = normalize_answers(answers)
    qs = [q for q in (p.questions or []) if isinstance(q, dict) and q.get("key") not in allowed]
    qs.extend(question_payload(key) for key in allowed)
    p.questions = qs
    p.current_question = max(0, len(qs) - len(allowed))
    p.status = "asking"
    p.last_error = "اطلاعات مبنای طراحی برق برای ادامه کافی نیست؛ موارد مشخص‌شده را تکمیل کنید."
    analysis = dict(p.analysis or {})
    analysis["electrical_basis_preflight"] = {"status": "INPUT_REQUIRED", "missing": allowed, "reopened_from_authority_failure": True}
    p.analysis = analysis
    return bool(allowed)


def infer_project_name(p):
    return str(getattr(p, "name", "") or "Electrical Project")
