"""Step 12: non-destructive final delivery acceptance.

The legacy v17 isolation layer may sanitize a candidate by deleting modelspace
entities or empty paperspace layouts. A release candidate must never become
acceptable because a post-generation cleanup removed evidence. This gate is
read-only and fails closed whenever that sanitizer had to mutate the candidate.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from .final_delivery_gate_v17 import validate_final_delivery


VERSION = "final-delivery-step12/1"
POLICY = "NO_POST_HOC_DELETION_TO_ACHIEVE_RELEASE_PASS"
_REQUIRED_ISOLATION_FIELDS = ("entities_before", "entities_after", "entities_removed", "empty_layouts_removed")
_REQUIRED_LEGACY_QA = ("architecture_preservation_qa_after_v17", "exact_file_final_delivery_qa", "montage_exact_reopen_qa")


def _file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _whole_number(value: Any):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    try:
        if float(value) != float(number):
            return None
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def validate_non_destructive_final_delivery(path: str | Path, report: dict | None) -> dict:
    """Validate the exact candidate and prove final acceptance did not need cleanup.

    This function never edits or saves the DXF. It treats missing mutation
    evidence as INPUT_REQUIRED and any recorded post-generation deletion as a
    release-blocking contradiction, even when the sanitized file itself looks
    valid afterwards.
    """
    path = Path(path)
    base = {"version": VERSION, "policy": POLICY}
    if not path.exists() or not path.is_file():
        return {**base, "status": "FAIL", "errors": ["FINAL_DXF_MISSING"], "missing_inputs": []}

    before_hash = _file_hash(path)
    report = report or {}
    isolation = report.get("final_delivery_isolation_qa")
    missing_inputs: list[str] = []
    errors: list[str] = []

    if not isinstance(isolation, dict) or not isolation:
        missing_inputs.append("FINAL_DELIVERY_ISOLATION_QA")
        isolation = {}
    else:
        missing_inputs.extend(
            f"FINAL_DELIVERY_ISOLATION_QA:{field}"
            for field in _REQUIRED_ISOLATION_FIELDS
            if field not in isolation
        )
        if isolation.get("status") != "PASS":
            errors.append("LEGACY_FINAL_DELIVERY_NOT_PASS")

    counts = {field: _whole_number(isolation.get(field)) for field in _REQUIRED_ISOLATION_FIELDS[:3]}
    if all(field in isolation for field in _REQUIRED_ISOLATION_FIELDS[:3]):
        invalid = [field for field, value in counts.items() if value is None]
        errors.extend(f"INVALID_MUTATION_COUNT:{field}" for field in invalid)
        if not invalid:
            if counts["entities_removed"] != 0:
                errors.append("POST_HOC_ENTITY_DELETION_REQUIRED")
            if counts["entities_before"] != counts["entities_after"]:
                errors.append("FINAL_ENTITY_COUNT_CHANGED_BY_SANITIZER")
            if counts["entities_before"] - counts["entities_after"] != counts["entities_removed"]:
                errors.append("FINAL_MUTATION_ACCOUNTING_MISMATCH")

    removed_layouts = isolation.get("empty_layouts_removed")
    if "empty_layouts_removed" in isolation:
        if not isinstance(removed_layouts, (list, tuple)):
            errors.append("INVALID_REMOVED_LAYOUT_EVIDENCE")
        elif removed_layouts:
            errors.append("POST_HOC_LAYOUT_DELETION_REQUIRED")

    legacy_qa_status = {}
    for key in _REQUIRED_LEGACY_QA:
        qa = report.get(key)
        if not isinstance(qa, dict) or not qa:
            missing_inputs.append(key.upper())
            legacy_qa_status[key] = "MISSING"
        else:
            status = str(qa.get("status") or "MISSING")
            legacy_qa_status[key] = status
            if status != "PASS":
                errors.append(f"{key.upper()}_NOT_PASS")

    exact = validate_final_delivery(path, report)
    if exact.get("status") != "PASS":
        errors.append("EXACT_FINAL_DELIVERY_RECHECK_FAILED")

    after_hash = _file_hash(path)
    if after_hash != before_hash:
        errors.append("STEP12_VALIDATOR_MUTATED_EXACT_DXF")

    status = "FAIL" if errors else ("INPUT_REQUIRED" if missing_inputs else "PASS")
    return {
        **base,
        "status": status,
        "errors": sorted(set(errors)),
        "missing_inputs": sorted(set(missing_inputs)),
        "exact_hash_before": before_hash,
        "exact_hash_after": after_hash,
        "hash_unchanged": before_hash == after_hash,
        "legacy_isolation_status": isolation.get("status", "MISSING"),
        "legacy_qa_status": legacy_qa_status,
        "entities_before": counts.get("entities_before"),
        "entities_after": counts.get("entities_after"),
        "entities_removed": counts.get("entities_removed"),
        "empty_layouts_removed": list(removed_layouts) if isinstance(removed_layouts, (list, tuple)) else removed_layouts,
        "exact_recheck": exact,
    }
