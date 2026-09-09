import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
TRUTH = ROOT / "standards" / "golden" / "project-10.reference-truth.json"


class ReferenceTruthSetTests(unittest.TestCase):
    def test_truth_set_has_verified_pair_hashes_without_source_bytes_or_names(self):
        value = json.loads(TRUTH.read_text(encoding="utf-8"))
        self.assertEqual(value["schema"], "reference-truth-set/1.1")
        self.assertEqual(value["project_id"], 10)
        self.assertEqual(value["cohort"], "DEVELOPMENT_DEBUG_REFERENCE")
        self.assertEqual(value["source"]["hash_status"], "VERIFIED")
        self.assertEqual(
            value["source"]["architecture_file_sha256"],
            "08b2e3f2a16a90727e1ef44e8dbc96455a57a553a6f7ef6b2d0800dcadeb13ca",
        )
        self.assertEqual(
            value["source"]["mechanical_reference_file_sha256"],
            "f912a181c6b4250e2ba51c24f7332c70ffd5840bbb17252f6360e8ed0bd36b42",
        )
        for key in ("architecture_file_sha256", "mechanical_reference_file_sha256"):
            self.assertRegex(value["source"][key], r"^[a-f0-9]{64}$")
        self.assertEqual(
            value["evidence_status"]["generation_use"],
            "FORBIDDEN_AS_HIDDEN_GENERATION_INPUT",
        )
        self.assertFalse(value["evidence_status"]["strict_blind_claim"])
        text = TRUTH.read_text(encoding="utf-8").lower()
        self.assertNotIn(".dxf", text)

    def test_known_reference_facts_are_explicit_and_non_authority_claims_remain_explicit(self):
        value = json.loads(TRUTH.read_text(encoding="utf-8"))
        self.assertEqual(value["facts"]["domestic_water"]["storage_tank_l"], 500)
        self.assertEqual(value["facts"]["domestic_water"]["pump_head_m"], 17)
        self.assertEqual(value["facts"]["domestic_water"]["pump_flow_gpm"], 17.5)
        self.assertEqual(value["facts"]["cooling"]["observed_split_capacities_btu_h"], [9000, 12000, 30000])
        self.assertEqual(value["facts"]["sanitary"]["observed_slope_percent"], 2)
        self.assertGreaterEqual(len(value["non_claims"]), 6)


if __name__ == "__main__":
    unittest.main()
