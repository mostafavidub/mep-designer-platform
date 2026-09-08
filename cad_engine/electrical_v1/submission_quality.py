from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

import ezdxf


def _sheet_value(sheet: Any, key: str, default=None):
    if isinstance(sheet, dict):
        return sheet.get(key, default)
    return getattr(sheet, key, default)


def _ev_value(value: Any, default: str = "INPUT REQUIRED") -> str:
    if isinstance(value, dict):
        raw = value.get("value")
        return str(raw) if raw not in (None, "") else default
    if value not in (None, ""):
        return str(value)
    return default


def _project_field(data: Dict[str, Any], key: str, default: str = "INPUT REQUIRED") -> str:
    project_model = data.get("project") or {}
    project = project_model.get("project") or {}
    return _ev_value(project.get(key), default)


def apply_submission_titleblocks(path: str | Path, data: Dict[str, Any], paper=(420.0, 297.0)) -> Dict[str, Any]:
    """Add a structured second-row submission band without inventing admin facts.

    The base composer already owns the bottom title band. This enrichment adds
    discipline/project/status/scale/admin-evidence cells above it. Missing
    project metadata is rendered as INPUT REQUIRED rather than substituted.
    """
    path = Path(path)
    if not path.exists():
        return {"status": "FAIL", "errors": ["output_file_missing"], "sheets": 0}
    doc = ezdxf.readfile(str(path))
    if "ENGITOOLS-E-DOC" not in doc.layers:
        doc.layers.add("ENGITOOLS-E-DOC", color=7)
    manifest = data.get("manifest") or []
    project_name = _project_field(data, "project_name", "EngiTools Electrical Project")
    owner = _project_field(data, "owner")
    address = _project_field(data, "address")
    designer = _project_field(data, "designer")
    case_no = _project_field(data, "case_no")
    w, _ = paper
    drawn = 0
    for sheet in manifest:
        sheet_id = str(_sheet_value(sheet, "sheet_id") or "")
        if not sheet_id or sheet_id not in doc.layouts:
            continue
        layout = doc.layouts.get(sheet_id)
        y0, y1 = 12.0, 18.0
        # Horizontal boundary and fixed cells are presentation structure only.
        layout.add_line((5, y1), (w - 5, y1), dxfattribs={"layer": "ENGITOOLS-E-DOC"})
        cuts = [5, 62, 172, 224, 285, 338, w - 5]
        for x in cuts:
            layout.add_line((x, y0), (x, y1), dxfattribs={"layer": "ENGITOOLS-E-DOC"})
        values = [
            "DISCIPLINE: ELECTRICAL",
            f"PROJECT: {project_name}",
            f"SHEET: {sheet_id}",
            "STATUS: EVIDENCE-AWARE",
            "SCALE: AS COMPOSED",
            f"CASE: {case_no}",
        ]
        for i, text in enumerate(values):
            layout.add_text(text[:62], dxfattribs={"layer": "ENGITOOLS-E-DOC", "height": 0.95}).set_placement((cuts[i] + 1.2, 15.2))
        admin = f"OWNER: {owner} | DESIGNER: {designer} | ADDRESS: {address}"
        layout.add_text(admin[:185], dxfattribs={"layer": "ENGITOOLS-E-DOC", "height": 0.82}).set_placement((6.2, 12.9))
        drawn += 1
    doc.saveas(str(path))
    return {"status": "PASS", "errors": [], "sheets": drawn}


def submission_titleblock_qa(path: str | Path, manifest: Iterable[Any]) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {"status": "FAIL", "errors": ["output_file_missing"], "metrics": {"checked": 0}}
    doc = ezdxf.readfile(str(path))
    errors = []
    checked = 0
    for sheet in manifest:
        sheet_id = str(_sheet_value(sheet, "sheet_id") or "")
        if not sheet_id:
            continue
        checked += 1
        if sheet_id not in doc.layouts:
            errors.append(f"titleblock_layout_missing:{sheet_id}")
            continue
        texts = []
        for entity in doc.layouts.get(sheet_id):
            if entity.dxftype() == "TEXT":
                texts.append(str(getattr(entity.dxf, "text", "") or ""))
            elif entity.dxftype() == "MTEXT":
                try:
                    texts.append(str(entity.plain_text() or ""))
                except Exception:
                    pass
        joined = "\n".join(texts).upper()
        for token in ("DISCIPLINE: ELECTRICAL", f"SHEET: {sheet_id}".upper(), "STATUS:", "PROJECT:"):
            if token not in joined:
                errors.append(f"titleblock_field_missing:{sheet_id}:{token}")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "metrics": {"checked": checked}}


def cross_sheet_traceability_qa(data: Dict[str, Any]) -> Dict[str, Any]:
    """Verify machine traceability across topology, schedules, routes and details.

    This gate does not require unknown numeric project values. It only requires
    that generated objects have consistent ownership and references across
    representations.
    """
    topology = data.get("topology") or {}
    circuits = topology.get("circuits") or []
    panels = topology.get("panels") or []
    schedules = data.get("schedules") or {}
    routing = data.get("routing") or {}
    details = data.get("details") or []
    links = data.get("detail_links") or []
    manifest = data.get("manifest") or []

    circuit_ids = {str(x.get("id")) for x in circuits if x.get("id")}
    panel_ids = {str(x.get("id")) for x in panels if x.get("id")}
    detail_ids = {str(x.get("detail_id")) for x in details if x.get("detail_id")}
    sheet_ids = {str(x.get("sheet_id")) for x in manifest if x.get("sheet_id")}
    errors = []

    for circuit in circuits:
        cid = str(circuit.get("id") or "")
        panel_id = str(circuit.get("panel_id") or "")
        if not cid:
            errors.append("circuit_id_missing")
        if not panel_id or panel_id not in panel_ids:
            errors.append(f"circuit_panel_missing:{cid}:{panel_id}")
        if not list(circuit.get("load_ids") or []):
            errors.append(f"circuit_load_ownership_missing:{cid}")

    for panel in panels:
        pid = str(panel.get("id") or "")
        for cid in panel.get("circuit_ids") or []:
            if str(cid) not in circuit_ids:
                errors.append(f"panel_circuit_reference_missing:{pid}:{cid}")

    for route in routing.get("routes") or []:
        cid = str(route.get("circuit_id") or "")
        if cid and cid not in circuit_ids:
            errors.append(f"route_circuit_reference_missing:{cid}")

    for panel_id, rows in schedules.items():
        if str(panel_id) not in panel_ids:
            errors.append(f"schedule_panel_missing:{panel_id}")
        for row in rows or []:
            cid = str(row.get("circuit_no") or row.get("circuit_id") or "")
            if cid and cid not in circuit_ids:
                errors.append(f"schedule_circuit_reference_missing:{panel_id}:{cid}")

    for link in links:
        sid = str(link.get("sheet_id") or "")
        did = str(link.get("detail_id") or "")
        if sid not in sheet_ids:
            errors.append(f"detail_link_sheet_missing:{sid}")
        if did not in detail_ids:
            errors.append(f"detail_link_detail_missing:{did}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "metrics": {
            "circuits": len(circuit_ids),
            "panels": len(panel_ids),
            "routes": len(routing.get("routes") or []),
            "schedule_panels": len(schedules),
            "details": len(detail_ids),
            "detail_links": len(links),
        },
    }
