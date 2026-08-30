"""Production release contract for the project-driven electrical engine.

A synthetic or recorded-data run may validate engineering logic, but it can
never satisfy Raw Real Project Acceptance. Production release requires the
same raw DXF/ZIP to pass the strict pipeline, reference similarity, visual QA,
and final same-file reopen validation.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

REQUIRED_FINAL_GATES = (
    "REFERENCE_SIMILARITY",
    "VISUAL_QA",
    "FINAL_FILE_REOPEN",
)


def evaluate_production_release(
    report: Dict[str, Any],
    *,
    source_kind: str,
    real_project_id: Optional[str] = None,
    raw_source_sha256: Optional[str] = None,
    visual_inspection_confirmed: bool = False,
    reference_audit_confirmed: bool = False,
) -> Dict[str, Any]:
    """Return a fail-closed release decision.

    ``source_kind`` must be RAW_DXF or RAW_ZIP. Recorded QA JSON, project-model
    snapshots, synthetic fixtures, previews, or previously generated output
    files are intentionally insufficient for production release.
    """
    gates = report.get("gates") or {}
    pipeline_pass = (report.get("acceptance") or {}).get("status") == "PASS"
    final_gate_status = {name: (gates.get(name) or {}).get("status") for name in REQUIRED_FINAL_GATES}
    raw_real_project = (
        source_kind in {"RAW_DXF", "RAW_ZIP"}
        and bool(real_project_id)
        and bool(raw_source_sha256)
    )
    final_gates_pass = all(value == "PASS" for value in final_gate_status.values())

    blockers = []
    if not pipeline_pass:
        blockers.append("STRICT_PIPELINE_NOT_PASS")
    if not raw_real_project:
        blockers.append("RAW_REAL_PROJECT_SOURCE_NOT_VERIFIED")
    if not reference_audit_confirmed:
        blockers.append("REFERENCE_AUDIT_NOT_CONFIRMED")
    if not visual_inspection_confirmed:
        blockers.append("VISUAL_INSPECTION_NOT_CONFIRMED")
    for name, status in final_gate_status.items():
        if status != "PASS":
            blockers.append(f"{name}:{status or 'MISSING'}")

    allowed = not blockers and final_gates_pass
    return {
        "status": "PASS" if allowed else "BLOCKED",
        "production_release_allowed": allowed,
        "real_project_acceptance": bool(raw_real_project and pipeline_pass and final_gates_pass),
        "source_kind": source_kind,
        "real_project_id": real_project_id,
        "raw_source_sha256": raw_source_sha256,
        "reference_audit_confirmed": bool(reference_audit_confirmed),
        "visual_inspection_confirmed": bool(visual_inspection_confirmed),
        "final_gates": final_gate_status,
        "blockers": blockers,
        "recorded_or_synthetic_data_can_release": False,
    }
