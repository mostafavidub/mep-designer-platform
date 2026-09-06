from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .authority_qa import reopened_file_authority_qa
from .construction_qa import construction_detail_qa, evidence_consistency_qa, plan_detail_link_qa
from .orientation import detect_project_north, draw_north_on_final_file
from .qa import visual_qa
from .release_contract import release_contract_status
from .authority_pipeline import _gate, _safe_area_qa, run_authority_electrical_pipeline


def run_acceptance_electrical_pipeline(source: str | Path, output: str | Path, config: Optional[Dict[str, Any]] = None):
    """Active Electrical authority-parity acceptance pipeline.

    North direction is inherited from architectural evidence when present and is
    never fabricated when absent. Same-file visual/reopen/safe-area gates run
    after the north graphic has been materialized. Construction-detail depth,
    plan-to-detail traceability and evidence-state consistency are also hard
    release requirements; a DXF that merely reopens cannot pass by itself.
    """
    report = run_authority_electrical_pipeline(source, output, config)
    report["acceptance_schema_revision"] = "electrical-acceptance/2"
    output = Path(output); data = report.get("data") or {}; gates = report.setdefault("gates", {})
    paper = tuple((config or {}).get("paper_mm") or (420.0, 297.0))
    frames = (data.get("architecture") or {}).get("frames") or []
    manifest = data.get("manifest") or []
    details = data.get("details") or []
    links = data.get("detail_links") or []

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

    evidence = evidence_consistency_qa(data)
    gates["EVIDENCE_CONSISTENCY_AUTHORITY"] = _gate(
        evidence["status"], evidence.get("errors"), error_count=(evidence.get("metrics") or {}).get("error_count", 0)
    )
    link_qa = plan_detail_link_qa(manifest, details, links)
    gates["PLAN_DETAIL_LINK_AUTHORITY"] = _gate(
        link_qa["status"], link_qa.get("errors"), link_qa.get("incomplete"), **(link_qa.get("metrics") or {})
    )

    if output.exists():
        manifest_objs = [type("Sheet", (), row) for row in manifest]
        reopen = reopened_file_authority_qa(output, manifest_objs, paper)
        gates["FINAL_REOPEN_AUTHORITY"] = _gate(
            reopen["status"], reopen.get("errors"),
            file_size_bytes=reopen.get("file_size_bytes"), layouts=reopen.get("layout_count")
        )
        gates["SAFE_DRAWING_AREA_AUTHORITY"] = _safe_area_qa(output, data)
        visual = visual_qa(output, manifest_objs, paper)
        gates["VISUAL_QA"] = _gate(
            visual["status"], visual.get("errors"), visual.get("warnings"),
            sheets=len(visual.get("sheets") or {})
        )
        detail_qa = construction_detail_qa(output, manifest, details, links)
        gates["CONSTRUCTION_DETAIL_AUTHORITY"] = _gate(
            detail_qa["status"], detail_qa.get("errors"), detail_qa.get("incomplete"), **(detail_qa.get("metrics") or {})
        )
        report["construction_detail_qa"] = detail_qa
    else:
        gates["CONSTRUCTION_DETAIL_AUTHORITY"] = _gate("FAIL", ["output_file_missing"])

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
        "acceptance_contract_revision": "electrical-acceptance/2",
    }
    return report
