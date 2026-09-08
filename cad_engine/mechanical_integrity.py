"""Fail-closed integrity checks for generated mechanical DXF artifacts.

This module validates the generated artifact, not merely the planner state. It
never repairs drawings or invents project facts. Any ambiguity in plan
identity, network topology, equipment identity, riser reconciliation,
calculation evidence or detail materialisation blocks release.
"""
from __future__ import annotations

from collections import Counter
from math import dist, hypot
from pathlib import Path
import re

import ezdxf
from ezdxf import bbox

REJECTED_PLAN_MARKERS = (
    "detail", "دیتیل", "section", "مقطع", "elevation", "نما",
    "parking", "پارکینگ", "slope", "شیب", "شيب", "lintel", "نعل درگاه",
    "door plan", "window plan", "پلان در", "پلان پنجره", "کف سازی", "کفسازی",
)

LEVEL_PATTERNS = (
    (r"(?:طبقه\s*)?همکف", "GROUND"),
    (r"(?:طبقه\s*)?اول", "FIRST"),
    (r"(?:طبقه\s*)?دوم", "SECOND"),
    (r"(?:طبقه\s*)?سوم", "THIRD"),
    (r"(?:طبقه\s*)?چهارم", "FOURTH"),
    (r"(?:طبقه\s*)?پنجم", "FIFTH"),
    (r"\bground(?:\s+floor)?\b", "GROUND"),
    (r"\bfirst(?:\s+floor)?\b", "FIRST"),
    (r"\bsecond(?:\s+floor)?\b", "SECOND"),
    (r"\bthird(?:\s+floor)?\b", "THIRD"),
    (r"\bfourth(?:\s+floor)?\b", "FOURTH"),
    (r"\bfifth(?:\s+floor)?\b", "FIFTH"),
)

NETWORK_FAMILY_TOKENS = {
    "WATER": ("COLD_WATER", "HOT_WATER", "-WATER", "WATER-"),
    "SANITARY_VENT": ("SANITARY", "VENT"),
    "GAS": ("-GAS", "GAS-"),
    "EXHAUST": ("EXHAUST",),
}

EQUIPMENT_NAMES = ("ENGI_AC_INDOOR", "ENGI_AC_OUTDOOR", "ENGI_RADIATOR")
DETAIL_ID_RE = re.compile(r"\bD-[A-Z]{1,4}-\d{2}\b", re.I)


