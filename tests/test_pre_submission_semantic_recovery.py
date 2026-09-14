import ezdxf

from cad_engine.mechanical_cad_base import qa_semantic_sheet_content


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
    result = qa_semantic_sheet_content(
        path, compose, {"blocked_at": "target_design_packages", "blockers": ["TARGET_DESIGN_PACKAGES_MISSING"]}
    )
    assert result["status"] == "PASS"
    assert result["pre_submission_disclosure"]["active"] is True
    assert result["pre_submission_disclosure"]["pending_family_content"] == ["M-H-01:HEATING"]
    assert "pre_submission_family_pending:M-H-01:HEATING" in result["warnings"]


def test_unrelated_pre_submission_blocker_cannot_bypass_semantic_qa(tmp_path):
    path, compose = _pending_heating_sheet(tmp_path)
    result = qa_semantic_sheet_content(path, compose, {"blocked_at": "manufacturer"})
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
