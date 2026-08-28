from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import ezdxf

from .authority_qa import normalized_semantic_duplicate_qa, reopened_file_authority_qa, release_contract_status
from .documentation import SYMBOL_LIBRARY
from .strict_pipeline import run_strict_electrical_pipeline

NEW_GATES = (
    "PLAN_ISOLATION_AUTHORITY", "EQUIPMENT_REPRESENTATION_AUTHORITY",
    "DETAIL_REFERENCE_PARITY_AUTHORITY", "SEMANTIC_DUPLICATE_AUTHORITY",
    "FINAL_REOPEN_AUTHORITY", "SAFE_DRAWING_AREA_AUTHORITY",
    "ELECTRICAL_RELEASE_CONTRACT",
)
PLAN_FAMILIES = {"LIGHTING", "POWER", "FIRE_ALARM", "LOW_CURRENT", "GROUNDING"}


def _gate(status: str, errors=None, warnings=None, **metrics):
    return {"status": status, "errors": errors or [], "warnings": warnings or [], "metrics": metrics}


def _family_accepts(sheet_family: str, system: str, equipment_type: str) -> bool:
    if sheet_family == "LIGHTING": return system in {"LIGHTING", "EMERGENCY_LIGHTING"} or equipment_type == "LIGHT_SWITCH"
    if sheet_family == "POWER": return system in {"GENERAL_RECEPTACLES", "DEDICATED_POWER", "KITCHEN_POWER", "HVAC_POWER", "ELEVATOR_POWER", "PUMP_POWER"}
    if sheet_family == "FIRE_ALARM": return system == "FIRE_ALARM"
    if sheet_family == "LOW_CURRENT": return system in {"TELECOM", "DATA", "TV", "INTERCOM", "CCTV", "ACCESS_CONTROL"}
    if sheet_family == "GROUNDING": return system in {"GROUNDING", "BONDING", "LIGHTNING_PROTECTION"}
    return False


def _fit(bounds, paper, margins=(12, 18, 12, 12)):
    pw, ph = paper; left, bottom, right, top = margins; x1, y1, x2, y2 = bounds
    aw = max(pw-left-right, 1e-6); ah = max(ph-bottom-top, 1e-6)
    w = max(x2-x1, 1e-9); h = max(y2-y1, 1e-9); scale = min(aw/w, ah/h)
    ox = left + (aw-w*scale)/2 - x1*scale; oy = bottom + (ah-h*scale)/2 - y1*scale
    return lambda p: (float(p[0])*scale+ox, float(p[1])*scale+oy)


def _plan_isolation(data: Dict[str, Any]) -> Dict[str, Any]:
    architecture = data.get("architecture") or {}; manifest = data.get("manifest") or []; routing = data.get("routing") or {}
    eligible = {f.get("id") for f in architecture.get("frames") or [] if f.get("eligible_for_electrical")}; errors = []; plan_sheets = 0
    for sheet in manifest:
        if sheet.get("family") not in PLAN_FAMILIES: continue
        plan_sheets += 1; frames = list(sheet.get("source_frame_ids") or [])
        if len(frames) != 1: errors.append(f"plan_sheet_must_own_one_frame:{sheet.get('sheet_id')}:{frames}")
        for frame_id in frames:
            if frame_id not in eligible: errors.append(f"noneligible_frame_on_electrical_sheet:{sheet.get('sheet_id')}:{frame_id}")
    route_count = 0
    for route in routing.get("routes") or []:
        route_count += 1; frame_id = route.get("frame_id")
        if not frame_id: errors.append(f"route_without_frame:{route.get('circuit_id')}")
        elif frame_id not in eligible: errors.append(f"route_on_noneligible_frame:{route.get('circuit_id')}:{frame_id}")
        if any(part.get("frame_id") not in {None, frame_id} for part in route.get("parts") or []): errors.append(f"cross_frame_route_parts:{route.get('circuit_id')}")
    return _gate("PASS" if not errors else "FAIL", errors, eligible_frames=len(eligible), plan_sheets=plan_sheets, routes=route_count)