def _norm(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")).strip()


def _text_value(entity) -> str:
    try:
        if entity.dxftype() == "TEXT":
            return _norm(entity.dxf.text)
        if entity.dxftype() == "MTEXT":
            return _norm(entity.plain_text())
    except Exception:
        return ""
    return ""


def _entity_center(entity):
    try:
        ex = bbox.extents([entity], fast=True)
        if ex.has_data:
            return ((float(ex.extmin.x) + float(ex.extmax.x)) / 2.0,
                    (float(ex.extmin.y) + float(ex.extmax.y)) / 2.0)
    except Exception:
        pass
    try:
        p = entity.dxf.insert
        return float(p.x), float(p.y)
    except Exception:
        return None


def _area(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    a, b, c, d = map(float, value)
    return min(a, c), min(b, d), max(a, c), max(b, d)


def _inside(point, area) -> bool:
    return bool(point and area and area[0] <= point[0] <= area[2] and area[1] <= point[1] <= area[3])


def _diag(area) -> float:
    return hypot(area[2] - area[0], area[3] - area[1]) if area else 0.0


def _canonical_family(value) -> str:
    key = _norm(value).upper()
    aliases = {
        "WATER_SUPPLY": "WATER", "WATER": "WATER",
        "SANITARY_VENT": "SANITARY_VENT", "SANITARY": "SANITARY_VENT",
        "VENT": "SANITARY_VENT", "GAS": "GAS",
        "VENTILATION_EXHAUST": "EXHAUST", "EXHAUST": "EXHAUST",
        "COOLING": "SPLIT_AC", "SPLIT_AC": "SPLIT_AC",
        "HEATING": "HEATING", "ROOF_RAINWATER": "ROOF", "ROOF": "ROOF",
    }
    return aliases.get(key, key)


def _plan_role(text: str) -> str:
    s = _norm(text)
    low = s.lower()
    if not s:
        return "OTHER"
    if any(marker in low for marker in REJECTED_PLAN_MARKERS):
        return "REJECTED"
    if "roof plan" in low or "پلان بام" in s or ("بام" in s and "پلان" in s):
        return "ROOF"
    if "پلان معماری" in s or "پلان مبلمان" in s or "architectural plan" in low or "furniture plan" in low:
        return "OCCUPIED"
    if "floor plan" in low:
        return "OCCUPIED"
    return "OTHER"


def _level_signature(text: str):
    s = _norm(text)
    low = s.lower()
    if _plan_role(s) == "ROOF":
        return "ROOF"
    found = []
    for pattern, name in LEVEL_PATTERNS:
        target = low if "\\b" in pattern else s
        if re.search(pattern, target, re.I):
            found.append(name)
    if found:
        # A legitimate explicit typical title may name several levels. Keep the
        # whole group as one signature rather than splitting it into phantom plans.
        return "+".join(dict.fromkeys(found))
    if _plan_role(s) == "OCCUPIED":
        return "OCCUPIED_UNSPECIFIED"
    return None


def _manifest_rows(report):
    composition = (report or {}).get("composition") or {}
    rows = composition.get("manifest") or []
    if isinstance(rows, dict):
        rows = rows.get("sheets") or rows.get("manifest") or []
    return [row for row in rows if isinstance(row, dict)]


def _board_descriptors(report):
    composition = (report or {}).get("composition") or {}
    boards = composition.get("boards") or {}
    output = []
    for row in _manifest_rows(report):
        purpose = _norm(row.get("purpose") or "PLAN").upper()
        family = _canonical_family(row.get("family") or row.get("drawing_family") or row.get("system"))
        board_id = str(row.get("old_sheet") or row.get("board_id") or "")
        board = boards.get(board_id) if isinstance(boards, dict) else None
        area = _area((board or {}).get("plan_area"))
        if purpose != "PLAN" or not area:
            continue
        output.append({
            "code": str(row.get("approved_code") or row.get("code") or row.get("sheet") or board_id),
            "board_id": board_id,
            "family": family,
            "area": area,
        })
    return output


def _entities_in_area(msp, area):
    for entity in msp:
        point = _entity_center(entity)
        if _inside(point, area):
            yield entity


def _polyline_length(entity) -> float:
    try:
        if entity.dxftype() == "LINE":
            a, b = entity.dxf.start, entity.dxf.end
            return dist((float(a.x), float(a.y)), (float(b.x), float(b.y)))
        if entity.dxftype() == "LWPOLYLINE":
            pts = [(float(x), float(y)) for x, y, *_ in entity.get_points("xy")]
        elif entity.dxftype() == "POLYLINE":
            pts = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
        else:
            return 0.0
        return sum(dist(a, b) for a, b in zip(pts, pts[1:]))
    except Exception:
        return 0.0


def _entity_span(entity) -> float:
    try:
        ex = bbox.extents([entity], fast=True)
        if not ex.has_data:
            return 0.0
        return max(float(ex.extmax.x - ex.extmin.x), float(ex.extmax.y - ex.extmin.y))
    except Exception:
        return 0.0


def _layer_matches_family(layer: str, family: str) -> bool:
    upper = str(layer or "").upper()
    if not upper.startswith("ENGITOOLS-M-"):
        return False
    return any(token in upper for token in NETWORK_FAMILY_TOKENS.get(family, ()))


def _cluster_count(points, tolerance):
    clusters = []
    for point in points:
        match = next((c for c in clusters if dist(point, c[0]) <= tolerance), None)
        if match is None:
            clusters.append([point, 1])
        else:
            match[1] += 1
    return len(clusters)


def _scope_errors(all_text: str, answers: dict) -> list[str]:
    errors = []
    a = answers or {}
    sanitary_basis = " ".join(str(a.get(k) or "") for k in ("sanitary_discharge", "sewage_disposal", "wastewater_disposal")).lower()
    septic_required = bool(a.get("septic_required")) or "septic" in sanitary_basis or "سپتیک" in sanitary_basis
    if septic_required and not ("SEPTIC" in all_text.upper() or "سپتیک" in all_text):
        errors.append("required_system_missing:SEPTIC")
    fire_required = bool(a.get("fire_water_required") or a.get("fire_fighting_required"))
    if fire_required and not any(token in all_text.upper() for token in ("FIRE WATER", "FIRE PUMP", "FIRE TANK")):
        errors.append("required_system_missing:FIRE_WATER")
    return errors


def validate_generated_mechanical_integrity(path, report=None, answers=None) -> dict:
    """Reopen and validate the exact generated mechanical DXF.

    The gate is intentionally fail-closed. It never edits the drawing and it
    never converts missing evidence into a project fact.
    """
    path = Path(path)
    errors, warnings = [], []
    metrics = {"boards": {}, "equipment": {}, "details": {}}
    if not path.exists():
        return {"version": "generated-mechanical-integrity/1.0", "status": "FAIL",
                "errors": ["generated_dxf_missing"], "warnings": [], "metrics": metrics}
    try:
        doc = ezdxf.readfile(path)
    except Exception as exc:
        return {"version": "generated-mechanical-integrity/1.0", "status": "FAIL",
                "errors": [f"generated_dxf_reopen_failed:{exc}"], "warnings": [], "metrics": metrics}

    msp = doc.modelspace()
    descriptors = _board_descriptors(report or {})
    if not descriptors:
        warnings.append("board_geometry_contract_unavailable")

    for board in descriptors:
        code, family, area = board["code"], board["family"], board["area"]
        entities = list(_entities_in_area(msp, area))
        texts = [_text_value(e) for e in entities if e.dxftype() in {"TEXT", "MTEXT"}]
        titles = [t for t in texts if _plan_role(t) in {"OCCUPIED", "ROOF", "REJECTED"}]
        level_signatures = sorted(set(filter(None, (_level_signature(t) for t in titles if _plan_role(t) in {"OCCUPIED", "ROOF"}))))
        rejected = [t for t in titles if _plan_role(t) == "REJECTED"]
        if len(level_signatures) > 1:
            errors.append(f"{code}:mixed_primary_plan_titles:" + ",".join(level_signatures))
        if rejected and any(_plan_role(t) == "OCCUPIED" for t in titles):
            errors.append(f"{code}:rejected_frame_mixed_with_occupied_plan")

        diag = max(_diag(area), 1e-9)
        route_entities = [
            e for e in entities
            if e.dxftype() in {"LINE", "LWPOLYLINE", "POLYLINE"}
            and _layer_matches_family(getattr(e.dxf, "layer", ""), family)
        ]
        total_length = sum(_polyline_length(e) for e in route_entities)
        max_span = max((_entity_span(e) for e in route_entities), default=0.0)
        if family in NETWORK_FAMILY_TOKENS and len(route_entities) >= 2:
            if max_span < diag * 0.02 and total_length < diag * 0.08:
                errors.append(f"{code}:degenerate_network_topology:{family}")
        metrics["boards"][code] = {
            "family": family,
            "level_signatures": level_signatures,
            "rejected_plan_titles": len(rejected),
            "route_entity_count": len(route_entities),
            "route_length": round(total_length, 6),
            "max_route_span": round(max_span, 6),
            "board_diagonal": round(diag, 6),
        }

    inserts = list(msp.query("INSERT"))
    by_name = Counter(str(e.dxf.name).upper() for e in inserts)
    idu = by_name.get("ENGI_AC_INDOOR", 0)
    odu = by_name.get("ENGI_AC_OUTDOOR", 0)
    schedule_text = "\n".join(_text_value(e) for e in msp.query("TEXT MTEXT"))
    if idu and not odu:
        errors.append("cooling:idu_without_outdoor_unit")
    if ("AC-O-" in schedule_text.upper() or "OUTDOOR UNIT" in schedule_text.upper()) and not odu:
        errors.append("cooling:schedule_outdoor_unit_without_plan_entity")

    whole_diag = 1.0
    try:
        ex = bbox.extents(msp, fast=True)
        if ex.has_data:
            whole_diag = max(hypot(float(ex.extmax.x-ex.extmin.x), float(ex.extmax.y-ex.extmin.y)), 1.0)
    except Exception:
        pass
    tol = whole_diag * 0.00015
    for name in EQUIPMENT_NAMES:
        points = []
        for e in inserts:
            if str(e.dxf.name).upper() == name:
                try:
                    points.append((float(e.dxf.insert.x), float(e.dxf.insert.y)))
                except Exception:
                    pass
        unique = _cluster_count(points, tol) if points else 0
        if len(points) >= 4 and unique / len(points) < 0.5:
            errors.append(f"equipment_coordinate_collapse:{name}:raw={len(points)}:unique={unique}")
        metrics["equipment"][name] = {"raw": len(points), "unique": unique}

    upper_text = schedule_text.upper()
    zero_branch = bool(re.search(r"BRANCHES\s*(?:\||=)\s*0\b", upper_text))
    passing_riser = bool(re.search(r"STATUS\s*:\s*(?:TRUE|PASS)\b", upper_text))
    if zero_branch and passing_riser:
        errors.append("riser:zero_branches_marked_pass")

    detail_ids = [m.group(0).upper() for m in DETAIL_ID_RE.finditer(upper_text)]
    detail_counts = Counter(detail_ids)
    has_register = "DETAIL REGISTER" in upper_text
    missing_materialized = sorted(detail_id for detail_id, count in detail_counts.items() if count < 2)
    if has_register and len(detail_counts) >= 3 and missing_materialized:
        errors.append("detail_register_not_materialized:" + ",".join(missing_materialized))
    metrics["details"] = {"registered_ids": len(detail_counts), "single_occurrence_ids": missing_materialized}

    a = answers or {}
    pressure_known = any(a.get(key) not in (None, "") for key in ("water_pressure", "water_inlet_pressure", "utility_water_pressure"))
    numeric_utility_pressure = bool(re.search(r"UTILITY\s+PRESSURE[^\n]{0,40}\d", upper_text))
    if numeric_utility_pressure and not pressure_known:
        errors.append("calculation_uses_unverified_utility_pressure")
    errors.extend(_scope_errors(schedule_text, a))

    try:
        auditor = doc.audit()
        audit_errors = len(auditor.errors)
    except Exception:
        audit_errors = 1
    if audit_errors:
        errors.append(f"dxf_audit_errors:{audit_errors}")
    metrics["dxf_audit_errors"] = audit_errors

    return {
        "version": "generated-mechanical-integrity/1.0",
        "status": "PASS" if not errors else "FAIL",
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "metrics": metrics,
        "policy": "FAIL_CLOSED_NO_PROJECT_FACT_FABRICATION",
        "exact_file_reopened": True,
    }
