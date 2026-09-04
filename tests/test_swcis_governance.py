import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.swcis_validate import ROOT, classify, contracts, impact_errors, repository_errors


class SwcisGovernanceTests(unittest.TestCase):
    def _request(self, directory, body):
        path = Path(directory) / "request.yaml"
        path.write_text(json.dumps(body))
        return path

    def test_canonical_repository_contract_is_complete(self):
        self.assertEqual(repository_errors(), [])

    def test_rule_traceability_is_end_to_end_and_nonempty(self):
        data = contracts()
        required = set(data["trace"]["required_chain"])
        for rule in data["trace"]["rules"]:
            self.assertLessEqual(required, set(rule))
            self.assertTrue(all(rule[field] for field in required))

    def test_dependency_closure_reaches_consumers(self):
        affected, types, unclassified = classify(["cad_engine/routing_v14.py"], contracts())
        self.assertFalse(unclassified)
        self.assertIn("routing", affected)
        self.assertLessEqual({"sizing", "detail_riser", "qa", "manifest", "ui_api", "deployment"}, affected)
        self.assertIn("routing", types)

    def test_unclassified_change_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self._request(directory, {"impacted_modules": [], "change_types": [], "evidence": {}, "risk": {"likelihood": 1, "severity": 1, "detectability": 1, "score": 1}})
            errors, _ = impact_errors(["unknown/location.xyz"], request)
        self.assertIn("unclassified_path:unknown/location.xyz", errors)

    def test_missing_dependent_or_evidence_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self._request(directory, {"impacted_modules": ["routing"], "change_types": ["routing"], "evidence": {}, "risk": {"likelihood": 2, "severity": 3, "detectability": 4, "score": 24}})
            errors, _ = impact_errors(["cad_engine/routing_v14.py"], request)
        self.assertTrue(any(e.startswith("undeclared_impacted_module:") for e in errors))
        self.assertIn("required_evidence_missing:golden_regression", errors)

    def test_traceability_gap_fails_repository_contract(self):
        broken = copy.deepcopy(contracts())
        broken["trace"]["rules"][0]["qa_rules"] = []
        self.assertIn("traceability_gap:MEP-INPUT-001:qa_rules", repository_errors(broken))

    def test_swcis_has_no_test_project_inventory(self):
        golden = contracts()["golden"]
        self.assertNotIn("real_projects", golden)
        self.assertNotIn("project_id", json.dumps(golden))
        self.assertEqual(
            {suite["suite_type"] for suite in golden["required_suites"]},
            {"representative_regression", "synthetic_negative"},
        )

    def test_expired_or_self_approved_waiver_fails(self):
        waiver_dir = ROOT / "standards" / "swcis" / "waivers"
        waiver_dir.mkdir(exist_ok=True)
        waiver = waiver_dir / "test-expired.yaml"
        waiver.write_text(json.dumps({"waiver_id": "W-TEST", "scope": ["tests"], "reason": "test", "risk": 10, "requester": "same", "reviewer": "same", "approved_at": "2020-01-01", "expires_at": "2020-01-02", "compensating_controls": ["test"]}))
        with tempfile.TemporaryDirectory() as directory:
            request = self._request(directory, {"impacted_modules": [], "change_types": [], "evidence": {}, "risk": {"likelihood": 1, "severity": 1, "detectability": 1, "score": 1}, "waiver": str(waiver.relative_to(ROOT))})
            errors, _ = impact_errors([], request)
        waiver.unlink()
        self.assertIn("waiver_expired", errors)
        self.assertIn("waiver_self_approval", errors)


if __name__ == "__main__":
    unittest.main()
