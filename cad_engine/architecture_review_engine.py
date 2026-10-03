"""Experimental bounded architecture preflight, review replay and qualification.

Human input may interpret existing source-backed candidates.  It never authors
geometry, and this module never replaces the independent architecture validator.
"""
from __future__ import annotations

from copy import deepcopy
import time

from .architecture_contract import content_hash
from .architecture_review_contract import create_review_item, validate_review_decision
from .architecture_snapshot import create_snapshot
from .architecture_validator import validate_architecture, validate_validator_report_integrity


PREFLIGHT_SCHEMA = "planha-architecture-preflight/1.0"
REGISTRY_SCHEMA = "planha-architecture-review-registry/1.0"
PRIMARY_STATES = {"AUTO_VALIDATED", "QUICK_REVIEW_REQUIRED",
                  "ARCHITECTURE_INPUT_REQUIRED", "CONFLICT"}
ISSUE_CLASSES = {"REVIEWABLE_SOURCE_INTERPRETATION", "SOURCE_INPUT_REQUIRED",
                 "ENGINE_DEFECT_OR_CONTRACT_ERROR", "NONCRITICAL_DIAGNOSTIC",
                 "ALREADY_RESOLVED"}

ENGINE_CODES = {"SCHEMA_MISMATCH", "ADAPTER_IDENTITY_MISSING", "MISSING_ID",
                "DUPLICATE_FRAME_ID", "DUPLICATE_LEVEL_ID", "DUPLICATE_WALL_ID",
                "DUPLICATE_PHYSICAL_SPACE_ID", "DUPLICATE_FUNCTIONAL_ZONE_ID",
                "DUPLICATE_APERTURE_ID", "DUPLICATE_VOID_ID", "DUPLICATE_OPENING_ID",
                "WALL_FRAME_REFERENCE_INVALID", "SPACE_FRAME_REFERENCE_INVALID",
                "FUNCTIONAL_ZONE_SPACE_REFERENCE_INVALID", "APERTURE_WALL_REFERENCE_INVALID",
                "PORTAL_HOST_WALL_INVALID", "PORTAL_HOST_APERTURE_INVALID",
                "PORTAL_SIDE_REFERENCE_INVALID", "ACCESS_EDGE_PORTAL_REFERENCE_INVALID",
                "ENCLOSURE_GRAPH_REFERENCE_INVALID", "CANONICAL_MODEL_HASH_MISMATCH",
                "VALIDATOR_MUTATED_INPUT", "UNKNOWN_AUTHORITY_STATUS",
                "UNKNOWN_AUTHORITY_ORIGIN", "STALE_REVIEW_AUTHORITY_FORBIDDEN",
                "VALIDATOR_REPORT_MISMATCH"}
CONFLICT_CODES = {"ILLEGAL_PHYSICAL_SPACE_OVERLAP", "CROSS_LEVEL_PORTAL_FORBIDDEN",
                  "SOURCE_REVISION_IDENTITY_MISMATCH"}
SOURCE_CODES = {"SOURCE_SHA256_MISSING_OR_INVALID", "EFFECTIVE_SCALE_REQUIRED",
                "FRAME_LEVEL_UNRESOLVED", "WALL_SOURCE_PROVENANCE_REQUIRED",
                "PHYSICAL_SPACE_POLYGON_INVALID", "WALL_GEOMETRY_INVALID",
                "VOID_GEOMETRY_INVALID", "VOID_SOURCE_GEOMETRY_REQUIRED",
                "LABEL_OR_VISION_DERIVED_VOID_FORBIDDEN", "VOID_OCCUPIED_SPACE_OVERLAP"}
DOMAIN_RANK = {"SOURCE": 0, "SPACE": 1, "WALL": 2, "VOID": 3,
               "PORTAL": 4, "SEMANTIC": 5, "DIMENSION": 6, "OTHER": 7}
IMPACT_RANK = {"RELEASE_CRITICAL": 0, "DOWNSTREAM_CRITICAL": 1,
               "REVIEW_CRITICAL": 2, "NONCRITICAL_DIAGNOSTIC": 3}


