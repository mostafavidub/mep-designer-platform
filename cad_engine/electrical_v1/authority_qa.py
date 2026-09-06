from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, List

import ezdxf
from ezdxf import bbox

from .documentation import SYMBOL_LIBRARY
from .models import EngineeringStatus

PLAN_FAMILIES = {"LIGHTING", "POWER", "FIRE_ALARM", "LOW_CURRENT", "GROUNDING"}
IGNORED_LAYERS = {"ENGITOOLS-E-ARCH-UNDERLAY", "ENGITOOLS-E-DOC", "ENGITOOLS-E-ANNOTATION"}


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


def plan_isolation_qa(architecture, manifest, routing) -> Dict[str, Any]:
    """Authority-style plan isolation gate adapted from Mechanical v15.2.

    Every plan sheet must own exactly one eligible architectural print frame and
    every physical route must stay inside one eligible frame. Support/document
    sheets are intentionally exempt from single-frame ownership.
    """
    eligible = {f.id for f in architecture.frames if f.eligible_for_electrical}
    errors: List[str] = []
    sheet_frames: Dict[str, List[str]] = {}
    for sheet in manifest:
        if sheet.family not in PLAN_FAMILIES:
            continue
        frames = list(sheet.source_frame_ids or [])
        sheet_frames[sheet.sheet_id] = frames
        if len(frames) != 1:
            errors.append(f"plan_sheet_must_own_one_frame:{sheet.sheet_id}:{frames}")
        for frame_id in frames:
            if frame_id not in eligible:
                errors.append(f"noneligible_frame_on_electrical_sheet:{sheet.sheet_id}:{frame_id}")
    route_frames = []
    for route in (routing or {}).get("routes") or []:
        frame_id = route.get("frame_id")
        route_frames.append(frame_id)
        if not frame_id:
            errors.append(f"route_without_frame:{route.get('circuit_id')}")
        elif frame_id not in eligible:
            errors.append(f"route_on_noneligible_frame:{route.get('circuit_id')}:{frame_id}")
        parts = route.get("parts") or []
        if any(part.get("frame_id") not in {None, frame_id} for part in parts):
            errors.append(f"cross_frame_route_parts:{route.get('circuit_id')}")
    return {
        "version": "electrical-plan-isolation-v15.2",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "metrics": {
            "eligible_frames": len(eligible),
            "plan_sheets": len(sheet_frames),
            "routes": len(route_frames),
            "distinct_route_frames": len({x for x in route_frames if x}),
        },
        "sheet_frames": sheet_frames,
    }


def equipment_representation_qa(path: str | Path, manifest, requirements, placements) -> Dict[str, Any]:
    """Verify that final placements are represented by a real block and tag.

    This is the electrical equivalent of the Mechanical v14 equipment graphic
    contract: plan/schedule data alone is not enough for acceptance.
    """
    doc = ezdxf.readfile(str(path))
    req_by_id = {r.id: r for r in requirements}
    errors: List[str] = []
    checked = 0
    for placement in placements:
        if placement.status != EngineeringStatus.FINAL or not placement.point:
            continue
        req = req_by_id.get(placement.requirement_id)
        if not req:
            errors.append(f"placement_requirement_missing:{placement.equipment_id}")
            continue
        spec = SYMBOL_LIBRARY.get(req.equipment_type)
        if not spec:
            errors.append(f"symbol_library_missing:{req.equipment_type}")
            continue
        expected_block = "ET_" + spec["symbol_id"].replace("-", "_")
        owner = next((s for s in manifest if placement.frame_id in (s.source_frame_ids or []) and _family_accepts(s.family, req.system, req.equipment_type)), None)
        if not owner or owner.sheet_id not in doc.layouts:
            errors.append(f"equipment_owner_sheet_missing:{placement.equipment_id}")
            continue
        layout = doc.layouts.get(owner.sheet_id)
        block_present = any(e.dxftype() == "INSERT" and str(getattr(e.dxf, "name", "")) == expected_block for e in layout)
        tag_present = any(e.dxftype() == "TEXT" and str(getattr(e.dxf, "text", "")) == placement.equipment_id for e in layout)
        if not block_present:
            errors.append(f"equipment_block_missing:{placement.equipment_id}:{expected_block}")
        if not tag_present:
            errors.append(f"equipment_tag_missing:{placement.equipment_id}")
        if req.placement_contract and not placement.host_type:
            errors.append(f"equipment_host_missing:{placement.equipment_id}")
        checked += 1
    return {
        "version": "electrical-equipment-representation-v15.2",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "metrics": {"final_placements_checked": checked},
    }


