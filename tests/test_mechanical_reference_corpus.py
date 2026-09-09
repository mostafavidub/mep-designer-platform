import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "standards" / "test-suites" / "mechanical-reference-corpus.json"
TRUTH = ROOT / "standards" / "golden" / "project-10.reference-truth.json"
GOLDEN = ROOT / "standards" / "test-suites" / "golden-regression.json"
HEX64 = re.compile(r"^[a-f0-9]{64}$")


class MechanicalReferenceCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        cls.projects = {p["project_id"]: p for p in cls.corpus["projects"]}

    def test_corpus_is_privacy_safe_and_generation_leakage_is_forbidden(self):
        self.assertEqual(self.corpus["schema_revision"], "mechanical-reference-corpus/1")
        self.assertEqual(
            self.corpus["generation_leakage_policy"],
            "REFERENCE_VALUES_MUST_NOT_BE_USED_AS_HIDDEN_GENERATION_DEFAULTS",
        )
        self.assertIn("NO_PROJECT_IN_THIS_CORPUS_IS_CLAIMED_STRICTLY_UNSEEN", self.corpus["strict_blind_status"])
        text = CORPUS.read_text(encoding="utf-8").lower()
        self.assertNotIn(".dxf", text)
        self.assertNotIn('"strict_blind"', text)

    def test_complete_pairs_have_verified_hashes_and_unique_project_ids(self):
        ids = [p["project_id"] for p in self.corpus["projects"]]
        self.assertEqual(len(ids), len(set(ids)))
        complete = [p for p in self.corpus["projects"] if p["pair_status"] == "COMPLETE_ARCHITECTURE_MECHANICAL_PAIR"]
        self.assertEqual({p["project_id"] for p in complete}, {1, 3, 4, 5, 6, 7, 8, 9, 10})
        for project in complete:
            self.assertRegex(project["source_hashes"]["architecture_sha256"], HEX64)
            self.assertRegex(project["source_hashes"]["mechanical_reference_sha256"], HEX64)
            self.assertEqual(project["direct_text_observations"]["evidence_class"], "REFERENCE_OBSERVED_NOT_DESIGN_RULE")

    def test_cohorts_are_disjoint_and_non_pair_projects_cannot_enter_generation_regression(self):
        cohorts = self.corpus["cohorts"]
        cohort_names = [
            "development_reference_projects",
            "validation_reference_projects",
            "reference_sealed_evaluation_projects",
            "reference_only_projects",
            "excluded_projects",
        ]
        sets = {name: set(cohorts[name]) for name in cohort_names}
        for index, left in enumerate(cohort_names):
            for right in cohort_names[index + 1 :]:
                self.assertTrue(sets[left].isdisjoint(sets[right]), f"{left} overlaps {right}")
        self.assertEqual(sets["reference_only_projects"], {12})
        self.assertEqual(sets["excluded_projects"], {11})
        self.assertEqual(self.projects[12]["pair_status"], "MECHANICAL_REFERENCE_WITH_ARCHITECTURE_BACKGROUND_ONLY")
        self.assertEqual(self.projects[11]["pair_status"], "EXCLUDED_NOT_MECHANICAL_PAIR")
        paired_regression = sets["development_reference_projects"] | sets["validation_reference_projects"] | sets["reference_sealed_evaluation_projects"]
        self.assertNotIn(11, paired_regression)
        self.assertNotIn(12, paired_regression)

    def test_evaluation_project_is_frozen_out_of_rule_extraction(self):
        cohorts = self.corpus["cohorts"]
        self.assertEqual(cohorts["reference_sealed_evaluation_projects"], [9])
        self.assertNotIn(9, cohorts["development_reference_projects"])
        self.assertNotIn(9, cohorts["validation_reference_projects"])
        requirements = " ".join(self.corpus["rule_promotion_policy"]["requirements"])
        self.assertIn("Evaluation-only Project 9", requirements)
        self.assertIn("not for rule extraction", requirements)

    def test_project_10_hashes_match_reviewed_truth(self):
        truth = json.loads(TRUTH.read_text(encoding="utf-8"))
        project = self.projects[10]
        self.assertEqual(project["alias"], "fasihi")
        self.assertEqual(project["source_hashes"]["architecture_sha256"], truth["source"]["architecture_file_sha256"])
        self.assertEqual(project["source_hashes"]["mechanical_reference_sha256"], truth["source"]["mechanical_reference_file_sha256"])
        self.assertEqual(truth["cohort"], "DEVELOPMENT_DEBUG_REFERENCE")

    def test_repeated_reference_patterns_cannot_self_promote_into_rules(self):
        for pattern in self.corpus["cross_project_observations"]:
            self.assertEqual(pattern["evidence_class"], "CROSS_PROJECT_REFERENCE_PATTERN_NOT_DESIGN_RULE")
            self.assertEqual(pattern["promotion_status"], "CANDIDATE_ONLY")
            self.assertGreaterEqual(len(pattern["supporting_projects"]), 2)
        self.assertTrue(self.corpus["rule_promotion_policy"]["reference_recurrence_is_not_authority"])

    def test_golden_inventory_lists_all_complete_pairs_without_misrepresenting_execution(self):
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(golden["schema_revision"], "golden-regression-inventory/3")
        self.assertEqual(set(golden["optional_reference_projects"]), {1, 3, 4, 5, 6, 7, 8, 9, 10})
        self.assertEqual(golden["development_reference_projects"], [1, 3, 5, 6, 8, 10])
        self.assertEqual(golden["validation_reference_projects"], [4, 7])
        self.assertEqual(golden["reference_sealed_evaluation_projects"], [9])
        self.assertEqual(golden["reference_only_projects"], [12])
        self.assertEqual(golden["excluded_projects"], [11])
        self.assertIn("Do not claim unexecuted comparisons passed", golden["pass_policy"])


if __name__ == "__main__":
    unittest.main()
