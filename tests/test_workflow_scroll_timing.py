import re
import unittest

from fastapi.testclient import TestClient
from app.main_auto import app


class WorkflowScrollTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_workflow_progress_starts_late_enough_to_show_step_one_to_two(self):
        js = self.client.get('/static/workflow-road.js')
        self.assertEqual(js.status_code, 200)
        self.assertIn('const start=vh*.56;', js.text)
        self.assertIn('const thresholds=[.04,.31,.59,.86];', js.text)

        # At the visual entry state from the 1536x1024 desktop capture, the
        # section top is roughly half a viewport down. The roadmap should still
        # be in step 1, not already past step 2.
        vh = 1024
        rect_top = 0.49 * vh
        section_height = 1024
        end = max(1, section_height - vh * .42)
        p = max(0, min(1, (vh * .56 - rect_top) / end))
        self.assertGreaterEqual(p, .04)
        self.assertLess(p, .31)


if __name__ == '__main__':
    unittest.main()
