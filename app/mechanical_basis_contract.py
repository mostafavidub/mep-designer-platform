"""Canonical, fail-closed mechanical design-basis answer contract."""
from __future__ import annotations

from datetime import datetime, timezone
import re


CONTRACT_VERSION = "mechanical-design-basis-v18.5.1"


def _text(value):
    return re.sub(
        r"\s+", " ",
        str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " "),
    ).strip()


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
    # Location answers may be "country, city" in Persian or Latin punctuation.
    parts = [part.strip() for part in re.split(r"[,،]", _text(value)) if part.strip()]
    return parts[-1] if parts else None


def canonical_shaft_strategy(value):
    text = _text(value).lower()
    if not text:
        return None
    if any(token in text for token in ("هسته فضاهای تر", "نزدیک هسته", "wet core", "propose_near_wet_core")):
        return "propose_near_wet_core"
    if any(token in text for token in ("کنار راه پله", "کنار راه‌پله", "adjacent_to_stair", "stair")):
        return "propose_adjacent_to_stair"
    if any(token in text for token in ("اجازه پیشنهاد", "باید پیشنهاد", "proposal allowed", "allow proposal")):
        return "proposal_authorized"
    if any(token in text for token in ("موجود معماری", "قطعی هستند", "existing architectural", "use_existing")):
        return "use_existing_architectural_shafts"
    return None


def normalize_answers(answers, *, answer_key=None, raw_answer=None):
    """Return a new answer dictionary with canonical values and provenance."""
    out = dict(answers or {})
    if answer_key:
        out[answer_key] = raw_answer
    city = canonical_city(out)
    if city:
        out["city"] = city
    rainfall = numeric(out.get("rainfall_intensity_mm_h") or out.get("rainfall_intensity"))
    if rainfall is not None:
        out["rainfall_intensity_mm_h"] = rainfall
    strategy = canonical_shaft_strategy(out.get("mechanical_shaft_route"))
    if strategy:
        out["mechanical_shaft_route"] = strategy
        existing = dict(out.get("mechanical_shaft_approval") or {})
        if answer_key == "mechanical_shaft_route" or existing.get("status") != "APPROVED":
            out["mechanical_shaft_approval"] = {
                "status": "APPROVED",
                "strategy": strategy,
                "source": "explicit_user_answer",
                "raw_answer": _text(raw_answer if answer_key == "mechanical_shaft_route" else (answers or {}).get("mechanical_shaft_route")),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "contract_version": CONTRACT_VERSION,
            }
    out["_mechanical_basis_contract"] = {
        "version": CONTRACT_VERSION,
        "status": "NORMALIZED",
    }
    return out


def shaft_approval(answers):
    approval = dict((answers or {}).get("mechanical_shaft_approval") or {})
    strategy = canonical_shaft_strategy(
        approval.get("strategy") or (answers or {}).get("mechanical_shaft_route")
    )
    if approval.get("status") == "APPROVED" and strategy:
        return {**approval, "strategy": strategy}
    # Backfill legacy explicit answers without silently approving unknown text.
    if strategy:
        return {
            "status": "APPROVED", "strategy": strategy,
            "source": "legacy_explicit_user_answer",
            "contract_version": CONTRACT_VERSION,
        }
    return None


def persisted_answer_is_valid(answers, key):
    """Verify the canonical value after a database reload."""
    if key in ("city", "location"):
        return bool(canonical_city(answers))
    if key == "rainfall_intensity":
        return numeric((answers or {}).get("rainfall_intensity_mm_h") or (answers or {}).get(key)) is not None
    if key == "mechanical_shaft_route":
        return bool(shaft_approval(answers))
    return bool(_text((answers or {}).get(key)))
