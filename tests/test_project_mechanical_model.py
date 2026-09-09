import unittest
from types import SimpleNamespace

from app.project_mechanical_model import PMM_SCHEMA, build_project_mechanical_model, install


class ProjectMechanicalModelTests(unittest.TestCase):
    def _analysis(self):
        return {"architectural_auto": {
            "effective_level_inference": "per-level-room-pattern-v3",
            "levels": [{"name": "Ground"}, {"name": "Roof"}],
            "level_profiles": [
                {"name":"Ground","roof":False,"room_counts":{"shop":1,"toilet":1,"shaft":1},"recognized_room_labels":3,
                 "wet_fixture_candidate":True,"sanitary_candidate":True,"conditioned_candidate":True,"ventilation_candidate":True,
                 "gas_candidate":False,"typical_confidence":"insufficient"},
                {"name":"Roof","roof":True,"room_counts":{},"recognized_room_labels":0,"wet_fixture_candidate":False,
                 "sanitary_candidate":False,"conditioned_candidate":False,"ventilation_candidate":False,"gas_candidate":False,
                 "typical_confidence":"insufficient"}],
            "fixture_counts":{"toilet":1,"floor_drain":1},"fixture_blocks_detected":2,"roof_drain_count":4}}

    def _scope(self):
        return {"conditioned_levels":["Ground"],"heated_levels":["Ground"],"wet_fixture_levels":["Ground"],
                "sanitary_fixture_levels":["Ground"],"ventilation_required_levels":["Ground"],"gas_consumer_levels":[],
                "roof_exists":True,"roof_level_name":"Roof","vertical_systems":False,"typical_groups":[]}

    def test_builds_json_safe_single_snapshot_with_stable_identity_registry(self):
        manifest=[{"code":"M-W-01","family":"water_supply","levels":["Ground"]},{"code":"M-R-01","family":"roof_rainwater","levels":["Roof"]}]
        model=build_project_mechanical_model(self._analysis(),answers={"heating":"yes"},scope=self._scope(),proposal={"drawing_manifest":manifest,"total_plans":2})
        self.assertEqual(model["schema"], "project-mechanical-model/v3")
        self.assertEqual(model["schema"], PMM_SCHEMA)
        self.assertEqual(model["drawing_manifest"], manifest)
        self.assertTrue(model["valid"])
        self.assertEqual(model["diagnostics"], [])
        ids=[row["entity_id"] for row in model["identity_registry"]["entities"]]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(all(value.startswith("PMM-") for value in ids))
        self.assertIn("M-W-01",model["identity_registry"]["alias_to_entity_id"])
        model2=build_project_mechanical_model(self._analysis(),answers={"heating":"yes"},scope=self._scope(),proposal={"drawing_manifest":manifest,"total_plans":2})
        self.assertEqual(model["identity_registry"],model2["identity_registry"])
        self.assertEqual(model["traceability_contract"]["policy"],"NO_ORPHAN_ENGINEERING_OUTPUT")

    def test_structural_diagnostics_remain_fail_closed(self):
        model=build_project_mechanical_model(self._analysis(),scope=self._scope(),proposal={"drawing_manifest":[{"code":"M-W-01"}],"total_plans":2})
        self.assertFalse(model["valid"])
        self.assertIn("planner_total_does_not_match_manifest_count",model["diagnostics"])

    def test_install_preserves_existing_proposal_behaviour(self):
        class FakeWorkflow:
            _pmm_v1_installed=False
            @staticmethod
            def build_scope(project): return self._scope()
            @staticmethod
            def create_proposal(project):
                proposal={"drawing_manifest":[{"code":"M-W-01","family":"water_supply","levels":["Ground"]}],"total_plans":1}
                analysis=dict(project.analysis or {}); analysis["drawing_set"]=proposal; project.analysis=analysis; project.status="drawing_set_review"; return proposal
        workflow=FakeWorkflow(); project=SimpleNamespace(analysis=self._analysis(),answers={"heating":"yes"},status="ready_to_design")
        install(workflow); proposal=workflow.create_proposal(project)
        self.assertEqual(proposal["total_plans"],1)
        self.assertEqual(project.analysis["drawing_set"],proposal)
        self.assertEqual(project.status,"drawing_set_review")
        self.assertEqual(project.analysis["project_mechanical_model"]["schema"],"project-mechanical-model/v3")


if __name__ == "__main__": unittest.main()