def empty_review_registry():
    return {"schema": REGISTRY_SCHEMA, "generated_review_items": [],
            "accepted_decisions": [], "rejected_decisions": [], "stale_decisions": [],
            "decision_history": [], "validation_history": [],
            "resolved_issue_ids": [], "unresolved_issue_ids": [],
            "convergence": {}, "manual_geometry_creation_count": 0}


def _issue_id(source_sha, bucket, code, context):
    return "PREFLIGHT-ISSUE-" + content_hash([source_sha, bucket, code, context])[:20].upper()


def _domain(code, context):
    text = (code + " " + str(context)).upper()
    for token, domain in (("SOURCE", "SOURCE"), ("FRAME", "SOURCE"), ("LEVEL", "SOURCE"),
                          ("SPACE", "SPACE"), ("WALL", "WALL"), ("VOID", "VOID"),
                          ("SHAFT", "VOID"), ("DUCT", "VOID"), ("PORTAL", "PORTAL"),
                          ("ACCESS", "PORTAL"), ("APERTURE", "PORTAL"),
                          ("DIMENSION", "DIMENSION"), ("SEMANTIC", "SEMANTIC")):
        if token in text:
            return domain
    return "OTHER"


def _target_exists(model, candidate):
    question = candidate.get("question_type")
    object_id = candidate.get("object_or_region_id")
    if question in {"SPACE_CLASSIFICATION", "OPEN_PLAN_CONFIRMATION"}:
        return any(x.get("physical_space_id") == object_id and x.get("polygon")
                   for x in model.get("physical_spaces") or [])
    if question in {"PORTAL_INTERPRETATION", "WALL_CONTINUITY_INTERPRETATION"}:
        aperture_id = candidate.get("target_aperture_id") or object_id
        return any(x.get("aperture_id") == aperture_id and x.get("geometry") and x.get("host_wall_ids")
                   for x in model.get("apertures") or [])
    if question == "VOID_INTERPRETATION":
        return any(x.get("void_id") == object_id and x.get("boundary") and x.get("source_handles")
                   for x in model.get("voids") or [])
    if question == "FRAME_LEVEL_CLASSIFICATION":
        return any(x.get("frame_id") == object_id for x in model.get("frames") or []) and bool(
            candidate.get("candidate_interpretations"))
    return bool(object_id and candidate.get("existing_source_evidence"))


def _default_effects(question_type, answers):
    forbidden = ["CREATE_GEOMETRY", "CREATE_WALL", "CREATE_APERTURE", "CREATE_PORTAL",
                 "CREATE_VOID", "CREATE_ACCESS", "MODIFY_SOURCE"]
    result = {}
    for answer in answers:
        if answer == "UNKNOWN":
            result[answer] = {"may": ["RECORD_UNKNOWN"], "must_not": forbidden}
        elif question_type == "PORTAL_INTERPRETATION":
            result[answer] = {"may": ["CLASSIFY_EXISTING_APERTURE", "CLASSIFY_EXISTING_PORTAL"],
                              "must_not": forbidden}
        elif question_type == "VOID_INTERPRETATION":
            result[answer] = {"may": ["CLASSIFY_EXISTING_VOID_BOUNDARY"], "must_not": forbidden}
        elif question_type == "WALL_CONTINUITY_INTERPRETATION":
            result[answer] = {"may": ["CLASSIFY_EXISTING_CONTINUITY_CANDIDATE"], "must_not": forbidden}
        elif question_type == "OPEN_PLAN_CONFIRMATION":
            result[answer] = {"may": ["CLASSIFY_EXISTING_SPACE_RELATION"], "must_not": forbidden}
        else:
            result[answer] = {"may": ["CLASSIFY_EXISTING_SOURCE_EVIDENCE"], "must_not": forbidden}
    return result


