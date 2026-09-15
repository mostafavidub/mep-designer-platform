"""Project-level deterministic, blind and fail-closed regression authority."""
from __future__ import annotations
from hashlib import sha256
import json, math

CONTRACT="mechanical-project-regression/1"
WEIGHTS={
 "cohort_isolation":4,"input_answer_seal":6,"reference_blind_order":6,"build_runtime_lock":5,
 "repeat_determinism":7,"artifact_retention":4,"manifest_scope_parity":5,"graph_identity_parity":7,
 "engineering_numeric_parity":8,"independent_recalculation":7,"architecture_preservation":7,
 "exact_dxf_semantic_diff":7,"sheet_visual_diff":6,"destructive_metamorphic_suite":5,
 "performance_recovery":4,"critical_gate_nonregression":5,"per_project_score_nonregression":4,
 "staging_exact_build_e2e":3,
}
assert len(WEIGHTS)==18 and sum(WEIGHTS.values())==100
CRITICAL={"manifest_scope_parity","graph_identity_parity","independent_recalculation","architecture_preservation","exact_dxf_semantic_diff","critical_gate_nonregression"}

def stable(value):
 raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)
 return sha256(raw.encode()).hexdigest()

def seal_inputs(architecture_sha256, answers, manifest, rulebook_hash, manufacturer_hash):
 record={"architecture_sha256":architecture_sha256,"answers_hash":stable(answers),"manifest_hash":stable(manifest),"rulebook_hash":rulebook_hash,"manufacturer_hash":manufacturer_hash}
 record["seal_hash"]=stable(record);return record

def numeric_diff(baseline,candidate,tolerances,path=""):
 """Return every numeric drift outside its declared engineering tolerance."""
 differences=[]
 if isinstance(baseline,dict) and isinstance(candidate,dict):
  for key in sorted(set(baseline)|set(candidate)):
   p=f"{path}.{key}" if path else key
   if key not in baseline or key not in candidate:differences.append({"path":p,"reason":"MISSING_SIDE"})
   else:differences.extend(numeric_diff(baseline[key],candidate[key],tolerances,p))
 elif isinstance(baseline,list) and isinstance(candidate,list):
  if len(baseline)!=len(candidate):differences.append({"path":path,"reason":"LENGTH","baseline":len(baseline),"candidate":len(candidate)})
  for i,(left,right) in enumerate(zip(baseline,candidate)):differences.extend(numeric_diff(left,right,tolerances,f"{path}[{i}]"))
 elif isinstance(baseline,(int,float)) and not isinstance(baseline,bool) and isinstance(candidate,(int,float)) and not isinstance(candidate,bool):
  tolerance=tolerances.get(path)
  if tolerance is None:differences.append({"path":path,"reason":"TOLERANCE_UNDECLARED"})
  elif not all(math.isfinite(float(x)) for x in (baseline,candidate,tolerance)):differences.append({"path":path,"reason":"NON_FINITE"})
  elif abs(float(candidate)-float(baseline))>float(tolerance):differences.append({"path":path,"reason":"OUTSIDE_TOLERANCE","baseline":baseline,"candidate":candidate,"tolerance":tolerance})
 elif baseline!=candidate:differences.append({"path":path,"reason":"VALUE","baseline":baseline,"candidate":candidate})
 return differences

