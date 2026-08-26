import unittest
from types import SimpleNamespace

from app.fixture_gate_v1 import (
    fixture_evidence_resolved,
    fixture_schedule_quantified,
    install,
    unresolved_wet_levels,
)


class FixtureEvidenceGateTests(unittest.TestCase):
    def _auto(self):
        return {
            'evidence_diagnostics': [
                'wet_level_without_detected_fixture:Ground',
                'wet_level_without_detected_fixture:Mezzanine',
            ]
        }

    def test_unresolved_levels_are_extracted(self):
        self.assertEqual(unresolved_wet_levels(self._auto()), ['Ground', 'Mezzanine'])

    def test_quantified_schedule_resolves_gate(self):
        self.assertFalse(fixture_evidence_resolved(self._auto(), {}))
        self.assertTrue(fixture_schedule_quantified('سینک 2، روشویی 3، توالت 3، دوش 2'))
        self.assertTrue(fixture_evidence_resolved(
            self._auto(), {'fixture_schedule': 'سینک 2، روشویی 3، توالت 3، دوش 2'}
        ))

    def test_non_quantified_text_does_not_resolve_gate(self):
        self.assertFalse(fixture_schedule_quantified('تأیید'))
        self.assertFalse(fixture_schedule_quantified('تجهیزات وجود دارد'))
        self.assertFalse(fixture_evidence_resolved(self._auto(), {'fixture_schedule': 'تأیید'}))

    def test_install_adds_question_and_blocks_approval_until_resolved(self):
        class MainAuto:
            _fixture_gate_v1_installed = False

            @staticmethod
            def dynamic_questions(analysis, discipline, auto):
                return [('heating', 'heating?')]

        class Workflow:
            @staticmethod
            def is_approved(project):
                return True

        main = MainAuto()
        workflow = Workflow()
        install(main, workflow)
        questions = main.dynamic_questions({}, 'mechanical', self._auto())
        keys = [key for key, _ in questions]
        self.assertIn('fixture_schedule', keys)

        project = SimpleNamespace(
            answers={'discipline': 'mechanical'},
            analysis={'discipline': 'mechanical', 'architectural_auto': self._auto()},
        )
        self.assertFalse(workflow.is_approved(project))
        project.answers['fixture_schedule'] = 'سینک 1، توالت 1'
        self.assertTrue(workflow.is_approved(project))

    def test_electrical_approval_is_untouched(self):
        class MainAuto:
            _fixture_gate_v1_installed = False

            @staticmethod
            def dynamic_questions(analysis, discipline, auto):
                return []

        class Workflow:
            @staticmethod
            def is_approved(project):
                return True

        main = MainAuto()
        workflow = Workflow()
        install(main, workflow)
        project = SimpleNamespace(
            answers={'discipline': 'electrical'},
            analysis={'discipline': 'electrical', 'architectural_auto': self._auto()},
        )
        self.assertTrue(workflow.is_approved(project))
        self.assertEqual(main.dynamic_questions({}, 'electrical', self._auto()), [])


if __name__ == '__main__':
    unittest.main()
