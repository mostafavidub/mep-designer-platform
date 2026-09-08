import unittest
from types import SimpleNamespace

from app.electrical_basis_contract import (
    CONTRACT_REVISION, canonical_supply, canonical_earthing, canonical_panel_strategy,
    normalize_answers, panel_location_approval, persisted_answer_is_valid,
)
from app.electrical_workflow import build_scope, required_basis_questions, reopen_basis_questions


def project(answers=None, analysis=None):
    return SimpleNamespace(
        name='Test Electrical', answers=dict(answers or {}), analysis=dict(analysis or {}),
        questions=[], current_question=0, status='ready_to_design', last_error=''
    )


class ElectricalBasisContractV19Tests(unittest.TestCase):
    def test_supply_is_canonical_but_not_invented(self):
        self.assertIsNone(canonical_supply(''))
        self.assertEqual(canonical_supply('واحدها تک‌فاز و مشاعات سه‌فاز')['configuration'], 'mixed_single_units_three_phase_common')
        normalized = normalize_answers({'discipline':'electrical', 'supply':'همه انشعاب‌ها سه‌فاز'})
        self.assertEqual(normalized['_electrical_basis_contract']['contract_revision'], CONTRACT_REVISION)
        self.assertEqual(normalized['supply_configuration']['configuration'], 'three_phase')

    def test_normalization_is_idempotent_for_retry_and_recovery(self):
        first = normalize_answers({
            'discipline':'electrical',
            'location':'تهران',
            'supply':'واحدها تک‌فاز و مشاعات سه‌فاز',
            'earthing':'ارت فونداسیون',
            'main_panel':'اجازه پیشنهاد محل مناسب را دارید',
        })
        second = normalize_answers(first)
        self.assertEqual(canonical_supply(second['supply_configuration'])['configuration'], 'mixed_single_units_three_phase_common')
        self.assertEqual(canonical_earthing(second['earthing_system']), 'foundation_earth')
        self.assertEqual(canonical_panel_strategy(second['service_panel_location']), 'proposal_authorized')
        self.assertTrue(persisted_answer_is_valid(second, 'supply_configuration'))
        self.assertTrue(persisted_answer_is_valid(second, 'earthing_system'))
        self.assertTrue(persisted_answer_is_valid(second, 'service_panel_location'))

    def test_panel_proposal_requires_recorded_approval(self):
        answers = normalize_answers({'main_panel':'اجازه پیشنهاد محل مناسب را دارید'})
        approval = panel_location_approval(answers)
        self.assertEqual(approval['status'], 'APPROVED')
        self.assertIn(approval['source'], {'explicit_user_answer','legacy_explicit_user_answer'})
        self.assertTrue(persisted_answer_is_valid(answers, 'service_panel_location'))

    def test_architecture_controls_scope_but_not_design_basis(self):
        p = project(
            {'discipline':'electrical'},
            {'architectural_auto': {
                'room_counts': {'kitchen':1, 'living':1, 'elevator':1},
                'detected_elevator':1,
                'level_profiles': [
                    {'name':'همکف','roof':False,'recognized_room_labels':3,'room_counts':{'kitchen':1,'living':1}},
                    {'name':'طبقه اول','roof':False,'recognized_room_labels':2,'room_counts':{'living':1}},
                ],
            }}
        )
        scope = build_scope(p)
        self.assertTrue(scope['elevator_power_required'])
        self.assertTrue(scope['vertical_systems'])
        missing = required_basis_questions(p)
        for key in ('city','supply_configuration','service_panel_location','earthing_system','dedicated_load_schedule','fire_alarm_requirement','low_current_systems','lighting_design_basis','local_electrical_code'):
            self.assertIn(key, missing)

    def test_complete_explicit_basis_removes_preflight_questions(self):
        answers = normalize_answers({
            'discipline':'electrical','location':'تهران','supply':'واحدها تک‌فاز و مشاعات سه‌فاز',
            'earthing':'ارت فونداسیون','main_panel':'محل در پلان مشخص شده است',
            'dedicated_load_schedule':'پمپ 2.2 kW سه فاز','fire_alarm_requirement':'خارج از محدوده این پروژه',
            'low_current_systems':'خارج از محدوده','lighting_design_basis':'Rule Book و استاندارد مصوب پروژه',
            'codes':'ضابطه مصوب پروژه','heights':'ارتفاع و سقف کاذب مطابق پلان معماری است',
        })
        p = project(answers, {'architectural_auto': {'room_counts': {'kitchen':1}, 'levels':[{'name':'همکف'}]}})
        self.assertEqual(required_basis_questions(p), [])
        p.answers = normalize_answers(p.answers)
        self.assertEqual(required_basis_questions(p), [])

    def test_late_failure_reopens_exact_questions(self):
        p = project({'discipline':'electrical','location':'تهران','supply':'همه واحدها تک‌فاز'}, {'architectural_auto':{}})
        self.assertTrue(reopen_basis_questions(p, ['supply_configuration','earthing_system','not-a-basis-key']))
        self.assertEqual(p.status, 'asking')
        keys = [q['key'] for q in p.questions]
        self.assertEqual(set(keys), {'supply_configuration','earthing_system'})


if __name__ == '__main__':
    unittest.main()
