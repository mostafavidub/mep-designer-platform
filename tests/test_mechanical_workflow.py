import unittest
from types import SimpleNamespace

from app.mechanical_workflow import build_scope, create_proposal, is_approved


class MechanicalWorkflowTests(unittest.TestCase):
    def project(self, answers=None, analysis=None):
        return SimpleNamespace(
            answers={'discipline': 'mechanical', **(answers or {})},
            analysis=analysis or {
                'discipline': 'mechanical',
                'files': [
                    {'file': 'plans.dxf', 'texts': ['همکف پلان معماری', 'طبقه اول پلان معماری', 'بام پلان معماری']}
                ],
            },
            status='ready_to_design',
        )

    def test_scope_detects_levels_and_vertical_system(self):
        p = self.project()
        scope = build_scope(p)
        self.assertEqual(scope['conditioned_levels'], ['همکف', 'طبقه اول', 'بام'])
        self.assertTrue(scope['vertical_systems'])
        self.assertTrue(scope['roof_exists'])

    def test_negative_gas_removes_gas_plans(self):
        p = self.project({'gas': 'خیر، ساختمان گاز ندارد'})
        scope = build_scope(p)
        self.assertEqual(scope['gas_consumer_levels'], [])

    def test_create_proposal_moves_to_review_and_requires_approval(self):
        p = self.project({'gas': 'خیر'})
        proposal = create_proposal(p)
        self.assertEqual(p.status, 'drawing_set_review')
        self.assertFalse(proposal['approved'])
        self.assertTrue(proposal['approval_required'])
        self.assertIn('drawing_set', p.analysis)
        self.assertFalse(is_approved(p))

    def test_approved_flag_is_respected(self):
        p = self.project()
        create_proposal(p)
        p.analysis['drawing_set']['approved'] = True
        self.assertTrue(is_approved(p))


if __name__ == '__main__':
    unittest.main()
