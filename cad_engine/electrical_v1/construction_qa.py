from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

import ezdxf


PLAN_FAMILIES = {"LIGHTING", "POWER", "FIRE_ALARM", "LOW_CURRENT", "GROUNDING"}
GRAPHIC_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "HATCH", "SOLID", "DIMENSION", "INSERT"}


def _sheet_value(sheet: Any, key: str, default=None):
    if isinstance(sheet, dict):
        return sheet.get(key, default)
    return getattr(sheet, key, default)


def _detail_value(detail: Any, key: str, default=None):
    if isinstance(detail, dict):
        return detail.get(key, default)
    return getattr(detail, key, default)


def _status(errors: List[str], incomplete: List[str]) -> str:
    if errors:
        return "FAIL"
    if incomplete:
        return "INPUT_REQUIRED"
    return "PASS"


def plan_detail_link_qa(manifest: Iterable[Any], details: Iterable[dict], links: Iterable[dict]) -> Dict[str, Any]:
    """Require explicit plan-to-detail traceability for every applicable plan family.

    Detail IDs remain project-generated; this gate checks ownership/reference parity,
    not a fixed sheet number or reference-project layout.
    """
    detail_ids = {str(_detail_value(d, "detail_id")) for d in details if _detail_value(d, "detail_id")}
    valid_sheets = {str(_sheet_value(s, "sheet_id")) for s in manifest if _sheet_value(s, "sheet_id")}
    plan_sheets = {
        str(_sheet_value(s, "sheet_id")): str(_sheet_value(s, "family"))
        for s in manifest
        if str(_sheet_value(s, "family")) in PLAN_FAMILIES
    }
    by_sheet: Dict[str, set[str]] = defaultdict(set)
    errors: List[str] = []
    for link in links or []:
        sheet_id = str(link.get("sheet_id") or "")
        detail_id = str(link.get("detail_id") or "")
        if sheet_id not in valid_sheets:
            errors.append(f"detail_link_owner_missing:{sheet_id}")
        if detail_id not in detail_ids:
            errors.append(f"detail_link_target_missing:{detail_id}")
        if sheet_id and detail_id:
            by_sheet[sheet_id].add(detail_id)

    keyword_map = {
        "LIGHTING": ("LIGHT", "SWITCH"),
        "POWER": ("PANEL", "SWITCH", "OUTLET", "ISOLATOR", "JB", "TERMINATION", "CONDUIT", "PEN"),
        "FIRE_ALARM": ("FIRE", "DETECTOR"),
        "GROUNDING": ("EARTH", "GROUND", "BOND"),
        "LOW_CURRENT": ("LOW", "DATA", "TV", "TELE", "INTERCOM"),
    }
    applicable_detail_ids: Dict[str, set[str]] = {}
    for family, words in keyword_map.items():
        applicable_detail_ids[family] = {d for d in detail_ids if any(word in d.upper() for word in words)}

    incomplete: List[str] = []
    for sheet_id, family in plan_sheets.items():
        applicable = applicable_detail_ids.get(family) or set()
        if applicable and not (by_sheet.get(sheet_id, set()) & applicable):
            incomplete.append(f"plan_detail_reference_required:{sheet_id}:{family}")

    return {
        "status": _status(errors, incomplete),
        "errors": errors,
        "incomplete": incomplete,
        "metrics": {
            "details": len(detail_ids),
            "links": sum(len(v) for v in by_sheet.values()),
            "plan_sheets": len(plan_sheets),
            "plan_sheets_with_links": sum(1 for sid in plan_sheets if by_sheet.get(sid)),
        },
    }


