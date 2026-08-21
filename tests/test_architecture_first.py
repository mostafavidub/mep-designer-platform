import unittest

from app.auto_inference import infer_architecture_facts, canonical_auto_answers, dynamic_questions
from cad_engine import main_v5


class ArchitectureFirstTests(unittest.TestCase):
    def sample_analysis(self):
        return {
            'files': [{
                'file': 'floor.dxf',
                'insunits': 4,
                'geometry_width_m': 14.0,
                'geometry_height_m': 10.0,
                'geometry_area_m2': 140.0,
                'texts': ['آشپزخانه', 'اتاق خواب', 'اتاق خواب', 'پذیرایی', 'حمام', 'سرویس', 'شفت'],
            }]
        }

    def test_electrical_infers_numeric_engineering_inputs(self):
        analysis = self.sample_analysis()
        auto = infer_architecture_facts(analysis, 'electrical')
        answers = canonical_auto_answers(auto, 'electrical')
        self.assertGreater(float(answers['design_load_kw']), 0)
        self.assertGreater(float(answers['cable_length_m']), 0)
        self.assertEqual(float(answers['power_factor']), 0.9)
        self.assertEqual(float(answers['max_voltage_drop_pct']), 3.0)
        keys = [k for k, _ in dynamic_questions(analysis, 'electrical', auto)]
        self.assertNotIn('loads', keys)
        self.assertNotIn('cable_length_m', keys)
        self.assertNotIn('power_factor', keys)
        self.assertNotIn('max_voltage_drop_pct', keys)

    def test_mechanical_infers_flow_and_thermal_proxies(self):
        analysis = self.sample_analysis()
        auto = infer_architecture_facts(analysis, 'mechanical')
        answers = canonical_auto_answers(auto, 'mechanical')
        self.assertGreater(float(answers['design_water_flow_lps']), 0)
        self.assertGreater(float(answers['cooling_load_kw']), 0)
        self.assertGreater(float(answers['heating_load_kw']), 0)
        keys = [k for k, _ in dynamic_questions(analysis, 'mechanical', auto)]
        self.assertNotIn('water', keys)
        self.assertNotIn('design_water_flow_lps', keys)
        self.assertNotIn('cooling_load_kw', keys)
        self.assertNotIn('heating_load_kw', keys)

    def test_cad_electrical_calc_consumes_architecture_auto(self):
        a = {'architectural_auto': {
            'estimated_electrical_load_kw': 12.5,
            'estimated_cable_route_m': 25.0,
            'power_factor': 0.9,
            'max_voltage_drop_pct': 3.0,
        }}
        r = main_v5.electrical_calc(a)
        self.assertEqual(r['design_load_kw'], 12.5)
        self.assertIsNotNone(r['design_current_a'])
        self.assertIsNotNone(r['voltage_drop_min_copper_mm2'])
        self.assertIn('architecture-derived', r['calculation_basis'])

    def test_cad_mechanical_calc_consumes_architecture_auto(self):
        a = {'architectural_auto': {
            'estimated_water_flow_lps': 0.8,
            'target_water_velocity_mps': 1.5,
            'estimated_cooling_load_kw': 15.0,
            'estimated_heating_load_kw': 10.0,
        }}
        r = main_v5.mechanical_calc(a)
        self.assertEqual(r['design_water_flow_lps'], 0.8)
        self.assertIsNotNone(r['preliminary_hydraulic_diameter_mm'])
        self.assertEqual(r['cooling_load_kw'], 15.0)
        self.assertEqual(r['heating_load_kw'], 10.0)


if __name__ == '__main__':
    unittest.main()
