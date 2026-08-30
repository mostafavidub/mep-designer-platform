import unittest

from app.main_auto import unanswered_questions
from app.mechanical_rulebook import automatic_answers
from app.mechanical_review_fix import analyzer_needs_refresh


class MechanicalQuestionnairePersistenceTests(unittest.TestCase):
    def test_answered_questions_are_not_reissued_after_analysis(self):
        questions = [('location', 'city?'), ('heating', 'system?'), ('cooling', 'system?')]
        answers = {'location': 'مشهد', 'heating': 'رادیاتور', 'cooling': '  '}
        self.assertEqual(unanswered_questions(questions, answers), [('cooling', 'system?')])

    def test_current_v35_analyzer_never_refreshes_on_flow_poll(self):
        analysis = {'architecture_analyzer_version': '3.5-project-evidence-gate'}
        self.assertFalse(analyzer_needs_refresh(analysis, has_source=True))

    def test_legacy_analyzer_refreshes_once_when_source_exists(self):
        self.assertTrue(analyzer_needs_refresh({'architecture_analyzer_version': '2.0'}, True))
        self.assertFalse(analyzer_needs_refresh({'architecture_analyzer_version': '2.0'}, False))

    def test_rulebook_never_injects_project_equipment_or_system_facts(self):
        auto = {
            'room_counts': {'bedroom': 2, 'living': 1},
            'estimated_cooling_load_kw': 9,
            'estimated_heating_load_kw': 12,
        }
        proposal = automatic_answers(auto)
        self.assertNotIn('equipment_schedule', proposal)
        self.assertNotIn('heating', proposal)
        self.assertNotIn('cooling', proposal)
        self.assertNotIn('water_inlet_pressure', proposal)
        self.assertIn('water_design_basis', proposal)
        self.assertIn('sanitary_design_basis', proposal)


if __name__ == '__main__':
    unittest.main()
