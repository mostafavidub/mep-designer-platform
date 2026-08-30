import unittest

from cad_engine.electrical_v1.release_gate import evaluate_production_release


PASS_REPORT = {
    "acceptance": {"status": "PASS"},
    "gates": {
        "REFERENCE_SIMILARITY": {"status": "PASS"},
        "VISUAL_QA": {"status": "PASS"},
        "FINAL_FILE_REOPEN": {"status": "PASS"},
    },
}


class ElectricalReleaseGateTests(unittest.TestCase):
    def test_synthetic_pass_can_never_release_production(self):
        result = evaluate_production_release(
            PASS_REPORT,
            source_kind="SYNTHETIC_DXF",
            reference_audit_confirmed=True,
            visual_inspection_confirmed=True,
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["real_project_acceptance"])
        self.assertFalse(result["production_release_allowed"])
        self.assertIn("RAW_REAL_PROJECT_SOURCE_NOT_VERIFIED", result["blockers"])

    def test_recorded_gonbad_project_model_can_never_substitute_raw_dxf(self):
        result = evaluate_production_release(
            PASS_REPORT,
            source_kind="RECORDED_PROJECT_MODEL",
            real_project_id="GONBAD",
            raw_source_sha256=None,
            reference_audit_confirmed=True,
            visual_inspection_confirmed=True,
        )
        self.assertFalse(result["production_release_allowed"])
        self.assertFalse(result["recorded_or_synthetic_data_can_release"])

    def test_raw_real_project_must_pass_all_final_gates(self):
        report = {"acceptance": {"status": "PASS"}, "gates": dict(PASS_REPORT["gates"])}
        report["gates"]["VISUAL_QA"] = {"status": "FAIL"}
        result = evaluate_production_release(
            report,
            source_kind="RAW_DXF",
            real_project_id="GONBAD",
            raw_source_sha256="abc123",
            reference_audit_confirmed=True,
            visual_inspection_confirmed=True,
        )
        self.assertFalse(result["production_release_allowed"])
        self.assertIn("VISUAL_QA:FAIL", result["blockers"])

    def test_only_verified_raw_real_project_can_release(self):
        result = evaluate_production_release(
            PASS_REPORT,
            source_kind="RAW_DXF",
            real_project_id="GONBAD",
            raw_source_sha256="abc123",
            reference_audit_confirmed=True,
            visual_inspection_confirmed=True,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["real_project_acceptance"])
        self.assertTrue(result["production_release_allowed"])


if __name__ == "__main__":
    unittest.main()
