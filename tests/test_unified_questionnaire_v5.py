import unittest
from pathlib import Path

from app.auto_inference import dynamic_questions
from app.main import present_question
from app.main_auto import build_unified_questionnaire
from app.main_health import app
from fastapi.testclient import TestClient


class UnifiedQuestionnaireV5Tests(unittest.TestCase):
    def auto(self):
        return {'room_counts': {}, 'occupancy_inferred': True, 'gas_absence_inferred': False,
                'water_inlet_pressure_inferred': False, 'detected_parking': False,
                'fixture_blocks_detected': True, 'roof_scope_reliable': False}

    def test_scope_decisions_are_part_of_mechanical_flow(self):
        keys = {key for key, _ in dynamic_questions({'files': [{'texts': []}]}, 'mechanical', self.auto())}
        for key in ('gas', 'has_boiler_room', 'has_pool', 'has_sauna', 'has_jacuzzi', 'has_fire_suppression'):
            self.assertIn(key, keys)
        self.assertNotIn('has_gas_system', keys)

    def test_architecture_evidence_removes_redundant_scope_questions(self):
        text = 'بدون گاز بدون موتورخانه بدون استخر بدون سونا بدون جکوزی اطفای حریق'
        auto = self.auto()
        auto['gas_absence_inferred'] = True
        keys = {key for key, _ in dynamic_questions({'files': [{'texts': [text]}]}, 'mechanical', auto)}
        for key in ('gas', 'has_boiler_room', 'has_pool', 'has_sauna', 'has_jacuzzi', 'has_fire_suppression'):
            self.assertNotIn(key, keys)

    def test_unified_questionnaire_positive_shared_contract(self):
        analysis = {'files': [{'texts': ['مشهد', 'مسکونی', 'ارتفاع طبقه 3.20 متر'], 'text_labels': []}]}
        _auto, _answers, questions = build_unified_questionnaire(
            analysis, 'mechanical', {'occupancy': 'مسکونی'}
        )
        keys = [key for key, _prompt in questions]
        self.assertNotIn('typical', keys)
        self.assertNotIn('heights', keys)
        self.assertIn('heating', keys)

    def test_unified_questionnaire_destructive_static_fallback_is_absent(self):
        engine_route = (
            Path(__file__).resolve().parents[1]
            / 'app/main_auto.py'
        ).read_text(encoding='utf-8')
        self.assertIn("@app.post('/api/questionnaire/analyze')", engine_route)
        self.assertIn('build_unified_questionnaire(', engine_route)
        self.assertNotIn('questionsForService', engine_route)

    def test_unified_questionnaire_golden_skips_extractable_architecture_facts(self):
        auto = self.auto()
        auto['floor_height_inferred'] = '3.20 متر'
        keys = {
            key for key, _ in dynamic_questions(
                {'files': [{'texts': ['مشهد مسکونی']}]},
                'mechanical',
                auto,
            )
        }
        self.assertNotIn('typical', keys)
        self.assertNotIn('heights', keys)

    def test_unified_questionnaire_web_choices_are_selectable(self):
        questions = dynamic_questions({'files': [{'texts': []}]}, 'mechanical', self.auto())
        for key, prompt in questions:
            rendered = present_question({'key': key, 'question': prompt})
            if key == 'location':
                self.assertEqual(rendered['input_type'], 'text')
            elif key in {'water_inlet_pressure', 'rainfall_intensity', 'gas_pressure'}:
                self.assertEqual(rendered['input_type'], 'number')
                self.assertEqual(rendered['options'], [])
            else:
                self.assertEqual(rendered['input_type'], 'radio', key)
                minimum = 1 if key == 'cooling' else 2
                self.assertGreaterEqual(len(rendered['options']), minimum, key)

    def test_invalid_zip_is_rejected_without_internal_server_error(self):
        response = TestClient(app).post(
            '/api/questionnaire/analyze?discipline=mechanical',
            files={'file': ('invalid.zip', b'not-a-zip', 'application/zip')},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
