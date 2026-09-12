from copy import deepcopy

import pytest

from app.design_basis_questionnaire_gate import CONTROL_WEIGHTS, evaluate_questionnaire_design_basis


def valid_context():
    context={
        "architecture_facts":{"source_sha256":"a"*64,"levels":["L1"],"spaces":["R1"],"areas":{"R1":20},
                              "equipment":[],"roof":True,"shafts":["SH1"],"wet_spaces":["R1"]},
        "answer_records":[{"key":"city","value":"تهران","source":"USER"}],
        "required_systems":["water","gas"],"system_scope":{"water":True,"gas":False},
        "question_applicability":{"status":"PASS","irrelevant_questions":[],"missing_questions":[]},
        "prior_answer_reuse":[{"key":"city","source_conversation_id":"C1","source_revision":"R1",
                               "verified":True,"target_scope":"ALL_PROJECTS_EXPLICIT","owner_authorized":True}],
        "normalization_qa":{"status":"PASS","unknown_terms":[],"noncanonical_keys":[]},
        "required_numeric_keys":["rainfall"],
        "numeric_inputs":[{"key":"rainfall","value":80,"unit":"mm/h","range_status":"PASS"}],
        "climate_basis":{"city":"تهران","elevation_m":1200,"summer_design":40,"winter_design":-5,
                         "rainfall_intensity":80,"water_pressure":2.5,"source":"authority","source_revision":"2026"},
        "system_design_basis":{"water":{"method":"fixture-unit","simultaneity":0.7,"velocity_limit":2,
            "pressure_drop_limit":20,"material":"PPR","insulation":"13mm","code_source":"INBR-16"}},
        "required_equipment_preference_keys":["cooling"],"equipment_preferences":{"cooling":"split"},
        "required_regulatory_keys":["occupancy","units"],"regulatory_facts":{"occupancy":"residential","units":1},
        "architecture_consistency_qa":{"status":"PASS","contradictions":[]},
        "dependency_qa":{"status":"PASS","invalid_activated":[],"missing_activated":[]},
        "basis_summary":{"status":"APPROVED","rendered_text":"Basis summary","approved_by":"owner","approved_at":"2026-09-12"},
        "persistence_qa":{"status":"PASS","roundtrip_mismatches":[],"destructive_test_failures":[]},
        "release_decision":{"status":"PASS","open_questions":[],"hidden_assumptions":[],"contradictions":[]},
    }
    probe=evaluate_questionnaire_design_basis(context)
    context["locked_revision"]={"revision_id":"DB-1","architecture_sha256":"a"*64,"rules_revision":"5.1",
                                "approved_at":"2026-09-12","content_hash":probe["expected_content_hash"],"mutated":False}
    return context


def test_all_eighteen_questionnaire_controls_total_100_and_release():
    result=evaluate_questionnaire_design_basis(valid_context())
    assert len(CONTROL_WEIGHTS)==18 and sum(CONTROL_WEIGHTS.values())==100
    assert result["status"]=="PASS" and result["score"]==100 and result["release_allowed"] is True


def test_missing_fact_is_input_required_and_never_guessed():
    context=valid_context(); del context["architecture_facts"]["roof"]
    result=evaluate_questionnaire_design_basis(context)
    assert result["status"] in {"INPUT_REQUIRED","FAIL"} and result["release_allowed"] is False
    assert any("ARCHITECTURE_FACT:roof" in x for x in result["missing_inputs"])


@pytest.mark.parametrize("mutation,error",[
    (lambda c:c["answer_records"].append({"key":"x","source":"MECHANICAL_REFERENCE"}),"MECHANICAL_REFERENCE_INPUT_FORBIDDEN"),
    (lambda c:c["prior_answer_reuse"][0].update({"owner_authorized":False}),"CROSS_PROJECT_REUSE_NOT_AUTHORIZED"),
    (lambda c:c["numeric_inputs"][0].update({"unit":None}),"INVALID_NUMERIC_INPUT:rainfall"),
    (lambda c:c["architecture_consistency_qa"].update({"contradictions":["levels"]}),"ARCHITECTURE_ANSWER_CONTRADICTION"),
    (lambda c:c["dependency_qa"].update({"invalid_activated":["chiller"]}),"QUESTION_DEPENDENCY_NOT_PASS"),
    (lambda c:c["locked_revision"].update({"mutated":True}),"DESIGN_BASIS_LOCK_IDENTITY_FAILED"),
    (lambda c:c["release_decision"].update({"hidden_assumptions":["pressure"]}),"DESIGN_BASIS_RELEASE_NOT_PASS"),
])
def test_ambiguity_reference_reuse_units_dependency_and_tamper_fail_closed(mutation,error):
    context=valid_context(); mutation(context); result=evaluate_questionnaire_design_basis(context)
    assert result["status"]=="FAIL" and result["release_allowed"] is False and error in result["errors"]


def test_active_system_requires_complete_engineering_basis():
    context=valid_context(); del context["system_design_basis"]["water"]["material"]
    result=evaluate_questionnaire_design_basis(context)
    assert result["status"] in {"INPUT_REQUIRED","FAIL"}
    assert any("SYSTEM_BASIS:water:material" in x for x in result["missing_inputs"])


def test_content_change_after_approval_invalidates_hash():
    context=valid_context(); context["climate_basis"]["rainfall_intensity"]=90
    result=evaluate_questionnaire_design_basis(context)
    assert "DESIGN_BASIS_LOCK_IDENTITY_FAILED" in result["errors"]
