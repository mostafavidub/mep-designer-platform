import unittest
from types import SimpleNamespace

from app import electrical_drawing_set
from app.discipline_workflow_dispatcher import required_basis_questions
from app.electrical_execution_score import score
from app.electrical_rulebook import validate_rulebook
from app.electrical_basis_contract import normalize_answers


def project(answers=None, analysis=None):
    return SimpleNamespace(name='Panel Electrical', answers=dict(answers or {}), analysis=dict(analysis or {}), questions=[], current_question=0, status='ready_to_design', last_error='')


def complete_answers():
    return normalize_answers({
        'discipline':'electrical', 'location':'تهران', 'supply':'واحدها تک‌فاز و مشاعات سه‌فاز',
        'earthing':'ارت فونداسیون', 'main_panel':'اجازه پیشنهاد محل مناسب را دارید',
        'dedicated_load_schedule':'ندارد', 'fire_alarm_requirement':'خارج از محدوده این پروژه',
        'low_current_systems':'خارج از محدوده', 'lighting_design_basis':'Rule Book و استاندارد مصوب پروژه',
        'codes':'ضابطه مصوب پروژه', 'heights':'ارتفاع و سقف کاذب مطابق پلان معماری است',
        'emergency':'نیاز نداریم',
    })


class ElectricalPanelParityTests(unittest.TestCase):
    def test_panel_dispatcher_asks_electrical_not_mechanical_basis(self):
        p = project({'discipline':'electrical'}, {'architectural_auto': {'levels':[{'name':'همکف'}]}})
        missing = required_basis_questions(p)
        self.assertIn('supply_configuration', missing)
        self.assertIn('earthing_system', missing)
        self.assertNotIn('water_inlet_pressure', missing)

    def test_complete_panel_preflight_persists_approved_manifest(self):
        p = project(complete_answers(), {'architectural_auto': {'levels':[{'name':'همکف'}], 'room_counts':{'living':1}}})
        self.assertEqual(required_basis_questions(p), [])
        drawing = p.analysis.get('drawing_set') or {}
        self.assertTrue(electrical_drawing_set.approved_manifest_is_valid(drawing), drawing)
        self.assertGreaterEqual(len(drawing['approved_manifest']), 6)

    def test_manifest_is_project_driven(self):
        one = project(complete_answers(), {'architectural_auto': {'level_profiles':[{'name':'همکف','roof':False,'recognized_room_labels':2,'room_counts':{'living':1}}]}})
        two = project(complete_answers(), {'architectural_auto': {'level_profiles':[{'name':'همکف','roof':False,'recognized_room_labels':2,'room_counts':{'living':1}}, {'name':'طبقه اول','roof':False,'recognized_room_labels':2,'room_counts':{'living':1}}]}})
        self.assertLess(len(electrical_drawing_set.build_manifest(one)), len(electrical_drawing_set.build_manifest(two)))
        self.assertTrue(any(row['family']=='RISER' for row in electrical_drawing_set.build_manifest(two)))

    def test_execution_score_never_overrides_hard_blocker(self):
        gates = {}
        from app.electrical_execution_score import CATEGORY_GATES
        for names in CATEGORY_GATES.values():
            for name in names:
                gates[name] = {'status':'PASS'}
        result = score(gates)
        self.assertEqual(result['score'], 100.0)
        self.assertTrue(result['execution_ready'])
        gates['FINAL_FILE_REOPEN'] = {'status':'FAIL'}
        result = score(gates)
        self.assertGreater(result['score'], 80)
        self.assertFalse(result['execution_ready'])
        self.assertIn('FINAL_FILE_REOPEN', result['hard_blockers'])

    def test_rulebook_contains_no_project_fact_defaults(self):
        self.assertEqual(validate_rulebook()['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
