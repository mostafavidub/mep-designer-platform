from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import ezdxf

from .models import EngineeringStatus, EvidenceValue, SheetManifestItem

MIN_PRINT_TEXT_HEIGHT = 0.90


def append_detail_sheet(manifest: List[SheetManifestItem], details) -> None:
    if not details or any(s.family == "DETAILS" for s in manifest):
        return
    nums = []
    for sheet in manifest:
        try:
            nums.append(int(sheet.sheet_id.split("-")[-1]))
        except Exception:
            pass
    sid = f"E-{(max(nums) if nums else 0) + 1:02d}"
    manifest.append(SheetManifestItem(
        sid, "DETAILS", None, "Project-specific electrical construction details",
        ["parametric_details"], ["ENGITOOLS-E-DETAIL", "ENGITOOLS-E-DOC"], [],
        {"parametric_details": 1}, [],
    ))


def _fit_transform(bounds, paper, margins=(12, 18, 12, 12)):
    pw, ph = paper
    left, bottom, right, top = margins
    x1, y1, x2, y2 = bounds
    aw = max(pw - left - right, 1e-6)
    ah = max(ph - bottom - top, 1e-6)
    w = max(x2 - x1, 1e-9)
    h = max(y2 - y1, 1e-9)
    scale = min(aw / w, ah / h)
    ox = left + (aw - w * scale) / 2 - x1 * scale
    oy = bottom + (ah - h * scale) / 2 - y1 * scale
    return lambda p: (float(p[0]) * scale + ox, float(p[1]) * scale + oy)


def _frame(architecture, frame_id):
    if architecture is None:
        return None
    return next((f for f in architecture.frames if f.id == frame_id), None)


def _text(layout, value, point, *, height=1.0, layer="ENGITOOLS-E-DETAIL"):
    """All generated construction text is kept above the visual-QA print floor."""
    h = max(float(height), MIN_PRINT_TEXT_HEIGHT)
    return layout.add_text(str(value), dxfattribs={"layer": layer, "height": h}).set_placement(point)


def _rect(layout, x1, y1, x2, y2, layer="ENGITOOLS-E-DETAIL"):
    return layout.add_lwpolyline(
        [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)],
        dxfattribs={"layer": layer},
    )


def _draw_cover(doc, manifest, signatures, paper):
    for sheet in [s for s in manifest if s.family == "COVER"]:
        if sheet.sheet_id not in doc.layouts:
            continue
        layout = doc.layouts.get(sheet.sheet_id)
        y = paper[1] - 28
        _text(layout, "ELECTRICAL DRAWING INDEX", (18, y), height=2.5, layer="ENGITOOLS-E-DOC")
        y -= 7
        for item in manifest:
            _text(layout, f"{item.sheet_id}  {item.purpose}", (18, y), height=1.2, layer="ENGITOOLS-E-DOC")
            y -= 4
        signatures.setdefault(sheet.sheet_id, {}).setdefault("signature", {})["sheet_index"] = len(manifest)


def _draw_panels(doc, manifest, topology, architecture, paper):
    if not topology or architecture is None:
        return
    for panel in topology.get("panels") or []:
        location = panel.location.value if isinstance(panel.location, EvidenceValue) and panel.location.status == EngineeringStatus.FINAL else None
        if not isinstance(location, dict) or not location.get("point"):
            continue
        frame_id = location.get("frame_id")
        if not frame_id:
            candidate = next((f for f in architecture.frames if f.level_id == panel.level_id and f.eligible_for_electrical), None)
            frame_id = candidate.id if candidate else None
        frame = _frame(architecture, frame_id)
        if not frame:
            continue
        point = _fit_transform(frame.bounds, paper)(location["point"])
        for sheet in manifest:
            if sheet.family != "POWER" or sheet.level_id != panel.level_id or sheet.sheet_id not in doc.layouts:
                continue
            layout = doc.layouts.get(sheet.sheet_id)
            if "ET_EL_PNL_01" in doc.blocks:
                layout.add_blockref("ET_EL_PNL_01", point, dxfattribs={"layer": "ENGITOOLS-E-POWER"})
            else:
                _rect(layout, point[0] - 2, point[1] - 3, point[0] + 2, point[1] + 3, "ENGITOOLS-E-POWER")
            _text(layout, panel.id, (point[0] + 3, point[1] + 2), height=1.3, layer="ENGITOOLS-E-ANNOTATION")


