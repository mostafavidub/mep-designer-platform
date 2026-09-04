import unittest
from pathlib import Path
from unittest.mock import patch
from cad_engine.mechanical_authority_site_v19 import design_mechanical_authority_site
from cad_engine.version_manifest import active_version_manifest


class MechanicalRuntimeV19Tests(unittest.TestCase):
    def test_missing_version_stamp_blocks_before_any_designer(self):
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers={},plan_analysis={})
        self.assertEqual(result["stage"],"v19_runtime_contract_gate")

    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    def test_current_version_without_structural_rcp_always_builds_pre_submission(self,designer):
        designer.return_value={"status":"PASS"}
        answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":{}}
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers=answers,plan_analysis={})
        designer.assert_called_once()
        self.assertEqual(result["submission_state"],"PRE_SUBMISSION")
        self.assertEqual(result["coordination_claim"],"NOT_COORDINATED")
        self.assertFalse(result["v19_qa"]["submission"]["submission_ready"])
        self.assertIn("STRUCTURAL_MODEL",result["v19_qa"]["submission"]["missing_inputs"])

    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    @patch("cad_engine.mechanical_authority_site_v19.run_v19_pipeline")
    def test_only_full_v19_pass_reaches_designer_and_stamps_report(self,pipeline,designer):
        pipeline.return_value={"status":"PASS","blocked_at":None,"phases":{},"submission":{"status":"PASS","release_allowed":True}}
        designer.return_value={"status":"PASS"}
        answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":{}}
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers=answers,plan_analysis={})
        designer.assert_called_once(); self.assertEqual(result["pipeline_authority"],"mechanical-v19")
        self.assertEqual(result["executed_versions"],active_version_manifest())

    def test_active_entrypoint_installs_v19_adapter(self):
        import cad_engine.main_v19 as active
        import cad_engine.main_v15 as base
        self.assertIs(base.design_mechanical_authority_site,active.design_mechanical_authority_site)
        self.assertEqual(active.mechanical_v19_status()["status"],"PASS")

    def test_site_stamps_request_and_rejects_any_non_v19_report(self):
        source=(Path(__file__).parents[1]/"app/dxf_output.py").read_text()
        self.assertIn("design_answers['_runtime_contract'] = active_version_manifest()",source)
        self.assertIn("design_answers['_v19_input_contract']",source)
        self.assertIn("report.get('pipeline_authority') != 'mechanical-v19'",source)
        self.assertIn("report.get('executed_versions') != active_versions",source)

    def test_panel_and_progress_expose_active_runtime_phases(self):
        root=Path(__file__).parents[1]
        panel=(root/"app/templates/project.html").read_text()
        progress=(root/"app/design_progress.py").read_text()
        self.assertIn("data-mechanical-runtime-v19",panel)
        for stage in ("coordination_v19","manufacturer_v19","documentation_v19"):
            self.assertIn(stage,progress)


if __name__ == "__main__": unittest.main()