def _normalize_issues(model, report, registry):
    source_sha = (model.get("source") or {}).get("source_sha256")
    issues = []
    unresolved = model.get("unresolved_items") or []
    has_specific = bool(unresolved)
    for bucket, rows in (("HARD", report.get("hard_errors") or []),
                         ("INPUT", report.get("input_requirements") or []),
                         ("WARNING", report.get("warnings") or [])):
        for raw in rows:
            code = raw.get("code", "UNKNOWN")
            if code == "ARCHITECTURE_RELEASE_INPUT_REQUIRED" and has_specific:
                continue
            context = {k: deepcopy(v) for k, v in raw.items() if k != "code"}
            if code in ENGINE_CODES:
                classification = "ENGINE_DEFECT_OR_CONTRACT_ERROR"
            elif code in CONFLICT_CODES or code in SOURCE_CODES:
                classification = "SOURCE_INPUT_REQUIRED"
            elif bucket == "WARNING":
                classification = "NONCRITICAL_DIAGNOSTIC"
            else:
                classification = "SOURCE_INPUT_REQUIRED"
            impact = "RELEASE_CRITICAL" if bucket == "HARD" else "DOWNSTREAM_CRITICAL"
            issues.append({"issue_id": _issue_id(source_sha, bucket, code, context),
                           "normalized_code": code, "raw_validator_codes": [code],
                           "raw_context": context, "classification": classification,
                           "impact_classification": impact, "domain": _domain(code, context),
                           "root_cause_key": content_hash([code, context]), "review_candidate": None})
    for row in unresolved:
        code = row.get("issue_type") or "CANONICAL_TOPOLOGY_UNRESOLVED"
        candidate = deepcopy(row.get("review_candidate") or {})
        context = {"unresolved_item_id": row.get("unresolved_item_id"),
                   "object_or_region_id": row.get("object_or_region_id"),
                   "evidence": deepcopy(row.get("evidence") or {})}
        noncritical = row.get("downstream_impact") == "NONCRITICAL_DIAGNOSTIC"
        reviewable = (not noncritical and candidate.get("can_resolve_without_geometry_creation") is True and
                      candidate.get("geometry_fingerprint") and candidate.get("evidence_fingerprint") and
                      candidate.get("allowed_answers") and _target_exists(model, candidate))
        classification = ("NONCRITICAL_DIAGNOSTIC" if noncritical else
                          "REVIEWABLE_SOURCE_INTERPRETATION" if reviewable else "SOURCE_INPUT_REQUIRED")
        impact = ("NONCRITICAL_DIAGNOSTIC" if noncritical else
                  row.get("impact_classification") or candidate.get("impact_classification") or "DOWNSTREAM_CRITICAL")
        root = candidate.get("root_cause_key") or content_hash([
            candidate.get("question_type"), candidate.get("frame_or_level_id"),
            candidate.get("object_or_region_id") or row.get("object_or_region_id"),
            candidate.get("geometry_fingerprint"), candidate.get("evidence_fingerprint")])
        issue = {"issue_id": _issue_id(source_sha, "CANONICAL", code, context),
                 "normalized_code": code, "raw_validator_codes": [code], "raw_context": context,
                 "classification": classification, "impact_classification": impact,
                 "domain": _domain(code, context), "root_cause_key": root,
                 "review_candidate": candidate}
        convergence = (registry.get("convergence") or {}).get(root) or {}
        if convergence.get("status") in {"EXHAUSTED", "DECLINED_UNKNOWN"}:
            issue["classification"] = ("ENGINE_DEFECT_OR_CONTRACT_ERROR" if
                                       convergence.get("cause") == "ENGINE" else "SOURCE_INPUT_REQUIRED")
            issue["convergence_status"] = convergence.get("status")
        issues.append(issue)
    return sorted(issues, key=lambda x: x["issue_id"])


