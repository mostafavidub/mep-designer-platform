from app.mechanical_basis_contract import (
    canonical_city, canonical_shaft_strategy, normalize_answers, numeric, shaft_approval,
)


def test_persian_answers_are_canonicalized_with_provenance():
    answers = normalize_answers({
        'location': 'ایران، مشهد',
        'rainfall_intensity': '۹۵ mm/h',
    }, answer_key='mechanical_shaft_route', raw_answer='پیشنهاد نزدیک هسته فضاهای تر')
    assert canonical_city(answers) == 'مشهد'
    assert answers['city'] == 'مشهد'
    assert answers['rainfall_intensity_mm_h'] == 95
    assert answers['mechanical_shaft_route'] == 'propose_near_wet_core'
    assert shaft_approval(answers)['status'] == 'APPROVED'
    assert shaft_approval(answers)['source'] == 'explicit_user_answer'


def test_contract_accepts_city_alias_and_rejects_unknown_shaft_text():
    assert canonical_city({'city': 'تهران'}) == 'تهران'
    assert numeric('۱۱۰٫۵ mm/h') == 110.5
    assert canonical_shaft_strategy('یک جای خوب پیدا کن') is None
    assert shaft_approval({'mechanical_shaft_route': 'یک جای خوب پیدا کن'}) is None
