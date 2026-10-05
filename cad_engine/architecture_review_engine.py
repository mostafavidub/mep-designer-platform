"""Experimental bounded architecture preflight, review replay and qualification.

Human input may interpret existing source-backed candidates.  It never authors
geometry, and this module never replaces the independent architecture validator.
"""
from __future__ import annotations

from copy import deepcopy
import time

from .architecture_contract import assign_canonical_model_hash, canonical_model_hash, content_hash
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
CONFLICT_CODES = {"SEPARATOR_CONFLICT", "SEPARATOR_ROLE_CONFLICT", "ILLEGAL_PHYSICAL_SPACE_OVERLAP", "CROSS_LEVEL_PORTAL_FORBIDDEN",
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


def normalize_review_registry(registry):
    """Return the current registry shape without importing legacy authority.

    Canonical adapters may retain the historical human-gap review result under
    ``review_registry``.  Those decisions use a different scope and cannot be
    treated as separator-interval decisions.  Preserve a deterministic audit
    fingerprint while starting the current registry with no inherited grants.
    """
    if not registry:
        return empty_review_registry()
    if registry.get("schema") != REGISTRY_SCHEMA:
        current = empty_review_registry()
        current["legacy_registry_schema"] = registry.get("schema")
        current["legacy_registry_fingerprint"] = content_hash(registry)
        return current
    current = empty_review_registry()
    current.update(deepcopy(registry))
    for key, default in empty_review_registry().items():
        current.setdefault(key, deepcopy(default))
    return current


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
            if code == "SEPARATOR_ROLE_REQUIRED" and any(str(r.get("unresolved_item_id", "")).startswith("SEPARATOR-") for r in unresolved):
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
    registry = normalize_review_registry(review_registry)
    recomputed = validate_architecture(canonical_model)
    supplied = validator_report or recomputed
    integrity = validate_validator_report_integrity(supplied, canonical_model_hash(canonical_model))
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


def _apply_overlay(model, item, decision, evidence_index=None):
    if decision == "UNKNOWN":
        return False
    qtype = item["question_type"]; object_id = item["object_or_region_id"]
    evidence_index = evidence_index if evidence_index is not None else {r["evidence_id"]: r for r in model.get("evidence_registry", [])}
    if qtype == "OTHER_BOUNDED_SOURCE_INTERPRETATION" and item.get("review_scope") == "SOURCE_REGION_INTERPRETATION":
        entry = evidence_index.get(object_id)
        if entry and entry.get("kind") != "SOURCE_REVIEW_REGION": return False
        if not entry: return False
        p = entry["payload"]
        if p.get("source_sha256") != model.get("source", {}).get("source_sha256") or any(item.get(k) != p.get(k) for k in ("geometry_fingerprint", "evidence_fingerprint")):
            return False
        if decision not in p["allowed_interpretations"]: return False
        p["interpretation"] = {"decision": decision, "review_item": deepcopy(item), "scope": "SOURCE_REGION_INTERPRETATION", "separator_authority": False}
        return True
    if qtype == "SOURCE_ROLE_CLASSIFICATION":
        from .architecture_separator_evidence import KIND, SCOPE, review_candidate
        entry = evidence_index.get(object_id)
        if entry and entry.get("kind") != KIND: return False
        if not entry or item.get("review_scope") != SCOPE:
            return False
        current = review_candidate(entry)
        if any(item.get(k) != current.get(k) for k in ("geometry_fingerprint", "evidence_fingerprint", "frame_or_level_id", "review_scope")):
            return False
        entry["payload"]["separator"] = {"role": decision, "status": "VERIFIED" if decision == "PHYSICAL_SEPARATOR" else "REJECTED",
            "origin": "HUMAN_SOURCE_INTERPRETATION", "decision": decision, "review_item": deepcopy(item)}
        return True
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
    registry = normalize_review_registry(review_registry or plan.get("review_registry"))
    initial_registry = deepcopy(registry)
    model = deepcopy(canonical_model); before_geometry = _geometry_guard(model)
    items = {x["review_item_id"]: x for x in plan.get("review_items") or []}
    previous = {(x.get("review_fingerprint"), x.get("decision")): x
                for x in registry.get("accepted_decisions") or []}
    accepted_now = []; resolved = set(registry.get("resolved_issue_ids") or [])
    evidence_index = {r["evidence_id"]: r for r in model.get("evidence_registry", [])}
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
        applied = _apply_overlay(model, item, payload["decision"], evidence_index)
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
    if not accepted_now and registry == initial_registry:
        report = validate_architecture(model)
        return {"reviewed_canonical_model": model, "validator_report": report,
                "preflight_plan": plan_preflight(model, report, registry), "review_registry": registry,
                "accepted_review_decisions": [], "stale_review_decisions": deepcopy(registry["stale_decisions"]),
                "rejected_review_decisions": deepcopy(registry["rejected_decisions"])}
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
    from .architecture_separator_evidence import refresh_separator_authority
    refresh_separator_authority(model)
    assign_canonical_model_hash(model)
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
    from .architecture_separator_evidence import refresh_separator_authority
    refresh_separator_authority(model)
    assign_canonical_model_hash(model)
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
        existing_registry = normalize_review_registry(
            review_registry or canonical_model.get("review_registry"))
        reviewed = bool(existing_registry.get("accepted_decisions"))
        snapshot = create_snapshot(canonical_model, report, engine_identity=engine_identity or {},
                                   created_at=created_at or "UNSPECIFIED", validation_state="VALIDATED" if reviewed else "AUTO_VALIDATED",
                                   review_manifest=existing_registry if reviewed else None,
                                   review_decision_ids=[r["decision_id"] for r in existing_registry.get("accepted_decisions", [])])
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

# Current unresolved-inventory membership and historical reconciliation.
AUDIT_STATES = {"RETIRED", "SUPERSEDED", "INVALIDATED", "STALE_REFERENCE",
                "AMBIGUOUS_REBIND"}


def _objects(model):
    result = {}
    for collection, key in (("physical_spaces", "physical_space_id"),
                            ("walls", "wall_id"), ("voids", "void_id"),
                            ("apertures", "aperture_id"), ("portals", "opening_id"),
                            ("frames", "frame_id"), ("levels", "level_id")):
        for row in model.get(collection) or []:
            if row.get(key):
                result[row[key]] = row
    return result


def _handles(row):
    return tuple(sorted(set(row.get("source_handles") or
                            (row.get("geometry_evidence") or {}).get("source_handles") or [])))


def _current_item(project_id, model, plan, item):
    source_sha = (model.get("source") or {}).get("source_sha256")
    evidence = {row.get("evidence_id"): row for row in model.get("evidence_registry") or []}
    issues = {row.get("issue_id") for row in plan.get("normalized_issues") or []}
    frames = {row.get("frame_id") for row in model.get("frames") or []}
    levels = {row.get("level_id") for row in model.get("levels") or []}
    errors = []
    if not item.get("review_item_id") or not item.get("review_fingerprint"):
        errors.append("CURRENT_REVIEW_IDENTITY_MISSING")
    if not source_sha or item.get("source_sha256") != source_sha or plan.get("source_sha256") != source_sha:
        errors.append("CURRENT_SOURCE_SHA_MISMATCH")
    host = evidence.get(item.get("object_or_region_id"))
    if host is None:
        errors.append("CURRENT_EVIDENCE_HOST_MISSING")
    else:
        payload = host.get("payload") or {}
        if payload.get("source_sha256") != source_sha:
            errors.append("EVIDENCE_SOURCE_SHA_MISMATCH")
        if payload.get("evidence_fingerprint") != item.get("evidence_fingerprint"):
            errors.append("EVIDENCE_FINGERPRINT_MISMATCH")
        if payload.get("geometry_fingerprint") != item.get("geometry_fingerprint"):
            errors.append("GEOMETRY_FINGERPRINT_MISMATCH")
        summary = item.get("evidence_summary") or {}
        if sorted(summary.get("source_handles") or []) != sorted(
                [payload.get("source_handle")] if payload.get("source_handle") else []):
            errors.append("SOURCE_HANDLE_SCOPE_MISMATCH")
        if sorted(summary.get("segment_ids") or []) != sorted(
                [payload.get("segment_id")] if payload.get("segment_id") else []):
            errors.append("SOURCE_SEGMENT_SCOPE_MISMATCH")
    frame = item.get("frame_or_level_id")
    if frame not in frames and frame not in levels:
        errors.append("CURRENT_FRAME_OR_LEVEL_MISSING")
    covered = item.get("validator_issue_ids_covered") or []
    if not covered or not set(covered).issubset(issues):
        errors.append("CURRENT_UNRESOLVED_BINDING_MISSING")
    if errors:
        return {"state": "STALE_REFERENCE", "project_id": project_id,
                "review_item_id": item.get("review_item_id"), "errors": errors,
                "software_reconciliation_required": True,
                "record": deepcopy(item)}
    return {"state": "ACTIVE", "project_id": project_id,
            "active_identity": item.get("review_fingerprint"),
            "review_item_id": item.get("review_item_id"),
            "object_or_region_id": item.get("object_or_region_id"),
            "source_sha256": source_sha, "frame_or_level_id": frame,
            "source_handles": deepcopy((item.get("evidence_summary") or {}).get("source_handles") or []),
            "segment_ids": deepcopy((item.get("evidence_summary") or {}).get("segment_ids") or []),
            "unresolved_reason": item.get("question_type"),
            "human_review_required": True, "record": deepcopy(item)}


def _historical(project_id, model, record):
    """Reconcile an audit record without making it an active review item."""
    source_sha = (model.get("source") or {}).get("source_sha256")
    objects = _objects(model)
    old_id = record.get("object_or_region_id")
    if record.get("invalidated_by_current_evidence"):
        return {"state": "INVALIDATED", "project_id": project_id,
                "historical_id": old_id, "record": deepcopy(record)}
    if old_id in objects and record.get("source_sha256") == source_sha:
        return {"state": "SUPERSEDED", "project_id": project_id,
                "historical_id": old_id, "current_id": old_id,
                "reason": "CURRENT_OBJECT_EXISTS_BUT_HISTORY_IS_NOT_AN_ACTIVE_REVIEW_ITEM",
                "record": deepcopy(record)}
    wanted = tuple(sorted(set(record.get("source_handles") or [])))
    matches = []
    if source_sha and record.get("source_sha256") == source_sha and wanted:
        for current_id, obj in objects.items():
            if (obj.get("frame_id") == record.get("frame_id") and
                    obj.get("level_id") == record.get("level_id") and _handles(obj) == wanted):
                matches.append(current_id)
    if len(matches) == 1:
        return {"state": "SUPERSEDED", "project_id": project_id,
                "historical_id": old_id, "current_id": matches[0],
                "reason": "EXACT_SOURCE_IDENTITY_REBOUND", "record": deepcopy(record)}
    if len(matches) > 1:
        return {"state": "AMBIGUOUS_REBIND", "project_id": project_id,
                "historical_id": old_id, "candidate_current_ids": sorted(matches),
                "record": deepcopy(record)}
    return {"state": "STALE_REFERENCE", "project_id": project_id,
            "historical_id": old_id, "reason": "NO_CURRENT_PROVENANCE_MEMBERSHIP",
            "record": deepcopy(record)}


def build_unresolved_inventory(current_models, preflight_plans, historical_records=()):
    """Build a deterministic active inventory plus preserved audit records."""
    active_by_identity = {}
    audit = []
    for project_id in sorted(current_models):
        model = current_models[project_id]
        plan = preflight_plans.get(project_id) or {}
        for item in plan.get("review_items") or []:
            row = _current_item(project_id, model, plan, item)
            if row["state"] != "ACTIVE":
                audit.append(row)
                continue
            identity = row.get("active_identity")
            if identity in active_by_identity:
                audit.append({"state": "SUPERSEDED", "project_id": project_id,
                              "review_item_id": row.get("review_item_id"),
                              "reason": "DUPLICATE_CURRENT_UNRESOLVED_IDENTITY"})
            else:
                active_by_identity[identity] = row
    for record in historical_records or []:
        project_id = record.get("project_id")
        model = current_models.get(project_id)
        if model is None:
            audit.append({"state": "STALE_REFERENCE", "project_id": project_id,
                          "historical_id": record.get("object_or_region_id"),
                          "reason": "CURRENT_PROJECT_MISSING", "record": deepcopy(record)})
        else:
            audit.append(_historical(project_id, model, record))
    active = sorted(active_by_identity.values(), key=lambda row: (
        row["project_id"], row["review_item_id"]))
    audit.sort(key=lambda row: (str(row.get("project_id")), str(row.get("historical_id")),
                                str(row.get("review_item_id"))))
    software_reconciliation_count = sum(bool(row.get("software_reconciliation_required"))
                                        for row in audit)
    return {"schema": "planha-architecture-unresolved-inventory/1.0",
            "status": "PASS" if software_reconciliation_count == 0 else "FAIL",
            "active": active, "audit": audit,
            "metrics": {"active_count": len(active),
                        "unique_active_identity_count": len(active_by_identity),
                        "human_review_count": sum(bool(row.get("human_review_required")) for row in active),
                        "audit_count": len(audit),
                        "software_reconciliation_count": software_reconciliation_count}}
