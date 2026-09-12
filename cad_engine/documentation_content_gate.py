"""Fail-closed details, schedules, notes and legends release acceptance."""
from __future__ import annotations

from hashlib import sha256
import json
import math


CONTRACT_VERSION = "documentation-content/1"
CONTROL_WEIGHTS = {
    "project_scope_inventory": 5, "required_document_matrix": 6,
    "standard_detail_library": 5, "calculation_bound_parameters": 8,
    "active_system_detail_selection": 6, "constructability_detail_coverage": 7,
    "equipment_schedule_from_model": 7, "network_schedule_complete": 6,
    "plan_riser_schedule_detail_identity": 8, "project_specific_notes": 5,
    "standards_provenance": 5, "used_symbol_legend": 5,
    "symbol_code_uniqueness": 4, "sheet_composition": 4,
    "printed_readability": 5, "coordination_constructability": 5,
    "sheet_by_sheet_document_qa": 5, "exact_output_document_parity": 4,
}
assert len(CONTROL_WEIGHTS) == 18 and sum(CONTROL_WEIGHTS.values()) == 100


def _stable(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def _positive(value):
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def _ids(rows, *keys):
    return {next((row.get(key) for key in keys if row.get(key)), None) for row in rows} - {None}


def exact_documentation_output_evidence(path, expected_detail_ids, expected_schedule_ids,
                                        expected_note_ids, expected_symbols):
    """Reopen the issued DXF and prove every public documentation identity exists."""
    try:
        import ezdxf
        doc = ezdxf.readfile(str(path)); texts = []
        for entity in doc.modelspace():
            if entity.dxftype() in {"TEXT", "MTEXT"}:
                texts.append(str(entity.dxf.text if entity.dxftype() == "TEXT" else entity.text))
        present = lambda values: sorted(value for value in values if any(str(value) in text for text in texts))
        return {"reopened": True, "immutable": True,
                "detail_ids": present(expected_detail_ids),
                "schedule_ids": present(expected_schedule_ids),
                "note_ids": present(expected_note_ids),
                "symbols": present(expected_symbols)}
    except Exception as exc:
        return {"reopened": False, "immutable": False, "detail_ids": [], "schedule_ids": [],
                "note_ids": [], "symbols": [], "error": type(exc).__name__}


def evaluate_documentation_content(context, exact_output=None):
    """Score all eighteen controls; absent evidence is never guessed as PASS."""
    context = context or {}; exact_output = exact_output or {}
    missing = {name: [] for name in CONTROL_WEIGHTS}; errors = {name: [] for name in CONTROL_WEIGHTS}
    systems = set(context.get("active_systems") or [])
    sheets = context.get("sheets") or []; details = context.get("details") or []
    schedules = context.get("schedules") or []; notes = context.get("notes") or []
    legends = context.get("legends") or []; requirements = context.get("requirements") or []

    scope = context.get("project_scope") or {}
    for key in ("project_id", "levels", "spaces", "equipment", "systems"):
        if scope.get(key) is None:
            missing["project_scope_inventory"].append("PROJECT_SCOPE_FIELD:" + key)
    if scope.get("mechanical_reference_used") is True:
        errors["project_scope_inventory"].append("MECHANICAL_REFERENCE_INPUT_FORBIDDEN")

    if not requirements:
        missing["required_document_matrix"].append("DOCUMENT_REQUIREMENT_MATRIX_REQUIRED")
    elif any(not row.get("system") or not row.get("kind") or not row.get("required_ids") for row in requirements):
        errors["required_document_matrix"].append("INCOMPLETE_DOCUMENT_REQUIREMENT_ROW")

    detail_by_id = {row.get("detail_id") or row.get("id"): row for row in details if row.get("detail_id") or row.get("id")}
    required_detail_ids = {item for row in requirements if row.get("kind") == "DETAIL" for item in row.get("required_ids") or []}
    if not context.get("detail_library_revision") or not details:
        missing["standard_detail_library"].append("GOVERNED_DETAIL_LIBRARY_REQUIRED")
    for did, row in detail_by_id.items():
        if not row.get("geometry") or not row.get("installation_components"):
            errors["standard_detail_library"].append("NON_EXECUTABLE_DETAIL:" + str(did))
        if not row.get("calc_ids") or not row.get("parameters") or any(v in (None, "", "PROJECT SELECTION") for v in row.get("parameters", {}).values()):
            missing["calculation_bound_parameters"].append("CALCULATION_BOUND_DETAIL_REQUIRED:" + str(did))
    detail_ids = set(detail_by_id)
    if requirements and detail_ids != required_detail_ids:
        errors["active_system_detail_selection"].append("REQUIRED_SELECTED_DETAIL_ID_MISMATCH")
    if any(row.get("system") not in systems for row in details):
        errors["active_system_detail_selection"].append("INACTIVE_SYSTEM_DETAIL_PRESENT")
    critical = set(context.get("required_constructability_detail_ids") or [])
    if not critical:
        missing["constructability_detail_coverage"].append("CONSTRUCTABILITY_DETAIL_REQUIREMENTS_REQUIRED")
    elif not critical <= detail_ids:
        errors["constructability_detail_coverage"].append("MISSING_CONSTRUCTABILITY_DETAILS")

    equipment_ids = set(context.get("equipment_ids") or [])
    equipment_rows = [row for row in schedules if row.get("kind") == "EQUIPMENT"]
    if _ids(equipment_rows, "equipment_id", "id") != equipment_ids:
        errors["equipment_schedule_from_model"].append("EQUIPMENT_SCHEDULE_MODEL_MISMATCH")
    required_equipment_fields = set(context.get("required_equipment_schedule_fields") or [])
    if not required_equipment_fields:
        missing["equipment_schedule_from_model"].append("EQUIPMENT_SCHEDULE_FIELDS_REQUIRED")
    elif any(not required_equipment_fields <= set(row) for row in equipment_rows):
        errors["equipment_schedule_from_model"].append("EQUIPMENT_SCHEDULE_FIELD_MISSING")

    network_rows = [row for row in schedules if row.get("kind") == "NETWORK"]
    network_fields = set(context.get("required_network_schedule_fields") or [])
    if not network_fields or not network_rows:
        missing["network_schedule_complete"].append("NETWORK_SCHEDULE_AND_FIELDS_REQUIRED")
    elif any(not network_fields <= set(row) for row in network_rows):
        errors["network_schedule_complete"].append("NETWORK_SCHEDULE_FIELD_MISSING")

    identities = context.get("identity_reconciliation") or {}
    if identities.get("status") != "PASS" or any(identities.get(key) for key in
            ("plan_mismatches", "riser_mismatches", "schedule_mismatches", "detail_mismatches")):
        errors["plan_riser_schedule_detail_identity"].append("CROSS_DOCUMENT_IDENTITY_MISMATCH")

    required_note_ids = {item for row in requirements if row.get("kind") == "NOTE" for item in row.get("required_ids") or []}
    note_ids = _ids(notes, "note_id", "id")
    if (requirements and note_ids != required_note_ids) or any(row.get("system") not in systems for row in notes):
        errors["project_specific_notes"].append("PROJECT_NOTE_SET_MISMATCH")
    if any(not row.get("standard") or not row.get("revision") or not row.get("clause") for row in notes):
        missing["standards_provenance"].append("NOTE_STANDARD_PROVENANCE_REQUIRED")

    used_symbols = set(context.get("used_symbols") or [])
    legend_symbols = _ids(legends, "symbol")
    if legend_symbols != used_symbols:
        errors["used_symbol_legend"].append("USED_SYMBOL_LEGEND_MISMATCH")
    meanings = [row.get("meaning") for row in legends]
    if None in meanings or len(legend_symbols) != len(legends) or len(meanings) != len(set(meanings)):
        errors["symbol_code_uniqueness"].append("AMBIGUOUS_OR_DUPLICATE_LEGEND")

    layout = context.get("layout_qa") or {}
    if layout.get("status") != "PASS" or layout.get("overlaps") or layout.get("clipped_items"):
        errors["sheet_composition"].append("DOCUMENT_LAYOUT_NOT_PASS")
    readability = context.get("readability_qa") or {}
    if readability.get("status") != "PASS" or not _positive(readability.get("minimum_text_height_mm")) or readability.get("unreadable_items"):
        errors["printed_readability"].append("PRINT_READABILITY_NOT_PASS")
    coordination = context.get("coordination_qa") or {}
    if coordination.get("status") != "PASS" or coordination.get("conflicts") or coordination.get("inaccessible_details"):
        errors["coordination_constructability"].append("DOCUMENT_CONSTRUCTABILITY_NOT_PASS")
    sheet_qa = context.get("sheet_qa") or {}
    expected_sheet_ids = _ids(sheets, "sheet_id", "id")
    if sheet_qa.get("status") != "PASS" or set(sheet_qa.get("sheet_ids") or []) != expected_sheet_ids or sheet_qa.get("defects"):
        errors["sheet_by_sheet_document_qa"].append("SHEET_DOCUMENT_QA_NOT_PASS")

    schedule_ids = _ids(schedules, "schedule_id", "id")
    if not exact_output:
        missing["exact_output_document_parity"].append("EXACT_DOCUMENT_OUTPUT_EVIDENCE_REQUIRED")
    elif (exact_output.get("reopened") is not True or exact_output.get("immutable") is not True
          or set(exact_output.get("detail_ids") or []) != detail_ids
          or set(exact_output.get("schedule_ids") or []) != schedule_ids
          or set(exact_output.get("note_ids") or []) != note_ids
          or set(exact_output.get("symbols") or []) != used_symbols):
        errors["exact_output_document_parity"].append("EXACT_DOCUMENT_OUTPUT_PARITY_FAILED")

    controls=[]
    for name, weight in CONTROL_WEIGHTS.items():
        status="FAIL" if errors[name] else ("INPUT_REQUIRED" if missing[name] else "PASS")
        controls.append({"id":name,"weight":weight,"status":status,"errors":errors[name],"missing_inputs":missing[name]})
    score=sum(row["weight"] for row in controls if row["status"] == "PASS")
    status="FAIL" if any(row["status"] == "FAIL" for row in controls) else ("INPUT_REQUIRED" if any(row["status"] == "INPUT_REQUIRED" for row in controls) else "PASS")
    report={"contract":CONTRACT_VERSION,"status":status,"score":score,"controls":controls,
            "all_controls_pass":all(row["status"] == "PASS" for row in controls),
            "release_allowed":status == "PASS" and score == 100,
            "errors":sorted({x for row in controls for x in row["errors"]}),
            "missing_inputs":sorted({x for row in controls for x in row["missing_inputs"]}),
            "evidence_hash":_stable({"context":context,"exact_output":exact_output})}
    report["preflight_allowed"] = all(row["status"] == "PASS" for row in controls[:-1])
    return report