def evaluate_project_regression(context):
 """Score one or more project cases. Evidence is required; PASS is never inferred."""
 c=context or {};missing={k:[] for k in WEIGHTS};errors={k:[] for k in WEIGHTS};cases=c.get("cases") or []
 cohorts=c.get("cohorts") or {}
 sets=[set(cohorts.get(k) or []) for k in ("development","validation","sealed_evaluation")]
 if not all(sets):missing["cohort_isolation"].append("THREE_NONEMPTY_COHORTS")
 elif any(sets[i]&sets[j] for i in range(3) for j in range(i+1,3)):errors["cohort_isolation"].append("COHORT_LEAKAGE")
 if not cases:missing["input_answer_seal"].append("REGRESSION_CASES")
 for case in cases:
  cid=str(case.get("case_id") or "UNKNOWN");seal=case.get("input_seal") or {}
  if not seal.get("seal_hash") or seal.get("seal_hash")!=stable({k:v for k,v in seal.items() if k!="seal_hash"}):errors["input_answer_seal"].append(f"{cid}:INPUT_SEAL_INVALID")
  order=case.get("reference_order") or []
  if order!=["ARCHITECTURE_INPUT","GENERATE","SEAL_OUTPUT","UNSEAL_REFERENCE","COMPARE"] or case.get("reference_used_for_generation") is not False:errors["reference_blind_order"].append(f"{cid}:REFERENCE_ORDER_VIOLATION")
  build=case.get("build") or {}
  if not build.get("commit_sha") or not build.get("dependency_hash") or not build.get("runtime_identity"):missing["build_runtime_lock"].append(f"{cid}:BUILD_RUNTIME_IDENTITY")
  runs=case.get("runs") or []
  if len(runs)<2:missing["repeat_determinism"].append(f"{cid}:TWO_RUNS_REQUIRED")
  elif len({r.get("semantic_hash") for r in runs})!=1 or any(not r.get("semantic_hash") for r in runs):errors["repeat_determinism"].append(f"{cid}:NONDETERMINISTIC_OUTPUT")
  required_artifacts={"dxf","pdf","calculations","schedules","manifest","qa","renders"}
  if not runs or any(set(r.get("artifact_hashes") or {})!=required_artifacts for r in runs):missing["artifact_retention"].append(f"{cid}:COMPLETE_ARTIFACT_SET")
  comparison=case.get("comparison") or {}
  gates={
   "manifest_scope_parity":"manifest_scope","graph_identity_parity":"graph_identity",
   "independent_recalculation":"independent_recalculation","architecture_preservation":"architecture_preservation",
   "exact_dxf_semantic_diff":"exact_dxf","sheet_visual_diff":"sheet_visual",
   "destructive_metamorphic_suite":"destructive_metamorphic","performance_recovery":"performance_recovery",
  }
  for control,evidence in gates.items():
   row=comparison.get(evidence) or {}
   if row.get("status")!="PASS" or row.get("failures"):errors[control].append(f"{cid}:{evidence.upper()}_NOT_PASS")
  numeric=comparison.get("engineering_numeric") or {}
  if not numeric.get("tolerances") or numeric.get("status")!="PASS" or numeric.get("differences"):errors["engineering_numeric_parity"].append(f"{cid}:NUMERIC_PARITY_NOT_PASS")
  baseline=case.get("baseline") or {};candidate=case.get("candidate") or {}
  critical=set(baseline.get("critical_pass") or [])
  if not CRITICAL<=critical or not critical<=set(candidate.get("critical_pass") or []):errors["critical_gate_nonregression"].append(f"{cid}:CRITICAL_GATE_REGRESSION")
  bs=baseline.get("scores") or {};cs=candidate.get("scores") or {}
  if not bs or set(bs)!=set(cs):missing["per_project_score_nonregression"].append(f"{cid}:COMPARABLE_SCORE_VECTOR")
  elif any(float(cs[k])<float(bs[k]) for k in bs):errors["per_project_score_nonregression"].append(f"{cid}:PROJECT_SCORE_REGRESSION")
 stage=c.get("staging") or {}
 if stage.get("status")!="PASS" or stage.get("commit_sha")!=c.get("candidate_commit_sha") or stage.get("e2e_status")!="PASS" or not stage.get("artifact_hash"):errors["staging_exact_build_e2e"].append("STAGING_EXACT_BUILD_E2E_NOT_PASS")
 controls=[]
 for name,w in WEIGHTS.items():
  status="FAIL" if errors[name] else ("INPUT_REQUIRED" if missing[name] else "PASS")
  controls.append({"id":name,"weight":w,"status":status,"errors":sorted(set(errors[name])),"missing_inputs":sorted(set(missing[name]))})
 score=sum(x["weight"] for x in controls if x["status"]=="PASS");status="FAIL" if any(x["status"]=="FAIL" for x in controls) else ("INPUT_REQUIRED" if any(x["status"]=="INPUT_REQUIRED" for x in controls) else "PASS")
 failed_projects=sorted({e.split(":",1)[0] for x in controls for e in x["errors"] if ":" in e})
 return {"contract":CONTRACT,"status":status,"score":score,"release_allowed":status=="PASS" and score==100,"controls":controls,"failed_projects":failed_projects,
         "errors":sorted({e for x in controls for e in x["errors"]}),"missing_inputs":sorted({e for x in controls for e in x["missing_inputs"]}),"evidence_hash":stable(c)}
