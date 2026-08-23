import unittest
from types import SimpleNamespace

from app.auto_inference import dynamic_questions
from app.mechanical_drawing_set import predict_drawing_set
from app.mechanical_workflow import build_scope


class MechanicalRoofScopeTests(unittest.TestCase):
    def _project(self, reliable):
        profiles = [
            {
                'name': 'طبقه همکف', 'roof': False,
                'conditioned_candidate': True, 'wet_fixture_candidate': True,
                'sanitary_candidate': True, 'ventilation_candidate': True,
                'gas_candidate': True,
            },
            {
                'name': 'طبقه اول', 'roof': False,
                'conditioned_candidate': True, 'wet_fixture_candidate': True,
                'sanitary_candidate': True, 'ventilation_candidate': True,
                'gas_candidate': True,
            },
            {
                'name': 'طبقه دوم', 'roof': False,
                'conditioned_candidate': True, 'wet_fixture_candidate': True,
                'sanitary_candidate': True, 'ventilation_candidate': True,
                'gas_candidate': True,
            },
            {
                'name': 'بام', 'roof': True,
                'conditioned_candidate': False, 'wet_fixture_candidate': False,
                'sanitary_candidate': False, 'ventilation_candidate': False,
                'gas_candidate': False,
                'room_counts': {'kitchen': 2, 'bedroom': 2, 'living': 2} if not reliable else {'roof': 1},
            },
        ]
        auto = {
            'levels': [{'name': x['name']} for x in profiles],
            'level_profiles': profiles,
            'typical_groups': [{'name': 'Typical 1-2', 'levels': ['طبقه اول', 'طبقه دوم']}],
            'roof_scope_reliable': reliable,
            'fixture_blocks_detected': 1,
        }
        return SimpleNamespace(
            analysis={'architectural_auto': auto, 'files': []},
            answers={'discipline': 'mechanical', 'heating': 'رادیاتور', 'cooling': 'اسپلیت', 'gas': 'تأیید'},
        )

    def test_reused_occupied_roof_title_does_not_add_false_sheets(self):
        project = self._project(False)
        scope = build_scope(project)
        proposal = predict_drawing_set(scope)
        self.assertFalse(scope['roof_exists'])
        self.assertEqual(proposal['deliverable_sheet_count'], 13)
        questions = dynamic_questions(project.analysis, 'mechanical', project.analysis['architectural_auto'])
        self.assertNotIn('roof_drainage_geometry', [key for key, _ in questions])

    def test_dedicated_roof_profile_remains_in_scope(self):
        project = self._project(True)
        scope = build_scope(project)
        proposal = predict_drawing_set(scope)
        self.assertTrue(scope['roof_exists'])
        self.assertEqual(proposal['deliverable_sheet_count'], 15)


if __name__ == '__main__':
    unittest.main()
