"""Privacy-safe independent-engineer redline triage and learning contract."""
from __future__ import annotations

from hashlib import sha256
import json


CATEGORIES = ("project-specific", "rulebook deficiency", "engine bug")
SEVERITIES = ("minor", "major", "critical")


def _stable_id(redline: dict) -> str:
    payload = {key:redline.get(key) for key in ("project_id", "sheet_id", "category", "severity", "summary")}
    digest = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:16]
    return "RL-" + digest.upper()


def process_engineer_redlines(review: dict | None) -> dict:
    """Quarantine project facts; promote only governed reusable findings."""
    if not isinstance(review, dict):
        return {"status":"INPUT_REQUIRED", "errors":["INDEPENDENT_ENGINEER_REVIEW_MISSING"],
                "project_specific":[], "rulebook_updates":[], "engine_regressions":[]}
    missing=[]
    for key in ("reviewer_id", "review_evidence_sha256", "redlines"):
        if key not in review: missing.append(key)
    evidence=review.get("review_evidence_sha256")
    if evidence is not None and (not isinstance(evidence, str) or len(evidence) != 64
                                 or any(ch not in "0123456789abcdefABCDEF" for ch in evidence)):
        missing.append("valid_review_evidence_sha256")
    if missing:
        return {"status":"INPUT_REQUIRED", "errors":["FEEDBACK_INPUT_MISSING:" + key for key in missing],
                "project_specific":[], "rulebook_updates":[], "engine_regressions":[]}

    errors=[]; project_specific=[]; rulebook=[]; regressions=[]; seen=set()
    for source in review["redlines"]:
        redline=dict(source)
        required=("project_id", "sheet_id", "category", "severity", "summary", "status")
        absent=[key for key in required if redline.get(key) in (None, "")]
        if absent:
            errors.append("REDLINE_FIELDS_MISSING:" + ",".join(absent)); continue
        if redline["category"] not in CATEGORIES:
            errors.append("REDLINE_CATEGORY_INVALID:" + str(redline["category"])); continue
        if redline["severity"] not in SEVERITIES:
            errors.append("REDLINE_SEVERITY_INVALID:" + str(redline["severity"])); continue
        redline["redline_id"]=_stable_id(redline)
        if redline["redline_id"] in seen:
            errors.append("REDLINE_DUPLICATE:" + redline["redline_id"]); continue
        seen.add(redline["redline_id"])
        if redline["category"] == "project-specific":
            redline["promotion_policy"]="PROJECT_ONLY_DO_NOT_PROMOTE"
            project_specific.append(redline)
        elif redline["category"] == "rulebook deficiency":
            if not redline.get("rule_id") or not redline.get("regression_test"):
                errors.append("RULEBOOK_REDLINE_GOVERNANCE_MISSING:" + redline["redline_id"]); continue
            redline["promotion_policy"]="RULEBOOK_AND_REGRESSION"
            rulebook.append(redline)
        else:
            if not redline.get("reproduction") or not redline.get("regression_test"):
                errors.append("ENGINE_BUG_REPRODUCTION_MISSING:" + redline["redline_id"]); continue
            redline["promotion_policy"]="ENGINE_FIX_AND_REGRESSION"
            regressions.append(redline)
    open_major=[row["redline_id"] for row in project_specific+rulebook+regressions
                if row["severity"] in {"major", "critical"} and row["status"] != "resolved"]
    if open_major: errors.append("OPEN_MAJOR_REDLINE:" + ",".join(sorted(open_major)))
    return {"status":"PASS" if not errors else "FAIL", "errors":errors,
            "project_specific":project_specific, "rulebook_updates":rulebook,
            "engine_regressions":regressions, "open_major_redlines":len(open_major),
            "privacy_policy":"HASH_ONLY_REVIEW_EVIDENCE_NO_PRIVATE_DRAWINGS"}
