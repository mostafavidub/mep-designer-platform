"""Offline residential design foundation. Never grants construction or pricing authority."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from cad_engine.build_identity import build_identity

DATA = Path(__file__).resolve().parents[1] / "data/rulebook/architecture"
STATUSES = {"VALIDATED", "REVIEW_REQUIRED", "INPUT_REQUIRED", "CONFLICT", "NO_FEASIBLE_LAYOUT"}


def stable_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load_catalog(name):
    if name not in {"rulebook", "sources", "owner-questionnaire", "symbols", "generation-contract",
                    "qa-matrix", "exam-coverage", "plan-study", "heuristics", "research-completion",
                    "golden-review-template"}:
        raise ValueError("Unknown foundation catalog")
    return json.loads((DATA / (name + ".json")).read_text())


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def numeric_check(check, facts):
    """Small declarative DSL. No executable expressions from sources or user input."""
    if not check:
        return "REVIEW_REQUIRED"
    if "all" in check:
        results = [numeric_check(c, facts) for c in check["all"]]
        if "FAIL" in results:
            return "FAIL"
        if "INPUT_REQUIRED" in results:
            return "INPUT_REQUIRED"
        return "PASS" if results and all(r == "PASS" for r in results) else "REVIEW_REQUIRED"
    left = facts.get(check["field"])
    if not isinstance(left, dict) or left.get("unit") != check["unit"] or not finite_number(left.get("value")):
        return "INPUT_REQUIRED"
    right = check.get("value")
    if "rhs_field" in check:
        rhs = facts.get(check["rhs_field"])
        if not isinstance(rhs, dict) or rhs.get("unit") != check["unit"] or not finite_number(rhs.get("value")):
            return "INPUT_REQUIRED"
        right = rhs["value"] * check["factor"]
    if not finite_number(right) or check.get("op") not in {">=", "<=", "=="}:
        return "INPUT_REQUIRED"
    return "PASS" if {">=": left["value"] >= right, "<=": left["value"] <= right,
                       "==": left["value"] == right}[check["op"]] else "FAIL"


def evaluate_rule(rule, facts, authority_review):
    """Applicability is separately reviewed and bound to exact source/rule/input hashes.

    A numeric pass cannot certify a currently disabled or incompletely qualified rule.
    """
    result = {"rule_id": rule["rule_id"], "status": "INPUT_REQUIRED",
              "numeric_result": "NOT_RUN", "rule_hash": stable_hash(rule), "facts_hash": stable_hash(facts)}
    expected = {"rule_hash": result["rule_hash"], "facts_hash": result["facts_hash"]}
    if any(authority_review.get(k) != v for k, v in expected.items()):
        result["reason"] = "MISSING_OR_STALE_APPLICABILITY_REVIEW"
        return result
    if not rule.get("release_enabled"):
        result["reason"] = "RULE_NOT_RELEASE_QUALIFIED"
        return result
    if authority_review.get("status") != "APPROVED" or not authority_review.get("reviewer_id"):
        result["reason"] = "AUTHORITY_REVIEW_REQUIRED"
        return result
    if authority_review.get("applicable") is not True:
        result["reason"] = "APPLICABILITY_NOT_ESTABLISHED"
        return result
    result["numeric_result"] = numeric_check(rule.get("check"), facts)
    result["status"] = result["numeric_result"]
    return result


def branch_state(condition, answers):
    if not condition:
        return "ACTIVE"
    if condition["field"] not in answers:
        return "UNRESOLVED"
    value = answers[condition["field"]]
    if "in" in condition:
        active = value in condition["in"]
    elif "gt" in condition:
        active = finite_number(value) and value > condition["gt"]
    elif condition.get("nonempty"):
        active = isinstance(value, list) and bool(value)
    else:
        raise ValueError("Unsupported questionnaire condition")
    return "ACTIVE" if active else "INACTIVE"


def questionnaire_state(answers):
    if not isinstance(answers, dict):
        raise ValueError("Owner answers must be an object")
    questions = load_catalog("owner-questionnaire")["questions"]
    known = {q["field"] for q in questions}
    if set(answers) - known:
        raise ValueError("Unknown owner fields")
    missing, invalid, active, unresolved = [], [], [], []
    for q in questions:
        field = q["field"]
        state = branch_state(q["condition"], answers)
        if state == "UNRESOLVED":
            unresolved.append(field)
            continue
        if state == "INACTIVE":
            continue
        active.append(field)
        if field not in answers:
            if q["requirement"] in {"MANDATORY", "CONDITIONAL"}:
                missing.append(field)
            continue
        value = answers[field]
        typ, allowed = q["data_type"], q["allowed_values"]
        bad = value is None or (isinstance(value, str) and not value.strip())
        if typ == "enum":
            bad |= value not in allowed
        elif typ == "boolean":
            bad |= type(value) is not bool
        elif typ in {"integer", "number"}:
            bad |= not finite_number(value)
            if not bad:
                bad |= typ == "integer" and type(value) is not int
                bad |= "minimum" in allowed and value < allowed["minimum"]
                bad |= "exclusive_minimum" in allowed and value <= allowed["exclusive_minimum"]
        elif typ in {"unique_array", "ranked_unique_array"}:
            bad |= not isinstance(value, list)
            if not bad:
                bad |= any(not isinstance(v, str) or v not in allowed for v in value)
                if not bad:
                    bad |= len(set(value)) != len(value)
        elif typ == "string":
            bad |= not isinstance(value, str)
        elif typ == "unit_program_array":
            bad |= bool(unit_program_errors(value, answers.get("units_per_floor")))
        elif typ == "per_unit_type_integer":
            program = answers.get("unit_program", [])
            program = program if isinstance(program, list) else []
            ids = {u.get("unit_type_id") for u in program if isinstance(u, dict) and isinstance(u.get("unit_type_id"), str)}
            bad |= not isinstance(value, dict)
            if not bad:
                bad |= set(value) != ids or any(type(v) is not int or v < 0 for v in value.values())
        else:
            # Structured program types need dedicated contract validation before approval.
            bad |= not isinstance(value, (dict, list)) or not value
        if field == "confirmation" and value is not True:
            bad = True
        if bad:
            invalid.append(field)
    return {"status": "INPUT_REQUIRED" if missing or invalid else "REVIEW_REQUIRED",
            "active": active, "unresolved_optional_branches": unresolved,
            "missing": missing, "invalid": invalid, "answers_hash": stable_hash(answers),
            "note": "Structured owner program still needs complete contract review; this is not design approval."}


def rank_candidates(candidates, required_check_ids, weights):
    """Rank only independently complete hard-gate results; no averaging away failures."""
    if not required_check_ids or len(set(required_check_ids)) != len(required_check_ids):
        raise ValueError("Explicit unique required checks are mandatory")
    if not weights or any(not finite_number(v) or v < 0 for v in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError("Invalid quality weights")
    ids = [c["candidate_id"] for c in candidates]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate candidate identity")
    ranked, blocked = [], []
    for c in candidates:
        checks = c.get("hard_checks", {})
        if (any(checks.get(k) != "PASS" for k in required_check_ids)
                or any(v != "PASS" for v in checks.values())
                or c.get("owner_mandatory") != "PASS"):
            blocked.append({"candidate_id": c["candidate_id"], "status": "REVIEW_REQUIRED",
                            "reason": "INCOMPLETE_OR_FAILED_HARD_GATE"})
            continue
        quality = c.get("quality", {})
        if any(not finite_number(quality.get(k)) or not 0 <= quality[k] <= 1 for k in weights):
            blocked.append({"candidate_id": c["candidate_id"], "status": "INPUT_REQUIRED", "reason": "INVALID_QUALITY"})
            continue
        score = sum(quality[k] * weights[k] for k in sorted(weights)) / sum(weights.values())
        ranked.append({"candidate_id": c["candidate_id"], "score": score})
    ranked.sort(key=lambda r: (-r["score"], r["candidate_id"]))
    return {"ranked": ranked, "blocked": blocked,
            "status": "REVIEW_REQUIRED", "construction_authority": False,
            "note": "No candidate search implemented; empty results are not proof of infeasibility."}


def unit_program_errors(value, units_per_floor):
    """Validate owner counts and ranges without deciding legal feasibility."""
    if not isinstance(value, list) or not value:
        return ["UNIT_PROGRAM_REQUIRED"]
    required = {"unit_type_id", "count", "bedrooms", "target_usable_area_min_m2",
                "target_usable_area_max_m2", "requirement_strength"}
    ids, count = set(), 0
    for row in value:
        if not isinstance(row, dict) or set(row) != required:
            return ["UNIT_PROGRAM_FIELDS"]
        key = row["unit_type_id"]
        if not isinstance(key, str) or not key.strip() or key in ids:
            return ["UNIT_TYPE_ID"]
        ids.add(key)
        if type(row["count"]) is not int or row["count"] < 1 or type(row["bedrooms"]) is not int or row["bedrooms"] < 0:
            return ["UNIT_COUNTS"]
        lo, hi = row["target_usable_area_min_m2"], row["target_usable_area_max_m2"]
        if not finite_number(lo) or not finite_number(hi) or not 0 < lo <= hi:
            return ["UNIT_AREA_RANGE"]
        if row["requirement_strength"] not in ("MANDATORY", "PREFERRED"):
            return ["UNIT_STRENGTH"]
        count += row["count"]
    return [] if type(units_per_floor) is int and count == units_per_floor else ["UNIT_TOTAL_MISMATCH"]


def validate_generation_input(payload):
    """Structural and geometric preflight, never legal/project approval."""
    from jsonschema import Draft202012Validator
    from shapely.geometry import Polygon
    schema = json.loads((DATA.parents[2] / "standards/test-suites/residential/generation-input.schema.json").read_text())
    errors = sorted((e.json_path + ": " + e.message for e in Draft202012Validator(schema).iter_errors(payload)))
    try:
        input_hash = stable_hash(payload)
    except (ValueError, TypeError):
        return {"status": "INPUT_REQUIRED", "errors": ["NON_FINITE_OR_NON_JSON_INPUT"], "input_hash": None}
    if errors:
        return {"status": "INPUT_REQUIRED", "errors": errors, "input_hash": input_hash}
    def polygon(points):
        if points[0] != points[-1] or any(not finite_number(v) for pt in points for v in pt):
            raise ValueError("Closed finite polygon required")
        poly = Polygon(points)
        if not poly.is_valid or poly.area <= 0:
            raise ValueError("Simple nonzero-area polygon required")
        return poly
    try:
        plot = polygon(payload["plot"]["boundary"])
        envelope = polygon(payload["authority"]["envelope"])
        if not plot.covers(envelope):
            errors.append("ENVELOPE_OUTSIDE_PLOT")
        if any(i >= len(payload["plot"]["boundary"]) - 1 for i in payload["plot"]["access_edges"]):
            errors.append("ACCESS_EDGE_OUT_OF_RANGE")
        ids = set()
        for reservation in payload["reservations"]:
            if reservation["id"] in ids:
                errors.append("DUPLICATE_RESERVATION")
            ids.add(reservation["id"])
            if not plot.covers(polygon(reservation["polygon"])):
                errors.append("RESERVATION_OUTSIDE_PLOT")
    except ValueError as exc:
        errors.append(str(exc))
    program = payload["program"]
    errors.extend(unit_program_errors(program["unit_types"], program["units_per_floor"]))
    if sum(payload["weights"].values()) <= 0:
        errors.append("POSITIVE_WEIGHT_SUM_REQUIRED")
    return {"status": "INPUT_REQUIRED" if errors else "REVIEW_REQUIRED", "errors": sorted(errors),
            "input_hash": input_hash, "construction_authority": False,
            "note": "Authority signatures, source currency, setbacks and design feasibility remain unqualified."}


def foundation_audit():
    rulebook = load_catalog("rulebook")
    sources = load_catalog("sources")["sources"]
    study = load_catalog("plan-study")
    gaps = [r["rule_id"] for r in rulebook["rules"] if not r.get("release_enabled")]
    actual = sum(r.get("review_status") == "VISUALLY_REVIEWED" for r in study["records"])
    return {"schema_version": "architecture-foundation-audit/1.0", "build_identity": build_identity(),
            "catalog_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DATA.glob("*.json"))},
            "status": "ARCHITECTURE_FOUNDATION_PARTIAL",
            "authority_status": "ARCHITECTURE_RULEBOOK_INPUT_REQUIRED",
            "rules_requiring_qualification": gaps,
            "unresolved_sources": [s["source_id"] for s in sources if s["status"] == "UNKNOWN_CURRENT_STATUS"],
            "actual_plan_count": actual, "study_target_met": actual >= 100,
            "golden_status": "HUMAN_ARCHITECTURE_GOLDEN_REQUIRED", "production_authorized": False,
            "customer_autonomous_ready": False}
