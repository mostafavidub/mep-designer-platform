from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import ezdxf

from .authority_qa import (
    normalized_semantic_duplicate_qa,
    reopened_file_authority_qa,
    release_contract_status,
)
from .documentation import SYMBOL_LIBRARY
from .strict_pipeline import run_strict_electrical_pipeline

NEW_GATES = (
    "PLAN_ISOLATION_AUTHORITY",
    "EQUIPMENT_REPRESENTATION_AUTHORITY",
    "DETAIL_REFERENCE_PARITY_AUTHORITY",
    "SEMANTIC_DUPLICATE_AUTHORITY",
    "FINAL_REOPEN_AUTHORITY",
    "ELECTRICAL_RELEASE_CONTRACT",
)

PLAN_FAMILIES = {"LIGHTING", "POWER", "FIRE_ALARM", "LOW_CURRENT", "GROUNDING"}


def _gate(status: str, errors=None, warnings=None, **metrics):
    return {"status": status, "errors": errors or [], "warnings": warnings or [], "metrics": metrics}


def _family_accepts(sheet_family: str, system: str, equipment_type: str) -> bool:
    if sheet_family == "LIGHTING":
        return system in {"LIGHTING", "EMERGENCY_LIGHTING"} or equipment_type == "LIGHT_SWITCH"
    if sheet_family == "POWER":
        return system in {"GENERAL_RECEPTACLES", "DEDICATED_POWER", "KITCHEN_POWER", "HVAC_POWER", "ELEVATOR_POWER", "PUMP_POWER"}
    if sheet_family == "FIRE_ALARM":
        return system == "FIRE_ALARM"
    if sheet_family == "LOW_CURRENT":
        return system in {"TELECOM", "DATA", "TV", "INTERCOM", "CCTV", "ACCESS_CONTROL"}
    if sheet_family == "GROUNDING":
        return system in {"GROUNDING", "BONDING", "LIGHTNING_PROTECTION"}
    return False


def _plan_isolation(data: Dict[str, Any]) -> Dict[str, Any]:
    architecture = data.get("architecture") or {}
    manifest = data.get("manifest") or []
    routing = data.get("routing") or {}
    eligible = {f.get("id") for f in architecture.get("frames") or [] if f.get("eligible_for_electrical")}
    errors = []
    plan_sheets = 0
    for sheet in manifest:
        if sheet.get("family") not in PLAN_FAMILIES:
            continue
        plan_sheets += 1
        frames = list(sheet.get("source_frame_ids") or [])
        if len(frames) != 1:
            errors.append(f"plan_sheet_must_own_one_frame:{sheet.get('sheet_id')}:{frames}")
        for frame_id in frames:
            if frame_id not in eligible:
                errors.append(f"noneligible_frame_on_electrical_sheet:{sheet.get('sheet_id')}:{frame_id}")
    route_count = 0
    for route in routing.get("routes") or []:
        route_count += 1
        frame_id = route.get("frame_id")
        if not frame_id:
            errors.append(f"route_without_frame:{route.get('circuit_id')}")
        elif frame_id not in eligible:
            errors.append(f"route_on_noneligible_frame:{route.get('circuit_id')}:{frame_id}")
        if any(part.get("frame_id") not in {None, frame_id} for part in route.get("parts") or []):
            errors.append(f"cross_frame_route_parts:{route.get('circuit_id')}")
    return _gate("PASS" if not errors else "FAIL", errors, eligible_frames=len(eligible), plan_sheets=plan_sheets, routes=route_count)


