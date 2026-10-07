import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/rulebook/architecture"
SCHEMAS = ROOT / "standards/test-suites/residential"


def load(name):
    return json.loads((DATA / f"{name}.json").read_text())


class ArchitectureRulebookQualificationTests(unittest.TestCase):
    def test_every_catalog_matches_its_schema(self):
        for path in DATA.glob("*.json"):
            schema_path = SCHEMAS / f"{path.stem}.schema.json"
            self.assertTrue(schema_path.exists(), path.name)
            schema = json.loads(schema_path.read_text())
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(json.loads(path.read_text()))

    def test_all_32_candidates_are_individually_qualified_and_fail_closed(self):
        candidates = [r for r in load("rulebook")["rules"] if r["authority_type"] == "HARD_RULE"]
        self.assertEqual(len(candidates), 32)
        required = {
            "classification", "enforcement_level", "jurisdiction", "applicable_country",
            "applicability_expression", "inputs_required", "rule_logic", "source_authority",
            "source_clause", "source_page", "evidence_strength", "release_status",
        }
        for rule in candidates:
            with self.subTest(rule=rule["rule_id"]):
                self.assertTrue(required <= rule.keys())
                self.assertEqual(rule["classification"], "MANDATORY_NATIONAL")
                self.assertEqual(rule["enforcement_level"], "BLOCK")
                self.assertEqual(rule["release_status"], "SOURCE_GAP")
                self.assertFalse(rule["release_enabled"])
                self.assertIn(rule["evidence_strength"], {"A", "B"})

    def test_no_release_block_without_primary_or_strong_official_evidence(self):
        for rule in load("rulebook")["rules"]:
            if rule.get("release_status") == "RELEASE_READY" and rule.get("enforcement_level") == "BLOCK":
                self.assertIn(rule["evidence_strength"], {"A", "B"})
                self.assertTrue(rule["release_enabled"])

    def test_local_authority_never_becomes_a_national_default(self):
        local = [r for r in load("rulebook")["rules"] if r["source_id"] == "IR-LOCAL"]
        self.assertTrue(local)
        for rule in local:
            self.assertFalse(rule["release_enabled"])
            self.assertNotEqual(rule["authority_type"], "HARD_RULE")

    def test_source_gap_register_is_complete_and_traceable(self):
        gaps = load("source-gap-register")["gaps"]
        self.assertEqual(len(gaps), 24)
        self.assertEqual(len(gaps), len({g["gap_id"] for g in gaps}))
        self.assertTrue(any(g["severity"] == "CRITICAL" for g in gaps))
        self.assertTrue(all(g["status"] == "OPEN" for g in gaps))

    def test_owner_questions_are_explicit_choices_and_never_hidden_defaults(self):
        catalog = load("owner-questionnaire")
        self.assertEqual(len(catalog["questions"]), 58)
        summary = catalog["qualification_summary"]
        self.assertEqual(summary, {"total": 58, "keep": 13, "derive_automatically": 0, "remove": 0, "delay": 45})
        for q in catalog["questions"]:
            self.assertEqual(q["classification"], "OWNER_DECISION")
            self.assertEqual(q["enforcement_level"], "ASK_USER")
            self.assertFalse(q["default_allowed"])
            self.assertEqual(q["derivation_policy"], "DO_NOT_INFER_OWNER_INTENT")

    def test_qualification_guard_exists_for_every_candidate(self):
        rules = {r["rule_id"] for r in load("rulebook")["rules"] if r["authority_type"] == "HARD_RULE"}
        guards = {c["authority_ref"] for c in load("qa-matrix")["cases"] if c["group"] == "RULE_QUALIFICATION"}
        self.assertEqual(guards, rules)

    def test_golden_truth_is_independent_and_not_yet_claimed(self):
        matrix = load("golden-matrix")
        self.assertEqual(len(matrix["cases"]), 8)
        self.assertFalse(matrix["engine_output_may_create_truth"])
        self.assertTrue(all(c["status"] == "NOT_COLLECTED" for c in matrix["cases"]))

    def test_generator_readiness_remains_blocked(self):
        report = load("qualification-report")
        self.assertEqual(report["status"], "ARCHITECTURE_RULEBOOK_BLOCKED")
        self.assertEqual(report["generator_readiness"], "NOT_READY")
        self.assertEqual(report["metrics"]["release_ready_count"], 0)


if __name__ == "__main__":
    unittest.main()
