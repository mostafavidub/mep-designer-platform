from cad_engine.mechanical_cad_shell import _effective_pre_submission, _pre_submission_pending_boards, _release_input_errors


def _report(family="EXHAUST", enrichment="exhaust_cfm", status="INPUT_REQUIRED"):
    return {"enrichment":{enrichment:{"status":status}}, "authority":{"design_basis":{"status":"PASS"}},
            "pipeline_qa":{"status":"PASS"}, "engineering_acceptance":{"status":"PASS"},
            "semantic_qa":{"pre_submission_disclosure":{"pending_family_content":[f"M-1:{family}"]}}}


def test_disclosed_target_package_exhaust_pending_is_not_a_release_input_error():
    assert _release_input_errors(_report(), {"blocked_at":"target_design_packages"}) == []


def test_final_or_unrelated_blocker_still_rejects_pending_enrichment():
    assert _release_input_errors(_report(), None) == ["exhaust_cfm:INPUT_REQUIRED"]
    assert _release_input_errors(_report(), {"blocked_at":"manufacturer"}) == ["exhaust_cfm:INPUT_REQUIRED"]


def test_fail_status_is_never_disclosed_as_pre_submission_pending():
    assert _release_input_errors(_report(status="FAIL"), {"blocked_at":"target_design_packages"}) == ["exhaust_cfm:FAIL"]


def test_unrelated_family_pending_cannot_suppress_enrichment_error():
    assert _release_input_errors(_report(family="HEATING"), {"blocked_at":"target_design_packages"}) == ["exhaust_cfm:INPUT_REQUIRED"]


def test_pending_equipment_board_scope_requires_exact_target_package_disclosure():
    report={"semantic_qa":{"pre_submission_disclosure":{"pending_family_content":["M-04:HEATING"]}}}
    assert _pre_submission_pending_boards(report,{"blocked_at":"target_design_packages"}) == {("m-04","HEATING")}
    assert _pre_submission_pending_boards(report,{"blocked_at":"manufacturer"}) == set()
    assert _pre_submission_pending_boards(report,None) == set()


def test_pending_equipment_board_scope_maps_public_code_to_internal_board():
    report={
        "semantic_qa":{"pre_submission_disclosure":{"pending_family_content":["M-104:HEATING"]}},
        "composition":{"manifest":[{"code":"M-104","old_sheet":"M-04","family":"HEATING"}]},
    }
    assert _pre_submission_pending_boards(report,{"blocked_at":"target_design_packages"}) == {
        ("m-104","HEATING"),("m-04","HEATING"),
    }


def test_pending_gas_schedule_record_maps_to_internal_equipment_board():
    report={
        "semantic_qa":{"pre_submission_disclosure":{"pending_family_content":[]}},
        "composition":{"manifest":[{"code":"M-141","old_sheet":"M-05","family":"GAS"}]},
        "enrichment":{"gas_table":{"status":"PASS","records":[
            {"sheet":"M-141","status":"INPUT_REQUIRED"},
        ]}},
    }
    assert _pre_submission_pending_boards(report,{"blocked_at":"target_design_packages"}) == {
        ("m-141","GAS"),("m-05","GAS"),
    }
    report["enrichment"]["gas_table"]["records"][0]["status"]="FAIL"
    assert _pre_submission_pending_boards(report,{"blocked_at":"target_design_packages"}) == set()


def test_shell_recovers_exact_target_package_state_from_engine_evidence():
    report={
        "pipeline_qa":{"status":"INPUT_REQUIRED","errors":["TARGET_DESIGN_PACKAGES_MISSING"]},
        "engineering_acceptance":{"status":"FAIL","errors":["TARGET_DESIGN_PACKAGES_MISSING"]},
    }
    effective=_effective_pre_submission(report,None)
    assert effective["blocked_at"]=="target_design_packages"
    report["pipeline_qa"]["errors"].append("OTHER")
    assert _effective_pre_submission(report,None) is None
