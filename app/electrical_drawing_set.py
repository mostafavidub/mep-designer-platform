"""Project-driven Electrical drawing-set proposal and approval contract v19.

The set is derived from project scope and never from a globally fixed sheet
count.  Optional systems produce sheets only when evidence/answers make them
applicable.  Approval is persisted as a hash so the CAD service can reject a
mismatched or silently changed manifest.
"""
from __future__ import annotations

import hashlib
import json

from . import electrical_workflow

DRAWING_SET_VERSION = "electrical-drawing-set-v19.0"


def _sheet(code, family, level, title, purpose="PLAN"):
    return {"code": code, "family": family, "level": level, "title": title, "purpose": purpose}


def build_manifest(project):
    scope = electrical_workflow.build_scope(project)
    rows = []
    rows.append(_sheet("E-000", "COVER", "MULTI", "صفحه عنوان و فهرست نقشه‌های برق", "COVER"))
    rows.append(_sheet("E-001", "GENERAL_NOTES", "MULTI", "مبانی طراحی، علائم و یادداشت‌های عمومی برق", "NOTES"))
    ordinal = 10
    for level in scope.get("electrical_plan_levels") or []:
        rows.append(_sheet(f"E-{ordinal:03d}", "LIGHTING", level, f"پلان روشنایی و کنترل — {level}")); ordinal += 1
        rows.append(_sheet(f"E-{ordinal:03d}", "POWER", level, f"پلان پریز و قدرت — {level}")); ordinal += 1
    if scope.get("fire_alarm_required") is True:
        for level in scope.get("electrical_plan_levels") or []:
            rows.append(_sheet(f"E-{ordinal:03d}", "FIRE_ALARM", level, f"پلان اعلام حریق — {level}")); ordinal += 1
    if scope.get("low_current_required") is True:
        for level in scope.get("electrical_plan_levels") or []:
            rows.append(_sheet(f"E-{ordinal:03d}", "LOW_CURRENT", level, f"پلان جریان ضعیف — {level}")); ordinal += 1
    rows.append(_sheet("E-100", "PANEL_SCHEDULE", "MULTI", "جداول تابلوها و مدارها", "SCHEDULE"))
    rows.append(_sheet("E-110", "SINGLE_LINE", "MULTI", "دیاگرام تک‌خطی توزیع برق", "DIAGRAM"))
    if scope.get("vertical_systems"):
        rows.append(_sheet("E-120", "RISER", "MULTI", "رایزر دیاگرام برق", "RISER"))
    rows.append(_sheet("E-130", "GROUNDING", "MULTI", "ارت، هم‌بندی و حفاظت", "PLAN/DETAIL"))
    rows.append(_sheet("E-140", "CALCULATIONS", "MULTI", "محاسبات بار، کابل، حفاظت، افت ولتاژ و بالانس فاز", "CALC"))
    rows.append(_sheet("E-150", "DETAILS", "MULTI", "جزئیات اجرایی موردنیاز پروژه", "DETAIL"))
    return rows


def proposal(project):
    manifest = build_manifest(project)
    scope = electrical_workflow.build_scope(project)
    unresolved = electrical_workflow.required_basis_questions(project)
    return {
        "version": DRAWING_SET_VERSION,
        "status": "INPUT_REQUIRED" if unresolved else "PROPOSED",
        "scope": scope,
        "manifest": manifest,
        "sheet_count": len(manifest),
        "unresolved_basis": unresolved,
        "project_driven": True,
    }


def _digest(manifest):
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def approve_drawing_set(value):
    value = dict(value or {})
    manifest = list(value.get("manifest") or [])
    if not manifest:
        raise ValueError("Electrical drawing manifest is empty")
    if value.get("unresolved_basis"):
        raise ValueError("Electrical design basis is incomplete")
    return {
        **value,
        "version": DRAWING_SET_VERSION,
        "status": "APPROVED",
        "approved_manifest": manifest,
        "manifest_sha256": _digest(manifest),
    }


def approved_manifest_is_valid(value):
    value = value or {}
    manifest = list(value.get("approved_manifest") or [])
    return bool(manifest) and value.get("status") == "APPROVED" and value.get("manifest_sha256") == _digest(manifest)
