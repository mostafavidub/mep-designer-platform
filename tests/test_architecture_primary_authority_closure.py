import json
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/rulebook/architecture"


def load(name):
    return json.loads((DATA / f"{name}.json").read_text())


class PrimaryAuthorityClosureTests(unittest.TestCase):
    def test_authority_lifecycle_is_explicit_and_fail_closed(self):
        assessments = {x["source_id"]: x for x in load("sources")["authority_assessments"]}
        self.assertEqual(set(assessments), {"IR-M3", "IR-M4", "IR-ACCESS"})
        required = {"document_title", "issuing_authority", "approval_authority", "publication_date",
                    "effective_date", "edition", "amendments", "corrigenda", "annexes", "supplements",
                    "transition_rules", "superseded_documents", "superseding_documents", "current_status",
                    "applicability_scope", "official_reference", "retrieved_date", "evidence_strength"}
        for item in assessments.values():
            self.assertTrue(required <= item.keys())
            self.assertIn(item["current_status"], {"OWNER_CONFIRMED_CURRENT_PRIMARY_BASELINE", "PRIMARY_FILE_REQUIRED_FOR_CLAUSE_MAPPING"})
        self.assertEqual(assessments["IR-ACCESS"]["verification_status"], "FILE_BYTES_HASH_CLAUSE_PAGE_REQUIRED")

    def test_all_numerical_candidates_remain_release_disabled(self):
        rules = [r for r in load("rulebook")["rules"] if r["authority_type"] == "HARD_RULE"]
        self.assertEqual(len(rules), 32)
        for rule in rules:
            self.assertEqual(rule["classification"], "MANDATORY_NATIONAL")
            self.assertIn(rule["release_status"], {"SOURCE_GAP", "HUMAN_REVIEW_REQUIRED"})
            self.assertFalse(rule["release_enabled"])
            self.assertEqual(rule["amendment_state"], "OWNER_CONFIRMED_NO_LATER_APPLICABLE_CHANGE")
            self.assertEqual(rule["effective_from"], "PROJECT_BASELINE_CONFIRMED_2026-10-08")
            self.assertTrue(rule["human_review_required"])
            self.assertTrue(rule["source_clause"])
            self.assertTrue(rule["source_page"])

    def test_original_gap_register_is_preserved_with_evidenced_transitions(self):
        catalog = load("source-gap-register")
        gaps = catalog["gaps"]
        counts = Counter(g["status"] for g in gaps)
        self.assertEqual(len(gaps), 24)
        self.assertEqual(len({g["gap_id"] for g in gaps}), 24)
        self.assertEqual(catalog["summary"]["total"], 24)
        for key, value in counts.items():
            self.assertEqual(catalog["summary"][key], value)
        self.assertEqual(Counter(g["severity"] for g in gaps), {"MEDIUM": 12, "HIGH": 11, "CRITICAL": 1})
        self.assertTrue(all(g["transition_evidence"] for g in gaps))

    def test_conflicts_are_explicit_and_never_auto_resolved(self):
        matrix = load("conflict-matrix")
        self.assertEqual(len(matrix["conflicts"]), 8)
        self.assertEqual(len({x["conflict_id"] for x in matrix["conflicts"]}), 8)
        self.assertTrue(any({x["source_a"], x["source_b"]} == {"IR-M3", "IR-M4"} for x in matrix["conflicts"]))
        self.assertTrue(any("LOCAL" in x["source_b"] for x in matrix["conflicts"]))
        self.assertTrue(all(x["result"] != "MORE_RESTRICTIVE_RESULT" for x in matrix["conflicts"]))

    def test_owner_questions_remain_owner_intent(self):
        catalog = load("owner-questionnaire")
        self.assertEqual(catalog["regulatory_reaudit_summary"], {
            "DERIVE_FROM_CODE": 0, "DERIVE_FROM_CITY": 0, "DERIVE_FROM_GEOMETRY": 0,
            "KEEP": 13, "DELAY": 45, "REMOVE": 0,
        })
        self.assertEqual(len(catalog["questions"]), 58)
        self.assertTrue(all(q["re_audit_disposition"] in {"KEEP", "DELAY"} for q in catalog["questions"]))

    def test_architect_review_package_has_no_fabricated_decisions(self):
        package = load("human-architect-review-package")
        self.assertEqual(package["reviewer_decisions"], [])
        self.assertEqual(len(package["items"]), 32)
        self.assertEqual(len({x["rule_id"] for x in package["items"]}), 32)
        self.assertTrue(all(x["human_review_status"] == "REQUIRED" for x in package["items"]))

    def test_generator_and_golden_validation_remain_unauthorized(self):
        report = load("qualification-report")
        completion = load("research-completion")
        self.assertEqual(report["status"], "ARCH_RULE_ACTIVATION_PARTIAL")
        self.assertEqual(report["generator_readiness"], "NOT_READY")
        self.assertEqual(report["metrics"]["release_ready_count"], 0)
        self.assertEqual(completion["primary_authority_closure"]["generator_gate"], "NOT_AUTHORIZED_FOR_HUMAN_GOLDEN_VALIDATION")
        self.assertFalse(completion["readiness"]["generator_implemented"])


if __name__ == "__main__":
    unittest.main()
