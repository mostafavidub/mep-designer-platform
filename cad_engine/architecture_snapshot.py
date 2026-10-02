"""Immutable validated architecture snapshot contract."""
from __future__ import annotations

from copy import deepcopy

from .architecture_contract import SCHEMA as CANONICAL_SCHEMA, content_hash


SNAPSHOT_SCHEMA = "planha-validated-architecture-snapshot/1.0"
LIFECYCLE_STATES = {"AUTO_VALIDATED", "QUICK_REVIEW_REQUIRED", "ARCHITECTURE_INPUT_REQUIRED",
                    "VALIDATED", "SUPERSEDED"}


def create_snapshot(canonical_model, validator_report, *, engine_identity, created_at,
                    source_revision=None, review_manifest=None, validation_state=None):
    if canonical_model.get("schema") != CANONICAL_SCHEMA:
        raise ValueError("CANONICAL_SCHEMA_MISMATCH")
    model_hash = canonical_model.get("canonical_model_hash")
    candidate = deepcopy(canonical_model); candidate.pop("canonical_model_hash", None)
    if model_hash != content_hash(candidate):
        raise ValueError("CANONICAL_MODEL_HASH_INVALID")
    report_hash = validator_report.get("report_hash")
    state = validation_state or ("AUTO_VALIDATED" if validator_report.get("status") == "PASS" else
                                 "ARCHITECTURE_INPUT_REQUIRED")
    if state not in LIFECYCLE_STATES:
        raise ValueError("SNAPSHOT_STATE_INVALID")
    review_hash = content_hash(review_manifest) if review_manifest else None
    identity = {"canonical_schema_version": CANONICAL_SCHEMA, "canonical_model_hash": model_hash,
                "source_sha256": canonical_model.get("source", {}).get("source_sha256"),
                "source_revision": source_revision or canonical_model.get("source", {}).get("source_revision_identity"),
                "adapter_id": canonical_model.get("source", {}).get("adapter", {}).get("adapter_id"),
                "adapter_version": canonical_model.get("source", {}).get("adapter", {}).get("adapter_version"),
                "engine_identity": deepcopy(engine_identity),
                "validator_version": validator_report.get("validator_version"),
                "validator_report_hash": report_hash, "review_manifest_hash": review_hash,
                "created_at": created_at, "validation_state": state}
    return {"schema": SNAPSHOT_SCHEMA, "snapshot_id": "ARCHSNAP-" + content_hash(identity)[:24].upper(),
            **identity, "immutable": True}


def validate_snapshot(snapshot, canonical_model, validator_report, *, review_manifest=None,
                      current_source_sha256=None):
    errors = []
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        errors.append("SNAPSHOT_SCHEMA_MISMATCH")
    if snapshot.get("validation_state") == "SUPERSEDED":
        errors.append("SNAPSHOT_SUPERSEDED")
    if snapshot.get("canonical_model_hash") != canonical_model.get("canonical_model_hash"):
        errors.append("SNAPSHOT_CANONICAL_MODEL_STALE")
    if snapshot.get("source_sha256") != canonical_model.get("source", {}).get("source_sha256"):
        errors.append("SNAPSHOT_SOURCE_IDENTITY_STALE")
    if current_source_sha256 and snapshot.get("source_sha256") != current_source_sha256:
        errors.append("SNAPSHOT_SOURCE_CHANGED")
    if snapshot.get("validator_version") != validator_report.get("validator_version") or snapshot.get(
            "validator_report_hash") != validator_report.get("report_hash"):
        errors.append("SNAPSHOT_VALIDATOR_RESULT_STALE")
    expected_review = content_hash(review_manifest) if review_manifest else None
    if snapshot.get("review_manifest_hash") != expected_review:
        errors.append("SNAPSHOT_REVIEW_MANIFEST_STALE")
    identity = {key: snapshot.get(key) for key in
                ("canonical_schema_version", "canonical_model_hash", "source_sha256", "source_revision",
                 "adapter_id", "adapter_version", "engine_identity", "validator_version",
                 "validator_report_hash", "review_manifest_hash", "created_at", "validation_state")}
    expected_id = "ARCHSNAP-" + content_hash(identity)[:24].upper()
    if snapshot.get("snapshot_id") != expected_id:
        errors.append("SNAPSHOT_IDENTITY_INVALID")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors,
            "current_authority": not errors and snapshot.get("validation_state") in {"AUTO_VALIDATED", "VALIDATED"}}


def supersede_snapshot(snapshot):
    row = deepcopy(snapshot)
    row["validation_state"] = "SUPERSEDED"
    identity = {key: row.get(key) for key in
                ("canonical_schema_version", "canonical_model_hash", "source_sha256", "source_revision",
                 "adapter_id", "adapter_version", "engine_identity", "validator_version",
                 "validator_report_hash", "review_manifest_hash", "created_at", "validation_state")}
    row["snapshot_id"] = "ARCHSNAP-" + content_hash(identity)[:24].upper()
    return row
