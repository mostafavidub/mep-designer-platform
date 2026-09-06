"""Install Electrical v19 preflight/recovery around the shared DXF design flow."""
from __future__ import annotations

import re

from . import electrical_workflow, electrical_drawing_set

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
    # Prefer machine-readable INPUT_REQUIRED lists when the CAD adapter emits them.
    match = re.search(r"input_required\[([^\]]+)\]", text, re.I)
    tokens = [x.strip() for x in (match.group(1).split(",") if match else []) if x.strip()]
    for key, aliases in ERROR_ALIASES.items():
        evidence = tokens + [text]
        if any(any(alias.lower() in item for alias in aliases) for item in evidence):
            found.append(key)
    return list(dict.fromkeys(found))


def _ensure_approved_manifest(project):
    missing = electrical_workflow.required_basis_questions(project)
    if missing:
        electrical_workflow.ensure_required_basis_questions(project)
        return False
    analysis = dict(project.analysis or {})
    current = dict(analysis.get("drawing_set") or {})
    if not electrical_drawing_set.approved_manifest_is_valid(current):
        approved = electrical_drawing_set.approve_drawing_set(electrical_drawing_set.proposal(project))
        analysis["drawing_set"] = approved
        analysis["electrical_drawing_set"] = approved
        project.analysis = analysis
    return True


def install(dxf_output, legacy):
    if getattr(legacy, "_electrical_design_v19_installed", False):
        return
    original_run = legacy.run_design
    original_flow = legacy.flow_payload

    def run_design(project_id, revision_id):
        db = legacy.Session(); project = db.get(legacy.Project, project_id)
        if not project:
            db.close(); return original_run(project_id, revision_id)
        discipline = (project.answers or {}).get("discipline", (project.analysis or {}).get("discipline", "mechanical"))
        if discipline != "electrical":
            db.close(); return original_run(project_id, revision_id)
        if not _ensure_approved_manifest(project):
            # Preserve the queued revision but do not send an invalid contract to CAD.
            revision = db.get(legacy.Revision, revision_id)
            if revision:
                revision.status = "queued"
                revision.error = ""
            db.commit(); db.close(); return
        db.commit(); db.close()

        original_run(project_id, revision_id)

        # The shared runner owns transaction/artifact durability and catches CAD
        # exceptions internally.  Inspect the persisted result and reopen the
        # exact missing basis question instead of stranding the user at failed.
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
        data["drawing_set"] = {
            "status": drawing.get("status"),
            "sheet_count": drawing.get("sheet_count") or len(drawing.get("approved_manifest") or []),
            "manifest_sha256": drawing.get("manifest_sha256"),
        }
        data["electrical_workflow_version"] = "v19.0"
        return data

    legacy.run_design = run_design
    legacy.flow_payload = flow_payload
    legacy._electrical_design_v19_installed = True