def construction_detail_qa(path: str | Path, manifest: Iterable[Any], details: Iterable[dict], links: Iterable[dict]) -> Dict[str, Any]:
    """Reject placeholder/text-only detail output even when the DXF itself reopens.

    Thresholds are intentionally structural rather than project-value defaults:
    enough real geometry must exist per generated detail, IDs must be rendered,
    and detail parameters required by the parametric definition must be supplied
    before construction acceptance can pass.
    """
    details = list(details or [])
    detail_sheets = [s for s in manifest if str(_sheet_value(s, "family")) == "DETAILS"]
    if not details and not detail_sheets:
        return {"status": "NOT_REQUIRED", "errors": [], "incomplete": [], "metrics": {"details": 0}}

    errors: List[str] = []
    incomplete: List[str] = []
    if details and not detail_sheets:
        errors.append("details_exist_without_detail_sheet")
        return {"status": "FAIL", "errors": errors, "incomplete": incomplete, "metrics": {"details": len(details)}}

    path = Path(path)
    if not path.exists():
        return {"status": "FAIL", "errors": ["output_file_missing"], "incomplete": [], "metrics": {"details": len(details)}}
    doc = ezdxf.readfile(str(path))
    detail_ids = {str(_detail_value(d, "detail_id")) for d in details if _detail_value(d, "detail_id")}
    rendered_ids: set[str] = set()
    entity_types: Counter[str] = Counter()
    text_count = 0
    graphic_count = 0
    detail_layer_graphics = 0

    for sheet in detail_sheets:
        sheet_id = str(_sheet_value(sheet, "sheet_id"))
        if sheet_id not in doc.layouts:
            errors.append(f"detail_layout_missing:{sheet_id}")
            continue
        layout = doc.layouts.get(sheet_id)
        for entity in layout:
            if entity.dxftype() == "VIEWPORT":
                continue
            entity_types[entity.dxftype()] += 1
            layer = str(getattr(entity.dxf, "layer", "") or "")
            if entity.dxftype() in GRAPHIC_TYPES:
                graphic_count += 1
                if layer == "ENGITOOLS-E-DETAIL":
                    detail_layer_graphics += 1
            if entity.dxftype() in {"TEXT", "MTEXT"}:
                text_count += 1
                try:
                    value = str(entity.dxf.text if entity.dxftype() == "TEXT" else entity.plain_text())
                except Exception:
                    value = ""
                for detail_id in detail_ids:
                    if detail_id and detail_id in value:
                        rendered_ids.add(detail_id)

    missing_ids = sorted(detail_ids - rendered_ids)
    if missing_ids:
        errors.append("detail_ids_not_rendered:" + ",".join(missing_ids))

    # A title + one line is not a construction detail. Scale with generated detail count.
    minimum_graphics = max(18, len(details) * 4)
    minimum_detail_layer_graphics = max(12, len(details) * 3)
    if graphic_count < minimum_graphics:
        errors.append(f"construction_detail_graphics_too_sparse:{graphic_count}<{minimum_graphics}")
    if detail_layer_graphics < minimum_detail_layer_graphics:
        errors.append(f"construction_detail_layer_too_sparse:{detail_layer_graphics}<{minimum_detail_layer_graphics}")
    if text_count > graphic_count * 1.5 and graphic_count > 0:
        errors.append("construction_detail_too_text_heavy")

    for detail in details:
        detail_id = str(_detail_value(detail, "detail_id") or "UNKNOWN")
        missing = list(_detail_value(detail, "missing", []) or [])
        status = str(_detail_value(detail, "status", "") or "")
        geometry = list(_detail_value(detail, "geometry", []) or [])
        parameters = dict(_detail_value(detail, "parameters", {}) or {})
        if missing:
            incomplete.append(f"detail_parameters_input_required:{detail_id}:{','.join(map(str, missing))}")
        if status == "FINAL" and missing:
            errors.append(f"detail_final_with_missing_parameters:{detail_id}")
        if any(str(g[0] if isinstance(g, (list, tuple)) and g else g) == "dimension" for g in geometry):
            if not parameters:
                errors.append(f"dimensioned_detail_without_parameters:{detail_id}")

    link_result = plan_detail_link_qa(manifest, details, links)
    errors.extend(link_result.get("errors") or [])
    incomplete.extend(link_result.get("incomplete") or [])

    return {
        "status": _status(errors, incomplete),
        "errors": errors,
        "incomplete": incomplete,
        "metrics": {
            "details": len(details),
            "detail_sheets": len(detail_sheets),
            "graphic_entities": graphic_count,
            "detail_layer_graphics": detail_layer_graphics,
            "text_entities": text_count,
            "rendered_detail_ids": len(rendered_ids),
            "entity_types": dict(entity_types),
            "plan_detail_links": link_result.get("metrics") or {},
        },
    }


def evidence_consistency_qa(data: Dict[str, Any]) -> Dict[str, Any]:
    """Catch contradictory evidence states such as FINAL values with no value/source."""
    errors: List[str] = []

    def walk(value: Any, path: str = "data") -> None:
        if isinstance(value, dict):
            status = str(value.get("status") or "")
            if status == "FINAL" and "value" in value:
                if value.get("value") is None:
                    errors.append(f"final_value_missing:{path}")
                if not value.get("source"):
                    errors.append(f"final_source_missing:{path}")
            if status == "FINAL" and value.get("missing"):
                errors.append(f"final_object_has_missing_inputs:{path}")
            for key, child in value.items():
                walk(child, f"{path}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(data)
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "metrics": {"error_count": len(errors)},
    }