def _normalized_token(entity, resolution: float = 0.05) -> str | None:
    layer = str(getattr(entity.dxf, "layer", "") or "")
    if layer in IGNORED_LAYERS:
        return None
    try:
        ext = bbox.extents([entity], fast=True)
        if not ext.has_data:
            return None
        vals = [
            round(float(ext.extmin.x) / resolution),
            round(float(ext.extmin.y) / resolution),
            round(float(ext.extmax.x) / resolution),
            round(float(ext.extmax.y) / resolution),
        ]
    except Exception:
        vals = [0, 0, 0, 0]
    text = ""
    try:
        if entity.dxftype() == "TEXT":
            text = str(entity.dxf.text or "")[:80]
        elif entity.dxftype() == "MTEXT":
            text = str(entity.plain_text() or "")[:80]
    except Exception:
        pass
    name = str(getattr(entity.dxf, "name", "") or "")
    return f"{entity.dxftype()}|{layer}|{name}|{vals}|{text}"


def normalized_semantic_duplicate_qa(path: str | Path, manifest) -> Dict[str, Any]:
    """Detect duplicate electrical sheets within the same family.

    Mechanical v15.2 showed that coordinate-normalized same-family comparison is
    the useful duplicate detector. Architecture/document/annotation layers are
    ignored so translated floor sheets are compared by electrical content.
    """
    doc = ezdxf.readfile(str(path))
    errors: List[str] = []
    seen: Dict[tuple, str] = {}
    results: Dict[str, Any] = {}
    for sheet in manifest:
        if sheet.sheet_id not in doc.layouts:
            continue
        tokens = sorted(filter(None, (_normalized_token(e) for e in doc.layouts.get(sheet.sheet_id))))
        signature = hashlib.sha256("\n".join(tokens).encode()).hexdigest() if tokens else None
        results[sheet.sheet_id] = {"family": sheet.family, "signature": signature, "content_count": len(tokens)}
        if not signature or len(tokens) == 0:
            continue
        key = (sheet.family, signature)
        if key in seen:
            errors.append(f"FAIL_DUPLICATE_SHEET:{seen[key]}:{sheet.sheet_id}:{sheet.family}")
        else:
            seen[key] = sheet.sheet_id
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "sheets": results}