def _equipment_representation(path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    requirements = {r.get("id"): r for r in data.get("equipment") or []}
    placements = data.get("placements") or []
    manifest = data.get("manifest") or []
    doc = ezdxf.readfile(str(path))
    errors = []
    checked = 0
    for placement in placements:
        if placement.get("status") != "FINAL" or not placement.get("point"):
            continue
        req = requirements.get(placement.get("requirement_id"))
        if not req:
            errors.append(f"placement_requirement_missing:{placement.get('equipment_id')}")
            continue
        spec = SYMBOL_LIBRARY.get(req.get("equipment_type"))
        if not spec:
            errors.append(f"symbol_library_missing:{req.get('equipment_type')}")
            continue
        owner = next((s for s in manifest if placement.get("frame_id") in (s.get("source_frame_ids") or []) and _family_accepts(s.get("family"), req.get("system"), req.get("equipment_type"))), None)
        if not owner or owner.get("sheet_id") not in doc.layouts:
            errors.append(f"equipment_owner_sheet_missing:{placement.get('equipment_id')}")
            continue
        layout = doc.layouts.get(owner.get("sheet_id"))
        block_name = "ET_" + spec["symbol_id"].replace("-", "_")
        block_present = any(e.dxftype() == "INSERT" and str(getattr(e.dxf, "name", "")) == block_name for e in layout)
        tag_present = any(e.dxftype() == "TEXT" and str(getattr(e.dxf, "text", "")) == placement.get("equipment_id") for e in layout)
        if not block_present:
            errors.append(f"equipment_block_missing:{placement.get('equipment_id')}:{block_name}")
        if not tag_present:
            errors.append(f"equipment_tag_missing:{placement.get('equipment_id')}")
        if req.get("placement_contract") and not placement.get("host_type"):
            errors.append(f"equipment_host_missing:{placement.get('equipment_id')}")
        checked += 1
    return _gate("PASS" if not errors else "FAIL", errors, final_placements_checked=checked)


def _detail_reference_parity(path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    details = data.get("details") or []
    links = data.get("detail_links") or []
    manifest = data.get("manifest") or []
    detail_ids = [d.get("detail_id") for d in details if d.get("detail_id")]
    link_ids = [x.get("detail_id") for x in links if x.get("detail_id")]
    errors = []
    if len(detail_ids) != len(set(detail_ids)):
        errors.append("duplicate_detail_ids")
    if set(detail_ids) != set(link_ids):
        errors.append("detail_reference_parity_mismatch")
    valid_sheets = {s.get("sheet_id") for s in manifest}
    for link in links:
        if link.get("sheet_id") not in valid_sheets:
            errors.append(f"detail_link_owner_missing:{link.get('sheet_id')}")
    # Mechanical v15.2 parity: metadata links are insufficient; they must be drawn.
    if detail_ids:
        doc = ezdxf.readfile(str(path))
        rendered = set()
        for sheet_id in valid_sheets:
            if sheet_id not in doc.layouts:
                continue
            for e in doc.layouts.get(sheet_id):
                if e.dxftype() != "TEXT":
                    continue
                text = str(getattr(e.dxf, "text", "") or "")
                if text.startswith("SEE DETAIL "):
                    for detail_id in detail_ids:
                        if detail_id in text:
                            rendered.add(detail_id)
        missing_rendered = sorted(set(detail_ids) - rendered)
        if missing_rendered:
            errors.append("detail_references_not_rendered:" + ",".join(missing_rendered))
    return _gate("PASS" if not errors else "FAIL", errors, details=len(detail_ids), references=len(link_ids))


def run_strict_electrical_pipeline_v15(source: str | Path, output: str | Path, config: Optional[Dict[str, Any]] = None):
    """Electrical authority-parity orchestrator incorporating Mechanical v15.2 lessons."""
    report = run_strict_electrical_pipeline(source, output, config)
    report["version"] = "electrical-project-driven-v15.2-authority-parity"
    output = Path(output)
    data = report.get("data") or {}
    gates = report.setdefault("gates", {})

    plan = _plan_isolation(data)
    gates["PLAN_ISOLATION_AUTHORITY"] = plan

    if output.exists():
        equipment = _equipment_representation(output, data)
        detail = _detail_reference_parity(output, data)
        duplicate = normalized_semantic_duplicate_qa(output, [type("Sheet", (), row) for row in data.get("manifest") or []])
        reopen = reopened_file_authority_qa(output, [type("Sheet", (), row) for row in data.get("manifest") or []], tuple((config or {}).get("paper_mm") or (420.0, 297.0)))
        gates["EQUIPMENT_REPRESENTATION_AUTHORITY"] = equipment
        gates["DETAIL_REFERENCE_PARITY_AUTHORITY"] = detail
        gates["SEMANTIC_DUPLICATE_AUTHORITY"] = _gate(duplicate["status"], duplicate.get("errors"), sheets=len(duplicate.get("sheets") or {}))
        gates["FINAL_REOPEN_AUTHORITY"] = _gate(reopen["status"], reopen.get("errors"), file_size_bytes=reopen.get("file_size_bytes"), layouts=reopen.get("layout_count"))
    else:
        for name in ("EQUIPMENT_REPRESENTATION_AUTHORITY", "DETAIL_REFERENCE_PARITY_AUTHORITY", "SEMANTIC_DUPLICATE_AUTHORITY", "FINAL_REOPEN_AUTHORITY"):
            gates[name] = _gate("FAIL", ["output_file_missing"])

    contract = release_contract_status()
    gates["ELECTRICAL_RELEASE_CONTRACT"] = _gate(contract["status"], [] if contract["status"] == "PASS" else ["release_contract_incomplete"], passed=contract["passed_count"], required=contract["required_count"])

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
        "authority_parity_version": "15.2",
    }
    return report