def _make_item(model, group, recommendations):
    candidate = deepcopy(group[0]["review_candidate"])
    answers = sorted(set(candidate.get("allowed_answers") or []))
    question_type = candidate.get("question_type") or "OTHER_BOUNDED_SOURCE_INTERPRETATION"
    recommendation = (recommendations or {}).get(candidate.get("root_cause_key"), {})
    effects = candidate.get("expected_effects") or _default_effects(question_type, answers)
    return create_review_item(
        source_sha256=model.get("source", {}).get("source_sha256"),
        frame_or_level_id=candidate.get("frame_or_level_id"),
        object_or_region_id=candidate.get("object_or_region_id") or group[0]["raw_context"].get("object_or_region_id"),
        geometry_fingerprint=candidate.get("geometry_fingerprint"),
        evidence_fingerprint=candidate.get("evidence_fingerprint"),
        review_scope=candidate.get("review_scope") or "BOUNDED_SOURCE_INTERPRETATION",
        question_type=question_type,
        candidate_interpretations=candidate.get("candidate_interpretations") or answers,
        allowed_answers=answers,
        impact={"classification": group[0]["impact_classification"],
                "downstream": candidate.get("downstream_impact")},
        evidence_summary=candidate.get("evidence_summary"),
        validator_issue_ids_covered=[x["issue_id"] for x in group],
        expected_effects=effects, can_resolve_without_geometry_creation=True,
        blocking_status="BLOCKING" if group[0]["impact_classification"] != "NONCRITICAL_DIAGNOSTIC" else "NONBLOCKING",
        preview_spec=candidate.get("preview_spec"),
        ai_recommendation=recommendation.get("answer"),
        ai_recommendation_confidence=recommendation.get("confidence"))


def plan_preflight(canonical_model, validator_report=None, review_registry=None,
                   recommendation_evidence=None):
    registry = deepcopy(review_registry or empty_review_registry())
    recomputed = validate_architecture(canonical_model)
    supplied = validator_report or recomputed
    integrity = validate_validator_report_integrity(supplied, content_hash(canonical_model))
    report_mismatch = supplied.get("report_hash") != recomputed.get("report_hash") or integrity["status"] != "PASS"
    issues = _normalize_issues(canonical_model, recomputed, registry)
    if report_mismatch:
        context = {"supplied_report_hash": supplied.get("report_hash"),
                   "recomputed_report_hash": recomputed.get("report_hash")}
        issues.append({"issue_id": _issue_id(canonical_model.get("source", {}).get("source_sha256"),
                                              "ENGINE", "VALIDATOR_REPORT_MISMATCH", context),
                       "normalized_code": "VALIDATOR_REPORT_MISMATCH",
                       "raw_validator_codes": integrity.get("errors") or ["VALIDATOR_REPORT_MISMATCH"],
                       "raw_context": context, "classification": "ENGINE_DEFECT_OR_CONTRACT_ERROR",
                       "impact_classification": "RELEASE_CRITICAL", "domain": "OTHER",
                       "root_cause_key": content_hash(context), "review_candidate": None})
    groups = {}
    for issue in issues:
        if issue["classification"] == "REVIEWABLE_SOURCE_INTERPRETATION":
            groups.setdefault(issue["root_cause_key"], []).append(issue)
    applied_fingerprints = {x.get("review_fingerprint") for x in registry.get("accepted_decisions") or []}
    items = []
    for root, group in sorted(groups.items()):
        item = _make_item(canonical_model, group, recommendation_evidence)
        if item["review_fingerprint"] not in applied_fingerprints:
            items.append(item)
    items.sort(key=lambda item: (IMPACT_RANK.get(item["impact_classification"], 9),
                                 DOMAIN_RANK.get(_domain(item["question_type"], item), 9),
                                 -len(item["validator_issue_ids_covered"]), item["review_item_id"]))
    engine = [x for x in issues if x["classification"] == "ENGINE_DEFECT_OR_CONTRACT_ERROR"]
    conflicts = [x for x in issues if x["normalized_code"] in CONFLICT_CODES]
    source_required = [x for x in issues if x["classification"] == "SOURCE_INPUT_REQUIRED"]
    critical = [x for x in issues if x["impact_classification"] != "NONCRITICAL_DIAGNOSTIC"]
    if recomputed["status"] == "PASS" and not critical:
        state = "AUTO_VALIDATED"
    elif engine or conflicts or recomputed["status"] == "CONFLICT":
        state = "CONFLICT"
    elif source_required:
        state = "ARCHITECTURE_INPUT_REQUIRED"
    elif items:
        state = "QUICK_REVIEW_REQUIRED"
    else:
        state = "ARCHITECTURE_INPUT_REQUIRED"
    covered = {issue_id for item in items for issue_id in item["validator_issue_ids_covered"]}
    hidden = [x["issue_id"] for x in critical if x["classification"] == "REVIEWABLE_SOURCE_INTERPRETATION"
              and x["issue_id"] not in covered and x.get("convergence_status") is None]
    registry["generated_review_items"] = deepcopy(items)
    registry["unresolved_issue_ids"] = sorted(x["issue_id"] for x in critical)
    issue_count = len(issues); question_count = len(items)
    metrics = {"validator_issue_count": issue_count, "critical_issue_count": len(critical),
               "reviewable_issue_count": sum(x["classification"] == "REVIEWABLE_SOURCE_INTERPRETATION" for x in issues),
               "nonreviewable_issue_count": sum(x["classification"] in {"SOURCE_INPUT_REQUIRED", "ENGINE_DEFECT_OR_CONTRACT_ERROR"} for x in issues),
               "generated_review_item_count": question_count,
               "issue_to_question_reduction_ratio": (issue_count / question_count if question_count else 0.0),
               "resolved_issue_count": len(registry.get("resolved_issue_ids") or []),
               "remaining_issue_count": len(critical),
               "stale_decision_count": len(registry.get("stale_decisions") or []),
               "duplicate_question_count": len(items) - len({x["review_fingerprint"] for x in items}),
               "repeated_question_after_same_decision_count": 0,
               "manual_geometry_creation_count": registry.get("manual_geometry_creation_count", 0),
               "critical_unresolved_hidden": len(hidden),
               "critical_unresolved_hidden_count": len(hidden),
               "false_review_authority_count": 0,
               "synthetic_portal_from_review_count": 0,
               "synthetic_void_from_review_count": 0,
               "synthetic_wall_from_review_count": 0,
               "validator_bypass_count": 0, "snapshot_created": False}
    return {"schema": PREFLIGHT_SCHEMA, "primary_state": state,
            "source_sha256": canonical_model.get("source", {}).get("source_sha256"),
            "canonical_model_hash": canonical_model.get("canonical_model_hash"),
            "validator_report_hash": recomputed.get("report_hash"),
            "raw_validator_codes": sorted({code for x in issues for code in x["raw_validator_codes"]}),
            "normalized_issues": issues, "review_items": items,
            "source_input_requirements": [_source_action(x) for x in source_required],
            "engine_defects": engine, "noncritical_diagnostics": [x for x in issues if x["classification"] == "NONCRITICAL_DIAGNOSTIC"],
            "review_registry": registry, "metrics": metrics,
            "validator_bypass_count": 0, "review_engine_self_pass": False}


