from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Iterable

import ezdxf


def _norm(value: Any) -> str:
    return " ".join(str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").split()).strip().lower()


def _point(entity):
    for attr in ("insert", "location", "start", "center"):
        try:
            p = getattr(entity.dxf, attr)
            return float(p.x), float(p.y)
        except Exception:
            pass
    return None


def _inside(point, bounds, tol=1e-6):
    if not point or not bounds:
        return False
    x, y = point; x1, y1, x2, y2 = bounds
    return x1-tol <= x <= x2+tol and y1-tol <= y <= y2+tol


def _text(entity) -> str:
    try:
        if entity.dxftype() == "TEXT":
            return str(entity.dxf.text or "")
        if entity.dxftype() == "MTEXT":
            return str(entity.plain_text() or "")
    except Exception:
        pass
    return ""


def _line_points(entity):
    try:
        if entity.dxftype() == "LINE":
            a, b = entity.dxf.start, entity.dxf.end
            return [(float(a.x), float(a.y)), (float(b.x), float(b.y))]
        if entity.dxftype() == "LWPOLYLINE":
            return [(float(x), float(y)) for x, y, *_ in entity.get_points()]
    except Exception:
        pass
    return []


def _detect_north_from_index(bounds, n_labels, line_points, *, radius_ratio: float = 0.10) -> Dict[str, Any] | None:
    """Resolve north for one frame from a pre-indexed modelspace scan.

    The source DXF may be tens of megabytes. Reading and rescanning it once per
    architectural frame made real-project acceptance effectively quadratic in
    practice. This helper keeps the evidence rule identical while reusing one
    source parse and one entity index for every frame.
    """
    frame_labels = [p for p in n_labels if _inside(p, bounds)]
    if not frame_labels:
        return None
    x1, y1, x2, y2 = bounds
    radius = max(math.hypot(x2-x1, y2-y1) * radius_ratio, 1e-6)
    frame_points = [p for p in line_points if _inside(p, bounds)]
    best = None
    for n in frame_labels:
        nearby = [p for p in frame_points if math.dist(p, n) <= radius]
        if len(nearby) < 3:
            continue
        cx = sum(p[0] for p in nearby) / len(nearby); cy = sum(p[1] for p in nearby) / len(nearby)
        vx, vy = n[0]-cx, n[1]-cy; length = math.hypot(vx, vy)
        if length < 1e-9:
            continue
        vx /= length; vy /= length
        candidate = {
            "vector": (vx, vy),
            "angle_deg": math.degrees(math.atan2(vy, vx)) % 360.0,
            "confidence": 0.82,
            "source": "ARCH_COMPASS_CLUSTER",
            "status": "FINAL",
            "north_label_point": n,
            "cluster_point_count": len(nearby),
        }
        if best is None or candidate["cluster_point_count"] > best["cluster_point_count"]:
            best = candidate
    return best


def _north_evidence_index(source: str | Path):
    doc = ezdxf.readfile(str(source)); msp = doc.modelspace()
    n_labels = []
    line_points = []
    for entity in msp:
        etype = entity.dxftype()
        if etype in {"TEXT", "MTEXT"}:
            if _norm(_text(entity)) == "n":
                p = _point(entity)
                if p is not None:
                    n_labels.append(p)
        elif etype in {"LINE", "LWPOLYLINE"}:
            line_points.extend(_line_points(entity))
    return n_labels, line_points


def detect_north_for_frame(source: str | Path, bounds, *, radius_ratio: float = 0.10) -> Dict[str, Any] | None:
    """Return architectural north only when a compass cluster is geometrically evidenced."""
    n_labels, line_points = _north_evidence_index(source)
    return _detect_north_from_index(bounds, n_labels, line_points, radius_ratio=radius_ratio)


def detect_project_north(source: str | Path, frames: Iterable[dict]) -> Dict[str, Any]:
    records = {}
    warnings = []
    n_labels, line_points = _north_evidence_index(source)
    for frame in frames:
        if not frame.get("eligible_for_electrical"):
            continue
        frame_id = frame.get("id")
        north = _detect_north_from_index(frame.get("bounds"), n_labels, line_points)
        records[frame_id] = north
        if north is None:
            warnings.append(f"north_input_required:{frame_id}")
    return {
        "version": "electrical-architecture-north-v15.2",
        "status": "PASS",
        "errors": [],
        "warnings": warnings,
        "records": records,
        "metrics": {
            "eligible_frames": len(records),
            "north_from_architecture": sum(1 for v in records.values() if v),
            "north_input_required": sum(1 for v in records.values() if not v),
        },
    }


def _fit(bounds, paper, margins=(12, 18, 12, 12)):
    pw, ph = paper; left, bottom, right, top = margins; x1, y1, x2, y2 = bounds
    aw = max(pw-left-right, 1e-6); ah = max(ph-bottom-top, 1e-6)
    w = max(x2-x1, 1e-9); h = max(y2-y1, 1e-9); scale = min(aw/w, ah/h)
    ox = left + (aw-w*scale)/2 - x1*scale; oy = bottom + (ah-h*scale)/2 - y1*scale
    return lambda p: (float(p[0])*scale+ox, float(p[1])*scale+oy)


def draw_north_on_final_file(path: str | Path, manifest: list[dict], frames: list[dict], records: dict, paper=(420.0, 297.0)) -> Dict[str, Any]:
    """Materialize a north arrow only for plan sheets with architectural evidence."""
    doc = ezdxf.readfile(str(path))
    if "ENGITOOLS-E-NORTH" not in doc.layers:
        doc.layers.add("ENGITOOLS-E-NORTH", color=7, lineweight=25)
    frame_map = {f.get("id"): f for f in frames}; arrows = 0
    plan_families = {"LIGHTING", "POWER", "FIRE_ALARM", "LOW_CURRENT", "GROUNDING"}
    for sheet in manifest:
        if sheet.get("family") not in plan_families or sheet.get("sheet_id") not in doc.layouts: continue
        source_frames = list(sheet.get("source_frame_ids") or [])
        if len(source_frames) != 1: continue
        frame_id = source_frames[0]; north = records.get(frame_id)
        if not north: continue
        layout = doc.layouts.get(sheet.get("sheet_id"))
        if any(e.dxftype() == "TEXT" and str(getattr(e.dxf, "layer", "")) == "ENGITOOLS-E-NORTH" and str(getattr(e.dxf, "text", "")) == "N" for e in layout):
            continue
        vx, vy = north["vector"]; px, py = -vy, vx
        cx, cy = paper[0]-24.0, paper[1]-24.0
        tip = (cx+vx*8.0, cy+vy*8.0); left = (cx+vx*5.5+px*1.5, cy+vy*5.5+py*1.5); right = (cx+vx*5.5-px*1.5, cy+vy*5.5-py*1.5)
        layout.add_line((cx, cy), (cx+vx*6.0, cy+vy*6.0), dxfattribs={"layer":"ENGITOOLS-E-NORTH"})
        layout.add_lwpolyline([tip, left, right, tip], dxfattribs={"layer":"ENGITOOLS-E-NORTH"})
        label = layout.add_text("N", dxfattribs={"layer":"ENGITOOLS-E-NORTH", "height":2.0, "rotation":north["angle_deg"]-90.0})
        label.set_placement((cx+vx*10.0-px*0.5, cy+vy*10.0-py*0.5)); arrows += 1
    doc.saveas(str(path))
    return {"status":"PASS", "errors":[], "arrows_drawn":arrows}
