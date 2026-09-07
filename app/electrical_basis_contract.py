"""Canonical, fail-closed electrical design-basis answer contract.

Project facts are never manufactured from Rule Book defaults. The contract only
normalizes explicit answers or evidence already persisted by the architecture
analyzer and records provenance for approvals that permit the engine to propose
an engineering location/strategy.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

CONTRACT_REVISION = "electrical-design-basis/1"
SUPPLY_CONFIGURATIONS = {"single_phase", "three_phase", "mixed_single_units_three_phase_common"}
EARTHING_VALUES = {"tn-s", "tn-c-s", "tt", "foundation_earth", "earth_electrode", "input_required"}
PANEL_STRATEGIES = {
    "use_evidenced_location", "propose_near_main_entry", "propose_parking_or_basement",
    "use_electrical_room", "proposal_authorized",
}


def _text(value):
    return re.sub(r"\s+", " ", str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")).strip()


def numeric(value):
    if value in (None, "", []):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    value = _text(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    match = re.search(r"[-+]?\d+(?:[.,٫]\d+)?", value)
    return float(match.group(0).replace("٫", ".").replace(",", ".")) if match else None


def canonical_city(answers):
    value = (answers or {}).get("city") or (answers or {}).get("location")
    if not _text(value):
        return None
    parts = [part.strip() for part in re.split(r"[,،]", _text(value)) if part.strip()]
    return parts[-1] if parts else None


def _supply_voltage(text):
    """Extract voltage from supply notation without mistaking 1/3-phase for volts."""
    explicit = re.search(r"(?<![\w.])(\d+(?:[.,٫]\d+)?)\s*v(?:olt(?:s)?)?\b", text, re.I)
    if explicit:
        return numeric(explicit.group(1))
    without_phase = re.sub(r"\b[13]\s*[- ]?ph(?:ase)?\b", " ", text, flags=re.I)
    return numeric(without_phase)


def canonical_supply(value):
    if isinstance(value, dict):
        configuration = str(value.get("configuration") or "").strip()
        if configuration in SUPPLY_CONFIGURATIONS:
            return {"configuration": configuration, "voltage_v": numeric(value.get("voltage_v"))}
        return None
    text = _text(value).lower()
    if not text:
        return None
    if text in SUPPLY_CONFIGURATIONS:
        return {"configuration": text, "voltage_v": None}
    three = any(x in text for x in ("سه فاز", "سه‌فاز", "three phase", "3ph", "3 ph", "3-phase", "3 phase"))
    single = any(x in text for x in ("تک فاز", "تک‌فاز", "single phase", "1ph", "1 ph", "1-phase", "1 phase"))
    mixed = any(x in text for x in ("مشاعات سه", "ترکیبی", "mixed"))
    voltage = _supply_voltage(text)
    if mixed:
        return {"configuration": "mixed_single_units_three_phase_common", "voltage_v": voltage}
    if three:
        return {"configuration": "three_phase", "voltage_v": voltage}
    if single:
        return {"configuration": "single_phase", "voltage_v": voltage}
    return None


def canonical_earthing(value):
    text = _text(value).lower()
    if not text:
        return None
    if text in EARTHING_VALUES:
        return text
    aliases = {
        "tn-s": ("tn-s", "tns"), "tn-c-s": ("tn-c-s", "tncs"),
        "tt": (" tt", "tt ", "سیستم tt"), "foundation_earth": ("ارت فونداسیون", "foundation earth"),
        "earth_electrode": ("چاه ارت", "الکترود زمین", "earth electrode"),
    }
    for key, tokens in aliases.items():
        if any(token in f" {text} " for token in tokens):
            return key
    if any(x in text for x in ("طبق گزارش خاک", "نظر مشاور", "نامشخص", "تعیین شود")):
        return "input_required"
    return None


def canonical_panel_strategy(value):
    text = _text(value).lower()
    if not text:
        return None
    if text in PANEL_STRATEGIES:
        return text
    if any(x in text for x in ("محل در پلان", "existing", "architectural", "مشخص شده")):
        return "use_evidenced_location"
    if any(x in text for x in ("نزدیک ورودی", "همکف نزدیک ورودی")):
        return "propose_near_main_entry"
    if any(x in text for x in ("پارکینگ", "زیرزمین", "parking", "basement")):
        return "propose_parking_or_basement"
    if any(x in text for x in ("اتاق برق", "electrical room")):
        return "use_electrical_room"
    if any(x in text for x in ("اجازه پیشنهاد", "proposal allowed", "پیشنهاد دهید")):
        return "proposal_authorized"
    return None


def canonical_yes_no(value):
    text = _text(value).lower()
    if not text:
        return None
    if any(x in text for x in ("ندارد", "خیر", "نیست", "none", "no ", "not required")):
        return False
    if any(x in text for x in ("دارد", "بله", "نیاز", "required", "yes", "ژنراتور", "ups")):
        return True
    return None


def _approval(strategy, raw, source="explicit_user_answer"):
    return {
        "status": "APPROVED", "strategy": strategy, "source": source,
        "raw_answer": _text(raw), "recorded_at": datetime.now(timezone.utc).isoformat(),
        "contract_revision": CONTRACT_REVISION,
    }


def normalize_answers(answers, *, answer_key=None, raw_answer=None):
    out = dict(answers or {})
    if answer_key:
        out[answer_key] = raw_answer
    city = canonical_city(out)
    if city:
        out["city"] = city
    supply = canonical_supply(out.get("supply_configuration") or out.get("supply"))
    if supply:
        out["supply_configuration"] = supply
    earth = canonical_earthing(out.get("earthing_system") or out.get("earthing"))
    if earth:
        out["earthing_system"] = earth
    strategy = canonical_panel_strategy(out.get("service_panel_location") or out.get("main_panel"))
    if strategy:
        out["service_panel_location"] = strategy
        existing = dict(out.get("service_panel_location_approval") or {})
        if answer_key in {"service_panel_location", "main_panel"} or existing.get("status") != "APPROVED":
            raw = raw_answer if answer_key else (out.get("main_panel") or strategy)
            out["service_panel_location_approval"] = _approval(strategy, raw)
    out["_electrical_basis_contract"] = {"contract_revision": CONTRACT_REVISION, "status": "NORMALIZED"}
    return out


def panel_location_approval(answers):
    approval = dict((answers or {}).get("service_panel_location_approval") or {})
    strategy = canonical_panel_strategy(approval.get("strategy") or (answers or {}).get("service_panel_location") or (answers or {}).get("main_panel"))
    if approval.get("status") == "APPROVED" and strategy:
        return {**approval, "strategy": strategy}
    if strategy:
        return _approval(strategy, (answers or {}).get("main_panel") or strategy, "legacy_explicit_user_answer")
    return None


def persisted_answer_is_valid(answers, key):
    answers = answers or {}
    if key in {"city", "location"}:
        return bool(canonical_city(answers))
    if key in {"supply_configuration", "supply"}:
        return bool(canonical_supply(answers.get("supply_configuration") or answers.get("supply")))
    if key in {"earthing_system", "earthing"}:
        return bool(canonical_earthing(answers.get("earthing_system") or answers.get("earthing")))
    if key in {"service_panel_location", "main_panel"}:
        return bool(panel_location_approval(answers))
    if key in {"utility_service_capacity_a", "main_breaker_a"}:
        return numeric(answers.get(key)) is not None
    return bool(_text(answers.get(key)))
