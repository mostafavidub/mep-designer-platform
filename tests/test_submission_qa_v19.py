import json, unittest
from pathlib import Path
from cad_engine.submission_qa_v19 import (GOLDEN_PROJECTS, SUBMISSION_ZERO_CHECKS, compare_outputs,
    evaluate_submission_readiness, run_golden_regression, run_pre_submission_regression,
    seal_blind_output, strict_score, submission_gate)


METRICS = {"system_completeness":100,"network_traceability":100,"calculation_consistency":100,"documentation_quality":100}
OUTPUT = {"submission_state":"PASS","semantics":["plan_riser_identity"],
          "artifacts":{"M-101":{"family":"plan","entities":10}},"numeric":{"flow_lps":1.0}}
CONTRACT = {"semantic":{"required":["plan_riser_identity"]},
            "artifact":{"inventory":{"M-101":{"family":"plan","entities":10}}},
            "numeric":{"values":{"flow_lps":1.0},"tolerances":{"flow_lps":{"absolute":0.01,"rule_id":"MEP-SIZE-001"}}}}


def reference(metrics=METRICS):
    return {"metrics":metrics,"comparison_contract":CONTRACT}


class SubmissionQAV19Tests(unittest.TestCase):
    def test_reference_cannot_be_present_at_seal_time(self):
        with self.assertRaises(ValueError): seal_blind_output(1,"a"*64,{"reference_opened":True})

    def test_mutation_after_seal_is_detected(self):
        output={"submission_state":"PASS"}; seal=seal_blind_output(1,"a"*64,output); output["changed"]=True
        self.assertEqual(strict_score(seal,output,reference())["status"],"FAIL")

    def test_input_required_is_visible_in_strict_score(self):
        output={**OUTPUT,"submission_state":"INPUT_REQUIRED"}; seal=seal_blind_output(1,"a"*64,output)
        result=strict_score(seal,output,reference())
        self.assertEqual(result["score"],85.0); self.assertEqual(result["penalties"],[15.0])

    def test_seven_project_regression_passes_locked_thresholds(self):
        baseline=json.loads((Path(__file__).parents[1]/"standards/golden/seven-project-v19.baseline.json").read_text())
        cases=[]
        for pid in GOLDEN_PROJECTS:
            output={**OUTPUT,"project_id":pid}
            cases.append({"project_id":pid,"blind_output":output,"seal":seal_blind_output(pid,str(pid)*64,output),
                          "generation_mode":"BLIND_ARCHITECTURE_ONLY","sealed_at":1,"reference_opened_at":2,
                          "post_seal_reference":reference()})
        result=run_golden_regression(cases,baseline)
        self.assertEqual(result["status"],"PASS"); self.assertEqual(result["pass_rate"],1.0)

    def test_regression_and_non_pass_phase_block_release(self):
        output=dict(OUTPUT); case={"project_id":1,"blind_output":output,"seal":seal_blind_output(1,"a"*64,output),"post_seal_reference":reference({k:50 for k in METRICS})}
        self.assertEqual(run_golden_regression([case],{"scores":{"1":84.5}})["status"],"FAIL")
        self.assertFalse(submission_gate({"coordination":{"status":"INPUT_REQUIRED"},"manufacturer":{"status":"PASS"},"documentation":{"status":"PASS"},"golden":{"status":"PASS"}})["release_allowed"])

    def test_submission_ready_requires_explicit_zero_for_all_ten_checks(self):
        self.assertEqual(evaluate_submission_readiness(None)["status"],"INPUT_REQUIRED")
        checks={name:0 for name in SUBMISSION_ZERO_CHECKS}
        self.assertTrue(evaluate_submission_readiness(checks)["submission_ready"])
        checks["unapproved_penetrations"]=1
        failed=evaluate_submission_readiness(checks)
        self.assertEqual(failed["status"],"FAIL")
        self.assertFalse(failed["submission_ready"])

    def test_golden_requires_proven_blind_order_and_unique_locked_cohort(self):
        cases=[]
        for pid in GOLDEN_PROJECTS:
            output={**OUTPUT,"project_id":pid}
            cases.append({"project_id":pid,"blind_output":output,"seal":seal_blind_output(pid,str(pid)*64,output),
                          "generation_mode":"BLIND_ARCHITECTURE_ONLY","sealed_at":2,"reference_opened_at":1,
                          "post_seal_reference":reference()})
        result=run_golden_regression(cases,{"private_drawings_stored":False,"scores":{str(p):100 for p in GOLDEN_PROJECTS}})
        self.assertEqual(result["status"],"FAIL")
        self.assertTrue(any("REFERENCE_ORDER_INVALID" in error for error in result["errors"]))

    def test_architecture_only_profile_passes_without_becoming_submission_ready(self):
        baseline=json.loads((Path(__file__).parents[1]/"standards/golden/seven-project-v19.baseline.json").read_text())
        cases=[]
        for pid in GOLDEN_PROJECTS:
            output={**OUTPUT,"project_id":pid,"submission_state":"PRE_SUBMISSION","submission_ready":False,
                    "coordination_claim":"NOT_COORDINATED","missing_inputs":["STRUCTURAL_MODEL","RCP_MODEL"]}
            cases.append({"project_id":pid,"blind_output":output,"seal":seal_blind_output(pid,"a"*64,output),
                          "post_seal_reference":reference({key:80 for key in METRICS})})
        result=run_pre_submission_regression(cases,baseline)
        self.assertEqual(result["status"],"PASS")
        self.assertFalse(result["submission_ready"])
        self.assertTrue(all(row["strict_score"]["status"]=="PRE_SUBMISSION" for row in result["results"]))

    def test_semantic_artifact_and_numeric_diffs_are_blocking(self):
        missing_semantic={**OUTPUT,"semantics":[]}
        self.assertEqual(compare_outputs(missing_semantic,{"comparison_contract":CONTRACT})["status"],"FAIL")
        changed_artifact={**OUTPUT,"artifacts":{"M-101":{"family":"plan","entities":9}}}
        self.assertEqual(compare_outputs(changed_artifact,{"comparison_contract":CONTRACT})["status"],"FAIL")
        numeric={**OUTPUT,"numeric":{"flow_lps":1.02}}
        self.assertEqual(compare_outputs(numeric,{"comparison_contract":CONTRACT})["status"],"FAIL")

    def test_missing_or_ungoverned_diff_contract_is_input_required(self):
        self.assertEqual(compare_outputs(OUTPUT,{})["status"],"INPUT_REQUIRED")
        bad=json.loads(json.dumps(CONTRACT)); bad["numeric"]["tolerances"]["flow_lps"].pop("rule_id")
        self.assertEqual(compare_outputs(OUTPUT,{"comparison_contract":bad})["status"],"INPUT_REQUIRED")


if __name__ == "__main__": unittest.main()