def _draw_grounding(doc, manifest, grounding, signatures, paper, architecture=None):
    elements = grounding.get("elements") or []
    for sheet in [s for s in manifest if s.family == "GROUNDING"]:
        if sheet.sheet_id not in doc.layouts:
            continue
        layout = doc.layouts.get(sheet.sheet_id)
        count = 0
        y = paper[1] - 35
        for element in elements:
            data = element.get("data")
            status = element.get("status")
            _text(layout, f"{element['kind']}: {data if data is not None else status}", (18, y), height=1.3, layer="ENGITOOLS-E-GROUNDING")
            y -= 5
            count += 1
            if element["kind"] == "earth_electrode" and isinstance(data, dict) and data.get("point"):
                frame_id = data.get("frame_id") or (sheet.source_frame_ids[0] if sheet.source_frame_ids else None)
                frame = _frame(architecture, frame_id)
                q = _fit_transform(frame.bounds, paper)(data["point"]) if frame else (90.0, y + 4.0)
                if "ET_EL_GND_01" in doc.blocks:
                    layout.add_blockref("ET_EL_GND_01", q, dxfattribs={"layer": "ENGITOOLS-E-GROUNDING"})
                else:
                    layout.add_circle(q, 2.0, dxfattribs={"layer": "ENGITOOLS-E-GROUNDING"})
                label = "EARTH ELECTRODE" if frame else "EARTH ELECTRODE - PLAN COORDINATION INPUT"
                _text(layout, label, (q[0] + 3, q[1] + 1), height=1.1, layer="ENGITOOLS-E-ANNOTATION")
                count += 1
        signatures.setdefault(sheet.sheet_id, {}).setdefault("signature", {})["grounding_elements"] = count


def _parameter_value(detail: dict, name: str) -> str:
    value = (detail.get("parameters") or {}).get(name)
    if isinstance(value, dict):
        raw = value.get("value")
        if raw not in (None, ""):
            return str(raw)
        return str(value.get("status") or "PROJECT INPUT")
    return str(value) if value not in (None, "") else "PROJECT INPUT"


