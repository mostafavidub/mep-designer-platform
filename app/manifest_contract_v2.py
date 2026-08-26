"""Approved mechanical drawing manifest contract v2.

Hardens the existing manifest workflow without changing how sheets are planned:
content hash, schema/count/code validation, frozen approval identity and exact
CAD parity are checked at every boundary.
"""
import copy
import hashlib
import json


def _canonical_payload(manifest):
    manifest = copy.deepcopy(manifest or {})
    manifest.pop("manifest_id", None)
    return manifest


def manifest_digest(manifest):
    payload = _canonical_payload(manifest)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_manifest(manifest, expected_schema=None):
    manifest = manifest or {}
    sheets = manifest.get("sheets") or []
    try:
        total = int(manifest.get("total_sheets"))
    except (TypeError, ValueError):
        return False
    codes = [str(row.get("code") or "") for row in sheets]
    if expected_schema and manifest.get("schema_version") != expected_schema:
        return False
    if total < 1 or total != len(sheets):
        return False
    if not codes or any(not code for code in codes) or len(codes) != len(set(codes)):
        return False
    stored = str(manifest.get("manifest_id") or "")
    return bool(stored) and stored == manifest_digest(manifest)


def install(workflow_module, planner_module, dxf_module):
    if getattr(workflow_module, "_manifest_contract_v2_installed", False):
        return

    schema = planner_module.MANIFEST_SCHEMA_VERSION
    original_approve = planner_module.approve_drawing_set
    original_validate_generated = dxf_module.validate_generated_manifest

    def is_current_manifest_v2(manifest):
        return validate_manifest(manifest, expected_schema=schema)

    def approve_v2(proposal):
        proposal = copy.deepcopy(proposal or {})
        manifest = proposal.get("drawing_manifest") or {}
        if not is_current_manifest_v2(manifest):
            raise ValueError("Drawing manifest content hash/schema/count is invalid; recalculate the proposal.")
        # Preserve the existing approval semantics after the stronger check.
        approved = original_approve(proposal)
        frozen = copy.deepcopy(approved.get("approved_manifest") or {})
        if not is_current_manifest_v2(frozen):
            raise ValueError("Approved drawing manifest could not be frozen safely.")
        approved["approved_manifest_id"] = frozen["manifest_id"]
        approved["approval_contract_version"] = "2.0"
        return approved

    def validate_generated_v2(drawing_set, design_reports):
        drawing_set = drawing_set or {}
        current = drawing_set.get("drawing_manifest") or {}
        approved = drawing_set.get("approved_manifest") or {}
        if not is_current_manifest_v2(current) or not is_current_manifest_v2(approved):
            raise RuntimeError("Generation Failed: drawing manifest contract is invalid or stale.")
        if current.get("manifest_id") != approved.get("manifest_id"):
            raise RuntimeError("Generation Failed: approved manifest changed after approval.")
        frozen_id = drawing_set.get("approved_manifest_id")
        if frozen_id and frozen_id != approved.get("manifest_id"):
            raise RuntimeError("Generation Failed: frozen approval manifest identity mismatch.")
        result = original_validate_generated(drawing_set, design_reports)
        if result.get("manifest_id") != approved.get("manifest_id"):
            raise RuntimeError("Generation Failed: CAD report manifest identity mismatch.")
        result["contract_version"] = "2.0"
        result["content_hash_verified"] = True
        return result

    planner_module.is_current_manifest = is_current_manifest_v2
    planner_module.approve_drawing_set = approve_v2
    workflow_module.is_current_manifest = is_current_manifest_v2
    workflow_module.approve_drawing_set = approve_v2
    dxf_module.validate_generated_manifest = validate_generated_v2
    workflow_module._manifest_contract_v2_installed = True