def measure_preflight_performance(canonical_model, decisions=None):
    """Return non-canonical timings; timings never affect plan identity."""
    started = time.perf_counter(); report = validate_architecture(canonical_model)
    validation_ms = (time.perf_counter() - started) * 1000.0
    started = time.perf_counter(); plan = plan_preflight(canonical_model, report)
    planning_ms = (time.perf_counter() - started) * 1000.0
    replay_ms = 0.0; revalidation_ms = 0.0
    if decisions:
        started = time.perf_counter(); replayed = replay_review_decisions(canonical_model, decisions, plan)
        replay_ms = (time.perf_counter() - started) * 1000.0
        revalidation_ms = replayed.get("preflight_plan", {}).get("performance", {}).get("revalidation_ms", 0.0)
    return {"issue_normalization_and_planning_ms": planning_ms,
            "initial_validation_ms": validation_ms, "replay_and_revalidation_ms": replay_ms,
            "revalidation_ms": revalidation_ms}


def _source_action(issue):
    code = issue["normalized_code"]
    guidance = {
        "EFFECTIVE_SCALE_REQUIRED": "Provide explicit drawing units or a governed scale calibration.",
        "FRAME_LEVEL_UNRESOLVED": "Provide an explicit level identity for the affected frame.",
        "VOID_SOURCE_GEOMETRY_REQUIRED": "Provide a closed source-backed void or shaft boundary.",
        "PORTAL_TOPOLOGY_UNRESOLVED": "Provide or correct the source-backed wall aperture and its host geometry.",
    }.get(code, "Correct the identified source geometry or identity; human classification cannot create the missing evidence.")
    return {"issue_id": issue["issue_id"], "frame_or_level_id": issue["raw_context"].get("frame_or_level_id"),
            "affected_object": issue["raw_context"].get("object_or_region_id"),
            "missing_evidence": code, "downstream_impact": issue["impact_classification"],
            "suggested_source_correction": guidance}