def _dimension(layout, p1, p2, base, label):
    try:
        dim = layout.add_linear_dim(base=base, p1=p1, p2=p2, angle=0, dimstyle="Standard")
        dim.dimension.dxf.layer = "ENGITOOLS-E-DETAIL"
        dim.dimension.dxf.text = str(label)
        dim.render()
    except Exception:
        layout.add_line(p1, (p1[0], base[1]), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_line(p2, (p2[0], base[1]), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_line((p1[0], base[1]), (p2[0], base[1]), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        _text(layout, label, ((p1[0] + p2[0]) / 2, base[1] + 1), height=MIN_PRINT_TEXT_HEIGHT)


def _host_section(layout, x, y, width=22, *, vertical=False):
    if vertical:
        layout.add_line((x, y - 7), (x, y + 7), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_line((x + 2, y - 7), (x + 2, y + 7), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        for k in range(7):
            yy = y - 6 + k * 2
            layout.add_line((x, yy), (x + 2, yy + 1), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
    else:
        layout.add_line((x, y), (x + width, y), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_line((x, y - 2), (x + width, y - 2), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        for k in range(8):
            xx = x + 1 + k * max((width - 2) / 7, 1)
            layout.add_line((xx - 1, y - 2), (xx + 1, y), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})


def _primitive(layout, detail: dict, kind: str, x: float, y: float, width: float, index: int):
    lane = index % 3
    bx = x + 7 + lane * max((width - 21) / 3, 22)
    by = y - 12 - (index // 3) * 14

    if kind == "wall_section":
        _host_section(layout, bx, by, vertical=True)
        _text(layout, "WALL / FINISH", (bx + 3, by + 5))
    elif kind in {"ceiling_section", "mounting_surface"}:
        _host_section(layout, bx, by + 4)
        _text(layout, "HOST / FINISH", (bx, by + 6))
    elif kind in {"panel_box", "meter_box", "device_box", "junction_box", "isolator", "equipment"}:
        _rect(layout, bx, by - 5, bx + 16, by + 5)
        _rect(layout, bx + 2, by - 3, bx + 14, by + 3)
        for q in range(4):
            layout.add_circle((bx + 4 + q * 3, by), 0.55, dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        _text(layout, kind.replace("_", " ").upper(), (bx, by + 6))
    elif kind in {"luminaire", "detector", "emergency_light"}:
        layout.add_circle((bx + 8, by), 4, dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_circle((bx + 8, by), 2.4, dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_line((bx + 2, by + 5), (bx + 14, by + 5), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_line((bx + 8, by + 5), (bx + 8, by + 3.8), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        _text(layout, kind.replace("_", " ").upper(), (bx, by + 7))
    elif kind in {"conduit", "cable"}:
        layout.add_line((bx, by - 1), (bx + 20, by - 1), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_line((bx, by + 1), (bx + 20, by + 1), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        for q in range(5):
            layout.add_circle((bx + 2 + q * 4, by), 0.55, dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        _text(layout, kind.upper(), (bx, by + 4))
    elif kind in {"connection", "terminal", "lug"}:
        layout.add_line((bx, by), (bx + 8, by), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_circle((bx + 10, by), 2.2, dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_circle((bx + 10, by), 0.7, dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_lwpolyline([(bx + 12, by), (bx + 17, by + 2), (bx + 21, by + 2), (bx + 23, by)], dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        _text(layout, kind.upper(), (bx, by + 5))
    elif kind == "support":
        layout.add_line((bx, by + 5), (bx + 22, by + 5), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        for q in range(4):
            xx = bx + 3 + q * 5
            layout.add_arc((xx, by + 1), 2.2, 0, 180, dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
            layout.add_line((xx - 2.2, by + 1), (xx - 2.2, by - 4), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
            layout.add_line((xx + 2.2, by + 1), (xx + 2.2, by - 4), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        _text(layout, "SUPPORT", (bx, by + 7))
    elif kind in {"sleeve", "firestop"}:
        _rect(layout, bx, by - 5, bx + 22, by + 5)
        _rect(layout, bx + 5, by - 4, bx + 17, by + 4)
        for q in range(4):
            xx = bx + 7 + q * 3
            layout.add_line((xx, by - 6), (xx, by + 6), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        _text(layout, "SLEEVE / FIRESTOP", (bx + 2, by + 7))
    elif kind in {"earth", "electrode"}:
        layout.add_line((bx + 10, by + 6), (bx + 10, by - 1), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_line((bx + 3, by - 1), (bx + 17, by - 1), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_line((bx + 5, by - 3.5), (bx + 15, by - 3.5), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_line((bx + 7, by - 6), (bx + 13, by - 6), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        _text(layout, "EARTH", (bx + 14, by + 2))
    elif kind in {"clearance", "clearance_zone", "access_zone"}:
        _rect(layout, bx, by - 5, bx + 22, by + 5)
        layout.add_line((bx, by - 5), (bx + 22, by + 5), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_line((bx, by + 5), (bx + 22, by - 5), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        _text(layout, "KEEP CLEAR / ACCESS", (bx, by + 7))
    elif kind == "dimension":
        name = str((detail.get("geometry") or [("dimension", "project_value")])[index][1]) if index < len(detail.get("geometry") or []) and len((detail.get("geometry") or [])[index]) > 1 else "project_value"
        _dimension(layout, (bx, by), (bx + 18, by), (bx, by - 6), _parameter_value(detail, name))
    else:
        # Unknown semantic primitives remain visible and non-silent instead of disappearing.
        layout.add_circle((bx + 8, by), 3.5, dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        layout.add_line((bx + 3, by), (bx + 13, by), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        _text(layout, kind.replace("_", " ").upper(), (bx, by + 5))


def _draw_details(doc, manifest, details, signatures, paper):
    sheets = [s for s in manifest if s.family == "DETAILS"]
    if not sheets:
        return
    sheet = sheets[0]
    if sheet.sheet_id not in doc.layouts:
        return
    layout = doc.layouts.get(sheet.sheet_id)
    cols = 2
    cell_w = (paper[0] - 30) / cols
    cell_h = 66
    count = 0
    for i, detail in enumerate(details):
        col = i % cols
        row = i // cols
        x = 12 + col * cell_w
        y = paper[1] - 25 - row * cell_h
        if y - cell_h < 19:
            break
        _rect(layout, x, y - cell_h + 5, x + cell_w - 5, y)
        _text(layout, detail.get("detail_id", f"DETAIL-{i + 1}"), (x + 3, y - 5), height=1.8)
        status = str(detail.get("status") or "PRELIMINARY")
        _text(layout, f"STATUS: {status}", (x + cell_w - 54, y - 5), height=1.0)
        for index, primitive in enumerate(detail.get("geometry") or []):
            kind = str(primitive[0] if isinstance(primitive, (tuple, list)) and primitive else primitive)
            _primitive(layout, detail, kind, x, y, cell_w - 5, index)
        params = detail.get("parameters") or {}
        if params:
            ptxt = " | ".join(f"{k}={_parameter_value(detail, k)}" for k in params)
            _text(layout, ptxt[:150], (x + 3, y - cell_h + 9), height=0.95)
        missing = list(detail.get("missing") or [])
        if missing:
            _text(layout, "INPUT REQUIRED: " + ", ".join(map(str, missing))[:120], (x + 3, y - cell_h + 5.5), height=0.95)
        count += 1
    signatures.setdefault(sheet.sheet_id, {}).setdefault("signature", {})["parametric_details"] = count


def _draw_detail_links(doc, manifest, links, paper):
    detail_sheet = next((s.sheet_id for s in manifest if s.family == "DETAILS"), None)
    if not detail_sheet:
        return
    grouped = {}
    for link in links or []:
        grouped.setdefault(link["sheet_id"], []).append(link["detail_id"])
    for sheet_id, detail_ids in grouped.items():
        if sheet_id not in doc.layouts:
            continue
        layout = doc.layouts.get(sheet_id)
        y = paper[1] - 22
        for did in sorted(set(detail_ids)):
            _text(layout, f"SEE DETAIL {detail_sheet} / {did}", (paper[0] - 92, y), height=1.0, layer="ENGITOOLS-E-ANNOTATION")
            y -= 3.2


def optimize_annotations(doc, manifest, paper):
    moved = 0
    for sheet in manifest:
        if sheet.sheet_id not in doc.layouts:
            continue
        layout = doc.layouts.get(sheet.sheet_id)
        texts = [e for e in layout if e.dxftype() == "TEXT" and str(getattr(e.dxf, "layer", "")) == "ENGITOOLS-E-ANNOTATION"]
        occupied = []
        for entity in texts:
            p = entity.dxf.insert
            height = max(float(entity.dxf.height or 1), MIN_PRINT_TEXT_HEIGHT)
            if float(entity.dxf.height or 0) < MIN_PRINT_TEXT_HEIGHT:
                entity.dxf.height = MIN_PRINT_TEXT_HEIGHT
            value = str(entity.dxf.text or "")
            width = max(height * 0.55 * len(value), height)
            box = [float(p.x), float(p.y), float(p.x) + width, float(p.y) + height]
            original = (float(p.x), float(p.y))
            attempts = 0
            while any(max(0, min(box[2], b[2]) - max(box[0], b[0])) * max(0, min(box[3], b[3]) - max(box[1], b[1])) > 0.2 for b in occupied) and attempts < 8:
                box = [box[0], box[1] + 3, box[2], box[3] + 3]
                attempts += 1
            if attempts:
                entity.dxf.insert = (box[0], box[1])
                layout.add_line(original, (box[0], box[1]), dxfattribs={"layer": "ENGITOOLS-E-ANNOTATION"})
                moved += 1
            occupied.append(box)
    return moved


def enforce_print_legibility(doc, manifest):
    """Repair generated text, not the QA threshold: no output TEXT may be below 0.8 mm."""
    changed = 0
    for sheet in manifest:
        if sheet.sheet_id not in doc.layouts:
            continue
        for entity in doc.layouts.get(sheet.sheet_id):
            if entity.dxftype() == "TEXT" and float(entity.dxf.height or 0) < MIN_PRINT_TEXT_HEIGHT:
                entity.dxf.height = MIN_PRINT_TEXT_HEIGHT
                changed += 1
    return changed


def apply_postcomposition(path: str | Path, manifest, details, grounding, signatures, paper=(420.0, 297.0), *, architecture=None, topology=None, links=None):
    doc = ezdxf.readfile(str(path))
    _draw_cover(doc, manifest, signatures, paper)
    _draw_panels(doc, manifest, topology or {}, architecture, paper)
    _draw_grounding(doc, manifest, grounding, signatures, paper, architecture)
    _draw_details(doc, manifest, details, signatures, paper)
    _draw_detail_links(doc, manifest, links or [], paper)
    moved = optimize_annotations(doc, manifest, paper)
    legibility_repairs = enforce_print_legibility(doc, manifest)
    doc.saveas(str(path))
    return {
        "status": "PASS",
        "annotations_moved_with_leaders": moved,
        "print_legibility_repairs": legibility_repairs,
        "minimum_text_height_mm": MIN_PRINT_TEXT_HEIGHT,
    }
