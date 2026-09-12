from copy import deepcopy

from cad_engine.final_engineering_release_gate import (
    CONTROL_WEIGHTS,
    evaluate_final_engineering_release,
)


HASH = "a" * 64


def valid_context():
    zero_groups = {
        "cross_sheet": ("identity_mismatches", "sheet_reference_errors"),
        "plan_riser": ("orphan_branches", "diameter_mismatches", "level_mismatches"),
        "calculation": ("untraced_values", "unit_errors", "capacity_mismatches"),
        "hvac": ("unserved_zones", "load_errors", "airflow_errors", "condensate_errors"),
        "water": ("pressure_errors", "flow_errors", "diameter_errors", "unserved_fixtures"),
        "sanitary_vent": ("slope_errors", "diameter_errors", "unvented_traps", "missing_cleanouts"),
        "gas": ("load_errors", "pressure_drop_errors", "diameter_errors", "safety_errors"),
        "coordination": ("critical_clashes", "inaccessible_elements", "missing_penetrations", "egress_conflicts"),
        "details": ("missing_active_families", "unbound_details", "parameter_errors"),
        "documentation": ("missing_legends", "missing_notes", "missing_schedules", "broken_references"),
    }
    context = {key: {field: 0 for field in fields} for key, fields in zero_groups.items()}
    context.update({
        "submission_checklist": {"revision": "TEHRAN-2026", "authority": "LOCAL_AHJ", "status": "PASS", "open_items": []},
        "drawing_scope_qa": {"status": "PASS", "score": 100},
        "architecture_release": {"status": "PASS", "source_sha256": HASH, "approved_revision": "A-12", "superseded": False},
        "equipment_selection_placement_qa": {"status": "PASS", "score": 100},
        "visual_qa": {"status": "PASS", "score": 100},
        "technical_file_qa": {"layers_valid": True, "units_valid": True, "coordinates_valid": True,
                              "fonts_resolved": True, "cad_reopen_pass": True, "pdf_reopen_pass": True},
        "independent_review": {"status": "PASS", "reviewer_id": "engineer-2", "evidence_sha256": HASH,
                               "open_critical": 0, "open_major": 0},
    })
    return context


def exact_package():
    return {"reopened": True, "immutable": True, "architecture_sha256": HASH,
            "artifacts": {name: HASH for name in
                          ("cad", "pdf", "calculation_book", "clash_report", "equipment_schedule", "datasheets", "signed_checklist")}}


def test_eighteen_controls_total_exactly_100_and_release():
    assert len(CONTROL_WEIGHTS) == 18
    assert sum(CONTROL_WEIGHTS.values()) == 100
    report = evaluate_final_engineering_release(valid_context(), exact_package())
    assert report["status"] == "PASS"
    assert report["score"] == 100
    assert report["all_controls_pass"] is True
    assert report["release_allowed"] is True
    assert report["legal_engineer_stamp_required"] is True


def test_missing_evidence_is_input_required_and_preflight_blocks():
    report = evaluate_final_engineering_release({})
    assert report["status"] == "INPUT_REQUIRED"
    assert report["release_allowed"] is False
    assert report["preflight_allowed"] is False
    assert "GOVERNED_SUBMISSION_CHECKLIST_REQUIRED" in report["missing_inputs"]


def test_any_engineering_violation_blocks_without_average_masking():
    context = valid_context()
    context["sanitary_vent"]["unvented_traps"] = 1
    report = evaluate_final_engineering_release(context, exact_package())
    assert report["status"] == "FAIL"
    assert report["score"] < 100
    assert report["release_allowed"] is False


def test_superseded_architecture_and_open_redlines_block():
    context = valid_context()
    context["architecture_release"]["superseded"] = True
    context["independent_review"]["open_major"] = 1
    report = evaluate_final_engineering_release(context, exact_package())
    assert report["status"] == "FAIL"
    assert "ARCHITECTURE_NOT_CURRENT_OR_PRESERVED" in report["errors"]
    assert "ENGINEERING_REVIEW_NOT_CLOSED" in report["errors"]


def test_exact_package_requires_all_artifact_hashes_and_architecture_identity():
    package = exact_package()
    del package["artifacts"]["pdf"]
    package["architecture_sha256"] = "b" * 64
    report = evaluate_final_engineering_release(valid_context(), package)
    assert report["status"] == "FAIL"
    assert any("EXACT_RELEASE_PACKAGE_PARITY_FAILED" in value for value in report["errors"])


def test_technical_file_qa_is_fail_closed():
    context = deepcopy(valid_context())
    context["technical_file_qa"]["fonts_resolved"] = False
    report = evaluate_final_engineering_release(context, exact_package())
    assert report["status"] == "FAIL"
    assert report["release_allowed"] is False


def test_preflight_accepts_first_seventeen_equipment_controls_only():
    context = valid_context()
    context["equipment_selection_placement_qa"] = {
        "status": "INPUT_REQUIRED", "score": 96, "preflight_allowed": True,
    }
    report = evaluate_final_engineering_release(context)
    assert report["preflight_allowed"] is True
    assert report["release_allowed"] is False
    assert report["status"] == "INPUT_REQUIRED"
