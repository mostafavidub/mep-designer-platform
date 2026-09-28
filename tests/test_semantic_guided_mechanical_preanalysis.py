import copy
import unittest

from cad_engine.semantic_guided_mechanical_preanalysis import (
    SemanticArtifactRejected, build_search_plan, run_shadow_ab,
)

SHA="a"*64; FRAME="FRAME-1"; COMMIT="f7c09e3"

def artifact():
    return {"schema":"fasihi-mep-preanalysis-qualification/1.0","source_sha256":SHA,"frame_id":FRAME,"render_sha256":"r",
      "anchors":[{"semantic_anchor_id":"A1"}],
      "hints":[
        {"semantic_hint_id":"H1","semantic_type":"TOILET","approx_bbox_norm":[.1,.1,.3,.3],"authority":"VISION_SEMANTIC_HINT","semantic_status":"EXACT_ANCHOR_SUPPORTED","exact_anchor_ids":["A1"]},
        {"semantic_hint_id":"H2","semantic_type":"KITCHEN","approx_bbox_norm":[.5,.5,.7,.7],"authority":"VISION_SEMANTIC_HINT","semantic_status":"VISION_ONLY"},
        {"semantic_hint_id":"BAD","semantic_type":"PARKING","approx_bbox_norm":[.2,.2,.8,.8],"authority":"VISION_SEMANTIC_HINT"}],
      "fusion":{"conflicts":[{"semantic_hint_id":"BAD"}]}}

def manifest(): return {"source_sha256":SHA,"frame_id":FRAME,"transform":{"cad_bounds":[0,0,100,100]}}

class ShadowTests(unittest.TestCase):
    def plan(self): return build_search_plan(artifact(),manifest(),source_sha256=SHA,frame_id=FRAME,dependency_commit=COMMIT,expected_dependency_commit=COMMIT,render_sha256="r")
    def test_plan_is_deterministic_bounded_and_conflict_excluded(self):
        a=self.plan(); b=self.plan()
        self.assertEqual(a["search_plan_hash"],b["search_plan_hash"])
        self.assertEqual([z["semantic_type"] for z in a["search_zones"]],["TOILET","KITCHEN"])
        self.assertLess(a["search_zones"][0]["priority"],a["search_zones"][1]["priority"])
        self.assertTrue(all(z["authority"]=="SEARCH_PRIORITY_ONLY" and not z["engineering_geometry"] for z in a["search_zones"]))
    def test_stale_source_wrong_frame_commit_and_bad_bbox_fail_closed(self):
        args=dict(artifact=artifact(),render_manifest=manifest(),source_sha256=SHA,frame_id=FRAME,dependency_commit=COMMIT,expected_dependency_commit=COMMIT,render_sha256="r")
        for key,value in (("source_sha256","b"*64),("frame_id","OTHER"),("dependency_commit","old")):
            bad=dict(args); bad[key]=value
            with self.assertRaises(SemanticArtifactRejected): build_search_plan(**bad)
        bad_art=artifact(); bad_art["hints"][0]["approx_bbox_norm"]=[-.1,0,.2,.2]
        with self.assertRaises(SemanticArtifactRejected): build_search_plan(bad_art,manifest(),source_sha256=SHA,frame_id=FRAME,dependency_commit=COMMIT,expected_dependency_commit=COMMIT,render_sha256="r")
    def test_priority_changes_order_only_and_global_fallback_preserves_recall(self):
        arch={"rooms":[],"all_texts":[],"all_inserts":[
          {"name":"unknown","layer":"0","point":[90,90]},
          {"name":"SINK","layer":"FIXTURE","point":[20,80]},
          {"name":"WC","layer":"FIXTURE","point":[80,20]}]}
        report=run_shadow_ab(arch,self.plan())
        self.assertEqual(report["baseline_detection_recall_in_b"],1.0)
        self.assertEqual(report["assisted"]["priority_entities_examined"]+report["assisted"]["fallback_entities_examined"],3)
        self.assertFalse(report["missed_baseline_signatures"])
        self.assertTrue(all(v==0 for v in report["authority_leak_counts"].values()))
    def test_missing_semantic_baseline_still_operates(self):
        arch={"rooms":[],"all_texts":[],"all_inserts":[{"name":"WC","layer":"FIXTURE","point":[1,1]}]}
        plan=self.plan(); plan["search_zones"]=[]
        report=run_shadow_ab(arch,plan)
        self.assertEqual(report["baseline_detection_recall_in_b"],1.0)
        self.assertEqual(report["assisted"]["fallback_entities_examined"],1)

if __name__=="__main__": unittest.main()
