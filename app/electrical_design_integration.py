"""Install active Electrical preflight/recovery around the shared DXF design flow."""
from __future__ import annotations

import os
import re
import requests

from . import electrical_workflow, electrical_drawing_set


# These questions are intentionally on-demand.  They are not added to the first
# design-basis questionnaire: the CAD authority resolves the applicable detail
# library first, then returns exact ``detail-id.parameter`` evidence keys.  Only
# the parameters needed by this project are reopened in the site/panel flow.
CONSTRUCTION_DETAIL_QUESTION_SPECS = {
    "detail_panel_mounting_height_mm": {
        "question": "ارتفاع نصب تابلو از کف تمام‌شده را برای دیتیل اجرایی مشخص کنید.",
        "input_type": "number", "options": [], "unit": "mm",
    },
    "detail_panel_clearance_mm": {
        "question": "فاصله آزاد دسترسی/کار مقابل تابلو را برای دیتیل اجرایی مشخص کنید.",
        "input_type": "number", "options": [], "unit": "mm",
    },
    "detail_wall_type": {
        "question": "نوع دیوار محل نصب تجهیزات و عبور تأسیسات را مشخص کنید (مثلاً بنایی، بتن، دیوار خشک یا دیتیل مصوب پروژه).",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_meter_mounting_height_mm": {
        "question": "ارتفاع نصب کنتور/باکس اندازه‌گیری از کف تمام‌شده را مشخص کنید.",
        "input_type": "number", "options": [], "unit": "mm",
    },
    "detail_service_type": {
        "question": "نوع سرویس ورودی و آرایش کنتور مورد تأیید پروژه را برای دیتیل اجرایی بنویسید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_conduit_support_spacing_mm": {
        "question": "فاصله ساپورت لوله/کاندوئیت برق را طبق مشخصات پروژه وارد کنید.",
        "input_type": "number", "options": [], "unit": "mm",
    },
    "detail_conduit_type": {
        "question": "نوع لوله/کاندوئیت مورد تأیید پروژه را مشخص کنید (جنس، نوع نصب یا کلاس لازم).",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_fire_rating": {
        "question": "درجه مقاومت حریق دیوار/نفوذ تأسیساتی را مشخص کنید؛ اگر الزام حریق ندارد، صریحاً همین مورد را ثبت کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_sleeve_type": {
        "question": "نوع Sleeve/غلاف عبور کابل از دیوار را طبق دیتیل مصوب پروژه مشخص کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_earthing_electrode_type": {
        "question": "نوع الکترود/ارت اجرایی پروژه را برای دیتیل اتصال زمین مشخص کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_earthing_conductor": {
        "question": "مشخصات هادی ارت/هم‌بندی مورد تأیید پروژه را وارد کنید (جنس و سطح مقطع/شرح مصوب).",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_earthing_inspection_point": {
        "question": "محل/نوع نقطه تست و بازرسی سیستم ارت را برای دیتیل اجرایی مشخص کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_ceiling_type": {
        "question": "نوع سقف/سقف کاذب مؤثر بر نصب چراغ و دتکتور را مشخص کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_fixture_type": {
        "question": "نوع نصب/ساپورت چراغ مورد تأیید پروژه را برای دیتیل اجرایی مشخص کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_device_mounting_height_mm": {
        "question": "ارتفاع نصب تجهیز دیواریِ این دیتیل (کلید/پریز تیپ) از کف تمام‌شده را وارد کنید. اگر تیپ‌ها ارتفاع متفاوت دارند، مقدار/شرح تیپ مصوب را در مدارک پروژه یکسان‌سازی کنید.",
        "input_type": "number", "options": [], "unit": "mm",
    },
    "detail_detector_clearance_basis": {
        "question": "مبنای فاصله آزاد/جانمایی دتکتور از موانع را طبق ضابطه یا دیتیل مصوب پروژه مشخص کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_emergency_mounting": {
        "question": "روش و محل نصب چراغ اضطراری را طبق پروژه مشخص کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_emergency_supply": {
        "question": "منبع/مدار تغذیه چراغ اضطراری را طبق مدارک پروژه مشخص کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_junction_box_size": {
        "question": "سایز/تیپ جعبه اتصال (Junction Box) را برای دیتیل اجرایی مشخص کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_junction_box_access": {
        "question": "روش دسترسی و محل مجاز Junction Box را مشخص کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_service_cable": {
        "question": "مشخصات کابل ورودی/فیدر این ترمینیشن را طبق محاسبات یا اطلاعات تأییدشده پروژه وارد کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_lug_type": {
        "question": "نوع کابلشو/سرکابل مورد تأیید پروژه برای ترمینیشن را مشخص کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_termination_protection": {
        "question": "روش حفاظت/عایق‌کاری و تکمیل ترمینیشن کابل را طبق مشخصات پروژه بنویسید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_isolator_rating": {
        "question": "رنج/ظرفیت ایزولاتور تجهیز را طبق نام‌پلاک یا محاسبات تأییدشده وارد کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_isolator_mounting": {
        "question": "روش/ارتفاع نصب ایزولاتور را طبق پروژه مشخص کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
    "detail_isolator_clearance": {
        "question": "فاصله آزاد دسترسی ایزولاتور از تجهیز/مانع را طبق پروژه مشخص کنید.",
        "input_type": "text", "options": [], "unit": None,
    },
}

RECOVERY_QUESTION_SPECS = {
    "building_type": {"question": "کاربری قطعی ساختمان را برای طراحی برق مشخص کنید.", "input_type": "text", "options": [], "unit": None},
    "number_of_units": {"question": "تعداد کل واحدهای مستقل ساختمان را وارد کنید.", "input_type": "number", "options": [], "unit": "واحد"},
    "earthing_final_basis": {"question": "برای صدور نقشه نهایی، سیستم ارت قطعی پروژه را طبق گزارش/مشاور تأیید کنید.", "input_type": "radio", "options": ["ارت فونداسیون", "چاه ارت / الکترود زمین", "TN-S", "TN-C-S", "TT"], "unit": None},
    "supply_voltage_v": {"question": "ولتاژ نامی انشعاب/شبکه برق پروژه را طبق اطلاعات شرکت برق یا مدارک پروژه وارد کنید.", "input_type": "number", "options": [], "unit": "V"},
    "hvac_electrical_loads": {"question": "آیا تجهیزات HVAC بار الکتریکی دارند؟ اگر دارند مشخصات/توان و فاز آن‌ها را بنویسید؛ اگر ندارند «ندارد» ثبت کنید.", "input_type": "text", "options": [], "unit": None},
    "emergency_lighting": {"question": "آیا روشنایی اضطراری در Scope پروژه لازم است؟", "input_type": "radio", "options": ["نیاز ندارد", "نیاز دارد"], "unit": None},
    "lightning_protection": {"question": "آیا حفاظت صاعقه در Scope پروژه لازم است؟", "input_type": "radio", "options": ["نیاز ندارد", "نیاز دارد"], "unit": None},
    "generator": {"question": "آیا ژنراتور در پروژه وجود دارد/لازم است؟", "input_type": "radio", "options": ["ندارد", "دارد"], "unit": None},
    "ups": {"question": "آیا UPS در پروژه وجود دارد/لازم است؟", "input_type": "radio", "options": ["ندارد", "دارد"], "unit": None},
    "ev_charging": {"question": "آیا شارژر خودروی برقی در Scope پروژه وجود دارد؟", "input_type": "radio", "options": ["ندارد", "دارد"], "unit": None},
    "solar_pv": {"question": "آیا سامانه خورشیدی/PV در Scope پروژه وجود دارد؟", "input_type": "radio", "options": ["ندارد", "دارد"], "unit": None},
    "elevator": {"question": "وضعیت آسانسور را مشخص کنید؛ اگر وجود دارد مشخصات برق/نام‌پلاک را بنویسید و اگر ندارد «ندارد» ثبت کنید.", "input_type": "text", "options": [], "unit": None},
    "pump": {"question": "وضعیت پمپ‌های برقی پروژه را مشخص کنید؛ اگر وجود دارند مشخصات برق/نام‌پلاک را بنویسید و اگر ندارند «ندارد» ثبت کنید.", "input_type": "text", "options": [], "unit": None},
    "lighting_basis_values": {"question": "لوکس هدف فضاها را طبق مبنای تأییدشده وارد کنید. نمونه: default=150; bedroom=100; living=150", "input_type": "text", "options": [], "unit": "lux"},
    "luminaire_schedule": {"question": "مشخصات چراغ تیپ/مصوب را وارد کنید. نمونه: lumens=1200; utilization_factor=0.60; maintenance_factor=0.80; input_power_w=12", "input_type": "text", "options": [], "unit": None},
    "switch_control_requirements": {"question": "تعداد نقاط کنترل/کلید را طبق طرح تأییدشده وارد کنید. نمونه: default=1; stair=2", "input_type": "text", "options": [], "unit": None},
    "socket_power_requirements": {"question": "قاعده پریز پروژه را از مرجع تأییدشده وارد کنید. نمونه: minimum_count=2; design_load_w_per_outlet=200; reference=مدرک/ضابطه پروژه", "input_type": "text", "options": [], "unit": None},
    "dedicated_appliance_requirements": {"question": "بارهای اختصاصی را با توان نام‌پلاک ثبت کنید. نمونه: kitchen=oven@2500,dishwasher@1800. اگر هیچ بار اختصاصی ندارید «ندارد» بنویسید.", "input_type": "text", "options": [], "unit": None},
    "opening_clearance_m": {"question": "حداقل فاصله مجاز تجهیزات برق از بازشوها را طبق ضابطه/دیتیل پروژه وارد کنید.", "input_type": "number", "options": [], "unit": "m"},
    "wall_host_tolerance_m": {"question": "تلرانس مجاز اتصال تجهیز به دیوار/Host را طبق معیار پروژه وارد کنید.", "input_type": "number", "options": [], "unit": "m"},
    "ceiling_layout_basis_confirmed": {"question": "آیا مبنای جانمایی تجهیزات سقفی و سقف کاذب برای این پروژه تأیید شده است؟", "input_type": "radio", "options": ["بله", "خیر"], "unit": None},
    "switch_door_relation_confirmed": {"question": "آیا سمت و رابطه کلیدها با بازشو/درها در طرح معماری تأیید شده است؟", "input_type": "radio", "options": ["بله", "خیر"], "unit": None},
    "power_factor": {"question": "ضریب توان مبنای طراحی را طبق اطلاعات بار/مشخصات پروژه وارد کنید.", "input_type": "number", "options": [], "unit": None},
    "service": {"question": "مشخصات سرویس ورودی برق پروژه را طبق مدارک شرکت برق/پروژه بنویسید.", "input_type": "text", "options": [], "unit": None},
    "meter": {"question": "نوع و آرایش کنتور/اندازه‌گیری پروژه را طبق مدارک تأییدشده بنویسید.", "input_type": "text", "options": [], "unit": None},
    "main_distribution": {"question": "مشخصات تابلو/توزیع اصلی بعد از کنتور را طبق طرح تأییدشده بنویسید.", "input_type": "text", "options": [], "unit": None},
    "riser_feeder_schedule": {"question": "مشخصات فیدر بین طبقات را از پایین به بالا، هر انتقال در یک خط بنویسید. نمونه: cable=...; protection=...; tag=...", "input_type": "text", "options": [], "unit": None},
    "grounding_earth_electrode": {"question": "مشخصات الکترود/سیستم اتصال زمین اجرایی را طبق مدارک پروژه بنویسید.", "input_type": "text", "options": [], "unit": None},
    "grounding_main_earth_bar": {"question": "مشخصات شینه اصلی ارت (MEB/MET) پروژه را بنویسید.", "input_type": "text", "options": [], "unit": None},
    "grounding_protective_conductors": {"question": "مشخصات هادی‌های حفاظتی PE/هم‌بندی را طبق طرح و محاسبات تأییدشده بنویسید.", "input_type": "text", "options": [], "unit": None},
    "grounding_panel_grounding": {"question": "روش و مشخصات اتصال تابلوها به سیستم ارت را طبق مدارک پروژه بنویسید.", "input_type": "text", "options": [], "unit": None},
    "installation_method": {"question": "روش نصب کابل/هادی را طبق پروژه مشخص کنید (مثلاً داخل لوله، سینی، دفنی یا روش مصوب دیگر).", "input_type": "text", "options": [], "unit": None},
    "conductor_material": {"question": "جنس هادی مورد تأیید پروژه را مشخص کنید.", "input_type": "radio", "options": ["مس", "آلومینیوم"], "unit": None},
    "voltage_drop_limits": {"question": "حد مجاز افت ولتاژ را طبق ضابطه/مشخصات پروژه وارد کنید. نمونه: default=3", "input_type": "text", "options": [], "unit": "%"},
    "phase_balance_threshold_pct": {"question": "حد مجاز عدم‌تعادل فاز را طبق معیار پروژه وارد کنید.", "input_type": "number", "options": [], "unit": "%"},
}

# ``reopen_basis_questions`` and ``question_payload`` read this shared registry.
# Construction and late engineering questions are added only after CAD proves
# they are applicable; the primary questionnaire stays short and project-driven.
electrical_workflow.REQUIRED_BASIS_QUESTION_SPECS.update(RECOVERY_QUESTION_SPECS)
electrical_workflow.REQUIRED_BASIS_QUESTION_SPECS.update(CONSTRUCTION_DETAIL_QUESTION_SPECS)

DETAIL_RECOVERY_KEYS = {
    "d-el-panel-mount.mounting_height": "detail_panel_mounting_height_mm",
    "d-el-panel-mount.wall_type": "detail_wall_type",
    "d-el-panel-mount.clearance": "detail_panel_clearance_mm",
    "d-el-meter.mounting_height": "detail_meter_mounting_height_mm",
    "d-el-meter.service_type": "detail_service_type",
    "d-el-conduit-support.support_spacing": "detail_conduit_support_spacing_mm",
    "d-el-conduit-support.conduit_type": "detail_conduit_type",
    "d-el-wall-pen.wall_type": "detail_wall_type",
    "d-el-wall-pen.fire_rating": "detail_fire_rating",
    "d-el-wall-pen.sleeve": "detail_sleeve_type",
    "d-el-earthing.electrode_type": "detail_earthing_electrode_type",
    "d-el-earthing.conductor": "detail_earthing_conductor",
    "d-el-earthing.inspection_point": "detail_earthing_inspection_point",
    "d-el-light-mount.ceiling_type": "detail_ceiling_type",
    "d-el-light-mount.fixture_type": "detail_fixture_type",
    "d-el-switch-outlet.mounting_height": "detail_device_mounting_height_mm",
    "d-el-switch-outlet.wall_type": "detail_wall_type",
    "d-el-fire-detector.ceiling_type": "detail_ceiling_type",
    "d-el-fire-detector.clearance_basis": "detail_detector_clearance_basis",
    "d-el-emergency.mounting": "detail_emergency_mounting",
    "d-el-emergency.supply": "detail_emergency_supply",
    "d-el-jb.box_size": "detail_junction_box_size",
    "d-el-jb.access": "detail_junction_box_access",
    "d-el-termination.cable": "detail_service_cable",
    "d-el-termination.lug": "detail_lug_type",
    "d-el-termination.protection": "detail_termination_protection",
    "d-el-isolator.rating": "detail_isolator_rating",
    "d-el-isolator.mounting": "detail_isolator_mounting",
    "d-el-isolator.clearance": "detail_isolator_clearance",
}

ERROR_ALIASES = {
    "city": ("city", "project location", "شهر"),
    "supply_configuration": ("supply_voltage_v", "phase_configuration", "utility_service", "supply", "انشعاب"),
    "earthing_system": ("earthing_system", "earthing", "ارت"),
    "service_panel_location": ("service_entry", "panel_location", "meter_location", "service_panel", "تابلو", "کنتور"),
    "dedicated_load_schedule": ("dedicated_appliance", "hvac_electrical_loads", "elevator", "pump", "special_load", "بار اختصاصی"),
    "fire_alarm_requirement": ("fire_alarm", "اعلام حریق"),
    "low_current_systems": ("low_current", "telecom", "data", "cctv", "جریان ضعیف"),
    "lighting_design_basis": ("lighting_basis", "lux", "luminaire", "روشنایی"),
    "local_electrical_code": ("applicable_rule", "code", "standard", "استاندارد", "ضابطه"),
    "ceiling_and_mounting": ("ceiling", "mounting", "height", "سقف", "ارتفاع"),
}


def missing_from_error(error):
    text = str(error or "").lower()
    found = []
    match = re.search(r"input_required\[([^\]]+)\]", text, re.I)
    tokens = [x.strip() for x in (match.group(1).split(",") if match else []) if x.strip()]
    unmatched_tokens = []
    system_map = {
        "hvac_power": "hvac_electrical_loads", "emergency_lighting": "emergency_lighting",
        "fire_alarm": "fire_alarm_requirement", "lightning_protection": "lightning_protection",
        "generator": "generator", "ups": "ups", "ev_charging": "ev_charging", "solar_pv": "solar_pv",
        "elevator_power": "elevator", "pump_power": "pump", "telecom": "low_current_systems",
        "data": "low_current_systems", "tv": "low_current_systems", "intercom": "low_current_systems",
        "cctv": "low_current_systems", "access_control": "low_current_systems",
    }
    direct_aliases = {
        "phase_configuration": "supply_configuration", "utility_service": "supply_configuration",
        "lighting_basis": "lighting_basis_values", "earthing_system": "earthing_final_basis", "earth_electrode": "grounding_earth_electrode",
        "main_earth_bar": "grounding_main_earth_bar", "protective_conductors": "grounding_protective_conductors",
        "panel_grounding": "grounding_panel_grounding",
    }
    registry = electrical_workflow.REQUIRED_BASIS_QUESTION_SPECS
    for token in tokens:
        lowered = token.lower()
        mapped = DETAIL_RECOVERY_KEYS.get(lowered)
        if mapped:
            found.append(mapped); continue
        if re.fullmatch(r"req-\d+(?:-a\d+)?", lowered):
            # Internal equipment IDs are diagnostics only. Their semantic causes
            # are emitted separately by the CAD recovery contract.
            continue
        mapped = direct_aliases.get(lowered) or system_map.get(lowered)
        if mapped:
            found.append(mapped); continue
        if lowered in registry:
            found.append(lowered); continue
        unmatched_tokens.append(token)

    # Structured recovery tokens own their exact question mapping. Broad aliases
    # remain only as compatibility for legacy/unstructured CAD failures.
    evidence = unmatched_tokens if tokens else [text]
    for key, aliases in ERROR_ALIASES.items():
        if any(any(alias.lower() in item for alias in aliases) for item in evidence):
            found.append(key)
    return list(dict.fromkeys(key for key in found if key in registry))


def _ensure_approved_manifest(project):
    missing = electrical_workflow.required_basis_questions(project)
    if missing:
        electrical_workflow.ensure_required_basis_questions(project)
        return False
    analysis = dict(project.analysis or {})
    current = dict(analysis.get("drawing_set") or {})
    if electrical_drawing_set.approved_manifest_is_valid(current):
        return True
    proposed = electrical_drawing_set.proposal(project)
    analysis["drawing_set"] = proposed
    analysis["electrical_drawing_set"] = proposed
    project.analysis = analysis
    project.status = "drawing_set_review"
    project.last_error = ""
    return False


def install(dxf_output, legacy):
    if getattr(legacy, "_electrical_design_installed", False):
        return
    original_run = legacy.run_design
    original_flow = legacy.flow_payload
    original_post = dxf_output._post_to_compatible_cad

    def post_to_compatible_cad(payload):
        if str((payload or {}).get("discipline") or "").lower() != "electrical":
            return original_post(payload)
        cobuilt = os.getenv("COBUILT_CAD_DESIGNER_URL", "http://127.0.0.1:8081").rstrip("/")
        response = requests.post(cobuilt + "/design-electrical", json=payload, timeout=3600)
        if response.ok:
            data = response.json()
            if data.get("mode") != "electrical-authoritative" or data.get("pipeline_authority") != "electrical-authority":
                raise RuntimeError("مسیر تولید برق با قرارداد فعال سیستم تطابق ندارد.")
        return response

    def run_design(project_id, revision_id):
        db = legacy.Session(); project = db.get(legacy.Project, project_id)
        if not project:
            db.close(); return original_run(project_id, revision_id)
        discipline = (project.answers or {}).get("discipline", (project.analysis or {}).get("discipline", "mechanical"))
        if discipline != "electrical":
            db.close(); return original_run(project_id, revision_id)
        if not _ensure_approved_manifest(project):
            revision = db.get(legacy.Revision, revision_id)
            if revision:
                revision.status = "queued"; revision.error = ""
            db.commit(); db.close(); return
        db.commit(); db.close()
        original_run(project_id, revision_id)
        db = legacy.Session(); project = db.get(legacy.Project, project_id)
        if project and project.status == "failed":
            missing = missing_from_error(project.last_error)
            if missing and electrical_workflow.reopen_basis_questions(project, missing):
                revision = db.get(legacy.Revision, revision_id)
                if revision:
                    revision.status = "queued"
                db.commit()
        db.close()

    def flow_payload(project):
        data = original_flow(project)
        discipline = (project.answers or {}).get("discipline", (project.analysis or {}).get("discipline", "mechanical"))
        if discipline != "electrical":
            return data
        missing = electrical_workflow.required_basis_questions(project)
        if missing:
            data["input_required"] = {
                "missing": missing,
                "resume_stage": "electrical_design_basis",
                "message": "تحلیل پلان و پاسخ‌های قبلی حفظ شده‌اند؛ فقط اطلاعات مبنای طراحی برق را تکمیل کنید.",
            }
            data["ready_to_design"] = False
        drawing = (project.analysis or {}).get("drawing_set") or {}
        if not electrical_drawing_set.approved_manifest_is_valid(drawing):
            data["ready_to_design"] = False
        data["drawing_set"] = {
            "status": drawing.get("status"),
            "sheet_count": drawing.get("sheet_count") or len(drawing.get("approved_manifest") or drawing.get("manifest") or []),
            "manifest_sha256": drawing.get("manifest_sha256"),
        }
        answers = dict(project.answers or {})
        construction_keys = set(CONSTRUCTION_DETAIL_QUESTION_SPECS)
        pending = [
            str(q.get("key")) for q in (project.questions or [])
            if isinstance(q, dict) and q.get("key") in construction_keys and not str(answers.get(q.get("key"), "")).strip()
        ]
        captured = [key for key in construction_keys if str(answers.get(key, "")).strip()]
        data["construction_detail_inputs"] = {
            "status": "INPUT_REQUIRED" if pending else ("CAPTURED" if captured else "ON_DEMAND"),
            "pending": pending,
            "captured_count": len(captured),
            "message": (
                "دیتیل‌های اجرایی فقط در صورت نیاز موتور CAD سؤال تکمیلی ایجاد می‌کنند؛ مقدار پیش‌فرض پروژه‌ای ساخته نمی‌شود."
            ),
        }
        data["electrical_contract_revision"] = "electrical-runtime/1"
        data["electrical_execution_detail_contract"] = "construction-detail-inputs/1"
        data["electrical_cad_mode"] = "electrical-authoritative"
        return data

    dxf_output._post_to_compatible_cad = post_to_compatible_cad
    legacy.run_design = run_design
    legacy.flow_payload = flow_payload
    legacy._electrical_design_installed = True
