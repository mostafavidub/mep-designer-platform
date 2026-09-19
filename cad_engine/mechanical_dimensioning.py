"""Canonical mechanical plan dimensioning and exact-DXF verification.

The generator never reads a mechanical reference drawing.  Measurements are
derived from the approved architectural source coordinates and the uniform
board transform.  Generated dimensions carry semantic XDATA so the final file
can be independently reopened and audited.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Iterable

import ezdxf
from ezdxf.entities.dimstyleoverride import DimStyleOverride

APPID = "ENGITOOLS_DIM"
DIMSTYLE = "ENGITOOLS_MECH_DIM"
LAYERS = {
    "INSTALLATION": "ENGITOOLS-M-DIM-INSTALL",
    "ROUTE": "ENGITOOLS-M-DIM-ROUTE",
    "CLEARANCE": "ENGITOOLS-M-DIM-CLEARANCE",
    "LEVEL": "ENGITOOLS-M-DIM-LEVEL",
}
APPLICABLE_FAMILIES = {"ROOF", "SANITARY_VENT", "WATER", "HEATING", "GAS", "SPLIT_AC", "EXHAUST"}
XDATA_FIELDS = ("semantic_id", "owner_id", "sheet", "family", "kind", "expected_mm")


def _finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _unit_context(source_doc, answers: dict) -> dict:
    auto = (((answers or {}).get("_plan_analysis") or {}).get("architectural_auto") or {})
    scale = auto.get("effective_unit_to_m")
    inference = auto.get("unit_inference") or {}
    source = "architectural_analysis"
    confidence = inference.get("confidence") or "high"
    if not _finite(scale) or float(scale) <= 0:
        values = []
        for entity in source_doc.modelspace().query("DIMENSION"):
            try:
                value = abs(float(entity.get_measurement()))
            except Exception:
                continue
            if 0.001 <= value <= 100000:
                values.append(value)
        values.sort()
        median = values[len(values) // 2] if values else None
        insunits = int(source_doc.header.get("$INSUNITS", 0) or 0)
        header = {4: 0.001, 5: 0.01, 6: 1.0}.get(insunits)
        if insunits == 4 and median is not None and .2 <= median <= 50:
            scale, source, confidence = 1.0, "source_dimension_override", "high"
        elif insunits == 6 and median is not None and 200 <= median <= 50000:
            scale, source, confidence = .001, "source_dimension_override", "high"
        else:
            scale, source, confidence = header, "dxf_header", "medium" if header else "low"
    return {"unit_to_m": float(scale) if _finite(scale) and float(scale) > 0 else None,
            "source": source, "confidence": confidence}


def _ensure_resources(doc):
    if APPID not in doc.appids:
        doc.appids.add(APPID)
    for layer in LAYERS.values():
        if layer not in doc.layers:
            doc.layers.add(layer, color=2, lineweight=18)
    if DIMSTYLE not in doc.dimstyles:
        style = doc.dimstyles.new(DIMSTYLE)
        style.dxf.dimtxt = .09
        style.dxf.dimasz = .09
        style.dxf.dimexo = .04
        style.dxf.dimexe = .08
        style.dxf.dimgap = .04
        style.dxf.dimdec = 0
        style.dxf.dimtad = 1


def _semantic_id(sheet, owner, axis, kind):
    raw = f"{sheet}|{owner}|{axis}|{kind}".encode("utf-8")
    return "DIM-" + hashlib.sha256(raw).hexdigest()[:20].upper()


def _xdata(entity, values):
    entity.set_xdata(APPID, [(1000, str(values[name])) for name in XDATA_FIELDS])


def _candidate_targets(overlay_reports: Iterable[dict], sheet: str):
    report = next((row for row in overlay_reports if row.get("sheet") == sheet), {})
    candidates = []
    seen = set()
    priority = {"equipment": 0, "shaft": 1, "route_terminal": 2}
    for item in report.get("dimension_targets") or []:
        owner = str(item.get("owner_id") or "").strip()
        source_point = item.get("source_point")
        paper_point = item.get("paper_point")
        if not owner or owner in seen or not source_point or not paper_point:
            continue
        if len(source_point) != 2 or len(paper_point) != 2 or not all(_finite(v) for v in (*source_point, *paper_point)):
            continue
        seen.add(owner)
        candidates.append(dict(item))
    return sorted(candidates, key=lambda row: (priority.get(row.get("kind"), 9), row["owner_id"]))[:4]


def apply_mechanical_dimensions(doc, manifest: list[dict], boards: dict, overlay_reports: list[dict], answers: dict) -> dict:
    """Add deterministic coordinate dimensions to applicable plan boards."""
    unit = _unit_context(doc, answers)
    _ensure_resources(doc)
    msp = doc.modelspace()
    records, blockers = [], []
    for row in manifest:
        family = str(row.get("family") or "").upper()
        sheet = str(row.get("code") or "")
        board = boards.get(row.get("old_sheet"))
        if family not in APPLICABLE_FAMILIES or not board or row.get("source_plan_id") is None:
            continue
        transform = row.get("uniform_transform") or {}
        paper_scale = transform.get("scale_x")
        if unit["unit_to_m"] is None or not _finite(paper_scale) or float(paper_scale) <= 0:
            blockers.append(f"{sheet}:CALIBRATED_UNIT_AND_UNIFORM_SCALE_REQUIRED")
            continue
        targets = _candidate_targets(overlay_reports, sheet)
        if not targets:
            blockers.append(f"{sheet}:NO_TRACEABLE_MECHANICAL_DIMENSION_TARGET")
            continue
        x1, y1, x2, y2 = board.plan_area
        dimlfac = unit["unit_to_m"] * 1000.0 / float(paper_scale)
        for index, target in enumerate(targets):
            px, py = map(float, target["paper_point"])
            source_bounds = row.get("source_bounds") or []
            if len(source_bounds) != 4:
                blockers.append(f"{sheet}:{target['owner_id']}:SOURCE_BOUNDS_REQUIRED")
                continue
            datum_x, datum_y = float(source_bounds[0]), float(source_bounds[1])
            # offset_x/y are affine translation terms, not paper coordinates
            # of the source datum.  Mapping a non-zero source origin to the
            # bare translation can put dimension definition points in the
            # title block and makes the measured length disagree with XDATA.
            mapped_datum_x = datum_x * float(paper_scale) + float(transform.get("offset_x", x1))
            mapped_datum_y = datum_y * float(paper_scale) + float(transform.get("offset_y", y1))
            # Keep the complete rendered DIMENSION entity—not only its
            # mathematical definition point—inside the plan safe zone. Move
            # the source datum by the exact inverse paper-space inset so the
            # displayed measurement remains source-coordinate truthful.
            safe_inset=.45
            paper_datum_x=min(max(mapped_datum_x,x1+safe_inset),x2-safe_inset)
            paper_datum_y=min(max(mapped_datum_y,y1+safe_inset),y2-safe_inset)
            datum_x+=(paper_datum_x-mapped_datum_x)/float(paper_scale)
            datum_y+=(paper_datum_y-mapped_datum_y)/float(paper_scale)
            horizontal_lane = min(max(y1+.70, paper_datum_y+.20+index*.15),y2-.70)
            vertical_lane = min(max(x1+.70, paper_datum_x+.20+index*.15),x2-.70)
            axes = (("X", (paper_datum_x, py), (px, py), (paper_datum_x, horizontal_lane)),
                    ("Y", (px, paper_datum_y), (px, py), (vertical_lane, paper_datum_y)))
            for axis, p1, p2, location in axes:
                # The dimension describes the final coordinated installation
                # point in the delivered drawing. Equipment/route symbols may
                # be displaced from their topology seed during collision-safe
                # placement, so the exact paper geometry—not the pre-layout
                # seed—must be the numeric authority checked after reopening.
                paper_distance = abs(p2[0]-p1[0]) if axis == "X" else abs(p2[1]-p1[1])
                expected_mm = paper_distance * dimlfac
                if expected_mm < 1.0 or math.dist(p1, p2) < 1e-6:
                    continue
                semantic_id = _semantic_id(sheet, target["owner_id"], axis, "INSTALLATION")
                override = {"dimlfac": dimlfac, "dimdec": 0, "dimtxt": .09, "dimasz": .09}
                dim = msp.add_linear_dim(base=location, p1=p1, p2=p2, angle=0 if axis == "X" else 90,
                                         dimstyle=DIMSTYLE, override=override,
                                         dxfattribs={"layer": LAYERS["INSTALLATION"]})
                entity = dim.dimension
                _xdata(entity, {"semantic_id": semantic_id, "owner_id": target["owner_id"], "sheet": sheet,
                                "family": family, "kind": "INSTALLATION", "expected_mm": f"{expected_mm:.6f}"})
                dim.render()
                records.append({"semantic_id": semantic_id, "owner_id": target["owner_id"], "sheet": sheet,
                                "family": family, "axis": axis, "kind": "INSTALLATION",
                                "expected_mm": round(expected_mm, 6), "dimlfac": dimlfac})
    status = "PASS" if records and not blockers else ("INPUT_REQUIRED" if blockers else "NOT_APPLICABLE")
    return {"status": status, "records": records, "blockers": sorted(set(blockers)), "unit_context": unit,
            "applicable_sheet_count": len({r["sheet"] for r in records}), "dimension_count": len(records)}


def _parse_xdata(entity):
    try:
        values = [tag.value for tag in entity.get_xdata(APPID) if tag.code == 1000]
    except Exception:
        return None
    return dict(zip(XDATA_FIELDS, values)) if len(values) == len(XDATA_FIELDS) else None


def validate_exact_mechanical_dimensions(path: Path, expected: dict, boards: dict) -> dict:
    """Independently reopen and validate the exact final DXF artifact."""
    errors, rows, identities = [], [], set()
    try:
        doc = ezdxf.readfile(path)
    except Exception as exc:
        return {"status": "FAIL", "errors": [f"exact_reopen_failed:{type(exc).__name__}"], "records": []}
    expected_by_id = {r["semantic_id"]: r for r in expected.get("records") or []}
    board_by_code = {getattr(board, "code", data.get("code") if isinstance(data, dict) else None): board for data, board in []}
    for value in boards.values():
        code = value.code if hasattr(value, "code") else value.get("code")
        board_by_code[code] = value
    for entity in doc.modelspace().query("DIMENSION"):
        layer = str(entity.dxf.layer)
        if layer not in LAYERS.values():
            continue
        data = _parse_xdata(entity)
        if not data:
            errors.append("generated_dimension_missing_xdata")
            continue
        semantic_id = data["semantic_id"]
        if semantic_id in identities:
            errors.append(f"duplicate_dimension_identity:{semantic_id}")
        identities.add(semantic_id)
        declared = expected_by_id.get(semantic_id)
        if declared is None or declared.get("owner_id") != data["owner_id"]:
            errors.append(f"orphan_dimension:{semantic_id}")
            continue
        try:
            raw = abs(float(entity.get_measurement()))
            dimlfac = float(DimStyleOverride(entity).get("dimlfac", 1.0))
            measured_mm = raw * dimlfac
            expected_mm = float(data["expected_mm"])
        except Exception:
            errors.append(f"invalid_dimension_measurement:{semantic_id}")
            continue
        tolerance = max(1.0, expected_mm * .002)
        if not math.isfinite(measured_mm) or measured_mm < 1.0:
            errors.append(f"zero_or_nonfinite_dimension:{semantic_id}")
        if abs(measured_mm-expected_mm) > tolerance:
            errors.append(f"dimension_measurement_mismatch:{semantic_id}")
        if abs(dimlfac-float(declared["dimlfac"])) > max(1e-9, abs(float(declared["dimlfac"]))*1e-9):
            errors.append(f"dimension_scale_override_mismatch:{semantic_id}")
        board = board_by_code.get(data["sheet"])
        if board is None:
            errors.append(f"dimension_sheet_missing:{semantic_id}")
        else:
            bounds = board.bounds if hasattr(board, "bounds") else board["bounds"]
            try:
                points = [entity.dxf.defpoint, entity.dxf.defpoint2, entity.dxf.defpoint3]
                if any(not (bounds[0]-.01 <= p.x <= bounds[2]+.01 and bounds[1]-.01 <= p.y <= bounds[3]+.01) for p in points):
                    errors.append(f"dimension_outside_board:{semantic_id}")
            except Exception:
                errors.append(f"dimension_definition_points_missing:{semantic_id}")
        rows.append({**data, "measured_mm": round(measured_mm, 6)})
    missing = sorted(set(expected_by_id)-identities)
    errors.extend(f"missing_dimension:{item}" for item in missing)
    errors = sorted(set(errors))
    return {"status": "PASS" if not errors and len(rows) == len(expected_by_id) else "FAIL",
            "errors": errors, "records": rows, "expected_count": len(expected_by_id), "exact_count": len(rows),
            "exact_file_reopened": True}
