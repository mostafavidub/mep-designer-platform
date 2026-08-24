import unittest

from app.main_auto import unanswered_questions
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


if __name__ == '__main__':
    unittest.main()
