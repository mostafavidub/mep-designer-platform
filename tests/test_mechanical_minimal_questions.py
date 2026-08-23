import unittest

from app.auto_inference import canonical_auto_answers, dynamic_questions


class MechanicalMinimalQuestionTests(unittest.TestCase):
    def auto(self, **overrides):
        value = {
            'room_counts': {'kitchen': 1, 'bath': 2, 'toilet': 2, 'bedroom': 3, 'living': 1},
            'occupancy_inferred': 'residential',
            'estimated_water_flow_lps': .7,
            'target_water_velocity_mps': 1.5,
            'estimated_cooling_load_kw': 15,
            'estimated_heating_load_kw': 12,
            'detected_parking': 0,
            'fixture_blocks_detected': 0,
            'levels': [{'name': 'همکف'}],
        }
        value.update(overrides)
        return value

    def test_rulebook_owns_material_coefficients_slopes_equipment_and_airflow(self):
        auto = self.auto()
        answers = canonical_auto_answers(auto, 'mechanical')
        self.assertIn('PPR', answers['water_design_basis'])
        self.assertIn('C=150', answers['water_design_basis'])
        self.assertIn('uPVC', answers['sanitary_design_basis'])
        self.assertIn('per room load', answers['equipment_schedule'])
        self.assertIn('m3/h', answers['ventilation_design_basis'])
        self.assertEqual(answers['mechanical_rulebook_version'], '1.4')

        analysis = {'files': [{'texts': ['پلان معماری همکف', 'مسکونی']}]}
        keys = [key for key, _ in dynamic_questions(analysis, 'mechanical', auto)]
        for forbidden in (
            'water_design_basis', 'sanitary_design_basis', 'equipment_schedule',
            'ventilation_design_basis', 'heating', 'cooling', 'water_source',
        ):
            self.assertNotIn(forbidden, keys)
        self.assertIn('water_inlet_pressure', keys)
        self.assertIn('fixture_schedule', keys)

    def test_fixture_question_is_skipped_when_architecture_has_real_blocks(self):
        auto = self.auto(fixture_blocks_detected=6, fixture_counts={'toilet': 2, 'sink': 2, 'bath': 2})
        analysis = {'files': [{'texts': ['تهران', 'ارتفاع طبقه 3.2 متر', 'فاضلاب شهری', '2.8 bar']}]}
        keys = [key for key, _ in dynamic_questions(analysis, 'mechanical', auto)]
        self.assertNotIn('fixture_schedule', keys)
        self.assertNotIn('water_inlet_pressure', keys)
        self.assertNotIn('sanitary_outlet', keys)

    def test_explicit_no_gas_in_architecture_prevents_gas_question(self):
        auto = self.auto(gas_absence_inferred=True)
        analysis = {'files': [{'texts': ['بدون گاز']}]}
        answers = canonical_auto_answers(auto, 'mechanical')
        keys = [key for key, _ in dynamic_questions(analysis, 'mechanical', auto)]
        self.assertNotIn('gas', keys)
        self.assertIn('ندارد', answers['gas'])


if __name__ == '__main__':
    unittest.main()