def _geometry_guard(model):
    return content_hash({"source": model.get("source"),
                         "walls": [{"id": x.get("wall_id"), "centerline": x.get("centerline"),
                                    "face_a": x.get("face_a"), "face_b": x.get("face_b")}
                                   for x in model.get("walls") or []],
                         "spaces": [{"id": x.get("physical_space_id"), "polygon": x.get("polygon"),
                                     "interior_rings": x.get("interior_rings")}
                                    for x in model.get("physical_spaces") or []],
                         "apertures": [{"id": x.get("aperture_id"), "geometry": x.get("geometry")}
                                       for x in model.get("apertures") or []],
                         "portals": [{"id": x.get("opening_id"), "geometry": x.get("geometry")}
                                     for x in model.get("portals") or []],
                         "voids": [{"id": x.get("void_id"), "boundary": x.get("boundary")}
                                   for x in model.get("voids") or []]})


def _review_trace(entity, item, decision):
    entity["review_status"] = "CONFIRMED"
    entity["review_authority"] = "HUMAN_SOURCE_INTERPRETATION"
    trace = {"review_item_id": item["review_item_id"], "decision": decision,
             "source_sha256": item["source_sha256"],
             "geometry_fingerprint": item["geometry_fingerprint"],
             "evidence_fingerprint": item["evidence_fingerprint"],
             "review_fingerprint": item["review_fingerprint"]}
    if trace not in (entity.get("review_trace") or []):
        entity.setdefault("review_trace", []).append(trace)


def _apply_overlay(model, item, decision):
    if decision == "UNKNOWN":
        return False
    qtype = item["question_type"]; object_id = item["object_or_region_id"]
    if qtype == "SPACE_CLASSIFICATION":
        entity = next((x for x in model.get("physical_spaces") or [] if x.get("physical_space_id") == object_id), None)
        if not entity: return False
        entity["category"] = decision; _review_trace(entity, item, decision); return True
    if qtype == "OPEN_PLAN_CONFIRMATION":
        entity = next((x for x in model.get("physical_spaces") or [] if x.get("physical_space_id") == object_id), None)
        if not entity: return False
        if decision == "SAME_PHYSICAL_SPACE": entity["category"] = "OPEN_PLAN"
        _review_trace(entity, item, decision); return True
    if qtype in {"PORTAL_INTERPRETATION", "WALL_CONTINUITY_INTERPRETATION"}:
        aperture = next((x for x in model.get("apertures") or [] if x.get("aperture_id") == object_id), None)
        if not aperture or not aperture.get("geometry") or not aperture.get("host_wall_ids"): return False
        aperture["classification"] = decision; _review_trace(aperture, item, decision)
        portal = next((x for x in model.get("portals") or [] if x.get("host_aperture_id") == object_id), None)
        if decision in {"DOOR", "WINDOW", "OPEN_PASSAGE"} and portal:
            portal["type"] = decision; _review_trace(portal, item, decision)
            if portal.get("host_wall_id") and portal.get("space_a") and portal.get("space_b"):
                portal["status"] = "VERIFIED"; portal.setdefault("authority", {})["portal"] = True
                portal["authority"]["access"] = decision in {"DOOR", "OPEN_PASSAGE"} and any(
                    e.get("portal_id") == portal.get("portal_id") for e in model.get("graphs", {}).get("access") or [])
        if decision == "WINDOW" and portal:
            portal.setdefault("authority", {})["access"] = False
            model["graphs"]["access"] = [e for e in model.get("graphs", {}).get("access") or []
                                                if e.get("portal_id") != portal.get("portal_id")]
        return True
    if qtype == "VOID_INTERPRETATION":
        entity = next((x for x in model.get("voids") or [] if x.get("void_id") == object_id), None)
        if not entity or not entity.get("boundary") or not entity.get("source_handles"): return False
        entity["type"] = decision; _review_trace(entity, item, decision); return True
    if qtype == "FRAME_LEVEL_CLASSIFICATION":
        entity = next((x for x in model.get("frames") or [] if x.get("frame_id") == object_id), None)
        if not entity or not any(x.get("level_id") == decision for x in model.get("levels") or []): return False
        entity["level_id"] = decision; _review_trace(entity, item, decision); return True
    return False


