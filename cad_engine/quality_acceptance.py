"""Final quantitative acceptance targets for the mechanical package."""
from __future__ import annotations


ZERO_TARGETS = (
    "structural_mep_clashes", "routing_warnings", "unapproved_penetrations",
    "manufacturer_violations", "missing_required_details",
    "plan_riser_schedule_mismatches", "major_redlines",
)
MINIMUM_TARGETS = {
    "route_efficiency_percent":90.0,
    "equipment_placement_score":90.0,
    "detail_completeness_percent":95.0,
    "package_average_score":90.0,
}


def evaluate_quality_targets(metrics: dict | None) -> dict:
    if not isinstance(metrics, dict):
        return {"status":"INPUT_REQUIRED", "accepted":False, "errors":["QUALITY_METRICS_MISSING"]}
    required=set(ZERO_TARGETS)|set(MINIMUM_TARGETS)|{"main_plan_scores"}
    missing=sorted(required-set(metrics))
    invalid=[]
    for key in required-{"main_plan_scores"}:
        value=metrics.get(key)
        if key in metrics and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
            invalid.append(key)
    plans=metrics.get("main_plan_scores")
    if "main_plan_scores" in metrics and (not isinstance(plans, dict) or not plans):
        invalid.append("main_plan_scores")
    elif isinstance(plans, dict):
        if any(not str(name).strip() or isinstance(score, bool) or not isinstance(score, (int, float))
               or score < 0 or score > 100 for name,score in plans.items()):
            invalid.append("main_plan_scores")
    if missing or invalid:
        return {"status":"INPUT_REQUIRED", "accepted":False,
                "errors":["QUALITY_METRIC_MISSING:"+key for key in missing] +
                         ["QUALITY_METRIC_INVALID:"+key for key in sorted(set(invalid))]}
    errors=["QUALITY_ZERO_TARGET_FAILED:"+key for key in ZERO_TARGETS if float(metrics[key]) != 0.0]
    errors += ["QUALITY_MINIMUM_TARGET_FAILED:"+key for key,target in MINIMUM_TARGETS.items()
               if float(metrics[key]) < target]
    low_plans=sorted(name for name,score in plans.items() if float(score) < 85.0)
    if low_plans: errors.append("MAIN_PLAN_SCORE_BELOW_85:" + ",".join(low_plans))
    return {"status":"PASS" if not errors else "FAIL", "accepted":not errors, "errors":errors,
            "targets":{"zero":list(ZERO_TARGETS), "minimums":MINIMUM_TARGETS,
                       "each_main_plan_score":85.0}, "metrics":metrics}
