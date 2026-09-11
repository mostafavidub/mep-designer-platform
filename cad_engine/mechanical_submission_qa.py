"""Submission gate and sealed, blind seven-project golden regression."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


GOLDEN_PROJECTS = (1, 3, 4, 6, 7, 8, 10)
DEFAULT_THRESHOLDS = {"minimum_score": 70.0, "maximum_drop": 0.0, "required_pass_rate": 1.0}
DIFF_KINDS = ("semantic", "artifact", "numeric")
SUBMISSION_ZERO_CHECKS = (
    "missing_required_systems",
    "orphan_fixtures",
    "unconnected_equipment",
    "missing_segment_sizes",
    "reverse_gravity_slopes",
    "route_warnings",
    "structural_clashes",
    "mep_clashes",
    "unapproved_penetrations",
    "gravity_violations",
    "equipment_without_calculation",
    "equipment_without_manufacturer_basis",
    "manufacturer_limit_violations",
    "missing_details",
    "missing_mandatory_details",
    "missing_rainwater_systems",
    "invalid_riser_levels",
    "plan_riser_schedule_mismatches",
    "unreadable_annotations",
)

TARGET_DESIGN_SHEETS = {
    "heating": ("M-131", "M-132"),
    "gas": ("M-141", "M-142"),
    "split_ac": ("M-161", "M-162"),
    "exhaust": ("M-171", "M-172"),
    "rainwater": ("M-R-01",),
    "riser": ("M-151",),
    "manufacturer_database": ("M-181",),
}


def validate_target_design_packages(packages: dict | None) -> dict:
    """Block issue unless stages 7-13 contain complete final engineering evidence."""
    if not isinstance(packages, dict):
        return {"status":"INPUT_REQUIRED","errors":["TARGET_DESIGN_PACKAGES_MISSING"],"sheets":{}}
    errors=[]; sheet_status={}
    for system,sheets in TARGET_DESIGN_SHEETS.items():
        package=packages.get(system)
        if not isinstance(package,dict):
            errors.append(f"{system}:PACKAGE_MISSING");continue
        if package.get("status") != "PASS":errors.append(f"{system}:STATUS_{package.get('status','MISSING')}")
        if package.get("basis_status") in {"PRELIMINARY","PRE_SUBMISSION","PRELIMINARY_OVERRIDEABLE"}:
            errors.append(f"{system}:PRELIMINARY_ONLY_FORBIDDEN")
        declared=tuple(package.get("sheets") or ())
        if declared != sheets:errors.append(f"{system}:SHEET_CONTRACT_MISMATCH")
        sheet_status.update({sheet:"PASS" if declared==sheets and package.get("status")=="PASS" else "FAIL" for sheet in sheets})
    heating=(packages.get("heating") or {})
    if not (heating.get("room_heat_loss") and heating.get("radiator_selection") and
            heating.get("heating_network") and heating.get("package_selection")):
        errors.append("heating:FINAL_CHAIN_INCOMPLETE")
    if any(row.get("selection_type")!="MANUFACTURER_MODEL" or row.get("status")!="PASS"
           for row in (heating.get("radiator_selection") or {}).get("radiators") or []):
        errors.append("heating:PRELIMINARY_OR_INVALID_RADIATOR")
    gas=(packages.get("gas") or {}).get("gas_network") or {}
    for row in gas.get("segments") or []:
        if any(row.get(key) is None for key in ("flow_m3h","equivalent_length_m","selected_dn_mm","calc_id")):
            errors.append(f"gas:SEGMENT_EVIDENCE_MISSING:{row.get('segment_id','UNKNOWN')}")
    split=(packages.get("split_ac") or {}).get("selection") or {}
    for row in split.get("idus") or []:
        required=("calculated_load_btu_h","selected_capacity_btu_h","selection_margin_percent",
                  "manufacturer","model","route_length_m","elevation_m","status","calc_id")
        if any(row.get(key) is None for key in required) or row.get("status")!="PASS":
            errors.append(f"split_ac:IDU_EVIDENCE_MISSING:{row.get('idu_id','UNKNOWN')}")
    if not gas.get("segments"):errors.append("gas:NO_SEGMENTS")
    if not split.get("idus") or not split.get("odu"):errors.append("split_ac:SELECTION_INCOMPLETE")
    exhaust=packages.get("exhaust") or {}
    exhaust_design=exhaust.get("exhaust_design") or {}
    fan_selection=exhaust.get("fan_selection") or {}
    if exhaust_design.get("unserved_room_ids") or fan_selection.get("unserved_room_ids"):
        errors.append("exhaust:UNSERVED_EXHAUST_ROOM")
    if not exhaust_design.get("rooms") or not fan_selection.get("fans"):
        errors.append("exhaust:DESIGN_OR_SELECTION_INCOMPLETE")
    for row in fan_selection.get("fans") or []:
        required=("required_cfm","required_esp_pa","manufacturer","model","selected_cfm",
                  "selected_esp_pa","fan_curve","calc_id","pmm_id","level_id","status")
        if any(row.get(key) is None for key in required) or row.get("status")!="PASS":
            errors.append(f"exhaust:FAN_EVIDENCE_MISSING:{row.get('room_id','UNKNOWN')}")
    rain=(packages.get("rainwater") or {}).get("rainwater_design") or {}
    coverage=rain.get("coverage") or {}
    if not rain.get("catchments") or not coverage.get("all_catchments_drained"):
        errors.append("rainwater:CATCHMENT_PLAN_INCOMPLETE")
    for row in rain.get("segments") or []:
        if len({row.get("calc_id"),row.get("plan_id"),row.get("riser_id"),row.get("schedule_id")})!=1:
            errors.append(f"rainwater:IDENTITY_MISMATCH:{row.get('id','UNKNOWN')}")
    riser=(packages.get("riser") or {}).get("riser_design") or {}
    if riser.get("claim")!="GRAPH_DERIVED" or not (riser.get("reconciliation") or {}).get("zero_mismatch"):
        errors.append("riser:PLAN_RISER_MISMATCH")
    invalid=(riser.get("reconciliation") or {}).get("invalid_levels") or []
    if invalid:errors.append("riser:INVALID_LEVEL_TYPE:"+",".join(sorted(invalid)))
    database=(packages.get("manufacturer_database") or {}).get("database") or {}
    if database.get("policy")!="OFFICIAL_MANUFACTURER_DOCUMENTATION_ONLY" or database.get("private_documents_stored") is not False:
        errors.append("manufacturer_database:OFFICIAL_HASH_ONLY_POLICY_MISSING")
    records=database.get("records") or []
    registered={(row.get("manufacturer"),row.get("model")) for row in records}
    selected=[]
    selected.extend((row.get("manufacturer"),row.get("model")) for row in
                    (heating.get("radiator_selection") or {}).get("radiators") or [])
    package_selection=(heating.get("package_selection") or {}).get("selection") or {}
    selected.append((package_selection.get("manufacturer"),package_selection.get("model")))
    selected.extend((row.get("manufacturer"),row.get("model")) for row in split.get("idus") or [])
    odu=split.get("odu") or {}; selected.append((odu.get("manufacturer"),odu.get("model")))
    selected.extend((row.get("manufacturer"),row.get("model")) for row in fan_selection.get("fans") or [])
    selected.extend((row.get("manufacturer"),row.get("model")) for row in
                    ((packages.get("gas") or {}).get("gas_network") or {}).get("appliances") or [])
    for manufacturer,model in selected:
        if manufacturer and model and (manufacturer,model) not in registered:
            errors.append(f"manufacturer_database:UNREGISTERED_SELECTION:{manufacturer}:{model}")
    explicit_failure=any((packages.get(system) or {}).get("status")=="FAIL" for system in TARGET_DESIGN_SHEETS)
    status="PASS" if not errors else ("FAIL" if explicit_failure else ("INPUT_REQUIRED" if any(
        token in value for value in errors for token in ("MISSING","INCOMPLETE","STATUS_INPUT_REQUIRED")
    ) else "FAIL"))
    return {"status":status,"errors":sorted(set(errors)),"sheets":sheet_status,
            "policy":"Steps 7-13 require final traced plans, graph-derived riser and hash-only official manufacturer records"}


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


def evaluate_submission_readiness(checks: dict | None) -> dict:
    """Require explicit, numeric zero evidence for every submission invariant."""
    if not isinstance(checks, dict):
        return {"status":"INPUT_REQUIRED", "submission_ready":False,
                "errors":["SUBMISSION_CHECKS_MISSING"], "checks":{}}
    missing = [name for name in SUBMISSION_ZERO_CHECKS if name not in checks]
    invalid = [name for name in SUBMISSION_ZERO_CHECKS
               if name in checks and (isinstance(checks[name], bool) or not isinstance(checks[name], (int, float))
                                      or checks[name] < 0)]
    if missing or invalid:
        errors = (["SUBMISSION_CHECK_MISSING:" + name for name in missing] +
                  ["SUBMISSION_CHECK_INVALID:" + name for name in invalid])
        return {"status":"INPUT_REQUIRED", "submission_ready":False,
                "errors":errors, "checks":{name:checks.get(name) for name in SUBMISSION_ZERO_CHECKS}}
    violations = [name for name in SUBMISSION_ZERO_CHECKS if float(checks[name]) != 0.0]
    return {"status":"PASS" if not violations else "FAIL", "submission_ready":not violations,
            "errors":["SUBMISSION_VIOLATION:" + name for name in violations],
            "checks":{name:checks[name] for name in SUBMISSION_ZERO_CHECKS},
            "policy":"ALL_SUBMISSION_INVARIANTS_MUST_HAVE_EXPLICIT_ZERO_EVIDENCE"}


def compare_outputs(blind_output: dict, post_seal_reference: dict) -> dict:
    """Produce deterministic fail-closed semantic, artifact and numeric diffs."""
    contract = post_seal_reference.get("comparison_contract") or {}
    missing_contract = [kind for kind in DIFF_KINDS if kind not in contract]
    if missing_contract:
        return {"status":"INPUT_REQUIRED", "errors":["DIFF_CONTRACT_MISSING:" + ",".join(missing_contract)]}

    expected_semantics = set(contract["semantic"].get("required") or [])
    actual_semantics = set(blind_output.get("semantics") or [])
    semantic = {"removed":sorted(expected_semantics-actual_semantics),
                "added":sorted(actual_semantics-expected_semantics)}

    expected_artifacts = contract["artifact"].get("inventory") or {}
    actual_artifacts = blind_output.get("artifacts") or {}
    artifact = {"missing":sorted(set(expected_artifacts)-set(actual_artifacts)),
                "unexpected":sorted(set(actual_artifacts)-set(expected_artifacts)), "changed":[]}
    for name in sorted(set(expected_artifacts) & set(actual_artifacts)):
        if expected_artifacts[name] != actual_artifacts[name]: artifact["changed"].append(name)

    numeric, numeric_errors = [], []
    expected_numeric = contract["numeric"].get("values") or {}
    actual_numeric = blind_output.get("numeric") or {}
    tolerances = contract["numeric"].get("tolerances") or {}
    for key, expected in sorted(expected_numeric.items()):
        tolerance = tolerances.get(key)
        if not tolerance or not tolerance.get("rule_id") or "absolute" not in tolerance:
            numeric_errors.append("NUMERIC_TOLERANCE_UNGOVERNED:" + key)
            continue
        if key not in actual_numeric:
            numeric_errors.append("NUMERIC_VALUE_MISSING:" + key)
            continue
        delta = abs(float(actual_numeric[key])-float(expected))
        numeric.append({"key":key,"expected":expected,"actual":actual_numeric[key],"delta":delta,
                        "tolerance":tolerance["absolute"],"rule_id":tolerance["rule_id"],
                        "pass":delta <= float(tolerance["absolute"])})
    errors = []
    if semantic["removed"]: errors.append("LOCKED_SEMANTIC_REMOVED:" + ",".join(semantic["removed"]))
    if artifact["missing"]: errors.append("ARTIFACT_MISSING:" + ",".join(artifact["missing"]))
    if artifact["changed"]: errors.append("ARTIFACT_CHANGED:" + ",".join(artifact["changed"]))
    errors.extend(numeric_errors)
    errors.extend("NUMERIC_REGRESSION:"+row["key"] for row in numeric if not row["pass"])
    status = "PASS" if not errors else ("INPUT_REQUIRED" if any("MISSING" in e or "UNGOVERNED" in e for e in errors) else "FAIL")
    return {"status":status,"errors":errors,"semantic":semantic,"artifact":artifact,"numeric":numeric}


def strict_score(seal: dict, blind_output: dict, post_seal_reference: dict) -> dict:
    if not verify_seal(seal, blind_output):
        return {"status":"FAIL", "score":0.0, "errors":["INVALID_OR_MUTATED_SEAL"]}
    if post_seal_reference.get("opened_before_seal"):
        return {"status":"FAIL", "score":0.0, "errors":["REFERENCE_LEAKAGE"]}
    diffs = compare_outputs(blind_output, post_seal_reference)
    if diffs["status"] != "PASS":
        return {"status":diffs["status"], "score":0.0, "errors":diffs["errors"], "diffs":diffs}
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
            "penalties":penalties, "reference_opened_post_seal":True, "diffs":diffs}


def run_golden_regression(cases: list[dict], baseline: dict, thresholds: dict | None = None) -> dict:
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    errors, results = [], []
    ids = [case.get("project_id") for case in cases]
    if len(ids) != len(set(ids)): errors.append("GOLDEN_COHORT_DUPLICATE")
    if sorted(ids) != list(GOLDEN_PROJECTS): errors.append("GOLDEN_COHORT_INCOMPLETE")
    if baseline.get("private_drawings_stored") is not False: errors.append("PRIVATE_DRAWING_POLICY_INVALID")
    for case in cases:
        if case.get("generation_mode") != "BLIND_ARCHITECTURE_ONLY":
            errors.append(f"PROJECT_{case.get('project_id')}_BLIND_GENERATION_UNPROVEN")
        if case.get("reference_opened_at") is not None and case.get("sealed_at") is not None:
            if case["reference_opened_at"] <= case["sealed_at"]:
                errors.append(f"PROJECT_{case.get('project_id')}_REFERENCE_ORDER_INVALID")
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
    required = ("coordination", "manufacturer", "documentation", "submission_quality",
                "engineer_feedback", "quality_targets", "golden")
    states = {name:(phases.get(name) or {}).get("status", "MISSING") for name in required}
    errors = [f"{name}:{status}" for name, status in states.items() if status != "PASS"]
    return {"status":"PASS" if not errors else "FAIL", "release_allowed":not errors,
            "states":states, "errors":errors, "policy":"FAIL_SKIP_MISSING_UNKNOWN_BLOCK"}


def load_baseline(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())
