import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
TRUTH = ROOT / "standards" / "golden" / "project-10.reference-truth.json"


class ReferenceTruthSetTests(unittest.TestCase):
    def test_truth_set_is_semantic_and_never_claims_missing_binary_hash(self):
        value = json.loads(TRUTH.read_text(encoding="utf-8"))
        self.assertEqual(value["schema"], "reference-truth-set/1.0")
        self.assertEqual(value["project_id"], 10)
        self.assertEqual(value["source"]["hash_status"], "INPUT_REQUIRED")
        self.assertIsNone(value["source"]["reference_file_sha256"])
        self.assertEqual(value["evidence_status"]["generation_use"], "FORBIDDEN_BEFORE_BLIND_SEAL")
        text = TRUTH.read_text(encoding="utf-8").lower()
        self.assertNotIn(".dxf\"", text)
        self.assertNotRegex(text, r"[a-f0-9]{64}.*reference_file_sha256")

    def test_known_reference_facts_are_explicit_and_non_authority_claims_remain_explicit(self):
        value = json.loads(TRUTH.read_text(encoding="utf-8"))
        self.assertEqual(value["facts"]["domestic_water"]["storage_tank_l"], 500)
        self.assertEqual(value["facts"]["domestic_water"]["pump_head_m"], 17)
        self.assertEqual(value["facts"]["domestic_water"]["pump_flow_gpm"], 17.5)
        self.assertEqual(value["facts"]["cooling"]["observed_split_capacities_btu_h"], [9000, 12000, 30000])
        self.assertEqual(value["facts"]["sanitary"]["observed_slope_percent"], 2)
        self.assertGreaterEqual(len(value["non_claims"]), 5)


if __name__ == "__main__":
    unittest.main()
