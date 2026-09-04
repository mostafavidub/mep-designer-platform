"""Submission gate and sealed, blind seven-project golden regression."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


GOLDEN_PROJECTS = (1, 3, 4, 6, 7, 8, 10)
DEFAULT_THRESHOLDS = {"minimum_score": 70.0, "maximum_drop": 0.0, "required_pass_rate": 1.0}


def _bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


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
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
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
