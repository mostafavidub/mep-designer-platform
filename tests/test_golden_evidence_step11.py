import hashlib
import os
import unittest
from copy import deepcopy
from unittest.mock import patch

from cad_engine.build_identity import build_identity
from cad_engine.mechanical_authority_site_v19 import _v19_payload
from cad_engine.submission_qa_v19 import (
    GOLDEN_PROJECTS,
    DEFAULT_BASELINE_PATH,
    assemble_golden_release_evidence,
    baseline_identity,
    build_golden_release_case,
    load_baseline,
    validate_golden_release_evidence,
)


def complete_evidence():
    baseline=load_baseline(DEFAULT_BASELINE_PATH)
    build=build_identity()
    cases=[]
    for pid in GOLDEN_PROJECTS:
        architecture_hash=hashlib.sha256(f"architecture-{pid}".encode()).hexdigest()
        score=float(baseline["scores"][str(pid)])
        blind={
            "project_id":pid,
            "reference_opened":False,
            "submission_state":"PASS",
            "submission_ready":True,
            "coordination_claim":"COORDINATED",
            "semantic_preview":{"networks":7,"identity_mismatches":0},
        }
        reference={
            "opened_before_seal":False,
            "metrics":{
                "system_completeness":score,
                "network_traceability":score,
                "calculation_consistency":score,
                "documentation_quality":score,
            },
        }
        cases.append(build_golden_release_case(
            pid,architecture_hash,blind,reference,
            semantic_diff={"status":"PASS","changes":[]},
            artifact_diff={"status":"PASS","changes":[]},
            build=build,
        ))
    return assemble_golden_release_evidence(cases,DEFAULT_BASELINE_PATH,build=build)


class GoldenEvidenceStep11Tests(unittest.TestCase):
    def test_complete_locked_build_bound_evidence_passes(self):
        evidence=complete_evidence()
        result=validate_golden_release_evidence(evidence)
        self.assertEqual(result["status"],"PASS",result)
        self.assertEqual(result["cohort"],list(GOLDEN_PROJECTS))
        self.assertEqual(result["pass_rate"],1.0)
        self.assertEqual(result["baseline_sha256"],baseline_identity()["sha256"])
        self.assertEqual(result["build_identity"],build_identity()["build_identity"])

    def test_status_only_pass_is_not_golden_evidence(self):
        result=validate_golden_release_evidence({"status":"PASS"})
        self.assertEqual(result["status"],"INPUT_REQUIRED")
        self.assertIn("golden_evidence:cases",result["missing_inputs"])

    def test_incomplete_cohort_is_release_blocking(self):
        evidence=complete_evidence(); evidence["cases"]=evidence["cases"][:-1]
        result=validate_golden_release_evidence(evidence)
        self.assertEqual(result["status"],"FAIL")
        self.assertIn("GOLDEN_CASE_SET_INCOMPLETE_OR_DUPLICATE",result["errors"])

    def test_baseline_hash_mismatch_is_release_blocking(self):
        evidence=complete_evidence(); evidence["baseline_sha256"]="0"*64
        result=validate_golden_release_evidence(evidence)
        self.assertEqual(result["status"],"FAIL")
        self.assertIn("GOLDEN_BASELINE_HASH_MISMATCH",result["errors"])

    def test_stale_or_foreign_build_evidence_is_release_blocking(self):
        evidence=complete_evidence(); evidence["commit_sha"]="1"*40
        result=validate_golden_release_evidence(evidence)
        self.assertEqual(result["status"],"FAIL")
        self.assertIn("GOLDEN_BUILD_BINDING_MISMATCH:commit_sha",result["errors"])

    def test_mutated_sealed_output_is_release_blocking(self):
        evidence=complete_evidence(); evidence["cases"][0]["blind_output"]["new_field"]="after-seal mutation"
        result=validate_golden_release_evidence(evidence)
        self.assertEqual(result["status"],"FAIL")
        self.assertTrue(any("SEAL_INVALID_OR_OUTPUT_MUTATED" in e for e in result["errors"]))

    def test_pre_submission_preview_cannot_be_release_evidence(self):
        evidence=complete_evidence(); case=evidence["cases"][0]
        # Rebuild the case so the PRE_SUBMISSION state is genuinely inside the seal.
        baseline=load_baseline(DEFAULT_BASELINE_PATH); build=build_identity(); pid=case["project_id"]
        score=float(baseline["scores"][str(pid)])
        case2=build_golden_release_case(
            pid,case["input_hash"],
            {"project_id":pid,"reference_opened":False,"submission_state":"PRE_SUBMISSION","submission_ready":False,"coordination_claim":"NOT_COORDINATED"},
            {"opened_before_seal":False,"metrics":{k:score for k in ("system_completeness","network_traceability","calculation_consistency","documentation_quality")}},
            {"status":"PASS"},{"status":"PASS"},build=build,
        )
        evidence["cases"][0]=case2
        result=validate_golden_release_evidence(evidence)
        self.assertEqual(result["status"],"FAIL")
        self.assertIn(f"PROJECT_{pid}_NOT_SUBMISSION_READY",result["errors"])

    def test_semantic_or_artifact_diff_must_pass(self):
        for field in ("semantic_diff","artifact_diff"):
            with self.subTest(field=field):
                evidence=complete_evidence(); evidence["cases"][0][field]={"status":"FAIL"}
                result=validate_golden_release_evidence(evidence)
                self.assertEqual(result["status"],"FAIL")
                token="SEMANTIC_DIFF_NOT_PASS" if field=="semantic_diff" else "ARTIFACT_DIFF_NOT_PASS"
                self.assertTrue(any(token in e for e in result["errors"]))

    def test_claimed_strict_score_is_recomputed_not_trusted(self):
        evidence=complete_evidence(); evidence["cases"][0]["strict_score"]={"status":"PASS","score":100.0}
        result=validate_golden_release_evidence(evidence)
        self.assertEqual(result["status"],"FAIL")
        self.assertTrue(any("STRICT_SCORE_MISMATCH" in e for e in result["errors"]))

    def test_environment_pass_can_no_longer_supply_production_golden_evidence(self):
        answers={"_v19_input_contract":{}}
        with patch.dict(os.environ,{"MECHANICAL_V19_GOLDEN_STATUS":"PASS"}):
            payload=_v19_payload(answers,{})
        self.assertIsNone(payload["golden_result"])

    def test_explicit_contract_evidence_is_forwarded_unchanged(self):
        evidence=complete_evidence(); answers={"_v19_input_contract":{"golden_release_evidence":evidence}}
        payload=_v19_payload(answers,{})
        self.assertIs(payload["golden_result"],evidence)


if __name__=="__main__":
    unittest.main()