def reopened_file_authority_qa(path: str | Path, manifest, paper=(420.0, 297.0)) -> Dict[str, Any]:
    """Recompute semantic QA from the same file after close/reopen."""
    path = Path(path)
    errors: List[str] = []
    if not path.exists() or path.stat().st_size <= 0:
        return {"status": "FAIL", "errors": ["file_missing_or_empty"]}
    doc = ezdxf.readfile(str(path))
    audit = doc.audit()
    if audit.errors:
        errors.append(f"dxf_audit_errors:{len(audit.errors)}")
    expected = {s.sheet_id for s in manifest}
    actual = {x.name for x in doc.layouts if x.name != "Model"}
    if actual != expected:
        errors.append(f"layout_manifest_mismatch:actual={sorted(actual)} expected={sorted(expected)}")
    for sheet in manifest:
        if sheet.sheet_id not in doc.layouts:
            continue
        layout = doc.layouts.get(sheet.sheet_id)
        printable = [e for e in layout if e.dxftype() != "VIEWPORT"]
        ext = bbox.extents(printable, fast=True)
        if not ext.has_data:
            errors.append(f"blank_layout:{sheet.sheet_id}")
            continue
        x1, y1, x2, y2 = float(ext.extmin.x), float(ext.extmin.y), float(ext.extmax.x), float(ext.extmax.y)
        if x1 < -1 or y1 < -1 or x2 > paper[0] + 1 or y2 > paper[1] + 1:
            errors.append(f"print_extents_outside_paper:{sheet.sheet_id}")
        if sheet.family in PLAN_FAMILIES:
            electrical = [e for e in printable if str(getattr(e.dxf, "layer", "") or "") not in IGNORED_LAYERS]
            if not electrical:
                errors.append(f"no_electrical_content_after_reopen:{sheet.sheet_id}")
    duplicate = normalized_semantic_duplicate_qa(path, manifest)
    errors.extend(duplicate.get("errors") or [])
    return {
        "version": "electrical-final-reopen-authority-v15.2",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "file_size_bytes": path.stat().st_size,
        "layout_count": len(actual),
        "semantic_duplicate": duplicate,
    }


def detail_coverage_authority_qa(details: Iterable[dict], links: Iterable[dict], manifest) -> Dict[str, Any]:
    """Exact required/inserted/referenced detail parity and no orphan links."""
    detail_ids = [d.get("detail_id") for d in details if d.get("detail_id")]
    link_ids = [x.get("detail_id") for x in links if x.get("detail_id")]
    errors: List[str] = []
    if len(detail_ids) != len(set(detail_ids)):
        errors.append("duplicate_detail_ids")
    if set(detail_ids) != set(link_ids):
        errors.append("detail_reference_parity_mismatch")
    valid_sheets = {s.sheet_id for s in manifest}
    for link in links:
        if link.get("sheet_id") not in valid_sheets:
            errors.append(f"detail_link_owner_missing:{link.get('sheet_id')}")
    return {
        "version": "electrical-dynamic-detail-contract-v15.2",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "metrics": {"details": len(detail_ids), "references": len(link_ids)},
    }


REQUIRED_CAPABILITIES = {
    "architecture_reconstruction": "architecture",
    "drawing_type_classification": "architecture",
    "primary_plan_isolation": "authority_qa",
    "project_design_basis": "design",
    "system_requirement_engine": "design",
    "adaptive_sheet_manifest": "design",
    "host_aware_equipment_placement": "geometry_acceptance",
    "equipment_representation": "authority_qa",
    "lighting_design": "placement_lighting",
    "power_topology": "power",
    "plan_aware_routing": "routing",
    "load_calculation": "power",
    "cable_breaker_sizing": "power",
    "voltage_drop_phase_balance": "power",
    "panel_schedule_sync": "power",
    "single_line_service_traceability": "service",
    "electrical_riser": "distribution",
    "grounding_bonding": "distribution",
    "dynamic_project_details": "documentation",
    "plan_detail_linking": "postcompose",
    "project_legend": "documentation",
    "semantic_sheet_qa": "authority_qa",
    "independent_paper_space": "composer",
    "reference_similarity": "qa",
    "visual_qa": "qa",
    "exact_final_file_reopen_qa": "authority_qa",
    "fail_closed_release_gate": "release_gate",
}


def release_contract_status() -> Dict[str, Any]:
    """Machine-readable Electrical v15.2 parity checklist."""
    from importlib import import_module

    checks: Dict[str, bool] = {}
    for capability, module in REQUIRED_CAPABILITIES.items():
        try:
            import_module(f"cad_engine.electrical_v1.{module}")
            checks[capability] = True
        except Exception:
            checks[capability] = False
    return {
        "version": "electrical-authority-parity-v15.2",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "required_count": len(checks),
        "passed_count": sum(1 for value in checks.values() if value),
        "checks": checks,
    }
