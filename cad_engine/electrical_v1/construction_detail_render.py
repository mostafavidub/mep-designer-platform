"""Construction-grade rendering for Electrical parametric detail sheets.

The project-driven pipeline already resolves which details are applicable and which
parameters remain INPUT_REQUIRED.  This module only renders that evidence: it
never supplies a missing project value.  The goal is to replace schematic/text-only
placeholders with section geometry, connections, dimensions and installation
assemblies before the acceptance visual/reopen/detail gates run.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import ezdxf

DETAIL_LAYER = "ENGITOOLS-E-DETAIL"
DOC_LAYER = "ENGITOOLS-E-DOC"
TEXT_HEIGHT = 0.90


def _value(detail: Dict[str, Any], name: str):
    raw = (detail.get("parameters") or {}).get(name)
    if isinstance(raw, dict):
        return raw.get("value")
    return raw


def _text(layout, value, point, height=TEXT_HEIGHT, layer=DETAIL_LAYER):
    return layout.add_text(
        str(value), dxfattribs={"layer": layer, "height": max(float(height), TEXT_HEIGHT)}
    ).set_placement(point)


def _line(layout, a, b, layer=DETAIL_LAYER):
    return layout.add_line(a, b, dxfattribs={"layer": layer})


def _rect(layout, x1, y1, x2, y2, layer=DETAIL_LAYER):
    return layout.add_lwpolyline(
        [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)],
        dxfattribs={"layer": layer},
    )


def _circle(layout, point, radius, layer=DETAIL_LAYER):
    return layout.add_circle(point, radius, dxfattribs={"layer": layer})


def _host_wall(layout, x, y1, y2, thickness=3.0):
    _line(layout, (x, y1), (x, y2))
    _line(layout, (x + thickness, y1), (x + thickness, y2))
    step = max((y2 - y1) / 10.0, 2.0)
    yy = y1
    while yy < y2:
        _line(layout, (x, yy), (x + thickness, min(yy + 1.4, y2)))
        yy += step


def _host_ceiling(layout, x1, x2, y, thickness=3.0):
    _line(layout, (x1, y), (x2, y))
    _line(layout, (x1, y - thickness), (x2, y - thickness))
    step = max((x2 - x1) / 12.0, 3.0)
    xx = x1
    while xx < x2:
        _line(layout, (xx, y - thickness), (min(xx + 2.0, x2), y))
        xx += step


def _dimension(layout, p1, p2, base, label):
    """Draw a real DIMENSION only when its project value is supplied."""
    if label in (None, ""):
        _text(layout, "DIMENSION: INPUT REQUIRED", (base[0], base[1] + 1.2))
        return False
    try:
        dim = layout.add_linear_dim(base=base, p1=p1, p2=p2, angle=0, dimstyle="Standard")
        dim.dimension.dxf.layer = DETAIL_LAYER
        dim.dimension.dxf.text = str(label)
        dim.render()
        return True
    except Exception:
        _line(layout, p1, (p1[0], base[1]))
        _line(layout, p2, (p2[0], base[1]))
        _line(layout, (p1[0], base[1]), (p2[0], base[1]))
        _text(layout, label, ((p1[0] + p2[0]) / 2.0, base[1] + 1.0))
        return True


def _connection(layout, x, y, scale=1.0):
    _line(layout, (x, y), (x + 7 * scale, y))
    _circle(layout, (x + 9 * scale, y), 2.0 * scale)
    _circle(layout, (x + 9 * scale, y), 0.65 * scale)
    _rect(layout, x + 11 * scale, y - 1.5 * scale, x + 18 * scale, y + 1.5 * scale)
    _line(layout, (x + 18 * scale, y), (x + 23 * scale, y))


def _panel_detail(layout, detail, x, y, w, h):
    wall_x = x + 12
    _host_wall(layout, wall_x, y + 10, y + h - 14)
    px1, py1 = wall_x + 5, y + 17
    px2, py2 = min(px1 + 31, x + w - 28), y + h - 20
    _rect(layout, px1, py1, px2, py2)
    _rect(layout, px1 + 3, py1 + 4, px2 - 3, py2 - 5)
    # Physical N / PE bars and termination ways.
    _line(layout, (px1 + 5, py1 + 8), (px2 - 5, py1 + 8))
    _line(layout, (px1 + 5, py1 + 12), (px2 - 5, py1 + 12))
    for i in range(5):
        xx = px1 + 6 + i * max((px2 - px1 - 12) / 4.0, 3.0)
        _circle(layout, (xx, py1 + 8), 0.5)
        _circle(layout, (xx, py1 + 12), 0.5)
    _text(layout, "PE BAR", (px1 + 3, py1 + 14))
    _text(layout, "N BAR", (px1 + 3, py1 + 4.5))
    # Cable entry / gland plate.
    for i in range(3):
        xx = px1 + 7 + i * 6
        _circle(layout, (xx, py2 - 2), 1.2)
        _line(layout, (xx, py2), (xx, min(py2 + 8, y + h - 10)))
    _dimension(layout, (wall_x, py1), (px2, py1), (wall_x, y + 12), _value(detail, "clearance"))
    _dimension(layout, (px1, py1), (px1, py2), (px1, y + 8), _value(detail, "mounting_height"))
    _text(layout, f"WALL: {_value(detail, 'wall_type') or 'INPUT REQUIRED'}", (x + 52, y + 11))


def _meter_detail(layout, detail, x, y, w, h):
    wall_x = x + 12
    _host_wall(layout, wall_x, y + 10, y + h - 14)
    bx1, by1 = wall_x + 5, y + 22
    bx2, by2 = min(bx1 + 28, x + w - 30), y + h - 22
    _rect(layout, bx1, by1, bx2, by2)
    _circle(layout, ((bx1 + bx2) / 2, (by1 + by2) / 2), min(7, (by2 - by1) / 3))
    _text(layout, "METER", (bx1 + 7, (by1 + by2) / 2 - 1))
    _line(layout, ((bx1 + bx2) / 2, by2), ((bx1 + bx2) / 2, y + h - 10))
    _line(layout, ((bx1 + bx2) / 2, by1), ((bx1 + bx2) / 2, y + 12))
    _dimension(layout, (bx1, by1), (bx1, by2), (bx1, y + 10), _value(detail, "mounting_height"))
    _text(layout, f"SERVICE: {_value(detail, 'service_type') or 'INPUT REQUIRED'}", (x + 48, y + 12))


def _conduit_support_detail(layout, detail, x, y, w, h):
    top = y + h - 20
    _host_ceiling(layout, x + 10, x + w - 10, top)
    base_y = y + 24
    for lane in range(3):
        cy = base_y + lane * 6
        _line(layout, (x + 20, cy - 1), (x + w - 18, cy - 1))
        _line(layout, (x + 20, cy + 1), (x + w - 18, cy + 1))
        for q in range(4):
            _circle(layout, (x + 30 + q * 14, cy), 0.55)
    for sx in (x + 30, x + w - 32):
        _line(layout, (sx, top - 3), (sx, base_y - 5))
        _line(layout, (sx + 4, top - 3), (sx + 4, base_y - 5))
        _line(layout, (sx - 2, base_y - 5), (sx + 6, base_y - 5))
    _dimension(layout, (x + 30, base_y), (x + w - 32, base_y), (x + 30, y + 13), _value(detail, "support_spacing"))
    _text(layout, f"CONDUIT: {_value(detail, 'conduit_type') or 'INPUT REQUIRED'}", (x + 12, y + 9))


def _wall_pen_detail(layout, detail, x, y, w, h):
    cx = x + w / 2
    _host_wall(layout, cx - 5, y + 10, y + h - 14, thickness=10)
    cy = y + h / 2
    _rect(layout, cx - 10, cy - 6, cx + 10, cy + 6)
    _rect(layout, cx - 7, cy - 4, cx + 7, cy + 4)
    for i in range(4):
        yy = cy - 3 + i * 2
        _line(layout, (x + 16, yy), (x + w - 16, yy))
    # Fire-stop packed zone is deliberately graphical rather than a text tag.
    for i in range(8):
        xx = cx - 9 + i * 2.5
        _line(layout, (xx, cy - 6), (xx + 4, cy + 6))
    _text(layout, f"FIRE RATING: {_value(detail, 'fire_rating') or 'INPUT REQUIRED'}", (x + 10, y + 9))
    _text(layout, f"SLEEVE: {_value(detail, 'sleeve') or 'INPUT REQUIRED'}", (x + 10, y + 13))
    _text(layout, f"WALL: {_value(detail, 'wall_type') or 'INPUT REQUIRED'}", (x + 10, y + 17))


def _earthing_detail(layout, detail, x, y, w, h):
    # Foundation/rebar section, copper conductor and inspection connection.
    fy1, fy2 = y + 13, y + 31
    _rect(layout, x + 10, fy1, x + w - 10, fy2)
    for i in range(7):
        xx = x + 18 + i * max((w - 36) / 6.0, 8.0)
        _circle(layout, (xx, fy1 + 5), 1.1)
        _circle(layout, (xx, fy2 - 5), 1.1)
        _line(layout, (xx, fy1 + 6), (xx, fy2 - 6))
    for yy in (fy1 + 5, fy2 - 5):
        _line(layout, (x + 16, yy), (x + w - 16, yy))
    conductor_y = fy2 + 9
    _line(layout, (x + 16, conductor_y), (x + w - 34, conductor_y))
    _line(layout, (x + 26, conductor_y), (x + 26, fy2 - 5))
    _connection(layout, x + w - 54, conductor_y)
    pit_x = x + w - 24
    _rect(layout, pit_x - 8, fy2 + 3, pit_x + 8, min(y + h - 12, fy2 + 19))
    _circle(layout, (pit_x, fy2 + 10), 2.0)
    _text(layout, "INSPECTION / TEST POINT", (pit_x - 17, fy2 + 21))
    _text(layout, f"ELECTRODE: {_value(detail, 'electrode_type') or 'INPUT REQUIRED'}", (x + 10, y + 8))
    _text(layout, f"CONDUCTOR: {_value(detail, 'conductor') or 'INPUT REQUIRED'}", (x + 58, y + 8))
    _text(layout, f"TEST POINT: {_value(detail, 'inspection_point') or 'INPUT REQUIRED'}", (x + 10, y + h - 10))


def _light_detail(layout, detail, x, y, w, h):
    top = y + h - 20
    _host_ceiling(layout, x + 10, x + w - 10, top)
    cx = x + w / 2
    _circle(layout, (cx, top - 9), 6)
    _circle(layout, (cx, top - 9), 3.5)
    for dx in (-5, 5):
        _line(layout, (cx + dx, top - 3), (cx + dx, top))
        _line(layout, (cx + dx - 2, top), (cx + dx + 2, top))
    _rect(layout, cx - 5, top + 3, cx + 5, top + 8)
    _line(layout, (cx, top + 8), (cx, y + h - 9))
    _text(layout, f"CEILING: {_value(detail, 'ceiling_type') or 'INPUT REQUIRED'}", (x + 10, y + 10))
    _text(layout, f"FIXTURE: {_value(detail, 'fixture_type') or 'INPUT REQUIRED'}", (x + 10, y + 14))


def _device_detail(layout, detail, x, y, w, h):
    wall_x = x + 18
    _host_wall(layout, wall_x, y + 10, y + h - 12)
    bx1, by1 = wall_x + 4, y + 24
    _rect(layout, bx1, by1, bx1 + 18, by1 + 13)
    _rect(layout, bx1 + 3, by1 + 3, bx1 + 15, by1 + 10)
    _circle(layout, (bx1 + 7, by1 + 6.5), 1.0)
    _circle(layout, (bx1 + 12, by1 + 6.5), 1.0)
    _line(layout, (bx1 + 9, by1 + 13), (bx1 + 9, y + h - 10))
    _dimension(layout, (wall_x, y + 12), (wall_x, by1), (x + 7, y + 12), _value(detail, "mounting_height"))
    _text(layout, f"WALL: {_value(detail, 'wall_type') or 'INPUT REQUIRED'}", (x + 50, y + 11))


def _fire_detector_detail(layout, detail, x, y, w, h):
    top = y + h - 20
    _host_ceiling(layout, x + 10, x + w - 10, top)
    cx = x + w / 2
    _circle(layout, (cx, top - 8), 5)
    _circle(layout, (cx, top - 8), 2.5)
    _line(layout, (cx - 8, top - 8), (cx + 8, top - 8))
    # Clearance envelope, not a fabricated numeric dimension.
    _circle(layout, (cx, top - 8), 11)
    _line(layout, (cx + 11, top - 8), (cx + 22, top - 8))
    _text(layout, "CLEARANCE ENVELOPE", (cx + 13, top - 6))
    _text(layout, f"CEILING: {_value(detail, 'ceiling_type') or 'INPUT REQUIRED'}", (x + 10, y + 10))
    _text(layout, f"BASIS: {_value(detail, 'clearance_basis') or 'INPUT REQUIRED'}", (x + 10, y + 14))


def _emergency_detail(layout, detail, x, y, w, h):
    wall_x = x + 16
    _host_wall(layout, wall_x, y + 10, y + h - 14)
    _rect(layout, wall_x + 5, y + 28, wall_x + 35, y + 42)
    _text(layout, "EMERGENCY LIGHT", (wall_x + 8, y + 33))
    _line(layout, (wall_x + 20, y + 42), (wall_x + 20, y + h - 10))
    _line(layout, (wall_x + 35, y + 35), (x + w - 12, y + 35))
    _text(layout, f"MOUNTING: {_value(detail, 'mounting') or 'INPUT REQUIRED'}", (x + 55, y + 12))
    _text(layout, f"SUPPLY: {_value(detail, 'supply') or 'INPUT REQUIRED'}", (x + 55, y + 16))


def _jb_detail(layout, detail, x, y, w, h):
    cx, cy = x + w / 2, y + h / 2
    _rect(layout, cx - 16, cy - 10, cx + 16, cy + 10)
    _rect(layout, cx - 13, cy - 7, cx + 13, cy + 7)
    for dx, dy in ((0, 18), (0, -18), (30, 0), (-30, 0)):
        if dx:
            _line(layout, (cx + (16 if dx > 0 else -16), cy), (cx + dx, cy))
            _line(layout, (cx + (16 if dx > 0 else -16), cy + 2), (cx + dx, cy + 2))
        else:
            _line(layout, (cx, cy + (10 if dy > 0 else -10)), (cx, cy + dy))
            _line(layout, (cx + 2, cy + (10 if dy > 0 else -10)), (cx + 2, cy + dy))
    for px, py in ((cx - 10, cy - 5), (cx + 10, cy - 5), (cx - 10, cy + 5), (cx + 10, cy + 5)):
        _circle(layout, (px, py), 0.8)
    _text(layout, f"BOX: {_value(detail, 'box_size') or 'INPUT REQUIRED'}", (x + 10, y + 9))
    _text(layout, f"ACCESS: {_value(detail, 'access') or 'INPUT REQUIRED'}", (x + 10, y + 13))


def _termination_detail(layout, detail, x, y, w, h):
    cy = y + h / 2
    # Multi-core cable, stripped section, lug, bolt/washer and terminal bar.
    _line(layout, (x + 10, cy - 4), (x + 42, cy - 4))
    _line(layout, (x + 10, cy + 4), (x + 42, cy + 4))
    for i in range(4):
        _circle(layout, (x + 22 + i * 5, cy), 1.1)
    _line(layout, (x + 42, cy), (x + 53, cy))
    _rect(layout, x + 53, cy - 3, x + 68, cy + 3)
    _circle(layout, (x + 72, cy), 3)
    _circle(layout, (x + 72, cy), 0.9)
    _circle(layout, (x + 72, cy), 1.8)
    _rect(layout, x + 75, cy - 5, min(x + w - 10, x + 98), cy + 5)
    _text(layout, f"CABLE: {_value(detail, 'cable') or 'INPUT REQUIRED'}", (x + 10, y + 10))
    _text(layout, f"LUG: {_value(detail, 'lug') or 'INPUT REQUIRED'}", (x + 10, y + 14))
    _text(layout, f"PROTECTION: {_value(detail, 'protection') or 'INPUT REQUIRED'}", (x + 55, y + 10))


def _isolator_detail(layout, detail, x, y, w, h):
    cy = y + h / 2
    _rect(layout, x + 14, cy - 12, x + 45, cy + 12)
    _text(layout, "EQUIPMENT", (x + 20, cy - 1))
    _rect(layout, x + 62, cy - 10, x + 84, cy + 10)
    _text(layout, "ISO", (x + 68, cy - 1))
    for yy in (cy - 2, cy + 2):
        _line(layout, (x + 45, yy), (x + 62, yy))
        _line(layout, (x + 84, yy), (x + w - 12, yy))
    _dimension(layout, (x + 45, cy), (x + 62, cy), (x + 45, y + 12), _value(detail, "clearance"))
    _text(layout, f"RATING: {_value(detail, 'rating') or 'INPUT REQUIRED'}", (x + 10, y + 8))
    _text(layout, f"MOUNTING: {_value(detail, 'mounting') or 'INPUT REQUIRED'}", (x + 58, y + 8))


def _generic_detail(layout, detail, x, y, w, h):
    cx, cy = x + w / 2, y + h / 2
    _rect(layout, x + 12, y + 14, x + w - 12, y + h - 18)
    _line(layout, (x + 12, cy), (x + w - 12, cy))
    _line(layout, (cx, y + 14), (cx, y + h - 18))
    for i in range(6):
        _circle(layout, (x + 22 + i * max((w - 44) / 5.0, 7), cy), 1.0)


def _draw_one(layout, detail, x, y, w, h):
    did = str(detail.get("detail_id") or "DETAIL")
    if "PANEL-MOUNT" in did:
        _panel_detail(layout, detail, x, y, w, h)
    elif "METER" in did:
        _meter_detail(layout, detail, x, y, w, h)
    elif "CONDUIT-SUPPORT" in did:
        _conduit_support_detail(layout, detail, x, y, w, h)
    elif "WALL-PEN" in did:
        _wall_pen_detail(layout, detail, x, y, w, h)
    elif "EARTHING" in did:
        _earthing_detail(layout, detail, x, y, w, h)
    elif "LIGHT-MOUNT" in did:
        _light_detail(layout, detail, x, y, w, h)
    elif "SWITCH-OUTLET" in did:
        _device_detail(layout, detail, x, y, w, h)
    elif "FIRE-DETECTOR" in did:
        _fire_detector_detail(layout, detail, x, y, w, h)
    elif "EMERGENCY" in did:
        _emergency_detail(layout, detail, x, y, w, h)
    elif did.endswith("-JB"):
        _jb_detail(layout, detail, x, y, w, h)
    elif "TERMINATION" in did:
        _termination_detail(layout, detail, x, y, w, h)
    elif "ISOLATOR" in did:
        _isolator_detail(layout, detail, x, y, w, h)
    else:
        _generic_detail(layout, detail, x, y, w, h)


def upgrade_construction_details(
    path: str | Path,
    manifest: Iterable[Dict[str, Any]],
    details: Iterable[Dict[str, Any]],
    paper: Tuple[float, float] = (420.0, 297.0),
) -> Dict[str, Any]:
    """Redraw the generated DETAILS layout at construction-document density.

    The current manifest owns one project-specific detail sheet.  Up to twelve
    resolved details are arranged on that A3 sheet using a 3-column grid.  This
    exactly covers the current parametric library without silently dropping later
    details; if the library grows beyond twelve, the function fails closed so the
    manifest can be paginated deliberately in a later contract revision.
    """
    details = list(details or [])
    detail_sheets = [s for s in (manifest or []) if str(s.get("family") or "") == "DETAILS"]
    if not details:
        return {"status": "NOT_REQUIRED", "details": 0, "rendered": 0}
    if not detail_sheets:
        return {"status": "FAIL", "errors": ["details_exist_without_detail_sheet"], "details": len(details), "rendered": 0}
    if len(details) > 12:
        return {"status": "FAIL", "errors": [f"detail_sheet_capacity_exceeded:{len(details)}>12"], "details": len(details), "rendered": 0}

    path = Path(path)
    doc = ezdxf.readfile(str(path))
    sheet_id = str(detail_sheets[0].get("sheet_id") or "")
    if sheet_id not in doc.layouts:
        return {"status": "FAIL", "errors": [f"detail_layout_missing:{sheet_id}"], "details": len(details), "rendered": 0}
    layout = doc.layouts.get(sheet_id)

    # Keep title-block/document geometry; replace only the generated detail layer.
    for entity in list(layout):
        if str(getattr(entity.dxf, "layer", "") or "") == DETAIL_LAYER:
            try:
                layout.delete_entity(entity)
            except Exception:
                pass

    cols = 3
    rows = max(1, math.ceil(len(details) / cols))
    usable_left, usable_right = 10.0, float(paper[0]) - 10.0
    usable_bottom, usable_top = 19.0, float(paper[1]) - 15.0
    cell_w = (usable_right - usable_left) / cols
    cell_h = (usable_top - usable_bottom) / rows
    if cell_h < 55.0:
        return {"status": "FAIL", "errors": [f"detail_cells_too_small:{cell_h:.1f}mm"], "details": len(details), "rendered": 0}

    dimensions = 0
    for index, detail in enumerate(details):
        col = index % cols
        row = index // cols
        x = usable_left + col * cell_w
        y = usable_top - (row + 1) * cell_h
        w = cell_w - 3.0
        h = cell_h - 3.0
        _rect(layout, x, y, x + w, y + h)
        did = str(detail.get("detail_id") or f"DETAIL-{index + 1}")
        _text(layout, did, (x + 3, y + h - 5), height=1.55)
        _text(layout, f"STATUS: {detail.get('status') or 'PRELIMINARY'}", (x + w - 47, y + h - 5), height=0.95)
        _draw_one(layout, detail, x, y, w, h)
        params = detail.get("parameters") or {}
        supplied = [name for name, raw in params.items() if _value(detail, name) not in (None, "")]
        missing = list(detail.get("missing") or [])
        _text(layout, "PARAMETERS: " + (", ".join(supplied) if supplied else "INPUT REQUIRED"), (x + 3, y + 3.3), height=0.9)
        if missing:
            _text(layout, "INPUT REQUIRED: " + ", ".join(map(str, missing))[:90], (x + 3, y + 6.4), height=0.9)
        dimensions += sum(1 for primitive in (detail.get("geometry") or []) if isinstance(primitive, (list, tuple)) and primitive and primitive[0] == "dimension" and len(primitive) > 1 and _value(detail, str(primitive[1])) not in (None, ""))

    doc.saveas(str(path))
    return {
        "status": "PASS",
        "detail_sheet": sheet_id,
        "details": len(details),
        "rendered": len(details),
        "columns": cols,
        "rows": rows,
        "cell_width_mm": round(cell_w, 2),
        "cell_height_mm": round(cell_h, 2),
        "dimensioned_parameters": dimensions,
    }
