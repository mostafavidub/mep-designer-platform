import unittest

from app.auto_inference_v2 import infer_architecture_facts, canonical_auto_answers, dynamic_questions
from cad_engine import main_v5


class ArchitectureFirstTests(unittest.TestCase):
    def sample_analysis(self):
        labels = [
            {'text': 'آشپزخانه', 'x': 1000, 'y': 1000},
            {'text': 'اتاق خواب', 'x': 3000, 'y': 1000},
            {'text': 'اتاق خواب', 'x': 6000, 'y': 1000},
            {'text': 'پذیرایی', 'x': 4000, 'y': 4000},
            {'text': 'حمام', 'x': 8000, 'y': 1000},
            {'text': 'سرویس', 'x': 9000, 'y': 1000},
            {'text': 'شفت', 'x': 9500, 'y': 1200},
        ]
        return {
            'files': [{
                'file': 'floor.dxf',
                'insunits': 4,
                'geometry_width_m': 14.0,
                'geometry_height_m': 10.0,
                'geometry_area_m2': 140.0,
                'texts': [x['text'] for x in labels],
                'text_labels': labels,
            }]
        }

    def test_spatial_room_count_preserves_repeated_room_names(self):
        auto = infer_architecture_facts(self.sample_analysis(), 'electrical')
        self.assertEqual(auto['room_counts'].get('bedroom'), 2)
        self.assertEqual(auto['room_counts'].get('kitchen'), 1)

    def test_electrical_infers_numeric_engineering_inputs(self):
        analysis = self.sample_analysis()
        auto = infer_architecture_facts(analysis, 'electrical')
        answers = canonical_auto_answers(auto, 'electrical')
        self.assertGreater(float(answers['design_load_kw']), 0)
        self.assertGreater(float(answers['cable_length_m']), 0)
        self.assertEqual(float(answers['power_factor']), 0.9)
        self.assertEqual(float(answers['max_voltage_drop_pct']), 3.0)
        keys = [k for k, _ in dynamic_questions(analysis, 'electrical', auto)]
        for forbidden in ['loads', 'cable_length_m', 'power_factor', 'max_voltage_drop_pct']:
            self.assertNotIn(forbidden, keys)

    def test_mechanical_infers_flow_and_thermal_proxies(self):
        analysis = self.sample_analysis()
        auto = infer_architecture_facts(analysis, 'mechanical')
        answers = canonical_auto_answers(auto, 'mechanical')
        self.assertGreater(float(answers['design_water_flow_lps']), 0)
        self.assertGreater(float(answers['cooling_load_kw']), 0)
        self.assertGreater(float(answers['heating_load_kw']), 0)
        keys = [k for k, _ in dynamic_questions(analysis, 'mechanical', auto)]
        for forbidden in ['water', 'design_water_flow_lps', 'cooling_load_kw', 'heating_load_kw']:
            self.assertNotIn(forbidden, keys)

    def test_title_block_like_geometry_is_rejected_for_area_based_loads(self):
        analysis = self.sample_analysis()
        f = analysis['files'][0]
        f['geometry_width_m'] = 400.0
        f['geometry_height_m'] = 250.0
        f['geometry_area_m2'] = 100000.0
        auto = infer_architecture_facts(analysis, 'mechanical')
        self.assertIsNone(auto['geometry_area_m2'])
        self.assertIsNotNone(auto['estimated_cooling_load_kw'])  # falls back to room inventory

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
