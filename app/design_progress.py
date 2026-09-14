"""Durable, milestone-based progress for long-running CAD design jobs."""
from __future__ import annotations

from datetime import datetime, timezone


STAGES = {
    "queued": (3, "در صف طراحی"),
    "preparing_inputs": (8, "آماده‌سازی فایل‌ها و اطلاعات پروژه"),
    "validating_contract": (12, "کنترل قرارداد و پاسخ‌های تأییدشده"),
    "coordination_validation": (16, "کنترل اطلاعات هماهنگی و مسیرگذاری چندترازی"),
    "equipment_constraints_validation": (18, "کنترل محدودیت‌های انتخاب تجهیزات"),
    "documentation_validation": (19, "کنترل الزامات پلان، رایزر، محاسبات و جداول"),
    "engine_designing": (20, "شروع طراحی مهندسی نقشه‌ها"),
    "architecture_interpretation": (24, "تفسیر هندسه، طبقات، فضاها و شفت‌های معماری"),
    "scope_mapping": (29, "تعیین سیستم‌های موردنیاز هر فضا و طبقه"),
    "network_topology": (35, "ساخت توپولوژی شبکه‌ها و ارتباط رایزرها"),
    "network_sizing": (42, "محاسبه و سایزبندی شاخه‌ها، دبی‌ها و ظرفیت‌ها"),
    "system_coordination": (49, "هماهنگی مسیرها و کنترل تداخل سیستم‌ها"),
    "equipment_placement": (56, "انتخاب و جانمایی تجهیزات مکانیکی"),
    "documentation_composition": (62, "آماده‌سازی رایزرها، دیتیل‌ها، جداول و علائم"),
    "drawing_composition": (68, "ترسیم و صفحه‌بندی پلان‌های مکانیکی"),
    "network_materialization": (73, "تثبیت مسیرها و مشخصات مهندسی در فایل CAD"),
    "exact_output_review": (76, "بازبینی فایل واقعی تولیدشده و تطبیق اجزای طراحی"),
    "mechanical_release_qa": (78, "کنترل تجهیزات، جزئیات و خوانایی بصری"),
    "validating_output": (82, "کنترل کامل‌بودن نقشه‌ها و شیت‌ها"),
    "packaging": (87, "ساخت بسته نهایی خروجی"),
    "artifact_qa": (92, "بازکردن مجدد فایل نهایی و کنترل سلامت"),
    "uploading_output": (95, "ذخیره امن فایل خروجی"),
    "finalizing": (98, "ثبت نسخه و نهایی‌سازی پروژه"),
    "completed": (100, "طراحی تکمیل شد"),
}


def progress_timeline(active_stage: str) -> list[dict]:
    """Expose completed/current/pending phases without inventing engine progress."""
    names=list(STAGES);active_index=names.index(active_stage)
    return [
        {"stage":name,"label":STAGES[name][1],"percent":STAGES[name][0],
         "state":"completed" if index<active_index else "current" if index==active_index else "pending"}
        for index,name in enumerate(names)
    ]


def stage_payload(stage: str, *, detail: str = "") -> dict:
    """Return the public progress contract for one known milestone."""
    if stage not in STAGES:
        raise ValueError(f"unknown design progress stage: {stage}")
    percent, label = STAGES[stage]
    return {
        "stage": stage,
        "label": label,
        "percent": percent,
        "detail": detail,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "timeline": progress_timeline(stage),
    }


def set_project_progress(project, stage: str, *, detail: str = "") -> dict:
    """Persist progress inside the existing Project.analysis JSON column."""
    progress = stage_payload(stage, detail=detail)
    analysis = dict(project.analysis or {})
    analysis["design_progress"] = progress
    project.analysis = analysis
    return progress


def get_project_progress(project) -> dict | None:
    progress = dict((project.analysis or {}).get("design_progress") or {})
    if not progress:
        return None
    stage = progress.get("stage")
    if stage not in STAGES:
        return None
    percent, label = STAGES[stage]
    progress["percent"] = percent
    progress["label"] = label
    progress["timeline"] = progress_timeline(stage)
    return progress
