import json
import tempfile
import unittest
from pathlib import Path

from cad_engine.golden_artifacts_v19 import generate


class GoldenArtifactsV19Tests(unittest.TestCase):
    def test_locked_cohort_artifacts_reopen_and_strict_diff_pass(self):
        root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as output:
            result = generate(output, root / "standards/golden/seven-project-v19.baseline.json")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["strict_submission_regression"]["pass_rate"], 1.0)
            records = [json.loads((Path(output) / name).read_text()) for name in result["artifacts"] if name.endswith(".json") and name.startswith("project-")]
            self.assertEqual(len(records), 7)
            self.assertTrue(all(record["reference_access"] == "POST_SEAL_ONLY" for record in records))
            self.assertTrue(all("archive" not in record["blind_output"]["source"] for record in records))


if __name__ == "__main__":
    unittest.main()
