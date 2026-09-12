from copy import deepcopy

import ezdxf
import pytest

from cad_engine.documentation_content_gate import (
    CONTROL_WEIGHTS,
    evaluate_documentation_content,
    exact_documentation_output_evidence,
)


def valid_context():
    return {
        "project_scope":{"project_id":"P","levels":["L1"],"spaces":["R1"],"equipment":["EQ1"],
                         "systems":["water"],"mechanical_reference_used":False},
        "active_systems":["water"],
        "requirements":[
            {"system":"water","kind":"DETAIL","required_ids":["D-W-01"]},
            {"system":"water","kind":"NOTE","required_ids":["N-W-01"]},
        ],
        "detail_library_revision":"details/1",
        "details":[{"detail_id":"D-W-01","system":"water","geometry":{"entities":3},
                    "installation_components":["valve","union"],"calc_ids":["C1"],
                    "parameters":{"diameter_mm":25,"insulation_mm":13}}],
        "required_constructability_detail_ids":["D-W-01"],
        "equipment_ids":["EQ1"],
        "required_equipment_schedule_fields":["equipment_id","tag","capacity","flow","power","connection_size"],
        "required_network_schedule_fields":["segment_id","diameter_mm","flow","velocity","pressure_drop","material","insulation","slope"],
        "schedules":[
            {"schedule_id":"S-EQ","kind":"EQUIPMENT","equipment_id":"EQ1","tag":"P-1","capacity":2,
             "flow":1,"power":1,"connection_size":25},
            {"schedule_id":"S-NET","kind":"NETWORK","segment_id":"E1","diameter_mm":25,"flow":1,
             "velocity":1,"pressure_drop":1,"material":"PPR","insulation":13,"slope":0},
        ],
        "identity_reconciliation":{"status":"PASS","plan_mismatches":[],"riser_mismatches":[],
                                   "schedule_mismatches":[],"detail_mismatches":[]},
        "notes":[{"note_id":"N-W-01","system":"water","standard":"INBR-16","revision":"current","clause":"16-4"}],
        "used_symbols":["CW"], "legends":[{"symbol":"CW","meaning":"COLD WATER"}],
        "layout_qa":{"status":"PASS","overlaps":0,"clipped_items":0},
        "readability_qa":{"status":"PASS","minimum_text_height_mm":2.5,"unreadable_items":0},
        "coordination_qa":{"status":"PASS","conflicts":0,"inaccessible_details":0},
        "sheets":[{"sheet_id":"M-501"}],
        "sheet_qa":{"status":"PASS","sheet_ids":["M-501"],"defects":[]},
    }


def exact():
    return {"reopened":True,"immutable":True,"detail_ids":["D-W-01"],
            "schedule_ids":["S-EQ","S-NET"],"note_ids":["N-W-01"],"symbols":["CW"]}


def test_all_eighteen_controls_total_100_and_release():
    result=evaluate_documentation_content(valid_context(), exact())
    assert len(CONTROL_WEIGHTS)==18 and sum(CONTROL_WEIGHTS.values())==100
    assert result["status"]=="PASS" and result["score"]==100 and result["release_allowed"] is True


def test_preflight_passes_seventeen_but_never_claims_final_release():
    result=evaluate_documentation_content(valid_context())
    assert result["status"]=="INPUT_REQUIRED" and result["preflight_allowed"] is True
    assert result["score"]==96 and result["release_allowed"] is False


@pytest.mark.parametrize("mutation,error", [
    (lambda c: c["project_scope"].update({"mechanical_reference_used":True}), "MECHANICAL_REFERENCE_INPUT_FORBIDDEN"),
    (lambda c: c["details"][0].update({"parameters":{"diameter_mm":"PROJECT SELECTION"}}), "CALCULATION_BOUND_DETAIL_REQUIRED:D-W-01"),
    (lambda c: c["details"].append({"detail_id":"D-G-01","system":"gas","geometry":{},"installation_components":[]}), "INACTIVE_SYSTEM_DETAIL_PRESENT"),
    (lambda c: c["identity_reconciliation"].update({"plan_mismatches":["EQ1"]}), "CROSS_DOCUMENT_IDENTITY_MISMATCH"),
    (lambda c: c["legends"].append({"symbol":"CW","meaning":"HOT WATER"}), "AMBIGUOUS_OR_DUPLICATE_LEGEND"),
    (lambda c: c["layout_qa"].update({"overlaps":1}), "DOCUMENT_LAYOUT_NOT_PASS"),
    (lambda c: c["coordination_qa"].update({"conflicts":1}), "DOCUMENT_CONSTRUCTABILITY_NOT_PASS"),
])
def test_destructive_documentation_defects_fail_closed(mutation, error):
    context=valid_context(); mutation(context)
    result=evaluate_documentation_content(context, exact())
    assert result["status"] in {"FAIL", "INPUT_REQUIRED"} and result["release_allowed"] is False
    assert error in result["errors"] or any(error in value for value in result["missing_inputs"])


def test_missing_requirements_are_input_required_not_guessed():
    context=valid_context(); context["requirements"]=[]
    result=evaluate_documentation_content(context, exact())
    assert result["status"]=="INPUT_REQUIRED"
    assert "DOCUMENT_REQUIREMENT_MATRIX_REQUIRED" in result["missing_inputs"]


def test_extra_missing_exact_document_identity_blocks():
    broken=exact(); broken["note_ids"]=[]
    result=evaluate_documentation_content(valid_context(), broken)
    assert result["status"]=="FAIL" and "EXACT_DOCUMENT_OUTPUT_PARITY_FAILED" in result["errors"]


def test_exact_issued_dxf_is_reopened_and_all_public_identities_are_found(tmp_path):
    path=tmp_path/"issued.dxf"; doc=ezdxf.new()
    for value in ("D-W-01", "S-EQ", "S-NET", "N-W-01", "CW"):
        doc.modelspace().add_text(value)
    doc.saveas(path)
    evidence=exact_documentation_output_evidence(path,["D-W-01"],["S-EQ","S-NET"],["N-W-01"],["CW"])
    assert evidence==exact()


def test_every_schedule_field_and_sheet_is_required():
    context=valid_context(); del context["schedules"][1]["diameter_mm"]
    context["sheet_qa"]["sheet_ids"]=[]
    result=evaluate_documentation_content(context, exact())
    assert "NETWORK_SCHEDULE_FIELD_MISSING" in result["errors"]
    assert "SHEET_DOCUMENT_QA_NOT_PASS" in result["errors"]
