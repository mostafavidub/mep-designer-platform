from app.main_auto import build_unified_questionnaire


def analysis():
    return {"files": [{"texts": [], "text_labels": []}]}


def test_positive_gas_requests_pressure_and_exact_density_once():
    _auto, _answers, questions = build_unified_questionnaire(
        analysis(), "mechanical", {"gas": "گاز برای پکیج و اجاق هر واحد"}
    )
    keys = [key for key, _prompt in questions]
    assert keys.count("gas_pressure") == 1
    assert keys.count("gas_relative_density") == 1


def test_rulebook_numeric_and_diameter_answers_survive_reanalysis():
    supplied = {
        "gas": "گاز برای پکیج",
        "gas_pressure": "20",
        "gas_relative_density": "0.65",
        "max_duct_velocity_m_s": "6",
        "candidate_round_duct_diameters_mm": "160,200,250",
    }
    _auto, answers, questions = build_unified_questionnaire(analysis(), "mechanical", supplied)
    keys = {key for key, _prompt in questions}
    assert answers["gas_relative_density"] == "0.65"
    assert answers["candidate_round_duct_diameters_mm"] == "160,200,250"
    assert {
        "gas_relative_density",
        "max_duct_velocity_m_s",
        "candidate_round_duct_diameters_mm",
    }.isdisjoint(keys)
