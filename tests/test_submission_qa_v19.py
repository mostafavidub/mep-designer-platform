import json, unittest
from pathlib import Path
from cad_engine.submission_qa_v19 import GOLDEN_PROJECTS, seal_blind_output, strict_score, run_golden_regression, run_pre_submission_regression, submission_gate


METRICS = {"system_completeness":100,"network_traceability":100,"calculation_consistency":100,"documentation_quality":100}


class SubmissionQAV19Tests(unittest.TestCase):
    def test_reference_cannot_be_present_at_seal_time(self):
        with self.assertRaises(ValueError): seal_blind_output(1,"a"*64,{"reference_opened":True})

    def test_mutation_after_seal_is_detected(self):
        output={"submission_state":"PASS"}; seal=seal_blind_output(1,"a"*64,output); output["changed"]=True
        self.assertEqual(strict_score(seal,output,{"metrics":METRICS})["status"],"FAIL")

    def test_input_required_is_visible_in_strict_score(self):
        output={"submission_state":"INPUT_REQUIRED"}; seal=seal_blind_output(1,"a"*64,output)
        result=strict_score(seal,output,{"metrics":METRICS})
        self.assertEqual(result["score"],85.0); self.assertEqual(result["penalties"],[15.0])

    def test_seven_project_regression_passes_locked_thresholds(self):
        baseline=json.loads((Path(__file__).parents[1]/"standards/golden/seven-project-v19.baseline.json").read_text())
        cases=[]
        for pid in GOLDEN_PROJECTS:
            output={"project_id":pid,"submission_state":"PASS"}
            cases.append({"project_id":pid,"blind_output":output,"seal":seal_blind_output(pid,str(pid)*64,output),"post_seal_reference":{"metrics":METRICS}})
        result=run_golden_regression(cases,baseline)
        self.assertEqual(result["status"],"PASS"); self.assertEqual(result["pass_rate"],1.0)

    def test_regression_and_non_pass_phase_block_release(self):
        output={"submission_state":"PASS"}; case={"project_id":1,"blind_output":output,"seal":seal_blind_output(1,"a"*64,output),"post_seal_reference":{"metrics":{k:50 for k in METRICS}}}
        self.assertEqual(run_golden_regression([case],{"scores":{"1":84.5}})["status"],"FAIL")
        self.assertFalse(submission_gate({"coordination":{"status":"INPUT_REQUIRED"},"manufacturer":{"status":"PASS"},"documentation":{"status":"PASS"},"golden":{"status":"PASS"}})["release_allowed"])

    def test_architecture_only_profile_passes_without_becoming_submission_ready(self):
        baseline=json.loads((Path(__file__).parents[1]/"standards/golden/seven-project-v19.baseline.json").read_text())
        cases=[]
        for pid in GOLDEN_PROJECTS:
            output={"project_id":pid,"submission_state":"PRE_SUBMISSION","submission_ready":False,
                    "coordination_claim":"NOT_COORDINATED","missing_inputs":["STRUCTURAL_MODEL","RCP_MODEL"]}
            cases.append({"project_id":pid,"blind_output":output,"seal":seal_blind_output(pid,"a"*64,output),
                          "post_seal_reference":{"metrics":{key:80 for key in METRICS}}})
        result=run_pre_submission_regression(cases,baseline)
        self.assertEqual(result["status"],"PASS")
        self.assertFalse(result["submission_ready"])
        self.assertTrue(all(row["strict_score"]["status"]=="PRE_SUBMISSION" for row in result["results"]))


if __name__ == "__main__": unittest.main()
