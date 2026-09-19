from cad_engine.post_materialization_release import _pending_equipment_boards


def _report():
    return {
        "semantic_qa":{"pre_submission_disclosure":{
            "active":True,
            "blocked_at":"target_design_packages",
            "pending_family_content":["M-104:HEATING"],
        }},
        "composition":{"manifest":[{"code":"M-104","old_sheet":"M-04","family":"HEATING"}]},
    }


def test_exact_file_gate_resolves_disclosed_public_and_internal_board_identity():
    answers={"_pre_submission_authority":{
        "blocked_at":"target_design_packages","blockers":["TARGET_DESIGN_PACKAGES_MISSING"],
    }}
    assert _pending_equipment_boards(_report(),answers)=={("m-104","HEATING"),("m-04","HEATING")}


def test_exact_file_gate_never_suppresses_final_or_unrelated_failure():
    assert _pending_equipment_boards(_report(),{})==set()
    report=_report();report["semantic_qa"]["pre_submission_disclosure"]["active"]=False
    assert _pending_equipment_boards(report,{"_pre_submission_authority":{
        "blocked_at":"target_design_packages","blockers":["UNRELATED_INPUT"],
    }})==set()


def test_exact_file_gate_uses_the_same_signed_disclosure_as_the_shell():
    answers={"_pre_submission_authority":{
        "blocked_at":"target_design_packages","blockers":["EQUIPMENT_SELECTION_EVIDENCE_REQUIRED"],
    }}
    assert _pending_equipment_boards(_report(),answers)=={("m-104","HEATING"),("m-04","HEATING")}
