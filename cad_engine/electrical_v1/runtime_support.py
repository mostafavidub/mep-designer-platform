"""Pure CAD-runtime helpers for the active Electrical system.

This module intentionally has no dependency on the web ``app`` package because
the dedicated CAD Docker image copies only ``cad_engine``.
"""
from __future__ import annotations

import re


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


def canonical_supply(value):
    if isinstance(value, dict) and value.get("configuration"):
        return dict(value)
    text = _text(value).lower()
    if not text:
        return None
    voltage = numeric(text)
    if any(x in text for x in ("مشاعات سه", "ترکیبی", "mixed")):
        return {"configuration":"mixed_single_units_three_phase_common", "voltage_v":voltage}
    if any(x in text for x in ("سه فاز", "سه‌فاز", "three phase", "3ph", "3 ph")):
        return {"configuration":"three_phase", "voltage_v":voltage}
    if any(x in text for x in ("تک فاز", "تک‌فاز", "single phase", "1ph", "1 ph")):
        return {"configuration":"single_phase", "voltage_v":voltage}
    return None


def canonical_earthing(value):
    text = _text(value).lower()
    if not text:
        return None
    aliases = {
        "tn-s": ("tn-s", "tns"), "tn-c-s": ("tn-c-s", "tncs"),
        "tt": ("سیستم tt", " tt "), "foundation_earth": ("ارت فونداسیون", "foundation earth"),
        "earth_electrode": ("چاه ارت", "الکترود زمین", "earth electrode"),
    }
    padded = f" {text} "
    for key, tokens in aliases.items():
        if any(token in padded for token in tokens):
            return key
    if any(x in text for x in ("طبق گزارش خاک", "نظر مشاور", "نامشخص", "تعیین شود")):
        return "input_required"
    return None


WEIGHTS = {
    "architecture_scope": 15, "design_basis": 15, "engineering_calculations": 20,
    "drawing_coverage_traceability": 15, "visual_documentation": 10,
    "same_file_reopen_semantic_qa": 10, "panel_flow_recovery": 10,
    "runtime_release_identity": 5,
}
MANDATORY = {
    "NO_FAKE_FINAL", "ARCHITECTURE_MODEL", "DESIGN_BASIS", "CIRCUIT_TOPOLOGY",
    "FINAL_FILE_REOPEN", "FINAL_REOPEN_AUTHORITY", "PANEL_FLOW_RECOVERY", "RUNTIME_RELEASE_IDENTITY",
}
CATEGORY_GATES = {
    "architecture_scope": {"ARCHITECTURE_MODEL","PROJECT_MODEL","SYSTEM_REQUIREMENTS","PLAN_ISOLATION_AUTHORITY"},
    "design_basis": {"DESIGN_BASIS","NO_FAKE_FINAL"},
    "engineering_calculations": {"CIRCUIT_TOPOLOGY","LOAD_CALCULATION","CABLE_SIZING","BREAKER_SIZING","VOLTAGE_DROP","PHASE_BALANCE","PANEL_DESIGN"},
    "drawing_coverage_traceability": {"SHEET_MANIFEST","PANEL_SCHEDULE","SINGLE_LINE","RISER","GROUNDING","DETAIL_REFERENCE_PARITY_AUTHORITY"},
    "visual_documentation": {"LEGEND","GENERAL_NOTES","REFERENCE_SIMILARITY","VISUAL_QA","SAFE_DRAWING_AREA_AUTHORITY"},
    "same_file_reopen_semantic_qa": {"FINAL_FILE_REOPEN","FINAL_REOPEN_AUTHORITY","SEMANTIC_DUPLICATE_AUTHORITY","FAMILY_PURITY"},
    "panel_flow_recovery": {"PANEL_FLOW_RECOVERY"},
    "runtime_release_identity": {"RUNTIME_RELEASE_IDENTITY","ELECTRICAL_RELEASE_CONTRACT"},
}


def execution_score(gates):
    gates = dict(gates or {})
    def status(name):
        value = gates.get(name)
        return str(value.get("status") or "UNKNOWN") if isinstance(value, dict) else str(value or "UNKNOWN")
    categories = {}; total = 0.0
    for category, weight in WEIGHTS.items():
        names = CATEGORY_GATES[category]
        applicable = [name for name in names if status(name) != "NOT_REQUIRED"]
        points = float(weight) if not applicable else weight * sum(status(name) == "PASS" for name in applicable) / len(applicable)
        categories[category] = {"points":round(points,2), "max":weight, "gates":{name:status(name) for name in names}}
        total += points
    blockers = sorted(name for name in MANDATORY if status(name) not in {"PASS","NOT_REQUIRED"})
    return {
        "score_schema_revision":"electrical-execution-score/1", "score":round(total,1), "threshold":80,
        "execution_ready":total >= 80 and not blockers, "hard_blockers":blockers,
        "categories":categories, "rule":"score>=80 AND zero mandatory blockers",
    }
