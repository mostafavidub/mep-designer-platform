"""Fail-closed checks executed after the last mutation of the issued DXF."""
from __future__ import annotations

from pathlib import Path
import math

from .mechanical_cad_preservation import evaluate_architecture_preservation
from .mechanical_release_hardening import (
    validate_titleblocks, validate_safe_zones, validate_architectural_presentation,
    validate_equipment_linkage, validate_detail_library, validate_content_completeness,
    validate_split_ac_visual_legibility, create_montage_and_validate,
)
from .sheet_visual_qa import validate_all_sheet_visual_qa


def _pending_equipment_boards(report: dict, answers: dict) -> set[tuple[str,str]]:
    """Resolve only exact target-package Pre-Submission disclosures."""
    pre_submission=(answers or {}).get("_pre_submission_authority")
    if not isinstance(pre_submission,dict) or pre_submission.get("blocked_at")!="target_design_packages":
        return set()
    disclosure=(((report or {}).get("semantic_qa") or {}).get("pre_submission_disclosure") or {})
    # The canonical shell has already evaluated the engine evidence and writes
    # this disclosure only for the exact target-package authority state.  Reuse
    # that signed board-level result after materialization instead of trying to
    # reconstruct it from a second (and sometimes narrower) blocker list.
    if disclosure.get("active") is not True or disclosure.get("blocked_at")!="target_design_packages":
        return set()
    items=disclosure.get("pending_family_content") or []
    manifest={
        str(row.get("code") or "").strip().lower():str(row.get("old_sheet") or row.get("code") or "").strip().lower()
        for row in ((((report or {}).get("composition") or {}).get("manifest")) or [])
        if isinstance(row,dict) and str(row.get("code") or "").strip()
    }
    result=set()
    for item in items:
        parts=str(item).split(":",1)
        if len(parts)!=2:continue
        code=parts[0].strip().lower();family=parts[1].strip().upper()
        result.add((code,family))
        if manifest.get(code):result.add((manifest[code],family))
    # Keep parity with the canonical pre-materialization gate: the gas plan
    # may have a valid approved board while its appliance schedule/route is an
    # explicit INPUT_REQUIRED record.  Admit only that exact record identity;
    # FAIL records and unrelated families remain blocking.
    gas_table=(((report or {}).get("enrichment") or {}).get("gas_table") or {})
    for record in gas_table.get("records") or []:
        if str(record.get("status") or "").upper()!="INPUT_REQUIRED":
            continue
        code=str(record.get("sheet") or "").strip().lower()
        if not code:
            continue
        result.add((code,"GAS"))
        if manifest.get(code):
            result.add((manifest[code],"GAS"))
    return result


def validate_coordinate_evidence(materialization):
    rows = materialization.get("coordinate_transforms") or []
    errors = []
    for row in rows:
        edge = str(row.get("edge_id") or "?")
        sx = float(row.get("scale_x") or 0); sy = float(row.get("scale_y") or 0)
        anisotropy = abs(sx / sy - 1.0) if abs(sy) > 1e-12 else math.inf
        if anisotropy > .005:
            errors.append(f"non_uniform_transform:{edge}:{anisotropy:.6f}")
        roundtrip = row.get("roundtrip_max_error")
        if roundtrip is None or float(roundtrip) > 1e-6:
            errors.append(f"coordinate_roundtrip_failed:{edge}")
    if not rows:
        errors.append("coordinate_transform_evidence_missing")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors,
            "transform_count": len(rows), "maximum_allowed_anisotropy": .005,
            "maximum_roundtrip_error": 1e-6}


def validate_after_last_mutation(src: Path, dst: Path, report: dict, answers: dict, materialization: dict) -> dict:
    """Reopen and revalidate the exact downloadable file after graph drawing."""
    composition = report.get("composition") or {}
    pending_equipment_boards = _pending_equipment_boards(report, answers)
    checks = {
        "coordinate_integrity": validate_coordinate_evidence(materialization),
        "architecture_preservation": evaluate_architecture_preservation(src, dst, report, answers=answers),
        "titleblocks": validate_titleblocks(dst, composition),
        "safe_zones": validate_safe_zones(dst, composition),
        "architectural_presentation": validate_architectural_presentation(dst, composition),
        "equipment_linkage": validate_equipment_linkage(dst, composition, pending_equipment_boards),
        "detail_library": validate_detail_library(dst, composition),
        "content_completeness": validate_content_completeness(dst, composition),
        "split_visual": validate_split_ac_visual_legibility(
            dst, composition, dst.with_name(dst.stem + "-final-split-previews"),
            allowed_pending=pending_equipment_boards,
        ),
        "all_sheet_visual": validate_all_sheet_visual_qa(dst, composition, dst.with_name(dst.stem + "-final-sheet-previews")),
        "exact_montage": create_montage_and_validate(dst, dst.with_name(dst.stem + "-final-montage.png")),
    }
    failed = [name for name, result in checks.items() if str((result or {}).get("status") or "").upper() != "PASS"]
    return {"status": "PASS" if not failed else "FAIL", "failed_checks": failed,
            "checks": checks, "exact_downloadable_file_reopened": True,
            "release_allowed": not failed, "policy": "FAIL_CLOSED_AFTER_LAST_DXF_MUTATION"}
