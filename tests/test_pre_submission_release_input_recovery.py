from cad_engine.mechanical_cad_shell import _release_input_errors


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
