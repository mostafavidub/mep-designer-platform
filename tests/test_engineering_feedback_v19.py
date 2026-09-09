import unittest

from cad_engine.engineering_feedback_v19 import process_engineer_redlines


def review(redlines):
    return {"reviewer_id":"ENG-INDEPENDENT-1", "review_evidence_sha256":"a"*64, "redlines":redlines}


class EngineeringFeedbackV19Tests(unittest.TestCase):
    def test_categories_route_without_project_overfit(self):
        rows=[
            {"project_id":10,"sheet_id":"M-101","category":"project-specific","severity":"minor","summary":"Owner preference","status":"open"},
            {"project_id":10,"sheet_id":"M-111","category":"rulebook deficiency","severity":"major","summary":"Missing generic valve rule","status":"resolved","rule_id":"MEP-WATER-009","regression_test":"tests/test_water.py::test_valve"},
            {"project_id":10,"sheet_id":"M-161","category":"engine bug","severity":"critical","summary":"Route identity lost","status":"resolved","reproduction":"fixture-v1","regression_test":"tests/test_route.py::test_identity"},
        ]
        result=process_engineer_redlines(review(rows))
        self.assertEqual(result["status"],"PASS")
        self.assertEqual(result["project_specific"][0]["promotion_policy"],"PROJECT_ONLY_DO_NOT_PROMOTE")
        self.assertEqual(len(result["rulebook_updates"]),1)
        self.assertEqual(len(result["engine_regressions"]),1)

    def test_missing_review_and_ungoverned_reusable_findings_fail_closed(self):
        self.assertEqual(process_engineer_redlines(None)["status"],"INPUT_REQUIRED")
        row={"project_id":1,"sheet_id":"M-101","category":"rulebook deficiency","severity":"major","summary":"Gap","status":"open"}
        result=process_engineer_redlines(review([row]))
        self.assertEqual(result["status"],"FAIL")
        self.assertTrue(any("RULEBOOK_REDLINE_GOVERNANCE_MISSING" in error for error in result["errors"]))

    def test_open_major_redline_blocks(self):
        row={"project_id":1,"sheet_id":"M-101","category":"project-specific","severity":"major","summary":"Unsafe access","status":"open"}
        result=process_engineer_redlines(review([row]))
        self.assertEqual(result["status"],"FAIL")
        self.assertEqual(result["open_major_redlines"],1)


if __name__ == "__main__": unittest.main()
