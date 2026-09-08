import unittest
from pathlib import Path
from unittest.mock import patch
from cad_engine.mechanical_authority_site_v19 import design_mechanical_authority_site
from cad_engine.version_manifest import active_version_manifest


class MechanicalRuntimeV19Tests(unittest.TestCase):
    def test_missing_version_stamp_blocks_before_any_designer(self):
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers={},plan_analysis={})
        self.assertEqual(result["stage"],"v19_runtime_contract_gate")

    @patch("cad_engine.mechanical_authority_site_v19.validate_non_destructive_final_delivery")
    @patch("cad_engine.mechanical_authority_site_v19.validate_exact_dxf_health")
    @patch("cad_engine.mechanical_authority_site_v19.validate_generated_mechanical_integrity")
    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    def test_current_version_without_structural_rcp_always_builds_pre_submission(self,designer,integrity,health,final_delivery):
        designer.return_value={"status":"PASS"}
        integrity.return_value={"status":"PASS","errors":[],"warnings":[],"exact_file_reopened":True}
        health.return_value={"status":"PASS","errors":[],"first_reopen":True,"second_reopen":True,"audit_error_count":0,"read_only_hash_preserved":True}
        final_delivery.return_value={"status":"PASS","errors":[],"missing_inputs":[],"hash_unchanged":True,"entities_removed":0,"empty_layouts_removed":[]}
        answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":{}}
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers=answers,plan_analysis={})
        designer.assert_called_once(); integrity.assert_called_once(); health.assert_called_once(); final_delivery.assert_called_once()
        self.assertEqual(result["submission_state"],"PRE_SUBMISSION")
        self.assertEqual(result["coordination_claim"],"NOT_COORDINATED")
        self.assertFalse(result["v19_qa"]["submission"]["submission_ready"])
        self.assertIn("STRUCTURAL_MODEL",result["v19_qa"]["submission"]["missing_inputs"])
        self.assertEqual(result["exact_dxf_health_qa"]["status"],"PASS")
        self.assertEqual(result["final_delivery_step12_qa"]["status"],"PASS")

    @patch("cad_engine.mechanical_authority_site_v19.validate_non_destructive_final_delivery")
    @patch("cad_engine.mechanical_authority_site_v19.validate_exact_dxf_health")
    @patch("cad_engine.mechanical_authority_site_v19.validate_generated_mechanical_integrity")
    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    @patch("cad_engine.mechanical_authority_site_v19.run_v19_pipeline")
    def test_only_full_v19_pass_reaches_designer_and_stamps_report(self,pipeline,designer,integrity,health,final_delivery):
        pipeline.return_value={"status":"PASS","blocked_at":None,"phases":{},"submission":{"status":"PASS","release_allowed":True}}
        designer.return_value={"status":"PASS"}
        integrity.return_value={"status":"PASS","errors":[],"warnings":[],"exact_file_reopened":True}
        health.return_value={"status":"PASS","errors":[],"first_reopen":True,"second_reopen":True,"audit_error_count":0,"read_only_hash_preserved":True}
        final_delivery.return_value={"status":"PASS","errors":[],"missing_inputs":[],"hash_unchanged":True,"entities_removed":0,"empty_layouts_removed":[]}
        answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":{}}
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers=answers,plan_analysis={})
        designer.assert_called_once(); integrity.assert_called_once(); health.assert_called_once(); final_delivery.assert_called_once(); self.assertEqual(result["pipeline_authority"],"mechanical-v19")
        self.assertEqual(result["executed_versions"],active_version_manifest())
        self.assertEqual(result["generated_dxf_integrity_qa"]["status"],"PASS")
        self.assertEqual(result["exact_dxf_health_qa"]["status"],"PASS")
        self.assertEqual(result["final_delivery_step12_qa"]["status"],"PASS")

    @patch("cad_engine.mechanical_authority_site_v19.validate_generated_mechanical_integrity")
    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    def test_generated_integrity_failure_blocks_release(self,designer,integrity):
        designer.return_value={"status":"PASS"}
        integrity.return_value={"status":"FAIL","errors":["M-111:degenerate_network_topology:WATER"],"warnings":[],"exact_file_reopened":True}
        answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":{}}
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers=answers,plan_analysis={})
        self.assertEqual(result["status"],"FAIL")
        self.assertEqual(result["stage"],"generated_dxf_integrity_gate")
        self.assertEqual(result["submission_state"],"BLOCKED")
        self.assertEqual(result["generated_dxf_integrity_qa"]["status"],"FAIL")

    @patch("cad_engine.mechanical_authority_site_v19.validate_non_destructive_final_delivery")
    @patch("cad_engine.mechanical_authority_site_v19.validate_exact_dxf_health")
    @patch("cad_engine.mechanical_authority_site_v19.validate_generated_mechanical_integrity")
    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    def test_step12_failure_blocks_release_without_weakening_gate(self,designer,integrity,health,final_delivery):
        designer.return_value={"status":"PASS"}
        integrity.return_value={"status":"PASS","errors":[],"warnings":[],"exact_file_reopened":True}
        health.return_value={"status":"PASS","errors":[],"first_reopen":True,"second_reopen":True,"audit_error_count":0,"read_only_hash_preserved":True}
        final_delivery.return_value={"status":"FAIL","errors":["POST_HOC_ENTITY_DELETION_REQUIRED"],"missing_inputs":[],"hash_unchanged":True,"entities_removed":2,"empty_layouts_removed":[]}
        answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":{}}
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers=answers,plan_analysis={})
        self.assertEqual(result["status"],"FAIL")
        self.assertEqual(result["stage"],"final_delivery_step12_gate")
        self.assertEqual(result["submission_state"],"BLOCKED")
        self.assertEqual(result["coordination_claim"],"NOT_RELEASED")
        self.assertEqual(result["final_delivery_step12_qa"]["status"],"FAIL")
        self.assertFalse(result["v19_qa"]["submission"]["release_allowed"])

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