def replay_review_decisions(canonical_model, decisions, preflight_plan=None, review_registry=None):
    plan = preflight_plan or plan_preflight(canonical_model, review_registry=review_registry)
    registry = deepcopy(review_registry or plan.get("review_registry") or empty_review_registry())
    model = deepcopy(canonical_model); before_geometry = _geometry_guard(model)
    items = {x["review_item_id"]: x for x in plan.get("review_items") or []}
    previous = {(x.get("review_fingerprint"), x.get("decision")): x
                for x in registry.get("accepted_decisions") or []}
    accepted_now = []; resolved = set(registry.get("resolved_issue_ids") or [])
    for payload in decisions or []:
        item = items.get(payload.get("review_item_id"))
        rejection = {"review_item_id": payload.get("review_item_id"), "decision": payload.get("decision")}
        if not item:
            rejection.update(status="REJECTED", errors=["REVIEW_ITEM_NOT_FOUND"])
            registry["rejected_decisions"].append(rejection); continue
        identity_keys = ("source_sha256", "frame_or_level_id", "object_or_region_id",
                         "geometry_fingerprint", "evidence_fingerprint", "review_scope", "review_fingerprint")
        mismatches = [key for key in identity_keys if payload.get(key) != item.get(key)]
        current_identity = {key: item.get(key) for key in identity_keys}
        current_identity["source_sha256"] = model.get("source", {}).get("source_sha256")
        validation = validate_review_decision(item, payload.get("decision"), current_identity)
        if mismatches or validation["status"] != "ACCEPTED":
            errors = (["STALE_REVIEW_DECISION"] if mismatches else []) + validation["errors"]
            rejection.update(status="STALE" if "STALE_REVIEW_DECISION" in errors else "REJECTED", errors=sorted(set(errors)))
            target = "stale_decisions" if rejection["status"] == "STALE" else "rejected_decisions"
            registry[target].append(rejection); continue
        key = (item["review_fingerprint"], payload["decision"])
        if key in previous:
            continue
        conflicting = next((x for x in registry.get("accepted_decisions") or []
                            if x.get("review_fingerprint") == item["review_fingerprint"] and
                            x.get("decision") != payload["decision"]), None)
        if conflicting:
            rejection.update(status="REJECTED", errors=["DECISION_CONFLICT"])
            registry["rejected_decisions"].append(rejection); continue
        applied = _apply_overlay(model, item, payload["decision"])
        record = {"decision_id": "ARCHDECISION-" + content_hash(key)[:20].upper(),
                  "review_item_id": item["review_item_id"], "review_fingerprint": item["review_fingerprint"],
                  "decision": payload["decision"], "review_authority": "HUMAN_SOURCE_INTERPRETATION",
                  "material_geometry_authority": False, "applied": applied,
                  "validator_issue_ids_covered": item["validator_issue_ids_covered"]}
        registry["accepted_decisions"].append(record); registry["decision_history"].append(record)
        accepted_now.append(record); previous[key] = record
        root = next((x["root_cause_key"] for x in plan["normalized_issues"]
                     if x["issue_id"] in item["validator_issue_ids_covered"]), item["review_fingerprint"])
        if payload["decision"] == "UNKNOWN":
            registry["convergence"][root] = {"status": "DECLINED_UNKNOWN", "cause": "SOURCE",
                                               "previous_decision": "UNKNOWN", "review_attempt_count": 1}
        elif applied:
            resolved.update(item["validator_issue_ids_covered"])
    if _geometry_guard(model) != before_geometry:
        registry["manual_geometry_creation_count"] += 1
        raise ValueError("REVIEW_GEOMETRY_MUTATION_FORBIDDEN")
    if resolved:
        model["unresolved_items"] = [x for x in model.get("unresolved_items") or []
                                     if _issue_id(model.get("source", {}).get("source_sha256"), "CANONICAL",
                                                  x.get("issue_type") or "CANONICAL_TOPOLOGY_UNRESOLVED",
                                                  {"unresolved_item_id": x.get("unresolved_item_id"),
                                                   "object_or_region_id": x.get("object_or_region_id"),
                                                   "evidence": deepcopy(x.get("evidence") or {})}) not in resolved]
    registry["resolved_issue_ids"] = sorted(resolved)
    remaining_critical = [x for x in model.get("unresolved_items") or []
                          if x.get("downstream_impact") != "NONCRITICAL_DIAGNOSTIC"]
    if not remaining_critical and accepted_now and all(x.get("decision") != "UNKNOWN" and x.get("applied") for x in accepted_now):
        model["release"] = {"status": "VERIFIED", "downstream_engineering_allowed": True, "release_allowed": True}
    model["review_registry"] = deepcopy(registry)
    model.pop("canonical_model_hash", None); model["canonical_model_hash"] = content_hash(model)
    post_report = validate_architecture(model)
    post_codes = sorted({x["code"] for key in ("hard_errors", "input_requirements") for x in post_report.get(key) or []})
    registry["validation_history"].append({"validator_report_hash": post_report["report_hash"],
                                           "validator_status": post_report["status"],
                                           "post_decision_validator_codes": post_codes})
    pre_codes = set(plan.get("raw_validator_codes") or [])
    if accepted_now and post_report["status"] != "PASS" and pre_codes == set(post_codes):
        for record in accepted_now:
            root = next((x["root_cause_key"] for x in plan["normalized_issues"]
                         if x["issue_id"] in record["validator_issue_ids_covered"]), record["review_fingerprint"])
            registry["convergence"][root] = {"status": "EXHAUSTED", "cause": "SOURCE",
                                               "previous_decision": record["decision"],
                                               "review_attempt_count": 1,
                                               "post_decision_validator_codes": post_codes}
    model["review_registry"] = deepcopy(registry)
    model.pop("canonical_model_hash", None); model["canonical_model_hash"] = content_hash(model)
    post_report = validate_architecture(model)
    next_plan = plan_preflight(model, post_report, registry)
    return {"reviewed_canonical_model": model, "validator_report": post_report,
            "preflight_plan": next_plan, "review_registry": registry,
            "accepted_review_decisions": accepted_now,
            "stale_review_decisions": deepcopy(registry["stale_decisions"]),
            "rejected_review_decisions": deepcopy(registry["rejected_decisions"])}


