"""Bounded, replay-safe review contract for canonical architecture evidence."""
from __future__ import annotations

from copy import deepcopy

from .architecture_contract import content_hash


REVIEW_SCHEMA = "planha-architecture-review/1.0"
REVIEW_AUTHORITY = "HUMAN_SOURCE_INTERPRETATION"
AI_AUTHORITY = "ADVISORY_ONLY"
QUESTION_TYPES = {"SPACE_CLASSIFICATION", "OPEN_PLAN_CONFIRMATION", "PORTAL_INTERPRETATION",
                  "VOID_INTERPRETATION", "WALL_CONTINUITY_INTERPRETATION",
                  "FRAME_LEVEL_CLASSIFICATION", "SOURCE_ROLE_CLASSIFICATION",
                  "OTHER_BOUNDED_SOURCE_INTERPRETATION"}
IMPACT_CLASSES = {"RELEASE_CRITICAL", "DOWNSTREAM_CRITICAL", "REVIEW_CRITICAL",
                  "NONCRITICAL_DIAGNOSTIC"}


def _review_identity(row):
    return {key: row.get(key) for key in
            ("source_sha256", "frame_or_level_id", "object_or_region_id",
             "geometry_fingerprint", "evidence_fingerprint", "review_scope")}


def _governed_item(row):
    return {key: deepcopy(row.get(key)) for key in
            ("schema", "review_item_id", "source_sha256", "frame_or_level_id",
             "object_or_region_id", "geometry_fingerprint", "evidence_fingerprint",
             "review_scope", "question_type", "candidate_interpretations",
             "allowed_answers", "expected_effects", "can_resolve_without_geometry_creation",
             "blocking_status",
             "ai_recommendation_authority", "review_authority",
             "manual_geometry_authority", "identity_fingerprint")}


def _presentation_item(row):
    return {key: deepcopy(row.get(key)) for key in
            ("review_item_id", "evidence_summary", "impact", "impact_classification",
             "validator_issue_ids_covered", "preview_spec", "ai_recommendation",
             "ai_recommendation_confidence")}


def create_review_item(*, source_sha256, frame_or_level_id, object_or_region_id,
                       geometry_fingerprint, evidence_fingerprint,
                       candidate_interpretations, allowed_answers, impact,
                       review_scope, question_type="OTHER_BOUNDED_SOURCE_INTERPRETATION",
                       evidence_summary=None, validator_issue_ids_covered=None,
                       expected_effects=None, can_resolve_without_geometry_creation=True,
                       blocking_status="BLOCKING", preview_spec=None,
                       ai_recommendation=None, ai_recommendation_confidence=None):
    if question_type not in QUESTION_TYPES:
        raise ValueError("REVIEW_QUESTION_TYPE_UNSUPPORTED")
    impact_classification = impact if isinstance(impact, str) else (impact or {}).get("classification")
    if impact_classification not in IMPACT_CLASSES:
        impact_classification = "REVIEW_CRITICAL"
    identity = {"source_sha256": source_sha256,
                "frame_or_level_id": frame_or_level_id,
                "object_or_region_id": object_or_region_id,
                "geometry_fingerprint": geometry_fingerprint,
                "evidence_fingerprint": evidence_fingerprint,
                "review_scope": review_scope}
    item = {"schema": REVIEW_SCHEMA,
            "review_item_id": "ARCHREVIEW-" + content_hash(identity)[:20].upper(),
            **identity,
            "candidate_interpretations": sorted(set(candidate_interpretations)),
            "allowed_answers": sorted(set(allowed_answers)),
            "question_type": question_type,
            "evidence_summary": deepcopy(evidence_summary or {}),
            "impact": deepcopy(impact), "impact_classification": impact_classification,
            "validator_issue_ids_covered": sorted(set(validator_issue_ids_covered or [])),
            "expected_effects": deepcopy(expected_effects or {}),
            "can_resolve_without_geometry_creation": bool(can_resolve_without_geometry_creation),
            "blocking_status": blocking_status,
            "preview_spec": deepcopy(preview_spec or {}),
            "ai_recommendation": ai_recommendation,
            "ai_recommendation_confidence": ai_recommendation_confidence,
            "ai_recommendation_authority": AI_AUTHORITY,
            "review_authority": REVIEW_AUTHORITY,
            "manual_geometry_authority": False,
            "identity_fingerprint": content_hash(identity)}
    item["review_fingerprint"] = content_hash(_governed_item(item))
    item["presentation_hash"] = content_hash(_presentation_item(item))
    return item


def validate_review_decision(item, decision, current_identity):
    errors = []
    if item.get("schema") != REVIEW_SCHEMA:
        errors.append("REVIEW_SCHEMA_MISMATCH")
    if decision not in (item.get("allowed_answers") or []):
        errors.append("REVIEW_DECISION_NOT_ALLOWED")
    identity = _review_identity(current_identity)
    current_fingerprint = content_hash(identity)
    if item.get("identity_fingerprint") != current_fingerprint:
        errors.append("REVIEW_DECISION_STALE")
    if item.get("review_fingerprint") != content_hash(_governed_item(item)):
        errors.append("REVIEW_ITEM_INTEGRITY_INVALID")
    if item.get("manual_geometry_authority") is not False:
        errors.append("REVIEW_GEOMETRY_AUTHORITY_FORBIDDEN")
    if not item.get("can_resolve_without_geometry_creation"):
        errors.append("REVIEW_REQUIRES_GEOMETRY_CREATION")
    return {"status": "ACCEPTED" if not errors else "REJECTED",
            "errors": errors, "decision": decision,
            "authority": REVIEW_AUTHORITY if not errors else "NONE",
            "material_geometry_authority": False}
