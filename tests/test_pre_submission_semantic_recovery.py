import ezdxf

from cad_engine.mechanical_cad_base import (
    _effective_target_package_pre_submission,
    _materialize_target_package_disclosures,
    qa_semantic_sheet_content,
)
from cad_engine.mechanical_design_core import _clip_polyline_to_rect, qa_authority_dxf
from cad_engine.mechanical_cad_shell import _release_input_errors


def _pending_heating_sheet(tmp_path):
    path = tmp_path / "pending-heating.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.add("ENGITOOLS-M-NOTES")
    note = msp.add_mtext(
        "APPROVED SERVICE PLAN — NO RELIABLE TERMINAL OR BRANCH ENDPOINT DETECTED",
        dxfattribs={"layer": "ENGITOOLS-M-NOTES", "char_height": 0.08},
    )
    note.dxf.insert = (1, 8)
    doc.saveas(path)
    compose = {
        "boards": {"B1": {"bounds": [0, 0, 20, 10]}},
        "manifest": [{"old_sheet": "B1", "code": "M-H-01", "family": "HEATING", "level": "GROUND"}],
    }
    return path, compose


def test_final_semantic_qa_still_blocks_missing_family_content(tmp_path):
    path, compose = _pending_heating_sheet(tmp_path)
    result = qa_semantic_sheet_content(path, compose)
    assert result["status"] == "FAIL"
    assert "missing_family_specific_content" in result["errors"]


def test_target_package_pre_submission_is_deliverable_with_explicit_disclosure(tmp_path):
    path, compose = _pending_heating_sheet(tmp_path)
    doc=ezdxf.readfile(path)
    result=_materialize_target_package_disclosures(doc,doc.modelspace(),compose,{
        "blocked_at":"target_design_packages","blockers":["TARGET_DESIGN_PACKAGES_MISSING"]
    })
    assert result["status"] == "PASS"
    doc.saveas(path)
    result = qa_semantic_sheet_content(
        path, compose, {"blocked_at": "target_design_packages", "blockers": ["TARGET_DESIGN_PACKAGES_MISSING"]}
    )
    assert result["status"] == "PASS"
    assert result["pre_submission_disclosure"]["active"] is True
    assert result["pre_submission_disclosure"]["pending_family_content"] == ["M-H-01:HEATING"]
    assert "pre_submission_family_pending:M-H-01:HEATING" in result["warnings"]


def test_exact_target_package_pipeline_input_is_not_a_release_error():
    report = {
        "pipeline_qa": {"status": "INPUT_REQUIRED", "errors": ["TARGET_DESIGN_PACKAGES_MISSING"]},
        "engineering_acceptance": {"status": "PASS"},
        "enrichment": {}, "authority": {"design_basis": {"status": "PASS"}},
    }
    pre_submission = {"blocked_at": "target_design_packages",
                      "blockers": ["TARGET_DESIGN_PACKAGES_MISSING"]}
    assert _release_input_errors(report, pre_submission) == []


def test_exact_target_package_engineering_acceptance_input_is_disclosed_not_failed():
    report = {
        "pipeline_qa": {"status": "PASS", "errors": []},
        "engineering_acceptance": {
            "status": "INPUT_REQUIRED",
            "errors": ["TARGET_DESIGN_PACKAGES_MISSING"],
        },
        "enrichment": {},
        "authority": {"design_basis": {"status": "PASS"}},
    }
    pre_submission = {
        "blocked_at": "target_design_packages",
        "blockers": ["TARGET_DESIGN_PACKAGES_MISSING"],
    }
    assert _release_input_errors(report, pre_submission) == []
    report["engineering_acceptance"]["status"] = "FAIL"
    assert _release_input_errors(report, pre_submission) == [
        "engineering_acceptance:TARGET_DESIGN_PACKAGES_MISSING"
    ]


def test_exact_engine_gate_evidence_recovers_missing_transient_pre_submission_key():
    result=_effective_target_package_pre_submission(
        None,
        {"status":"INPUT_REQUIRED","errors":["TARGET_DESIGN_PACKAGES_MISSING"]},
        {"status":"INPUT_REQUIRED","errors":["TARGET_DESIGN_PACKAGES_MISSING"]},
    )
    assert result["blocked_at"]=="target_design_packages"
    assert result["source"]=="EXACT_ENGINE_GATE_EVIDENCE"
    result=_effective_target_package_pre_submission(
        None,
        {"status":"PASS","errors":[]},
        {"status":"PRE_SUBMISSION","errors":["TARGET_DESIGN_PACKAGES_MISSING"]},
    )
    assert result["blocked_at"]=="target_design_packages"
    assert _effective_target_package_pre_submission(
        None,
        {"status":"INPUT_REQUIRED","errors":["TARGET_DESIGN_PACKAGES_MISSING","OTHER"]},
        {"status":"PASS","errors":[]},
    ) is None


