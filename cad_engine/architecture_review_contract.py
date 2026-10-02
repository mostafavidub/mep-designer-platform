"""Bounded, replay-safe review contract for canonical architecture evidence."""
from __future__ import annotations

from copy import deepcopy

from .architecture_contract import content_hash


REVIEW_SCHEMA = "planha-architecture-review/1.0"
REVIEW_AUTHORITY = "HUMAN_SOURCE_INTERPRETATION"
AI_AUTHORITY = "ADVISORY_ONLY"


def create_review_item(*, source_sha256, frame_or_level_id, object_or_region_id,
                       geometry_fingerprint, evidence_fingerprint,
                       candidate_interpretations, allowed_answers, impact,
                       review_scope, ai_recommendation=None,
                       ai_recommendation_confidence=None):
    identity = {"source_sha256": source_sha256,
                "frame_or_level_id": frame_or_level_id,
                "object_or_region_id": object_or_region_id,
                "geometry_fingerprint": geometry_fingerprint,
                "evidence_fingerprint": evidence_fingerprint,
                "review_scope": review_scope}
    return {"schema": REVIEW_SCHEMA,
            "review_item_id": "ARCHREVIEW-" + content_hash(identity)[:20].upper(),
            **identity,
            "candidate_interpretations": sorted(set(candidate_interpretations)),
            "allowed_answers": sorted(set(allowed_answers)),
            "impact": deepcopy(impact),
            "ai_recommendation": ai_recommendation,
            "ai_recommendation_confidence": ai_recommendation_confidence,
            "ai_recommendation_authority": AI_AUTHORITY,
            "review_authority": REVIEW_AUTHORITY,
            "manual_geometry_authority": False,
            "review_fingerprint": content_hash(identity)}


def validate_review_decision(item, decision, current_identity):
    errors = []
    if item.get("schema") != REVIEW_SCHEMA:
        errors.append("REVIEW_SCHEMA_MISMATCH")
    if decision not in (item.get("allowed_answers") or []):
        errors.append("REVIEW_DECISION_NOT_ALLOWED")
    identity = {key: current_identity.get(key) for key in
                ("source_sha256", "frame_or_level_id", "object_or_region_id",
                 "geometry_fingerprint", "evidence_fingerprint", "review_scope")}
    current_fingerprint = content_hash(identity)
    if item.get("review_fingerprint") != current_fingerprint:
        errors.append("REVIEW_DECISION_STALE")
    if item.get("manual_geometry_authority") is not False:
        errors.append("REVIEW_GEOMETRY_AUTHORITY_FORBIDDEN")
    return {"status": "ACCEPTED" if not errors else "REJECTED",
            "errors": errors, "decision": decision,
            "authority": REVIEW_AUTHORITY if not errors else "NONE",
            "material_geometry_authority": False}
