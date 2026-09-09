import unittest
from pathlib import Path
from unittest.mock import patch
from cad_engine.mechanical_authority_site_v19 import design_mechanical_authority_site
from cad_engine.version_manifest import active_version_manifest


def _authority_contract():
    return {
        "project_mechanical_model": {
            "schema": "project-mechanical-model/v3",
            "traceability_contract": {"policy": "NO_ORPHAN_ENGINEERING_OUTPUT"},
            "systems": {"wet_fixture_levels": ["L1"]},
        },
        "calculation_rows": [{"calc_id": "CALC-1"}],
        "network_graph": {
            "graph_id": "G1",
            "levels": [{"id": "L1", "type": "FIRST"}],
            "nodes": [{"id": "N1", "level": "L1"}, {"id": "N2", "level": "L1"}],
            "edges": [{
                "id": "E1", "from": "N1", "to": "N2", "system": "cold_water",
                "calc_id": "CALC-1", "plan_id": "CALC-1", "riser_id": "CALC-1",
                "schedule_id": "CALC-1", "size": "DN20", "material": "PPR",
                "levels": ["L1"],
            }],
        },
    }


def _passing_pipeline():
    return {
        "status": "PASS",
        "blocked_at": None,
        "phases": {
            "documentation": {
                "status": "PASS",
                "pmm_traceability_required": True,
                "calculation_reconciliation": {"status": "PASS", "zero_mismatch": True},
            }
        },
        "submission": {"status": "PASS", "release_allowed": True, "submission_ready": True},
    }


class MechanicalRuntimeV19Tests(unittest.TestCase):
    def test_missing_version_stamp_blocks_before_any_designer(self):
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers={},plan_analysis={})
        self.assertEqual(result["stage"],"v19_runtime_contract_gate")

    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    @patch("cad_engine.mechanical_authority_site_v19.run_v19_pipeline")
    def test_current_version_without_authority_evidence_blocks_before_pipeline_or_renderer(self,pipeline,designer):
        answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":{}}
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers=answers,plan_analysis={})
        self.assertEqual(result["stage"],"v19_network_authority_gate")
        self.assertEqual(result["input_required"]["status"],"INPUT_REQUIRED")
        self.assertIn("PROJECT_MECHANICAL_MODEL_V3",result["input_required"]["missing_inputs"])
        pipeline.assert_not_called()
        designer.assert_not_called()

    @patch("cad_engine.mechanical_authority_site_v19.materialize_authoritative_network")
    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    @patch("cad_engine.mechanical_authority_site_v19.run_v19_pipeline")
    def test_full_v19_pass_reaches_renderer_only_and_stamps_report(self,pipeline,designer,materializer):
        pipeline.return_value=_passing_pipeline()
        designer.return_value={"status":"PASS","composition":{}}
        materializer.return_value={"status":"PASS","materialized_segments":1,"exact_file_reopened":True}
        answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":_authority_contract()}
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers=answers,plan_analysis={})
        designer.assert_called_once()
        materializer.assert_called_once()
        self.assertEqual(result["pipeline_authority"],"mechanical-v19")
        self.assertEqual(result["engineering_authority"],"PMM_V3_V19")
        self.assertEqual(result["cad_materializer"],"legacy-v17-shell+graph-native-v19-network")
        self.assertEqual(result["legacy_renderer_role"],"CAD_SHELL_ONLY")
        self.assertEqual(result["submission_state"],"SUBMISSION_READY")
        self.assertEqual(result["executed_versions"],active_version_manifest())
        self.assertTrue(result["v19_materialization_qa"]["exact_file_reopened"])

    @patch("cad_engine.mechanical_authority_site_v19._design_v17")
    @patch("cad_engine.mechanical_authority_site_v19.run_v19_pipeline")
    def test_missing_structural_coordination_no_longer_bypasses_v19_authority(self,pipeline,designer):
        pipeline.return_value={
            "status":"INPUT_REQUIRED","blocked_at":"coordination",
            "phases":{"coordination":{"model":{"missing_inputs":["STRUCTURAL_MODEL","RCP_MODEL"]}}},
            "submission":{"status":"FAIL","release_allowed":False},
        }
        answers={"_runtime_contract":active_version_manifest(),"_v19_input_contract":_authority_contract()}
        result=design_mechanical_authority_site(Path("a.dxf"),Path("b.dxf"),answers=answers,plan_analysis={})
        self.assertEqual(result["stage"],"v19_authority_release_gate")
        self.assertIn("STRUCTURAL_MODEL",result["input_required"]["missing_inputs"])
        self.assertIn("RCP_MODEL",result["input_required"]["missing_inputs"])
        designer.assert_not_called()

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
