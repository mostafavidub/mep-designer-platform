import unittest

from cad_engine.quality_acceptance_v19 import evaluate_quality_targets


def metrics():
    return {"structural_mep_clashes":0,"routing_warnings":0,"unapproved_penetrations":0,
            "manufacturer_violations":0,"missing_required_details":0,
            "plan_riser_schedule_mismatches":0,"major_redlines":0,
            "route_efficiency_percent":90,"equipment_placement_score":90,
            "detail_completeness_percent":95,"package_average_score":90,
            "main_plan_scores":{"M-101":85,"M-111":92}}


class QualityAcceptanceV19Tests(unittest.TestCase):
    def test_exact_boundary_targets_pass(self):
        result=evaluate_quality_targets(metrics())
        self.assertEqual(result["status"],"PASS")
        self.assertTrue(result["accepted"])

    def test_missing_metric_is_input_required(self):
        value=metrics(); value.pop("route_efficiency_percent")
        self.assertEqual(evaluate_quality_targets(value)["status"],"INPUT_REQUIRED")

    def test_each_threshold_and_each_plan_are_blocking(self):
        value=metrics(); value["route_efficiency_percent"]=89.99
        self.assertEqual(evaluate_quality_targets(value)["status"],"FAIL")
        value=metrics(); value["main_plan_scores"]["M-111"]=84.99
        result=evaluate_quality_targets(value)
        self.assertEqual(result["status"],"FAIL")
        self.assertIn("MAIN_PLAN_SCORE_BELOW_85:M-111",result["errors"])

    def test_nonzero_major_redline_blocks(self):
        value=metrics(); value["major_redlines"]=1
        self.assertEqual(evaluate_quality_targets(value)["status"],"FAIL")


if __name__ == "__main__": unittest.main()
