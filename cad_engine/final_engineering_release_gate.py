"""Fail-closed final engineering and issue-readiness acceptance gate."""
from __future__ import annotations

from hashlib import sha256
import json
import math


CONTRACT_VERSION = "final-engineering-release/1"
CONTROL_WEIGHTS = {
    "governed_submission_checklist": 4,
    "drawing_scope_complete": 7,
    "current_architecture_bound": 7,
    "cross_sheet_consistency": 5,
    "plan_riser_reconciliation": 7,
    "calculation_traceability": 8,
    "hvac_engineering_complete": 7,
    "water_engineering_complete": 6,
    "sanitary_vent_engineering_complete": 6,
    "gas_engineering_complete": 4,
    "equipment_release_complete": 6,
    "coordination_constructability": 6,
    "executable_details_complete": 5,
    "sheet_documentation_complete": 3,
    "all_sheet_visual_qa": 5,
    "exact_file_technical_qa": 5,
    "independent_engineer_review": 5,
    "immutable_release_package": 4,
}
assert len(CONTROL_WEIGHTS) == 18 and sum(CONTROL_WEIGHTS.values()) == 100


def _stable(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def _pass(report):
    return isinstance(report, dict) and report.get("status") == "PASS"


def _zero(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value == 0


def evaluate_final_engineering_release(context, exact_output=None):
    """Score eighteen independent controls; no average may mask a failed control."""
    context = context or {}; exact_output = exact_output or {}
    missing = {name: [] for name in CONTROL_WEIGHTS}
    errors = {name: [] for name in CONTROL_WEIGHTS}

    checklist = context.get("submission_checklist")
    if not isinstance(checklist, dict) or not checklist.get("revision") or not checklist.get("authority"):
        missing["governed_submission_checklist"].append("GOVERNED_SUBMISSION_CHECKLIST_REQUIRED")
    elif checklist.get("status") != "PASS" or checklist.get("open_items"):
        errors["governed_submission_checklist"].append("SUBMISSION_CHECKLIST_NOT_CLOSED")

    report_controls = (
        ("drawing_scope_complete", "drawing_scope_qa"),
        ("equipment_release_complete", "equipment_selection_placement_qa"),
        ("all_sheet_visual_qa", "visual_qa"),
    )
    for control, key in report_controls:
        report = context.get(key)
        if not report:
            missing[control].append(key.upper() + "_REQUIRED")
        elif control == "equipment_release_complete" and not exact_output and report.get("preflight_allowed") is True:
            # The equipment gate's eighteenth control is itself an exact-file
            # check. Accept its first seventeen controls only during preflight;
            # the final invocation below still requires its full 100/100 PASS.
            pass
        elif not _pass(report) or report.get("score") != 100:
            errors[control].append(key.upper() + "_100_REQUIRED")

    architecture = context.get("architecture_release")
    if not architecture or not architecture.get("source_sha256") or not architecture.get("approved_revision"):
        missing["current_architecture_bound"].append("APPROVED_ARCHITECTURE_IDENTITY_REQUIRED")
    elif architecture.get("status") != "PASS" or architecture.get("superseded") is True:
        errors["current_architecture_bound"].append("ARCHITECTURE_NOT_CURRENT_OR_PRESERVED")

    zero_controls = (
        ("cross_sheet_consistency", "cross_sheet", ("identity_mismatches", "sheet_reference_errors")),
        ("plan_riser_reconciliation", "plan_riser", ("orphan_branches", "diameter_mismatches", "level_mismatches")),
        ("calculation_traceability", "calculation", ("untraced_values", "unit_errors", "capacity_mismatches")),
        ("hvac_engineering_complete", "hvac", ("unserved_zones", "load_errors", "airflow_errors", "condensate_errors")),
        ("water_engineering_complete", "water", ("pressure_errors", "flow_errors", "diameter_errors", "unserved_fixtures")),
        ("sanitary_vent_engineering_complete", "sanitary_vent", ("slope_errors", "diameter_errors", "unvented_traps", "missing_cleanouts")),
        ("gas_engineering_complete", "gas", ("load_errors", "pressure_drop_errors", "diameter_errors", "safety_errors")),
        ("coordination_constructability", "coordination", ("critical_clashes", "inaccessible_elements", "missing_penetrations", "egress_conflicts")),
        ("executable_details_complete", "details", ("missing_active_families", "unbound_details", "parameter_errors")),
        ("sheet_documentation_complete", "documentation", ("missing_legends", "missing_notes", "missing_schedules", "broken_references")),
    )
    for control, key, fields in zero_controls:
        report = context.get(key)
        if not isinstance(report, dict):
            missing[control].append(key.upper() + "_EVIDENCE_REQUIRED")
            continue
        absent = [field for field in fields if field not in report]
        invalid = [field for field in fields if field in report and not _zero(report[field])]
        if absent:
            missing[control].append(key.upper() + "_FIELDS:" + ",".join(absent))
        if invalid:
            errors[control].append(key.upper() + "_VIOLATIONS:" + ",".join(invalid))

    technical = context.get("technical_file_qa")
    required_file_checks = ("layers_valid", "units_valid", "coordinates_valid", "fonts_resolved", "cad_reopen_pass", "pdf_reopen_pass")
    if not isinstance(technical, dict):
        missing["exact_file_technical_qa"].append("TECHNICAL_FILE_QA_REQUIRED")
    else:
        absent = [key for key in required_file_checks if key not in technical]
        failed = [key for key in required_file_checks if key in technical and technical[key] is not True]
        if absent:
            missing["exact_file_technical_qa"].append("TECHNICAL_FILE_CHECKS:" + ",".join(absent))
        if failed:
            errors["exact_file_technical_qa"].append("TECHNICAL_FILE_FAILURES:" + ",".join(failed))

    review = context.get("independent_review")
    if not isinstance(review, dict) or not review.get("reviewer_id") or not review.get("evidence_sha256"):
        missing["independent_engineer_review"].append("INDEPENDENT_ENGINEER_REVIEW_REQUIRED")
    elif review.get("status") != "PASS" or not _zero(review.get("open_critical")) or not _zero(review.get("open_major")):
        errors["independent_engineer_review"].append("ENGINEERING_REVIEW_NOT_CLOSED")

    required_artifacts = {"cad", "pdf", "calculation_book", "clash_report", "equipment_schedule", "datasheets", "signed_checklist"}
    artifacts = exact_output.get("artifacts") or {}
    if not exact_output:
        missing["immutable_release_package"].append("EXACT_RELEASE_PACKAGE_EVIDENCE_REQUIRED")
    else:
        invalid_artifacts = sorted(name for name in required_artifacts if len(str(artifacts.get(name) or "")) != 64)
        if (exact_output.get("reopened") is not True or exact_output.get("immutable") is not True
                or exact_output.get("architecture_sha256") != (architecture or {}).get("source_sha256")
                or invalid_artifacts):
            errors["immutable_release_package"].append(
                "EXACT_RELEASE_PACKAGE_PARITY_FAILED" + (":" + ",".join(invalid_artifacts) if invalid_artifacts else "")
            )

    controls = []
    for name, weight in CONTROL_WEIGHTS.items():
        status = "FAIL" if errors[name] else ("INPUT_REQUIRED" if missing[name] else "PASS")
        controls.append({"id": name, "weight": weight, "status": status,
                         "errors": errors[name], "missing_inputs": missing[name]})
    score = sum(row["weight"] for row in controls if row["status"] == "PASS")
    status = "FAIL" if any(row["status"] == "FAIL" for row in controls) else (
        "INPUT_REQUIRED" if any(row["status"] == "INPUT_REQUIRED" for row in controls) else "PASS")
    report = {"contract": CONTRACT_VERSION, "status": status, "score": score,
              "all_controls_pass": all(row["status"] == "PASS" for row in controls),
              "release_allowed": status == "PASS" and score == 100,
              "legal_engineer_stamp_required": True,
              "controls": controls,
              "errors": sorted({item for row in controls for item in row["errors"]}),
              "missing_inputs": sorted({item for row in controls for item in row["missing_inputs"]}),
              "evidence_hash": _stable({"context": context, "exact_output": exact_output})}
    report["preflight_allowed"] = all(row["status"] == "PASS" for row in controls[:-2])
    return report