def test_pending_gas_table_is_deliverable_only_as_explicit_target_package_pre_submission():
    report = {
        "pipeline_qa": {"status": "INPUT_REQUIRED", "errors": ["TARGET_DESIGN_PACKAGES_MISSING"]},
        "engineering_acceptance": {"status": "PASS"},
        "enrichment": {"gas_table": {"status": "INPUT_REQUIRED"}},
        "authority": {"design_basis": {"status": "PASS"}},
        # A routed GAS plan can be semantically populated while its schedule is
        # still pending appliance loads.  The artifact-wide Pre-Submission
        # disclosure, not a false missing-family flag, carries that limitation.
        "semantic_qa": {"pre_submission_disclosure": {"pending_family_content": []}},
    }
    pre_submission = {
        "blocked_at": "target_design_packages",
        "blockers": ["TARGET_DESIGN_PACKAGES_MISSING"],
    }
    assert _release_input_errors(report, pre_submission) == []
    assert _release_input_errors(report, {"blocked_at": "manufacturer"}) == [
        "gas_table:INPUT_REQUIRED",
        "pipeline:TARGET_DESIGN_PACKAGES_MISSING",
    ]


def test_pending_gas_table_record_is_disclosed_without_weakening_failures():
    report = {
        "pipeline_qa": {"status": "INPUT_REQUIRED", "errors": ["TARGET_DESIGN_PACKAGES_MISSING"]},
        "engineering_acceptance": {"status": "PASS"},
        "enrichment": {
            "gas_table": {
                "status": "PASS",
                "records": [{"sheet": "M-141", "status": "INPUT_REQUIRED"}],
            }
        },
        "authority": {"design_basis": {"status": "PASS"}},
        "semantic_qa": {"pre_submission_disclosure": {"pending_family_content": []}},
    }
    pre_submission = {"blocked_at": "target_design_packages"}
    assert _release_input_errors(report, pre_submission) == []
    report["enrichment"]["gas_table"]["records"][0]["status"] = "FAIL"
    assert _release_input_errors(report, pre_submission) == ["gas_table:M-141:FAIL"]


def test_unrelated_pre_submission_blocker_cannot_bypass_semantic_qa(tmp_path):
    path, compose = _pending_heating_sheet(tmp_path)
    result = qa_semantic_sheet_content(path, compose, {"blocked_at": "manufacturer"})
    assert result["status"] == "FAIL"


def test_target_blocker_without_exact_missing_package_reason_cannot_bypass_semantic_qa(tmp_path):
    path, compose = _pending_heating_sheet(tmp_path)
    result = qa_semantic_sheet_content(path, compose, {
        "blocked_at": "target_design_packages", "blockers": ["UNRELATED_INPUT"]
    })
    assert result["status"] == "FAIL"


def test_blank_sheet_never_passes_even_for_target_package_pre_submission(tmp_path):
    path = tmp_path / "blank.dxf"
    ezdxf.new("R2010").saveas(path)
    compose = {
        "boards": {"B1": {"bounds": [0, 0, 20, 10]}},
        "manifest": [{"old_sheet": "B1", "code": "M-H-01", "family": "HEATING", "level": "GROUND"}],
    }
    result = qa_semantic_sheet_content(path, compose, {"blocked_at": "target_design_packages"})
    assert result["status"] == "FAIL"
    assert "blank_sheet_content" in result["errors"]


def test_titleblock_content_without_disclosure_cannot_bypass_semantic_qa(tmp_path):
    path = tmp_path / "title-only.dxf"
    doc = ezdxf.new("R2010")
    doc.layers.add("ENGITOOLS-SHEET-TITLE")
    text = doc.modelspace().add_mtext("M-H-01 HEATING PLAN", dxfattribs={"layer": "ENGITOOLS-SHEET-TITLE"})
    text.dxf.insert = (1, 8)
    doc.saveas(path)
    compose = {
        "boards": {"B1": {"bounds": [0, 0, 20, 10]}},
        "manifest": [{"old_sheet": "B1", "code": "M-H-01", "family": "HEATING", "level": "GROUND"}],
    }
    result = qa_semantic_sheet_content(path, compose, {"blocked_at": "target_design_packages"})
    assert result["status"] == "FAIL"
    assert result["pre_submission_disclosure"]["active"] is False


def test_titleblock_overlap_is_attributed_to_exact_sheet_and_layer(tmp_path):
    path=tmp_path/"overlap.dxf";doc=ezdxf.new("R2010");doc.layers.add("ENGITOOLS-M-HEAT-FLOW")
    doc.modelspace().add_line((2,1),(5,1),dxfattribs={"layer":"ENGITOOLS-M-HEAT-FLOW"});doc.saveas(path)
    compose={"boards":{"B1":{"sheet":"B1","code":"M-H-01","family":"HEATING","level":"GROUND","title":"H","bounds":[0,0,20,10],"plan_area":[1,3,19,9],"title_area":[1,.4,19,2.4],"subtitle_area":[1,2.4,19,2.8]}},"copy_failures":[],"north":{"M-H-01":True}}
    result=qa_authority_dxf(path,compose)
    assert result["status"]=="FAIL"
    assert result["metrics"]["titleblock_overlap_by_sheet"]=={"M-H-01":1}
    assert result["metrics"]["titleblock_overlap_layers"]=={"M-H-01":{"ENGITOOLS-M-HEAT-FLOW":1}}


def test_route_overlay_clips_crossing_segments_and_omits_titleblock_segments():
    rect=(1,3,19,9)
    assert _clip_polyline_to_rect([(5,1),(5,5)],rect)==[((5.0,3.02),(5.0,5.0))]
    assert _clip_polyline_to_rect([(2,1),(18,1)],rect)==[]
    for piece in _clip_polyline_to_rect([(-5,6),(25,6)],rect):
        assert all(1<point[0]<19 and 3<point[1]<9 for point in piece)
