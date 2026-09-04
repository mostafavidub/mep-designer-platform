from app.mechanical_basis_contract import (
    canonical_city, canonical_cooling_system, canonical_shaft_strategy,
    normalize_answers, numeric, persisted_answer_is_valid, shaft_approval,
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


def test_cooling_contract_accepts_only_explicit_wall_split():
    for value in ('اسپلیت دیواری', 'کولر گازی دیواری', 'wall_mounted_split_ac'):
        assert canonical_cooling_system({'cooling': value}) == 'wall_mounted_split_ac'
    for value in ('اسپلیت یا داکت‌اسپلیت', 'داکت اسپلیت', 'VRF/VRV', 'چیلر و فن‌کویل', 'کولر آبی'):
        assert canonical_cooling_system({'cooling': value}) is None
        assert not persisted_answer_is_valid({'cooling': value}, 'cooling_system')


def test_normalization_persists_the_same_cooling_authority_used_by_cad():
    answers = normalize_answers({}, answer_key='cooling_system', raw_answer='اسپلیت دیواری')
    assert answers['cooling_system'] == 'wall_mounted_split_ac'
    assert persisted_answer_is_valid(answers, 'cooling_system')