def execute_preflight(canonical_model, decisions=None, review_registry=None, *,
                      engine_identity=None, created_at=None, recommendation_evidence=None):
    report = validate_architecture(canonical_model)
    initial = plan_preflight(canonical_model, report, review_registry, recommendation_evidence)
    if report["status"] == "PASS" and not decisions:
        snapshot = create_snapshot(canonical_model, report, engine_identity=engine_identity or {},
                                   created_at=created_at or "UNSPECIFIED", validation_state="AUTO_VALIDATED")
        initial["metrics"]["snapshot_created"] = True
        return {"preflight_plan": initial, "canonical_model": canonical_model,
                "validator_report": report, "review_registry": initial["review_registry"],
                "snapshot": snapshot}
    if not decisions:
        return {"preflight_plan": initial, "canonical_model": canonical_model,
                "validator_report": report, "review_registry": initial["review_registry"], "snapshot": None}
    replayed = replay_review_decisions(canonical_model, decisions, initial, review_registry)
    snapshot = None
    if replayed["validator_report"]["status"] == "PASS":
        registry = replayed["review_registry"]
        snapshot = create_snapshot(replayed["reviewed_canonical_model"], replayed["validator_report"],
                                   engine_identity=engine_identity or {}, created_at=created_at or "UNSPECIFIED",
                                   review_manifest=registry,
                                   review_decision_ids=[x["decision_id"] for x in registry["accepted_decisions"]],
                                   validation_state="VALIDATED")
        replayed["preflight_plan"]["metrics"]["snapshot_created"] = True
    replayed["snapshot"] = snapshot
    return replayed
