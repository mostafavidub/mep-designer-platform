import unittest
from types import SimpleNamespace

from app.mechanical_workflow import (
    build_scope, create_proposal, is_approved, required_basis_questions,
    ensure_required_basis_questions, REQUIRED_BASIS_QUESTION_SPECS,
)


class MechanicalWorkflowTests(unittest.TestCase):
    def project(self, answers=None, analysis=None):
        return SimpleNamespace(
            answers={'discipline': 'mechanical', **(answers or {})},
            analysis=analysis or {
                'discipline': 'mechanical',
                'architectural_auto': {
                    'level_profiles': [
                        {'name':'همکف','conditioned_candidate':True,'wet_fixture_candidate':True,'sanitary_candidate':True,'ventilation_candidate':True,'gas_candidate':True,'roof':False},
                        {'name':'بام','conditioned_candidate':False,'wet_fixture_candidate':False,'sanitary_candidate':False,'ventilation_candidate':False,'gas_candidate':False,'roof':True},
                    ],
                    'roof_scope_reliable': True,
                },
                'files': [{'file': 'plans.dxf', 'texts': ['همکف پلان معماری', 'بام پلان معماری']}],
            },
            status='ready_to_design', questions=[], current_question=0,
        )

    def test_scope_detects_levels_and_vertical_system(self):
        p = self.project(); scope = build_scope(p)
        self.assertEqual(scope['all_levels'], ['همکف', 'بام']); self.assertTrue(scope['roof_exists'])

    def test_negative_gas_removes_gas_plans(self):
        p = self.project({'gas': 'خیر، ساختمان گاز ندارد'}); self.assertEqual(build_scope(p)['gas_consumer_levels'], [])

    def test_explicit_tank_or_booster_enters_approved_water_scope(self):
        p = self.project({'gas':'خیر','water_source':'کنتور شهری + مخزن ۵۰۰ لیتری + بوسترپمپ'})
        scope = build_scope(p)
        self.assertTrue(scope['central_water_equipment'])
        proposal = create_proposal(p)
        water_types = {x.get('drawing_type') for x in proposal['drawing_manifest']['sheets'] if x.get('family') == 'water_supply'}
        self.assertIn('equipment_plan', water_types)
        self.assertIn('calculation_sheet', water_types)

    def test_direct_city_water_does_not_invent_central_equipment(self):
        p = self.project({'gas':'خیر','water_source':'انشعاب مستقیم آب شهری بدون مخزن و بدون پمپ'})
        self.assertFalse(build_scope(p)['central_water_equipment'])

    def test_explicit_hot_water_return_enters_scope(self):
        p = self.project({'hot_water_system':'پکیج مرکزی با خط برگشت آب گرم'})
        self.assertTrue(build_scope(p)['hot_water_return_required'])
        p.answers['hot_water_system'] = 'پکیج بدون برگشت'
        self.assertFalse(build_scope(p)['hot_water_return_required'])

    def test_preflight_requires_project_water_rain_and_gas_values(self):
        p = self.project({'gas':'تأیید'}); missing = required_basis_questions(p)
        self.assertEqual(missing, ['water_inlet_pressure','rainfall_intensity','gas_pressure']); self.assertTrue(ensure_required_basis_questions(p)); self.assertEqual(p.status, 'asking')
        self.assertEqual([q['key'] for q in p.questions], missing); self.assertTrue(all(q['input_type']=='radio' and len(q['options'])>=4 for q in p.questions)); self.assertEqual((p.analysis or {})['basis_preflight']['status'], 'INPUT_REQUIRED')

    def test_preflight_does_not_accept_unknown_as_numeric_fact(self):
        p = self.project({'gas':'خیر','water_inlet_pressure':'نامشخص','rainfall_intensity':'unknown'}); self.assertEqual(required_basis_questions(p), ['water_inlet_pressure','rainfall_intensity'])

    def test_preflight_passes_only_after_explicit_numeric_values(self):
        p = self.project({'gas':'تأیید','water_inlet_pressure':'2.8 bar','rainfall_intensity':'95 mm/h','gas_pressure':'21 mbar'})
        self.assertEqual(required_basis_questions(p), []); self.assertFalse(ensure_required_basis_questions(p))

    def test_basis_question_options_are_suggestions_not_defaults(self):
        for key, spec in REQUIRED_BASIS_QUESTION_SPECS.items():
            self.assertGreaterEqual(len(spec['options']), 4); self.assertNotIn('default', spec['question'].lower()); self.assertNotIn('خودکار', spec['question'])

    def test_create_proposal_moves_to_review_and_requires_approval(self):
        p = self.project({'gas':'خیر','water_inlet_pressure':'2.5 bar','rainfall_intensity':'90 mm/h'}); proposal = create_proposal(p)
        self.assertEqual(p.status, 'drawing_set_review'); self.assertFalse(proposal['approved']); self.assertTrue(proposal['approval_required']); self.assertIn('drawing_set', p.analysis); self.assertFalse(is_approved(p))

    def test_missing_basis_invalidates_even_previously_approved_drawing_set(self):
        p = self.project({'gas':'خیر','water_inlet_pressure':'2.5 bar','rainfall_intensity':'90 mm/h'})
        proposal = create_proposal(p)
        proposal['approved'] = True
        p.analysis['drawing_set'] = proposal
        self.assertEqual(required_basis_questions(p), [])
        p.answers['water_inlet_pressure'] = 'نامشخص'
        self.assertIn('water_inlet_pressure', required_basis_questions(p))
        self.assertFalse(is_approved(p))


if __name__ == '__main__': unittest.main()
