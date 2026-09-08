"""Submission gate and sealed, blind seven-project golden regression."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .build_identity import build_identity


GOLDEN_PROJECTS = (1, 3, 4, 6, 7, 8, 10)
DEFAULT_THRESHOLDS = {"minimum_score": 70.0, "maximum_drop": 0.0, "required_pass_rate": 1.0}
GOLDEN_RELEASE_SCHEMA = "seven-project-golden-release/2.0"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE_PATH = ROOT / "standards" / "golden" / "seven-project-v19.baseline.json"


def _bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _hex64(value: Any) -> bool:
    text=str(value or "").strip().lower()
    return len(text)==64 and all(ch in "0123456789abcdef" for ch in text)


def baseline_identity(path: str | Path = DEFAULT_BASELINE_PATH) -> dict[str,Any]:
    path=Path(path); raw=path.read_bytes(); baseline=json.loads(raw.decode("utf-8"))
    return {"path":str(path),"sha256":sha256(raw).hexdigest(),"baseline":baseline}


def seal_blind_output(project_id: int, architecture_hash: str, output: dict) -> dict:
    if project_id not in GOLDEN_PROJECTS:
        raise ValueError("project is not in the locked golden cohort")
    if output.get("reference_opened") or output.get("reference_inputs"):
        raise ValueError("blind output is contaminated by reference data")
    payload = {"project_id": project_id, "architecture_hash": architecture_hash, "output": output}
    return {"schema":"blind-seal/1.0", "project_id":project_id, "architecture_hash":architecture_hash,
            "output_hash":sha256(_bytes(output)).hexdigest(), "seal_hash":sha256(_bytes(payload)).hexdigest(),
            "sealed_before_reference":True}


def verify_seal(seal: dict, output: dict) -> bool:
    return bool(seal.get("sealed_before_reference")) and seal.get("output_hash") == sha256(_bytes(output)).hexdigest()


def strict_score(seal: dict, blind_output: dict, post_seal_reference: dict) -> dict:
    if not verify_seal(seal, blind_output):
        return {"status":"FAIL", "score":0.0, "errors":["INVALID_OR_MUTATED_SEAL"]}
    if post_seal_reference.get("opened_before_seal"):
        return {"status":"FAIL", "score":0.0, "errors":["REFERENCE_LEAKAGE"]}
    metrics = post_seal_reference.get("metrics") or {}
    required = {"system_completeness", "network_traceability", "calculation_consistency", "documentation_quality"}
    if required - metrics.keys():
        return {"status":"INPUT_REQUIRED", "score":0.0, "errors":["REFERENCE_METRICS_MISSING"]}
    values = [float(metrics[key]) for key in sorted(required)]
    if any(value < 0 or value > 100 for value in values):
        return {"status":"FAIL", "score":0.0, "errors":["METRIC_OUT_OF_RANGE"]}
    score = round(sum(values) / len(values), 2)
    penalties = []
    state = blind_output.get("submission_state")
    if state == "INPUT_REQUIRED": penalties.append(15.0)
    elif state == "PRE_SUBMISSION": penalties.append(5.0)
    score = round(max(0.0, score - sum(penalties)), 2)
    score_status = state if state in {"INPUT_REQUIRED", "PRE_SUBMISSION"} else "PASS"
    return {"status":score_status, "score":score, "raw_score":round(sum(values)/len(values), 2),
            "penalties":penalties, "reference_opened_post_seal":True}


def run_golden_regression(cases: list[dict], baseline: dict, thresholds: dict | None = None) -> dict:
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or baseline.get("thresholds") or {})}
    errors, results = [], []
    ids = sorted(case.get("project_id") for case in cases)
    if ids != list(GOLDEN_PROJECTS): errors.append("GOLDEN_COHORT_INCOMPLETE")
    for case in cases:
        result = strict_score(case["seal"], case["blind_output"], case["post_seal_reference"])
        prior = float((baseline.get("scores") or {}).get(str(case["project_id"]), 0))
        result.update({"project_id":case["project_id"], "baseline":prior, "delta":round(result["score"]-prior, 2)})
        if result["status"] != "PASS": errors.append(f"PROJECT_{case['project_id']}_{result['status']}")
        if result["score"] < thresholds["minimum_score"]: errors.append(f"PROJECT_{case['project_id']}_BELOW_MINIMUM")
        if result["delta"] < -float(thresholds["maximum_drop"]): errors.append(f"PROJECT_{case['project_id']}_REGRESSION")
        results.append(result)
    pass_rate = sum(r["status"] == "PASS" for r in results) / max(1, len(GOLDEN_PROJECTS))
    if pass_rate < float(thresholds["required_pass_rate"]): errors.append("PASS_RATE_BELOW_THRESHOLD")
    return {"status":"PASS" if not errors else "FAIL", "errors":errors, "results":results,
            "thresholds":thresholds, "pass_rate":pass_rate}


def build_golden_release_case(project_id:int, architecture_hash:str, output:dict,
                              post_seal_reference:dict, semantic_diff:dict, artifact_diff:dict,
                              build:dict[str,Any] | None=None) -> dict[str,Any]:
    """Build one sealed release-evidence case without inventing comparison data.

    The caller must supply the actual blind output, post-seal reference metrics,
    semantic diff and artifact diff. This helper only stamps immutable build
    identity and creates the seal.
    """
    if not _hex64(architecture_hash): raise ValueError("architecture_hash must be sha256")
    current=dict(build or build_identity())
    blind=dict(output or {})
    blind["build_identity"]=current.get("build_identity")
    blind["generator_version"]=current.get("commit_sha")
    blind["rulebook_version"]=current.get("rulebook_schema_revision")
    blind["pmm_schema_version"]=current.get("pmm_schema_revision")
    seal=seal_blind_output(project_id,architecture_hash,blind)
    score=strict_score(seal,blind,post_seal_reference or {})
    return {
        "project_id":project_id,
        "input_hash":architecture_hash,
        "generator_version":current.get("commit_sha"),
        "build_identity":current.get("build_identity"),
        "rulebook_version":current.get("rulebook_schema_revision"),
        "pmm_schema_version":current.get("pmm_schema_revision"),
        "output_hash":seal.get("output_hash"),
        "blind_output":blind,
        "seal":seal,
        "post_seal_reference":post_seal_reference or {},
        "semantic_diff":semantic_diff or {},
        "artifact_diff":artifact_diff or {},
        "strict_score":score,
    }


def assemble_golden_release_evidence(cases:list[dict], baseline_path:str|Path=DEFAULT_BASELINE_PATH,
                                     build:dict[str,Any] | None=None) -> dict[str,Any]:
    """Assemble evidence from already-produced blind cases; never synthesize cases."""
    identity=baseline_identity(baseline_path); baseline=identity["baseline"]; current=dict(build or build_identity())
    regression=run_golden_regression([
        {"project_id":row.get("project_id"),"blind_output":row.get("blind_output") or {},
         "seal":row.get("seal") or {},"post_seal_reference":row.get("post_seal_reference") or {}}
        for row in cases
    ],baseline,baseline.get("thresholds"))
    return {
        "schema":GOLDEN_RELEASE_SCHEMA,
        "status":regression["status"],
        "cohort":list(GOLDEN_PROJECTS),
        "baseline_sha256":identity["sha256"],
        "build_identity":current.get("build_identity"),
        "commit_sha":current.get("commit_sha"),
        "rulebook_version":current.get("rulebook_schema_revision"),
        "pmm_schema_version":current.get("pmm_schema_revision"),
        "pass_rate":regression["pass_rate"],
        "errors":list(regression["errors"]),
        "cases":list(cases),
        "thresholds":regression["thresholds"],
        "policy":"LOCKED_COHORT_SEALED_BUILD_BOUND_POST_SEAL_COMPARISON",
    }


def validate_golden_release_evidence(evidence:dict|None, baseline_path:str|Path=DEFAULT_BASELINE_PATH,
                                     expected_build:dict[str,Any] | None=None) -> dict[str,Any]:
    """Step 11: independently validate full release evidence for the locked cohort.

    A string/status-only PASS is never evidence. Release evidence must be tied
    to the exact build, baseline and all seven sealed projects, and each case
    must independently prove semantic + artifact diff PASS and strict score.
    """
    current=dict(expected_build or build_identity()); identity=baseline_identity(baseline_path); baseline=identity["baseline"]
    base={"version":"golden-evidence-step11/1","policy":"NO_STATUS_ONLY_PASS_LOCKED_SEVEN_PROJECT_BUILD_BINDING"}
    if not isinstance(evidence,dict) or not evidence:
        return {**base,"status":"INPUT_REQUIRED","errors":[],"missing_inputs":["SEVEN_PROJECT_GOLDEN_RELEASE_EVIDENCE"]}
    structural_required=("schema","cohort","baseline_sha256","build_identity","commit_sha","rulebook_version","pmm_schema_version","cases")
    missing=[key for key in structural_required if evidence.get(key) in (None,"",[])]
    if missing:
        return {**base,"status":"INPUT_REQUIRED","errors":[],"missing_inputs":[f"golden_evidence:{key}" for key in missing]}
    errors=[]
    if evidence.get("schema")!=GOLDEN_RELEASE_SCHEMA: errors.append("GOLDEN_EVIDENCE_SCHEMA_MISMATCH")
    if list(evidence.get("cohort") or [])!=list(GOLDEN_PROJECTS): errors.append("GOLDEN_COHORT_MISMATCH")
    if evidence.get("baseline_sha256")!=identity["sha256"]: errors.append("GOLDEN_BASELINE_HASH_MISMATCH")
    expected={
        "build_identity":current.get("build_identity"),"commit_sha":current.get("commit_sha"),
        "rulebook_version":current.get("rulebook_schema_revision"),"pmm_schema_version":current.get("pmm_schema_revision"),
    }
    if expected["commit_sha"] in (None,"","UNKNOWN") or expected["build_identity"] in (None,""):
        return {**base,"status":"INPUT_REQUIRED","errors":[],"missing_inputs":["CURRENT_BUILD_IDENTITY"]}
    for key,value in expected.items():
        if evidence.get(key)!=value: errors.append(f"GOLDEN_BUILD_BINDING_MISMATCH:{key}")

    cases=evidence.get("cases") or []; ids=[row.get("project_id") for row in cases if isinstance(row,dict)]
    if sorted(ids)!=list(GOLDEN_PROJECTS) or len(set(ids))!=len(GOLDEN_PROJECTS): errors.append("GOLDEN_CASE_SET_INCOMPLETE_OR_DUPLICATE")
    normalized=[]
    required_case_fields=("input_hash","generator_version","build_identity","rulebook_version","pmm_schema_version","output_hash",
                          "blind_output","seal","post_seal_reference","semantic_diff","artifact_diff","strict_score")
    for row in cases:
        if not isinstance(row,dict):
            errors.append("GOLDEN_CASE_INVALID_TYPE"); continue
        pid=row.get("project_id"); prefix=f"PROJECT_{pid}"
        absent=[key for key in required_case_fields if row.get(key) in (None,"")]
        if absent:
            errors.extend(f"{prefix}_MISSING_{key.upper()}" for key in absent); continue
        if not _hex64(row.get("input_hash")): errors.append(f"{prefix}_INPUT_HASH_INVALID")
        seal=row.get("seal") or {}; blind=row.get("blind_output") or {}
        if seal.get("project_id")!=pid: errors.append(f"{prefix}_SEAL_PROJECT_MISMATCH")
        if seal.get("architecture_hash")!=row.get("input_hash"): errors.append(f"{prefix}_INPUT_SEAL_MISMATCH")
        if not verify_seal(seal,blind): errors.append(f"{prefix}_SEAL_INVALID_OR_OUTPUT_MUTATED")
        if row.get("output_hash")!=seal.get("output_hash"): errors.append(f"{prefix}_OUTPUT_HASH_MISMATCH")
        for key,value in expected.items():
            case_key="generator_version" if key=="commit_sha" else key
            if row.get(case_key)!=value: errors.append(f"{prefix}_{case_key.upper()}_MISMATCH")
        if blind.get("build_identity")!=expected["build_identity"]: errors.append(f"{prefix}_BLIND_BUILD_IDENTITY_MISMATCH")
        if blind.get("generator_version")!=expected["commit_sha"]: errors.append(f"{prefix}_BLIND_GENERATOR_MISMATCH")
        if blind.get("rulebook_version")!=expected["rulebook_version"]: errors.append(f"{prefix}_BLIND_RULEBOOK_MISMATCH")
        if blind.get("pmm_schema_version")!=expected["pmm_schema_version"]: errors.append(f"{prefix}_BLIND_PMM_MISMATCH")
        if blind.get("submission_state") in {"PRE_SUBMISSION","INPUT_REQUIRED"} or blind.get("submission_ready") is False:
            errors.append(f"{prefix}_NOT_SUBMISSION_READY")
        if (row.get("semantic_diff") or {}).get("status")!="PASS": errors.append(f"{prefix}_SEMANTIC_DIFF_NOT_PASS")
        if (row.get("artifact_diff") or {}).get("status")!="PASS": errors.append(f"{prefix}_ARTIFACT_DIFF_NOT_PASS")
        computed=strict_score(seal,blind,row.get("post_seal_reference") or {})
        provided=row.get("strict_score") or {}
        if provided.get("status")!=computed.get("status") or float(provided.get("score",-1))!=float(computed.get("score",-2)):
            errors.append(f"{prefix}_STRICT_SCORE_MISMATCH")
        normalized.append({"project_id":pid,"blind_output":blind,"seal":seal,"post_seal_reference":row.get("post_seal_reference") or {}})

    regression=run_golden_regression(normalized,baseline,baseline.get("thresholds")) if len(normalized)==len(GOLDEN_PROJECTS) else {"status":"FAIL","errors":["GOLDEN_COHORT_INCOMPLETE"],"results":[],"pass_rate":0.0,"thresholds":baseline.get("thresholds") or DEFAULT_THRESHOLDS}
    if regression.get("status")!="PASS": errors.extend("REGRESSION:"+str(item) for item in regression.get("errors") or ["FAIL"])
    if evidence.get("status")!="PASS": errors.append("GOLDEN_EVIDENCE_STATUS_NOT_PASS")
    if float(evidence.get("pass_rate",-1))!=float(regression.get("pass_rate",0)): errors.append("GOLDEN_PASS_RATE_MISMATCH")
    return {**base,"status":"PASS" if not errors else "FAIL","errors":sorted(set(errors)),"missing_inputs":[],
            "cohort":list(GOLDEN_PROJECTS),"baseline_sha256":identity["sha256"],"build_identity":expected["build_identity"],
            "commit_sha":expected["commit_sha"],"regression":regression,"pass_rate":regression.get("pass_rate",0.0)}


def run_pre_submission_regression(cases: list[dict], baseline: dict) -> dict:
    """Verify the architecture-only profile without granting submission approval."""
    errors, results = [], []
    ids = sorted(case.get("project_id") for case in cases)
    if ids != list(GOLDEN_PROJECTS):
        errors.append("GOLDEN_COHORT_INCOMPLETE")
    for case in cases:
        project_id = case["project_id"]
        output = case["blind_output"]
        score = strict_score(case["seal"], output, case["post_seal_reference"])
        missing = set(output.get("missing_inputs") or [])
        checks = {
            "seal_valid": verify_seal(case["seal"], output),
            "pre_submission": output.get("submission_state") == "PRE_SUBMISSION",
            "not_coordinated": output.get("coordination_claim") == "NOT_COORDINATED",
            "structural_input_listed": "STRUCTURAL_MODEL" in missing,
            "rcp_input_listed": "RCP_MODEL" in missing,
            "submission_ready_false": output.get("submission_ready") is False,
        }
        failed = [name for name, passed in checks.items() if not passed]
        errors.extend(f"PROJECT_{project_id}_{name.upper()}" for name in failed)
        results.append({"project_id":project_id,"status":"PASS" if not failed else "FAIL",
                        "checks":checks,"strict_score":score,
                        "baseline":float((baseline.get("scores") or {}).get(str(project_id),0))})
    return {"status":"PASS" if not errors else "FAIL","errors":errors,"results":results,
            "profile":"ARCHITECTURE_ONLY_PRE_SUBMISSION","submission_ready":False,
            "policy":"PROFILE_PASS_DOES_NOT_GRANT_COORDINATION_OR_SUBMISSION_APPROVAL"}


def submission_gate(phases: dict) -> dict:
    required = ("coordination", "manufacturer", "documentation", "golden")
    states = {name:(phases.get(name) or {}).get("status", "MISSING") for name in required}
    errors = [f"{name}:{status}" for name, status in states.items() if status != "PASS"]
    return {"status":"PASS" if not errors else "FAIL", "release_allowed":not errors,
            "states":states, "errors":errors, "policy":"FAIL_SKIP_MISSING_UNKNOWN_BLOCK"}


def load_baseline(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())