def _materialize_authority_graphics(path: Path, data: Dict[str, Any], paper) -> Dict[str, Any]:
    """Write metadata-backed engineering graphics into the same final DXF before reopen QA."""
    doc = ezdxf.readfile(str(path)); manifest = data.get("manifest") or []; architecture = data.get("architecture") or {}
    frames = {f.get("id"): f for f in architecture.get("frames") or []}; drawn_links = 0; drawn_panels = 0
    detail_sheet = next((s.get("sheet_id") for s in manifest if s.get("family") == "DETAILS"), None)
    grouped = {}
    for link in data.get("detail_links") or []: grouped.setdefault(link.get("sheet_id"), []).append(link.get("detail_id"))
    if detail_sheet:
        for sheet_id, detail_ids in grouped.items():
            if sheet_id not in doc.layouts: continue
            layout = doc.layouts.get(sheet_id); existing = {str(getattr(e.dxf, "text", "") or "") for e in layout if e.dxftype() == "TEXT"}; y = paper[1]-22
            for detail_id in sorted(set(x for x in detail_ids if x)):
                text = f"SEE DETAIL {detail_sheet} / {detail_id}"
                if text not in existing:
                    layout.add_text(text, dxfattribs={"layer":"ENGITOOLS-E-ANNOTATION", "height":1.0}).set_placement((paper[0]-92, y)); drawn_links += 1
                y -= 3.2
    topology = data.get("topology") or {}
    for panel in topology.get("panels") or []:
        location = panel.get("location") or {}
        if location.get("status") != "FINAL" or not isinstance(location.get("value"), dict): continue
        loc = location.get("value") or {}; point = loc.get("point"); frame_id = loc.get("frame_id")
        if not point: continue
        if not frame_id:
            frame_id = next((f.get("id") for f in frames.values() if f.get("level_id") == panel.get("level_id") and f.get("eligible_for_electrical")), None)
        frame = frames.get(frame_id)
        if not frame: continue
        q = _fit(frame.get("bounds"), paper)(point)
        owner = next((s for s in manifest if s.get("family") == "POWER" and s.get("level_id") == panel.get("level_id") and frame_id in (s.get("source_frame_ids") or [])), None)
        if not owner or owner.get("sheet_id") not in doc.layouts: continue
        layout = doc.layouts.get(owner.get("sheet_id")); panel_id = panel.get("id")
        tag_present = any(e.dxftype() == "TEXT" and str(getattr(e.dxf, "text", "")) == panel_id for e in layout)
        if not tag_present:
            if "ET_EL_PNL_01" in doc.blocks: layout.add_blockref("ET_EL_PNL_01", q, dxfattribs={"layer":"ENGITOOLS-E-POWER"})
            else: layout.add_lwpolyline([(q[0]-2,q[1]-3),(q[0]+2,q[1]-3),(q[0]+2,q[1]+3),(q[0]-2,q[1]+3),(q[0]-2,q[1]-3)], dxfattribs={"layer":"ENGITOOLS-E-POWER"})
            layout.add_text(panel_id, dxfattribs={"layer":"ENGITOOLS-E-ANNOTATION", "height":1.3}).set_placement((q[0]+3,q[1]+2)); drawn_panels += 1
    doc.saveas(str(path)); return {"drawn_detail_links": drawn_links, "drawn_panels": drawn_panels}


