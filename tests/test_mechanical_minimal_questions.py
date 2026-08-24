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
        self.assertEqual(answers['mechanical_rulebook_version'], '1.9')
        self.assertEqual(answers['heights'], '3.20 m floor-to-floor; 0.40 m false ceiling in wet/service zones')
        self.assertIn('2.5 bar', answers['water_inlet_pressure'])
        self.assertIn('booster pump', answers['water_source'])
        self.assertEqual(answers['questionnaire_evidence_version'], '1.0')

        analysis = {'files': [{'texts': ['پلان معماری همکف', 'مسکونی']}]}
        keys = [key for key, _ in dynamic_questions(analysis, 'mechanical', auto)]
        for forbidden in ('water_design_basis', 'sanitary_design_basis'):
            self.assertNotIn(forbidden, keys)
        for required in (
            'heights', 'heating', 'cooling', 'water_inlet_pressure',
            'water_source', 'water_service_connection', 'sanitary_outlet',
            'mechanical_shaft_route', 'equipment_schedule', 'ventilation_design_basis',
            'hot_water_system', 'local_mechanical_code',
        ):
            self.assertIn(required, keys)
        self.assertIn('fixture_schedule', keys)
        prompts = dict(dynamic_questions(analysis, 'mechanical', auto))
        self.assertIn('پاسخ کوتاه', prompts['gas'])
        self.assertIn('پیشنهاد خودکار تجهیزات', prompts['fixture_schedule'])

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

    def test_complete_architecture_evidence_avoids_redundant_questions(self):
        auto = self.auto(
            fixture_blocks_detected=6,
            fixture_counts={'toilet': 2, 'sink': 2, 'bath': 2},
            gas_absence_inferred=True,
            water_inlet_pressure_inferred='3 bar',
            detected_shafts=1,
        )
        text = (
            'تهران مسکونی ارتفاع 3.2 متر سقف کاذب 40 سانتی متر بدون گاز '
            'پکیج 24 kW رادیاتور اسپلیت 18000 BTU کنتور آب و مخزن و بوستر؛ '
            'محل انشعاب آب ضلع جنوبی؛ فاضلاب شهری؛ شفت مکانیکی کنار پله؛ '
            'تهویه 6 ACH و تخلیه بالای بام و هوای جبرانی؛ برگشت آب گرم؛ '
            'ضوابط نظام مهندسی مبحث 14'
        )
        keys = [key for key, _ in dynamic_questions({'files': [{'texts': [text]}]}, 'mechanical', auto)]
        self.assertEqual(keys, [])


if __name__ == '__main__':
    unittest.main()
