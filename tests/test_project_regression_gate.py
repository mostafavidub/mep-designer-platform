from copy import deepcopy
from cad_engine.project_regression_gate import CRITICAL, evaluate_project_regression, numeric_diff, seal_inputs

def valid():
 artifacts={k:k for k in ("dxf","pdf","calculations","schedules","manifest","qa","renders")}
 comparison={k:{"status":"PASS","failures":[]} for k in ("manifest_scope","graph_identity","independent_recalculation","architecture_preservation","exact_dxf","sheet_visual","destructive_metamorphic","performance_recovery")}
 comparison["engineering_numeric"]={"status":"PASS","tolerances":{"loads.room_1":0.01},"differences":[]}
 scores={"architecture":90,"calculations":90,"routing":90,"documentation":90,"visual":90,"issuance":90}
 case={"case_id":"CASE-A","input_seal":seal_inputs("a"*64,{"city":"X"},[{"code":"M-1"}],"b"*64,"c"*64),
       "reference_order":["ARCHITECTURE_INPUT","GENERATE","SEAL_OUTPUT","UNSEAL_REFERENCE","COMPARE"],"reference_used_for_generation":False,
       "build":{"commit_sha":"abc","dependency_hash":"d"*64,"runtime_identity":"canonical"},
       "runs":[{"semantic_hash":"s","artifact_hashes":artifacts},{"semantic_hash":"s","artifact_hashes":artifacts}],"comparison":comparison,
       "baseline":{"critical_pass":sorted(CRITICAL),"scores":deepcopy(scores)},"candidate":{"critical_pass":sorted(CRITICAL),"scores":deepcopy(scores)}}
 return {"cohorts":{"development":["CASE-A"],"validation":["CASE-B"],"sealed_evaluation":["CASE-C"]},"cases":[case],"candidate_commit_sha":"abc","staging":{"status":"PASS","commit_sha":"abc","e2e_status":"PASS","artifact_hash":"e"*64}}

def test_complete_project_regression_scores_100():
 r=evaluate_project_regression(valid());assert r["status"]=="PASS" and r["score"]==100 and r["release_allowed"]

def test_reference_leakage_and_nondeterminism_block_release():
 c=valid();x=c["cases"][0];x["reference_used_for_generation"]=True;x["runs"][1]["semantic_hash"]="other"
 r=evaluate_project_regression(c);assert r["status"]=="FAIL" and not r["release_allowed"]
 assert any("REFERENCE_ORDER_VIOLATION" in e for e in r["errors"]) and any("NONDETERMINISTIC" in e for e in r["errors"])

def test_one_project_regression_cannot_hide_behind_average():
 c=valid();c["cases"][0]["candidate"]["scores"]["visual"]=89
 r=evaluate_project_regression(c);assert "CASE-A:PROJECT_SCORE_REGRESSION" in r["errors"]

def test_critical_gate_regression_always_blocks():
 c=valid();c["cases"][0]["candidate"]["critical_pass"].remove("architecture_preservation")
 assert "CASE-A:CRITICAL_GATE_REGRESSION" in evaluate_project_regression(c)["errors"]

def test_numeric_diff_requires_declared_tolerance_and_detects_drift():
 assert numeric_diff({"load":10.0},{"load":10.2},{"load":0.1})[0]["reason"]=="OUTSIDE_TOLERANCE"
 assert numeric_diff({"load":10.0},{"load":10.0},{})[0]["reason"]=="TOLERANCE_UNDECLARED"

def test_input_tamper_and_wrong_staging_sha_fail_closed():
 c=valid();c["cases"][0]["input_seal"]["answers_hash"]="tampered";c["staging"]["commit_sha"]="old"
 r=evaluate_project_regression(c);assert any("INPUT_SEAL_INVALID" in e for e in r["errors"]);assert "STAGING_EXACT_BUILD_E2E_NOT_PASS" in r["errors"]

def test_missing_second_run_and_artifacts_are_input_required():
 c=valid();c["cases"][0]["runs"]=[{"semantic_hash":"s","artifact_hashes":{}}]
 r=evaluate_project_regression(c);assert r["status"]=="INPUT_REQUIRED" and not r["release_allowed"]
