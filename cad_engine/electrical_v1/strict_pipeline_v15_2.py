from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .authority_qa import reopened_file_authority_qa
from .orientation import detect_project_north, draw_north_on_final_file
from .qa import visual_qa
from .release_contract_v15_2 import release_contract_status
from .strict_pipeline_v15 import _gate, _safe_area_qa, run_strict_electrical_pipeline_v15


def run_strict_electrical_pipeline_v15_2(source: str | Path, output: str | Path, config: Optional[Dict[str, Any]] = None):
    """Final Electrical v15.2 authority-parity pipeline.

    This stage incorporates the last reusable Mechanical v15.2 presentation
    contract: inherit north direction from architectural evidence when present,
    never fabricate it when absent, then re-run same-file visual/reopen/safe-area
    gates after the north graphic has been materialized.
    """
    report = run_strict_electrical_pipeline_v15(source, output, config)
    report["version"] = "electrical-project-driven-v15.2.0-authority-parity"
    output = Path(output); data = report.get("data") or {}; gates = report.setdefault("gates", {})
    paper = tuple((config or {}).get("paper_mm") or (420.0, 297.0))
    frames = (data.get("architecture") or {}).get("frames") or []
    manifest = data.get("manifest") or []

    orientation = detect_project_north(source, frames)
    draw = {"status":"NOT_REQUIRED", "arrows_drawn":0}
    if output.exists():
        draw = draw_north_on_final_file(output, manifest, frames, orientation.get("records") or {}, paper)
    warnings = list(orientation.get("warnings") or [])
    gates["NORTH_ORIENTATION"] = _gate(
        "PASS" if orientation.get("status") == "PASS" and draw.get("status") in {"PASS","NOT_REQUIRED"} else "FAIL",
        list(orientation.get("errors") or []) + list(draw.get("errors") or []),
        warnings,
        north_from_architecture=(orientation.get("metrics") or {}).get("north_from_architecture", 0),
        north_input_required=(orientation.get("metrics") or {}).get("north_input_required", 0),
        arrows_drawn=draw.get("arrows_drawn", 0),
    )
    report["north_orientation"] = {**orientation, "drawing": draw}

    if output.exists():
        manifest_objs = [type("Sheet", (), row) for row in manifest]
        reopen = reopened_file_authority_qa(output, manifest_objs, paper)
        gates["FINAL_REOPEN_AUTHORITY"] = _gate(
            reopen["status"], reopen.get("errors"),
            file_size_bytes=reopen.get("file_size_bytes"), layouts=reopen.get("layout_count")
        )
        safe = _safe_area_qa(output, data)
        gates["SAFE_DRAWING_AREA_AUTHORITY"] = safe
        visual = visual_qa(output, manifest_objs, paper)
        gates["VISUAL_QA"] = _gate(
            visual["status"], visual.get("errors"), visual.get("warnings"),
            sheets=len(visual.get("sheets") or {})
        )

    contract = release_contract_status()
    gates["ELECTRICAL_RELEASE_CONTRACT"] = _gate(
        contract["status"], [] if contract["status"] == "PASS" else ["release_contract_incomplete"],
        passed=contract["passed_count"], required=contract["required_count"]
    )
    report["release_contract"] = contract

    hard = [name for name, value in gates.items() if value.get("status") == "FAIL"]
    incomplete = [name for name, value in gates.items() if value.get("status") not in {"PASS", "NOT_REQUIRED"}]
    accepted = not hard and not incomplete
    previous = report.get("acceptance") or {}
    report["acceptance"] = {
        **previous,
        "status": "PASS" if accepted else "NOT_ACCEPTED",
        "hard_fail_gates": hard,
        "incomplete_gates": incomplete,
        "real_project_acceptance": False,
        "production_release_allowed": False,
        "authority_parity_version": "15.2.0",
    }
    return report