def _equipment_representation(path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    requirements = {r.get("id"): r for r in data.get("equipment") or []}; placements = data.get("placements") or []; manifest = data.get("manifest") or []
    doc = ezdxf.readfile(str(path)); errors = []; checked = 0
    for placement in placements:
        if placement.get("status") != "FINAL" or not placement.get("point"): continue
        req = requirements.get(placement.get("requirement_id"))
        if not req: errors.append(f"placement_requirement_missing:{placement.get('equipment_id')}"); continue
        spec = SYMBOL_LIBRARY.get(req.get("equipment_type"))
        if not spec: errors.append(f"symbol_library_missing:{req.get('equipment_type')}"); continue
        owner = next((s for s in manifest if placement.get("frame_id") in (s.get("source_frame_ids") or []) and _family_accepts(s.get("family"), req.get("system"), req.get("equipment_type"))), None)
        if not owner or owner.get("sheet_id") not in doc.layouts: errors.append(f"equipment_owner_sheet_missing:{placement.get('equipment_id')}"); continue
        layout = doc.layouts.get(owner.get("sheet_id")); block_name = "ET_" + spec["symbol_id"].replace("-", "_")
        block_present = any(e.dxftype() == "INSERT" and str(getattr(e.dxf, "name", "")) == block_name for e in layout)
        tag_present = any(e.dxftype() == "TEXT" and str(getattr(e.dxf, "text", "")) == placement.get("equipment_id") for e in layout)
        if not block_present: errors.append(f"equipment_block_missing:{placement.get('equipment_id')}:{block_name}")
        if not tag_present: errors.append(f"equipment_tag_missing:{placement.get('equipment_id')}")
        if req.get("placement_contract") and not placement.get("host_type"): errors.append(f"equipment_host_missing:{placement.get('equipment_id')}")
        checked += 1
    return _gate("PASS" if not errors else "FAIL", errors, final_placements_checked=checked)


def _detail_reference_parity(path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    details = data.get("details") or []; links = data.get("detail_links") or []; manifest = data.get("manifest") or []
    detail_ids = [d.get("detail_id") for d in details if d.get("detail_id")]; link_ids = [x.get("detail_id") for x in links if x.get("detail_id")]; errors = []
    if len(detail_ids) != len(set(detail_ids)): errors.append("duplicate_detail_ids")
    if set(detail_ids) != set(link_ids): errors.append("detail_reference_parity_mismatch")
    valid_sheets = {s.get("sheet_id") for s in manifest}
    for link in links:
        if link.get("sheet_id") not in valid_sheets: errors.append(f"detail_link_owner_missing:{link.get('sheet_id')}")
    if detail_ids:
        doc = ezdxf.readfile(str(path)); rendered = set()
        for sheet_id in valid_sheets:
            if sheet_id not in doc.layouts: continue
            for e in doc.layouts.get(sheet_id):
                if e.dxftype() != "TEXT": continue
                text = str(getattr(e.dxf, "text", "") or "")
                if text.startswith("SEE DETAIL "):
                    for detail_id in detail_ids:
                        if detail_id in text: rendered.add(detail_id)
        missing = sorted(set(detail_ids)-rendered)
        if missing: errors.append("detail_references_not_rendered:" + ",".join(missing))
    return _gate("PASS" if not errors else "FAIL", errors, details=len(detail_ids), references=len(link_ids))


def _safe_area_qa(path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    doc = ezdxf.readfile(str(path)); errors = []; checked = 0
    for sheet in data.get("manifest") or []:
        if sheet.get("family") not in PLAN_FAMILIES or sheet.get("sheet_id") not in doc.layouts: continue
        checked += 1
        for e in doc.layouts.get(sheet.get("sheet_id")):
            if e.dxftype() == "VIEWPORT": continue
            layer = str(getattr(e.dxf, "layer", "") or "")
            if layer in {"ENGITOOLS-E-DOC", "ENGITOOLS-E-ARCH-UNDERLAY", "VIEWPORTS"}: continue
            try:
                from ezdxf import bbox
                ext = bbox.extents([e], fast=True)
                if ext.has_data and float(ext.extmin.y) < 14.0: errors.append(f"electrical_content_over_title_band:{sheet.get('sheet_id')}:{layer}")
            except Exception: pass
    return _gate("PASS" if not errors else "FAIL", errors, plan_sheets_checked=checked)


def run_strict_electrical_pipeline_v15(source: str | Path, output: str | Path, config: Optional[Dict[str, Any]] = None):
    report = run_strict_electrical_pipeline(source, output, config); report["version"] = "electrical-project-driven-v15.2-authority-parity"
    output = Path(output); data = report.get("data") or {}; gates = report.setdefault("gates", {}); paper = tuple((config or {}).get("paper_mm") or (420.0, 297.0))
    gates["PLAN_ISOLATION_AUTHORITY"] = _plan_isolation(data)
    if output.exists():
        materialized = _materialize_authority_graphics(output, data, paper)
        equipment = _equipment_representation(output, data); detail = _detail_reference_parity(output, data)
        manifest_objs = [type("Sheet", (), row) for row in data.get("manifest") or []]
        duplicate = normalized_semantic_duplicate_qa(output, manifest_objs); reopen = reopened_file_authority_qa(output, manifest_objs, paper); safe = _safe_area_qa(output, data)
        gates["EQUIPMENT_REPRESENTATION_AUTHORITY"] = equipment; gates["DETAIL_REFERENCE_PARITY_AUTHORITY"] = detail
        gates["SEMANTIC_DUPLICATE_AUTHORITY"] = _gate(duplicate["status"], duplicate.get("errors"), sheets=len(duplicate.get("sheets") or {}))
        gates["FINAL_REOPEN_AUTHORITY"] = _gate(reopen["status"], reopen.get("errors"), file_size_bytes=reopen.get("file_size_bytes"), layouts=reopen.get("layout_count"))
        gates["SAFE_DRAWING_AREA_AUTHORITY"] = safe; report["authority_postcomposition"] = materialized
    else:
        for name in ("EQUIPMENT_REPRESENTATION_AUTHORITY", "DETAIL_REFERENCE_PARITY_AUTHORITY", "SEMANTIC_DUPLICATE_AUTHORITY", "FINAL_REOPEN_AUTHORITY", "SAFE_DRAWING_AREA_AUTHORITY"):
            gates[name] = _gate("FAIL", ["output_file_missing"])
    contract = release_contract_status(); gates["ELECTRICAL_RELEASE_CONTRACT"] = _gate(contract["status"], [] if contract["status"] == "PASS" else ["release_contract_incomplete"], passed=contract["passed_count"], required=contract["required_count"])
    hard = [name for name,value in gates.items() if value.get("status") == "FAIL"]; incomplete = [name for name,value in gates.items() if value.get("status") not in {"PASS","NOT_REQUIRED"}]; accepted = not hard and not incomplete
    previous = report.get("acceptance") or {}; report["acceptance"] = {**previous, "status":"PASS" if accepted else "NOT_ACCEPTED", "hard_fail_gates":hard, "incomplete_gates":incomplete, "real_project_acceptance":False, "production_release_allowed":False, "authority_parity_version":"15.2"}
    return report
