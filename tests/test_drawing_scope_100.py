import copy

import pytest

from app.mechanical_drawing_set import approve_drawing_set, predict_drawing_set
from cad_engine.mechanical_release_scope import CONTROL_WEIGHTS, evaluate_drawing_scope, scope_contract_is_valid


def scope(**overrides):
    occupied = ["Ground", "First", "Second"]
    value = {
        "all_levels": occupied + ["Roof"],
        "conditioned_levels": occupied,
        "heated_levels": occupied,
        "wet_fixture_levels": occupied,
        "sanitary_fixture_levels": occupied,
        "ventilation_required_levels": occupied,
        "gas_consumer_levels": occupied,
        "roof_exists": True,
        "roof_level_name": "Roof",
        "vertical_systems": True,
        "typical_groups": [],
        "level_types": {"Ground":"occupied", "First":"occupied", "Second":"occupied", "Roof":"roof"},
        "reference_inputs_used": False,
    }
    value.update(overrides)
    return value


def test_all_eighteen_scope_controls_are_required_and_score_exactly_100():
    proposal = predict_drawing_set(scope())
    qa = proposal["drawing_manifest"]["scope_contract"]
    assert qa["status"] == "PASS"
    assert qa["score"] == 100
    assert len(qa["controls"]) == 18
    assert sum(CONTROL_WEIGHTS.values()) == 100
    assert scope_contract_is_valid(proposal["drawing_manifest"])
    assert approve_drawing_set(proposal)["approved"] is True


def test_ambiguous_scope_fails_closed_and_cannot_be_approved():
    proposal = predict_drawing_set(scope(scope_ambiguities=["two equal-confidence Ground frames"]))
    qa = proposal["drawing_manifest"]["scope_contract"]
    assert qa["status"] == "FAIL"
    assert "ambiguity_fail_closed" in qa["failures"]
    with pytest.raises(ValueError):
        approve_drawing_set(proposal)


def test_missing_required_floor_and_unsupported_extra_system_are_detected():
    base = scope()
    proposal = predict_drawing_set(base)
    sheets = copy.deepcopy(proposal["deliverable_sheets"])
    sheets = [row for row in sheets if not (row["family"] == "heating" and row["drawing_type"] == "floor_plan" and "First" in row["levels"])]
    qa = evaluate_drawing_scope(base, sheets)
    assert "required_system_omission_zero" in qa["failures"]
    sheets.append({"family":"electrical", "code":"E-01", "drawing_type":"floor_plan", "levels":["Ground"], "special":False})
    qa = evaluate_drawing_scope(base, sheets)
    assert "unsupported_system_zero" in qa["failures"]


def test_special_sanitary_roof_sheet_is_not_misread_as_floor_system_coverage():
    single = scope(
        all_levels=["Typical", "Roof", "Penthouse Roof"],
        conditioned_levels=["Typical"],
        heated_levels=["Typical"],
        wet_fixture_levels=["Typical"],
        sanitary_fixture_levels=["Typical"],
        ventilation_required_levels=["Typical"],
        gas_consumer_levels=["Typical"],
        roof_exists=False,
        roof_level_name="Roof",
        vertical_systems=False,
        level_types={"Typical": "occupied", "Roof": "roof", "Penthouse Roof": "roof"},
    )
    proposal = predict_drawing_set(single)
    rain_detail = next(row for row in proposal["drawing_manifest"]["sheets"] if row["code"] == "M-S-RAIN")
    assert rain_detail["family"] == "sanitary_vent"
    assert rain_detail["drawing_type"] == "roof_plan"
    assert rain_detail["special"] is True
    qa = proposal["drawing_manifest"]["scope_contract"]
    assert qa["status"] == "PASS", qa
    assert "unsupported_system_zero" not in qa["failures"]


def test_typical_groups_must_be_explicit_disjoint_and_level_bound():
    bad = scope(typical_groups=[
        {"name":"Typical A", "levels":["First", "Second"]},
        {"name":"Typical B", "levels":["Second", "Missing"]},
    ])
    proposal = predict_drawing_set(bad)
    qa = proposal["drawing_manifest"]["scope_contract"]
    assert "typical_floor_evidence" in qa["failures"]


def test_reference_input_and_post_approval_tamper_never_pass():
    proposal = predict_drawing_set(scope(reference_inputs_used=True))
    assert "blind_reference_isolation" in proposal["drawing_manifest"]["scope_contract"]["failures"]
    clean = approve_drawing_set(predict_drawing_set(scope()))
    clean["drawing_manifest"]["sheets"][0]["levels"] = ["Invented"]
    with pytest.raises(ValueError):
        approve_drawing_set(clean)
