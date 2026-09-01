import unittest
from pathlib import Path

from app.design_progress import STAGES, get_project_progress, progress_timeline, set_project_progress, stage_payload


ROOT = Path(__file__).resolve().parents[1]


class FakeProject:
    def __init__(self):
        self.analysis = {"existing": {"preserved": True}}


class DesignProgressTests(unittest.TestCase):
    def test_stage_percentages_are_monotonic_and_finish_at_100(self):
        values = [percent for percent, _label in STAGES.values()]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[-1], 100)
        self.assertTrue(all(label for _percent, label in STAGES.values()))

    def test_progress_persists_without_erasing_project_analysis(self):
        project = FakeProject()
        set_project_progress(project, "engine_designing")
        self.assertTrue(project.analysis["existing"]["preserved"])
        progress = get_project_progress(project)
        self.assertEqual(progress["stage"], "engine_designing")
        self.assertEqual(progress["percent"], 20)
        self.assertIn("طراحی نقشه", progress["label"])

    def test_unknown_stage_fails_closed(self):
        with self.assertRaises(ValueError):
            stage_payload("made_up_stage")

    def test_release_qa_is_visible_and_timeline_marks_real_state(self):
        payload=stage_payload('mechanical_release_qa')
        self.assertEqual(payload['percent'],78)
        self.assertIn('تجهیزات',payload['label'])
        states={x['stage']:x['state'] for x in progress_timeline('mechanical_release_qa')}
        self.assertEqual(states['engine_designing'],'completed')
        self.assertEqual(states['mechanical_release_qa'],'current')
        self.assertEqual(states['packaging'],'pending')

    def test_backend_emits_real_milestones_around_cad_and_artifact_work(self):
        source = (ROOT / "app/dxf_output.py").read_text(encoding="utf-8")
        ordered = [
            "'preparing_inputs'", "'validating_contract'", "'engine_designing'",
            "requests.post", "'mechanical_release_qa'", "'validating_output'", "'packaging'", "'artifact_qa'",
            "'uploading_output'", "'finalizing'", "'completed'",
        ]
        positions = [source.index(token) for token in ordered]
        self.assertEqual(positions, sorted(positions))

    def test_flow_and_queue_expose_progress_and_both_uis_render_it(self):
        queue = (ROOT / "app/job_queue.py").read_text(encoding="utf-8")
        modal = (ROOT / "app/static/resumable-upload.js").read_text(encoding="utf-8")
        project = (ROOT / "app/templates/project.html").read_text(encoding="utf-8")
        self.assertIn("data['design_progress']", queue)
        self.assertIn("payload['design_progress']", queue)
        self.assertIn("d.design_progress", modal)
        self.assertIn("p.timeline", modal)
        self.assertIn("data-design-progress", project)
        self.assertIn("data-design-timeline", project)
        self.assertIn("aria-valuenow", project)


if __name__ == "__main__":
    unittest.main()
