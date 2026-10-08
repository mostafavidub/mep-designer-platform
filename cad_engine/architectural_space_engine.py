"""Canonical deterministic-first architectural-space understanding.

This module owns architectural geometry and semantics.  Downstream disciplines
consume its model; they must not reconstruct rooms independently.  Exact DXF
facts are retained as evidence and unresolved facts fail closed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
import json
import math
import os
import re
import time

import ezdxf
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import nearest_points, polygonize, unary_union
from shapely.strtree import STRtree

from .architectural_topology_quality import (
    _axis,
    building_envelope_from_walls,
    canonical_enclosure_continuity,
    canonical_space_subdivision,
    classify_internal_wall_gaps,
    evidence_based_building_envelope,
    reconstruct_canonical_walls,
    source_supported_endpoint_closures,
    virtual_opening_closures,
)
from .architectural_gap_review import (
    apply_review_decisions,
    build_review_manifest,
    validate_review_decisions,
)
from .pre_topology_object_classifier import (
    annotate_source_roles,
    classify_source_record,
    excludes_from_wall_admission,
    repeated_compact_column_handles,
    standardize_source_records,
)

from .architecture_boundary_evidence import physical_boundary_evidence
from .architecture_enclosure_candidates import reconcile_enclosure_candidates
from .architecture_text_evidence import (
    bind_text_hosts,
    build_title_block_fields,
    extract_text_evidence,
    functional_composition,
    legacy_text_records,
    normalize_text as canonical_normalize_text,
    semantic_candidates as canonical_semantic_candidates,
    SPACE_ONTOLOGY as CANONICAL_SPACE_ONTOLOGY,
)

SCHEMA = "canonical-architectural-model/1.0"
STATUSES = {"VERIFIED", "HIGH_CONFIDENCE", "AMBIGUOUS", "INPUT_REQUIRED", "CONFLICT", "REJECTED"}

SPACE_ONTOLOGY = CANONICAL_SPACE_ONTOLOGY

OBJECT_TERMS = {
    "bed": ("bed", "تخت"), "wardrobe": ("wardrobe", "closet", "کمد"),
    "sink": ("sink", "سینک"), "stove": ("stove", "range", "اجاق"),
    "wc": ("toilet", "wc", "توالت", "فرنگی"), "shower": ("shower", "دوش"),
    "dining_table": ("dining", "table", "میز ناهار"), "car": ("car", "vehicle", "خودرو"),
    "stair": ("stair", "پله"), "elevator": ("elevator", "lift", "آسانسور"),
    "cabinet": ("cabinet", "کابینت"),
    "door": ("door", "در ورودی", "درب"),
    "window": ("window", "پنجره"),
}

FRAME_TYPES = {"PRIMARY_FLOOR", "ROOF", "SITE", "FURNITURE_PLAN", "SECTION", "ELEVATION", "DETAIL", "SCHEDULE", "LEGEND", "UNKNOWN"}
NON_BOUNDARY_TOKENS = ("dim", "dimension", "اندازه", "text", "anno", "hatch", "furn", "furniture", "مبلمان", "grid", "axis", "محور",
                       "door", "درب", "window", "پنجره", "opening")
WALL_TOKENS = ("wall", "a-wall", "دیوار", "partition")


def normalize_text(value):
    return canonical_normalize_text(value)


def _stable_id(prefix, payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{sha256(raw.encode('utf-8')).hexdigest()[:16].upper()}"


def _round_points(points, precision=6):
    rows = [(round(float(x), precision), round(float(y), precision)) for x, y in points]
    if rows and rows[0] == rows[-1]: rows.pop()
    if not rows: return rows
    # Make ring identity independent of starting vertex and direction.
    rotations = []
    for seq in (rows, list(reversed(rows))):
        rotations.extend(seq[i:] + seq[:i] for i in range(len(seq)))
    return min(rotations)


def _space_polygon(space):
    return Polygon(space["polygon"], space.get("interior_rings") or [])


def _entity_text(entity):
    try:
        if entity.dxftype() == "TEXT": return str(entity.dxf.text or "")
        if entity.dxftype() == "MTEXT": return str(entity.plain_text() or "")
        if entity.dxftype() in {"ATTRIB", "ATTDEF"}: return str(entity.dxf.text or "")
    except Exception:
        return ""
    return ""


def _point(entity, attr="insert"):
    try:
        value = getattr(entity.dxf, attr)
        return (float(value.x), float(value.y))
    except Exception:
        return None


def _handle(entity):
    return str(getattr(entity.dxf, "handle", "") or "")


def _layer(entity):
    return str(getattr(entity.dxf, "layer", "0") or "0")


def _classify_text(text):
    candidates = canonical_semantic_candidates(text)
    return (candidates[0], normalize_text(text)) if candidates else (None, None)


def _is_space_label_record(text):
    candidates=text.get("role_candidates")
    if candidates is None:  # Compatibility for direct synthetic helper inputs.
        return bool(canonical_semantic_candidates(text.get("text")))
    roles={row.get("role") for row in candidates}
    document={"PLAN_TITLE","DRAWING_TYPE_TITLE","LEVEL_TITLE","SECTION_ELEVATION_LABEL",
              "PROJECT_METADATA","DRAWING_NUMBER","REVISION","DATE","SCALE_TEXT",
              "DISCIPLINE","DESIGNER_OR_COMPANY_METADATA"}
    return "SPACE_LABEL" in roles and not roles.intersection(document)


def _classify_object(name, layer):
    text = normalize_text(f"{name} {layer}")
    found = []
    for kind, aliases in OBJECT_TERMS.items():
        if any(normalize_text(alias) in text for alias in aliases): found.append(kind)
    return sorted(set(found))


def _boundary_geometry_decision(layer, source_block, entity_type):
    """Conservative wall-boundary admission policy.

    Exploded furniture, sanitary fixtures, SHX glyphs and door swings are a
    major source of phantom cells.  Top-level straight/polyline drafting can
    participate unless explicitly non-architectural.  Nested geometry and
    curves need positive wall evidence.
    """
    context=normalize_text(f"{layer} {source_block or ''}")
    if any(token in context for token in NON_BOUNDARY_TOKENS): return False,"NON_BOUNDARY_LAYER"
    wall_evidence=any(token in context for token in WALL_TOKENS)
    if source_block and not wall_evidence: return False,"NESTED_BLOCK_EXCLUDED"
    if entity_type in {"ARC","SPLINE"} and not wall_evidence: return False,"CURVE_WITHOUT_WALL_EVIDENCE"
    return True,"SOURCE_GEOMETRY_RETAINED"


def _is_boundary_geometry(layer, source_block, entity_type):
    return _boundary_geometry_decision(layer,source_block,entity_type)[0]


def _unit_scale(insunits):
    # ezdxf/AutoCAD INSUNITS: 4 mm, 5 cm, 6 m.
    return {4: .001, 5: .01, 6: 1.0}.get(int(insunits or 0))


def _calibrate_scale(source, frames, dimensions):
    """Resolve the effective drawing scale from independent CAD evidence.

    Consultant files frequently retain an incorrect INSUNITS header after a
    unit conversion.  Frame spans and native DIMENSION measurements provide an
    independent signal.  A disagreement is retained as explicit provenance;
    it is never silently presented as PROJECT_INPUT.
    """
    declared = source.get("declared_metres_per_unit")
    relevant = [f for f in frames if f.get("scope_relevance") == "MECHANICAL_AUTHORITY" and f.get("bounds")]
    spans = [max(f["bounds"][2] - f["bounds"][0], f["bounds"][3] - f["bounds"][1]) for f in relevant]
    measurements = sorted(float(d["measurement"]) for d in dimensions if 0 < float(d.get("measurement") or 0) < 1e7)
    votes = []
    if spans:
        span = sorted(spans)[len(spans)//2]
        if 5 <= span <= 200: votes.append((1.0, "authoritative_frame_span"))
        elif 500 <= span <= 200000: votes.append((.001, "authoritative_frame_span"))
    if measurements:
        measurement = measurements[len(measurements)//2]
        if .1 <= measurement <= 50: votes.append((1.0, "native_dimension_distribution"))
        elif 100 <= measurement <= 50000: votes.append((.001, "native_dimension_distribution"))
    counts = Counter(scale for scale, _ in votes)
    inferred = counts.most_common(1)[0][0] if counts else None
    effective = inferred or declared
    agreeing = [reason for scale, reason in votes if scale == effective]
    status = "DECLARED"
    conflict = False
    if inferred is not None:
        status = "INFERRED"
        conflict = declared is not None and not math.isclose(inferred, declared)
    return {**source, "metres_per_unit": effective,
            "unit_calibration": {"status": status, "declared_metres_per_unit": declared,
                                 "effective_metres_per_unit": effective, "evidence": agreeing,
                                 "declared_unit_conflict": conflict,
                                 "confidence": 1.0 if len(set(reason for _, reason in votes)) >= 2 else .85}}


def _adaptive_tolerance(lines, scale):
    lengths = sorted(line.length for line in lines if line.length > 0)
    if not lengths: return None
    median = lengths[len(lengths)//2]
    # 0.2% of a typical segment, bounded to 2–50 mm in project metres.
    metres = max(.002, min(.05, median * (scale or 1.0) * .002))
    return metres / (scale or 1.0)


@dataclass(frozen=True)
class VisionCandidate:
    candidate_type: str
    region: tuple[float, float, float, float]
    confidence: float
    evidence: tuple[str, ...]
    uncertainty: str = ""

    def as_evidence(self, *, frame_id, region_id):
        return {"frame_id": frame_id, "region_id": region_id,
                "candidate_semantic_type": self.candidate_type,
                "objects_seen": [], "text_seen": [],
                "reason": list(self.evidence), "confidence": float(self.confidence),
                "ambiguity": self.uncertainty,
                "suggested_classification": self.candidate_type,
                "authority": "SUPPORTING_EVIDENCE_ONLY"}


class VisionAdapter(Protocol):
    def analyze(self, *, image_path: str, frame_id: str, regions: list[dict],
                context: dict | None = None) -> list[VisionCandidate]: ...


class NoVisionAdapter:
    def analyze(self, *, image_path: str, frame_id: str, regions: list[dict],
                context: dict | None = None) -> list[VisionCandidate]:
        return []


def _primitive_points(record):
    if record.get("start") and record.get("end"):
        return [record["start"], record["end"]]
    return list(record.get("points") or [])


def _opening_candidates(extracted, source_hash):
    """Return explicit opening evidence without pretending every symbol is valid.

    Inserts are preferred.  Exploded line/arc symbols remain candidates and
    require a host-wall/topology match before acceptance.
    """
    rows = []
    for obj in extracted["objects"]:
        if obj.get("pre_topology_object_class") in {"DETAIL_GRAPHIC","SECTION_CUT","SHEET_FRAME"}: continue
        kinds = set(obj.get("object_types") or [])
        if not kinds.intersection({"door", "window"}):
            continue
        for kind in sorted(kinds.intersection({"door", "window"})):
            rows.append({"opening_id": _stable_id(kind.upper(), [source_hash, obj.get("handle"), obj.get("point")]),
                         "kind": kind, "geometry": {"point": obj.get("point"), "bounds": obj.get("bounds")},
                         "source_handle": obj.get("handle"), "evidence": [{"class": "CAD_BLOCK", "name": obj.get("name"), "layer": obj.get("layer")}],
                         "status": "CANDIDATE"})
    for primitive in extracted["primitives"]:
        if primitive.get("pre_topology_object_class") in {"DETAIL_GRAPHIC","SECTION_CUT","SHEET_FRAME"}: continue
        if primitive.get("source_block"):
            continue
        layer = normalize_text(primitive.get("layer"))
        kind = "door" if "door" in layer or "درب" in layer else ("window" if "window" in layer or "پنجره" in layer else None)
        pts = _primitive_points(primitive)
        if not kind or len(pts) < 2:
            continue
        rows.append({"opening_id": _stable_id(kind.upper(), [source_hash, primitive.get("handle"), _round_points(pts)]),
                     "kind": kind, "geometry": {"points": pts}, "source_handle": primitive.get("handle"),
                     "evidence": [{"class": "CAD_LAYER_SYMBOL", "layer": primitive.get("layer")}], "status": "CANDIDATE"})
    unique = {row["opening_id"]: row for row in rows}
    return [unique[key] for key in sorted(unique)]


def _geometric_door_candidates(extracted, wall_lines, source_hash, tolerance, metres_per_unit, frame_bounds=None):
    """Recognize anonymous doors only from combined independent evidence."""
    tol=max(float(tolerance or .001)*5,1e-8); scale=metres_per_unit or 1.0
    frame_clip=box(*frame_bounds) if frame_bounds else None; leaves=[]
    for primitive in extracted["primitives"]:
        if primitive.get("pre_topology_object_class") in {"DETAIL_GRAPHIC","SECTION_CUT","SHEET_FRAME"}: continue
        if primitive.get("entity_type")!="LINE": continue
        pts=_primitive_points(primitive)
        if len(pts)==2:
            leaf=LineString(pts)
            if frame_clip is None or frame_clip.intersects(leaf): leaves.append((primitive,leaf))
    walls=STRtree(wall_lines) if wall_lines else None; rows=[]
    for arc in extracted["primitives"]:
        if arc.get("pre_topology_object_class") in {"DETAIL_GRAPHIC","SECTION_CUT","SHEET_FRAME"}: continue
        if arc.get("entity_type")!="ARC" or not arc.get("center") or not arc.get("radius"): continue
        pivot=Point(arc["center"])
        if frame_clip is not None and not frame_clip.covers(pivot): continue
        radius=float(arc["radius"]); radius_m=radius*scale
        if not .45<=radius_m<=2.5: continue
        matching=[]
        for leaf_record,leaf in leaves:
            arc_insert=arc.get("source_insert_handle"); leaf_insert=leaf_record.get("source_insert_handle")
            if arc_insert and leaf_insert and arc_insert!=leaf_insert: continue
            coords=list(leaf.coords)
            if min(pivot.distance(Point(coords[0])),pivot.distance(Point(coords[-1])))<=tol and .65*radius<=leaf.length<=1.35*radius:
                matching.append((leaf_record,leaf))
        if not matching or walls is None: continue
        wall_indexes=walls.query(pivot.buffer(max(tol,.20/scale)))
        near=[wall_lines[int(index)] for index in wall_indexes if wall_lines[int(index)].distance(pivot)<=max(tol,.20/scale)]
        if not near: continue
        leaf_record,leaf=min(matching,key=lambda row:abs(row[1].length-radius))
        arc_ref=arc.get("handle") or arc.get("source_insert_handle")
        leaf_ref=leaf_record.get("handle") or leaf_record.get("source_insert_handle")
        source_handles=sorted({str(value) for value in (arc_ref,leaf_ref) if value})
        evidence=[{"class":"SWING_ARC","handle":arc_ref},
                  {"class":"DOOR_LEAF","handle":leaf_ref},
                  {"class":"HOST_WALL_PROXIMITY"}]
        if arc.get("source_insert_handle"):
            evidence.append({"class":"NESTED_BLOCK_ASSEMBLY","insert_handle":arc.get("source_insert_handle"),
                             "block_path":arc.get("source_block_path") or [arc.get("source_block")]})
        rows.append({"opening_id":_stable_id("DOOR",[source_hash,source_handles,_round_points(list(leaf.coords))]),
                     "kind":"door","geometry":{"point":[pivot.x,pivot.y],"points":list(leaf.coords),"arc_points":arc.get("points")},
                     "source_handle":arc_ref,"source_handles":source_handles,
                     "width_drawing_units":leaf.length,
                     "evidence":evidence,"status":"CANDIDATE"})
    return rows


def _opening_source_inventory(extracted, frame, metres_per_unit):
    """Count native source motifs without assigning architectural meaning."""
    clip=box(*frame["bounds"]) if frame.get("bounds") else None; scale=metres_per_unit or 1.0
    def in_frame(point): return bool(point and (clip is None or clip.covers(Point(point))))
    objects=[row for row in extracted["objects"] if in_frame(row.get("point"))]
    primitives=[]
    for row in extracted["primitives"]:
        point=row.get("center") or (row.get("start") if row.get("start") else None)
        if in_frame(point): primitives.append(row)
    opening_blocks=[row for row in objects if set(row.get("object_types") or [])&{"door","window"}]
    layer_geometry=[row for row in primitives if any(token in normalize_text(row.get("layer"))
                                                      for token in ("door","window","درب","پنجره"))]
    swing_arcs=[row for row in primitives if row.get("entity_type")=="ARC" and row.get("radius")
                and .45<=float(row["radius"])*scale<=2.5]
    return {"frame_id":frame["frame_id"],"raw_arc_count":sum(row.get("entity_type")=="ARC" for row in primitives),
            "raw_line_count":sum(row.get("entity_type")=="LINE" for row in primitives),
            "door_window_block_count":len(opening_blocks),
            "door_window_layer_geometry_count":len(layer_geometry),
            "plausible_swing_arc_count":len(swing_arcs),
            "block_source_handles":sorted(row.get("handle") for row in opening_blocks if row.get("handle")),
            "layer_source_handles":sorted(row.get("handle") for row in layer_geometry if row.get("handle")),
            "swing_arc_source_handles":sorted(row.get("handle") for row in swing_arcs if row.get("handle")),
            "jamb_window_frame_detector_status":"NO_INDEPENDENT_EXISTING_DETECTOR"}


def _opening_anchor(candidate):
    geometry=candidate.get("geometry") or {}
    points=geometry.get("points") or []
    if len(points)>=2:
        line=LineString(points)
        return (Point(geometry["point"]) if geometry.get("point") else line.centroid), line
    if geometry.get("point"):
        return Point(geometry["point"]), None
    bounds=geometry.get("bounds")
    if bounds and len(bounds)==4:
        return box(*bounds).centroid, None
    return None, None


def _pre_envelope_opening_evidence(candidates, walls, frame, *, tolerance):
    """Map deterministic opening evidence to walls without creating portals."""
    clip=box(*frame["bounds"]) if frame.get("bounds") else None
    tol=max(float(tolerance or .001),1e-8); rows=[]
    for candidate in candidates:
        anchor,line=_opening_anchor(candidate)
        if anchor is None or (clip is not None and not clip.buffer(tol*5).covers(anchor)):
            continue
        mapped=[]
        for wall in walls:
            axis=LineString(wall["centerline"]); thickness=float(wall.get("thickness") or 0.0)
            search=max(tol*5,thickness*1.5,(line.length*.35 if line is not None else 0.0))
            distance=axis.distance(anchor)
            if distance>search: continue
            u,_,wall_angle,_=_axis(axis); origin=wall["wall_solid"]["axis_origin"]
            projected=(anchor.x-origin[0])*u[0]+(anchor.y-origin[1])*u[1]
            orientation=None
            if line is not None and line.length>tol:
                _,_,candidate_angle,_=_axis(line)
                delta=min(abs(wall_angle-candidate_angle),180-abs(wall_angle-candidate_angle))
                orientation="PARALLEL_OR_PERPENDICULAR" if delta<=20 or delta>=70 else "CONFLICT"
            occupied=wall["wall_solid"].get("occupied_intervals") or []
            before=any(a<=projected<=b or b<=projected and projected-b<=search for a,b in occupied)
            after=any(a<=projected<=b or a>=projected and a-projected<=search for a,b in occupied)
            nearby=[]
            for index,interruption in enumerate(wall.get("interruptions") or []):
                low,high=interruption["interval"]
                if low-search<=projected<=high+search:
                    nearby.append({"interruption_index":index,"interval":[low,high],
                                   "kind":interruption.get("kind"),
                                   "face_a_gap":interruption.get("face_a_gap"),
                                   "face_b_gap":interruption.get("face_b_gap")})
            mapped.append({"wall_id":wall["wall_id"],"distance":distance,
                           "orientation_agreement":orientation,"projection":projected,
                           "wall_representation":wall.get("representation"),
                           "wall_material_before":before,"wall_material_after":after,
                           "nearby_interruptions":nearby,"junction_support":False})
        mapped.sort(key=lambda row:(row["distance"],row["wall_id"]))
        classes=sorted({item.get("class") for item in candidate.get("evidence") or [] if item.get("class")})
        strong_symbol=bool(set(classes)&{"CAD_BLOCK","CAD_LAYER_SYMBOL"}) or {"SWING_ARC","DOOR_LEAF"}.issubset(classes)
        compatible=[row for row in mapped if row["orientation_agreement"]!="CONFLICT"]
        rows.append({"opening_evidence_id":_stable_id("OPENEV",[frame["frame_id"],candidate["opening_id"]]),
                     "frame_id":frame["frame_id"],"candidate_type":candidate.get("kind"),
                     "geometry":candidate.get("geometry"),
                     "source_handles":candidate.get("source_handles") or [candidate.get("source_handle")],
                     "evidence_classes":classes,"candidate_host_wall_ids":[row["wall_id"] for row in compatible],
                     "host_evaluations":mapped,"confidence":.85 if strong_symbol and compatible else .35,
                     "status":"OPENING_EVIDENCE_PRESENT" if strong_symbol and compatible else "REJECTED",
                     "material_gap_status":"UNPROVEN","portal_status":"NOT_CLASSIFIED",
                     "access_edge_status":"NOT_EVALUATED"})
    return rows


def _ingest(path):
    source = Path(path)
    data = source.read_bytes()
    if len(data) > 250 * 1024 * 1024: raise ValueError("DXF_TOO_LARGE")
    doc = ezdxf.readfile(source)
    insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    declared_scale = _unit_scale(insunits)
    return doc, {"source_sha256": sha256(data).hexdigest(), "source_size": len(data), "dxf_version": doc.dxfversion,
                 "insunits": insunits, "declared_metres_per_unit": declared_scale,
                 "metres_per_unit": declared_scale}


def _source_backed_dimension_measurement(dimtype, reported, stored, witness_distance):
    """Select a dimension value without concealing conflicting source facts."""
    measurement, basis = reported, "EZDXF_GET_MEASUREMENT"
    if (dimtype & 7) in {0, 1} and abs(reported) <= 1e-9 and stored > 1e-9 and witness_distance > 1e-9:
        allowed=max(1e-6, abs(stored)*.005)
        if abs(stored-witness_distance) <= allowed:
            measurement, basis = stored, "SOURCE_ACTUAL_MEASUREMENT_AND_WITNESSES"
    return measurement, basis


def _extract(doc, source_sha256=None):
    primitives, texts, objects, dimensions, boundary_lines, boundary_meta, boundary_rejections = [], [], [], [], [], [], []
    counts = Counter(); seen_nested = set()

    def visit(entity, transform_source=None, depth=0, source_insert_handle=None, source_block_path=()):
        if depth > 12: return
        kind = entity.dxftype(); counts[kind] += 1; layer = _layer(entity); handle = _handle(entity)
        record = {"entity_type": kind, "handle": handle, "layer": layer, "source_block": transform_source,
                  "source_insert_handle": source_insert_handle,
                  "source_block_path": list(source_block_path)}
        if kind == "LINE":
            a, b = _point(entity, "start"), _point(entity, "end")
            if a and b and a != b:
                record.update(start=a, end=b); primitives.append(record)
                retained,reason=_boundary_geometry_decision(layer,transform_source,kind)
                if retained:
                    boundary_lines.append(LineString([a, b])); boundary_meta.append({"layer":layer,"entity_type":kind,"handle":handle,"source_block":transform_source,"source_insert_handle":source_insert_handle,"source_block_path":list(source_block_path),"closed":False})
                else: boundary_rejections.append({**record,"geometry":[a,b],"reason":reason})
        elif kind in {"LWPOLYLINE", "POLYLINE"}:
            try:
                pts = ([(float(x), float(y)) for x, y, *_ in entity.get_points()] if kind == "LWPOLYLINE"
                       else [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices])
            except Exception: pts = []
            if len(pts) >= 2:
                closed = bool(getattr(entity, "closed", False)) or pts[0] == pts[-1]
                record.update(points=pts, closed=closed)
                if kind == "LWPOLYLINE":
                    record["bulges"]=[float(p[4]) for p in entity.get_points()]
                else:
                    record["bulges"]=[float(getattr(v.dxf,"bulge",0) or 0) for v in entity.vertices]
                primitives.append(record)
                retained,reason=_boundary_geometry_decision(layer,transform_source,kind)
                if retained:
                    for a, b in zip(pts, pts[1:] + ([pts[0]] if closed else [])):
                        if a != b:
                            boundary_lines.append(LineString([a, b])); boundary_meta.append({"layer":layer,"entity_type":kind,"handle":handle,"source_block":transform_source,"source_insert_handle":source_insert_handle,"source_block_path":list(source_block_path),"closed":closed})
                else: boundary_rejections.append({**record,"geometry":pts,"reason":reason})
        elif kind == "ARC":
            try:
                pts = [(float(p.x), float(p.y)) for p in entity.flattening(0.5)]
            except Exception: pts = []
            if len(pts) >= 2:
                center=_point(entity,"center")
                record.update(points=pts,center=center,radius=float(getattr(entity.dxf,"radius",0) or 0),
                              start_angle=float(getattr(entity.dxf,"start_angle",0) or 0),
                              end_angle=float(getattr(entity.dxf,"end_angle",0) or 0))
                primitives.append(record)
                retained,reason=_boundary_geometry_decision(layer,transform_source,kind)
                if retained:
                    boundary_lines.append(LineString(pts)); boundary_meta.append({"layer":layer,"entity_type":kind,"handle":handle,"source_block":transform_source,"source_insert_handle":source_insert_handle,"source_block_path":list(source_block_path),"closed":False})
                else: boundary_rejections.append({**record,"geometry":pts,"reason":reason})
        elif kind in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}:
            value = _entity_text(entity).strip(); p = _point(entity)
            if value and p: record.update(text=value, point=p); texts.append(record); primitives.append(record)
        elif kind == "DIMENSION":
            try:
                role_points={name:_point(entity,name) for name in ("defpoint","defpoint2","defpoint3","defpoint4")}
                role_points={name:p for name,p in role_points.items() if p and Point(p).distance(Point(0,0))>1e-9}
                witnesses=[role_points[name] for name in ("defpoint2","defpoint3") if name in role_points]
                dimtype=int(getattr(entity.dxf,"dimtype",0) or 0)
                reported=float(entity.get_measurement())
                stored=float(getattr(entity.dxf,"actual_measurement",0) or 0)
                witness_distance=(LineString(witnesses).length if len(witnesses)==2 else 0.0)
                measurement,measurement_basis=_source_backed_dimension_measurement(
                    dimtype,reported,stored,witness_distance)
                # Some consultant drawings use DIMTYPE bit flags (for example
                # 32 + linear).  ezdxf can then return zero from
                # get_measurement() even though the source stores a valid
                # associative measurement and two consistent witness points.
                # Recover only linear dimensions, and only from mutually
                # consistent source geometry; never turn a disagreement into
                # authoritative dimension evidence.
                row = {**record, "measurement": measurement, "definition_points": list(role_points.values()),
                       "dimension_points":role_points,"witness_points":witnesses,
                       "dimension_type":dimtype&15,
                       "raw_dimension_type":dimtype,
                       "measurement_basis":measurement_basis,
                       "reported_measurement":reported,
                       "source_actual_measurement":stored,
                       "witness_distance":witness_distance,
                       "text_override": str(getattr(entity.dxf, "text", "") or "")}
                dimensions.append(row); primitives.append(row)
            except Exception: primitives.append(record)
        elif kind == "INSERT":
            p = _point(entity); name = str(getattr(entity.dxf, "name", "") or "")
            kinds = _classify_object(name, layer)
            try:
                children = list(entity.virtual_entities())
            except Exception:
                children = []
            if p:
                row = {**record, "name": name, "point": p, "object_types": kinds}; objects.append(row); primitives.append(row)
            key = (handle, depth)
            if key not in seen_nested:
                seen_nested.add(key)
                parent_handle=source_insert_handle or handle
                path=tuple(source_block_path)+(name,)
                for child in children: visit(child, name, depth + 1, parent_handle, path)
        elif kind in {"CIRCLE", "SPLINE", "HATCH", "SOLID", "TRACE", "LEADER", "MLEADER"}:
            primitives.append(record)

    for entity in doc.modelspace(): visit(entity)
    # Exploded SHX glyphs often arrive as thousands of tiny top-level segments
    # on a neutral layer.  Detect the drafting signature statistically rather
    # than hard-coding a consultant layer name.
    lengths=defaultdict(list)
    for line,meta in zip(boundary_lines,boundary_meta): lengths[meta["layer"]].append(line.length)
    arc_counts=Counter(p.get("layer") for p in primitives if p.get("entity_type")=="ARC" and not p.get("source_block"))
    glyph_layers=set()
    for layer,values in lengths.items():
        ordered=sorted(v for v in values if v>0)
        median=ordered[len(ordered)//2] if ordered else 0
        metric_signature=ordered and median < .05 and ordered[-1] < 1.0
        scale_independent_glyph_signature=ordered and arc_counts[layer] >= len(ordered) and ordered[-1]/max(median,1e-12) < 30
        if len(ordered)>=100 and (metric_signature or scale_independent_glyph_signature):
            glyph_layers.add(layer)
    for line,meta in zip(boundary_lines,boundary_meta):
        if meta["layer"] in glyph_layers:
            boundary_rejections.append({**meta,"geometry":[list(point) for point in line.coords],"reason":"GLYPH_FILTER"})
    retained=[(line,meta) for line,meta in zip(boundary_lines,boundary_meta) if meta["layer"] not in glyph_layers]
    boundary_lines=[line for line,_ in retained]; boundary_meta=[meta for _,meta in retained]
    text_evidence = extract_text_evidence(doc, source_sha256=source_sha256 or "0" * 64)
    canonical_texts = legacy_text_records(text_evidence)
    return {"primitives": primitives, "texts": canonical_texts, "text_evidence": text_evidence,
            "objects": objects, "dimensions": dimensions,
            "boundary_lines": boundary_lines, "boundary_meta":boundary_meta,
            "boundary_rejections":boundary_rejections,
            "excluded_graphic_glyph_layers":sorted(glyph_layers), "entity_counts": dict(counts)}


def _frame_from_extent(extracted, source_hash):
    points = []
    for line in extracted["boundary_lines"]: points.extend(line.coords)
    if not points:
        return {"frame_id": _stable_id("FRAME", [source_hash, "EMPTY"]), "frame_type": "UNKNOWN", "bounds": None,
                "level_candidate": None, "confidence": 0.0, "evidence": [], "status": "INPUT_REQUIRED"}
    xs, ys = [p[0] for p in points], [p[1] for p in points]; bounds = [min(xs), min(ys), max(xs), max(ys)]
    normalized_text = " ".join(normalize_text(t.get("text")) for t in extracted["texts"])
    non_floor = next((kind for kind, tokens in {
        "SECTION": ("section", "مقطع"), "ELEVATION": ("elevation", "نما"), "DETAIL": ("detail", "دیتیل"),
        "LEGEND": ("legend", "راهنما"), "SCHEDULE": ("schedule", "جدول")}.items() if any(x in normalized_text for x in tokens)), None)
    floor_tokens = ("floor", "ground", "طبقه", "همکف", "پلان")
    frame_type = non_floor or ("PRIMARY_FLOOR" if any(x in normalized_text for x in floor_tokens) or len(extracted["boundary_lines"]) >= 4 else "UNKNOWN")
    status = "HIGH_CONFIDENCE" if frame_type == "PRIMARY_FLOOR" else "INPUT_REQUIRED"
    return {"frame_id": _stable_id("FRAME", [source_hash, _round_points([(bounds[0], bounds[1]), (bounds[2], bounds[3])])]),
            "frame_type": frame_type, "bounds": bounds, "level_candidate": None,
            "confidence": .80 if frame_type == "PRIMARY_FLOOR" else .40,
            "evidence": ["modelspace_extent", "drawing_text_classification"], "status": status}


def _detected_frames(path, source_hash, fallback):
    """Use the governed print-frame detector without making it a prerequisite."""
    try:
        from .plan_segmentation import detect_print_plans
        plans = detect_print_plans(path)
    except Exception:
        plans = []
    mapped = {"ARCH_FLOOR_PLAN":"PRIMARY_FLOOR", "ROOF_PLAN":"ROOF", "FURNITURE_PLAN":"FURNITURE_PLAN",
              "SECTION":"SECTION", "ELEVATION":"ELEVATION", "DETAIL":"DETAIL"}
    frames = []
    for plan in plans:
        bounds = plan.get("bounds"); frame_type = mapped.get(plan.get("drawing_type"), "UNKNOWN")
        role = str(plan.get("mechanical_role") or "EXCLUDE")
        relevant = role in {"PRIMARY_FLOOR", "ROOF_SUPPORT"}
        frames.append({"frame_id": _stable_id("FRAME", [source_hash, plan.get("plan_id"), bounds]),
                       "frame_type": frame_type, "bounds": bounds, "level_candidate": plan.get("level"),
                       "represented_levels": plan.get("represented_levels") or [],
                       "title_text": plan.get("title_text") or [],
                       "title_evidence": plan.get("title_evidence") or [],
                       "title_source_handles": sorted({row.get("source_handle") for row in
                                                        (plan.get("title_evidence") or []) if row.get("source_handle")}),
                       "source_plan_id": plan.get("plan_id"), "mechanical_role": role,
                       "scope_relevance": "MECHANICAL_AUTHORITY" if relevant else "REFERENCE_ONLY",
                       "confidence": min(1.0, float(plan.get("frame_confidence") or 0)/100.0),
                       "evidence": ["governed_print_frame_detector"] + sorted(k for k,v in (plan.get("frame_evidence") or {}).items() if v),
                       "status": ("VERIFIED" if relevant and frame_type in {"PRIMARY_FLOOR", "ROOF", "SITE"}
                                  else "REFERENCE_ONLY")})
    return frames or [fallback]


def _line_in_frame(line, frame):
    bounds = frame.get("bounds")
    if not bounds: return False
    point = line.interpolate(.5, normalized=True)
    return bounds[0] <= point.x <= bounds[2] and bounds[1] <= point.y <= bounds[3]


def _segment_direction(line):
    coords=list(line.coords); dx=coords[-1][0]-coords[0][0]; dy=coords[-1][1]-coords[0][1]
    length=math.hypot(dx,dy)
    return ((dx/length,dy/length),length) if length else ((0.0,0.0),0.0)


def _parallel_overlap(left, right):
    (ux,uy),left_length=_segment_direction(left); (vx,vy),right_length=_segment_direction(right)
    parallel=abs(ux*vx+uy*vy)
    if parallel < math.cos(math.radians(3)): return 0.0
    origin=list(left.coords)[0]
    def projection(point): return (point[0]-origin[0])*ux+(point[1]-origin[1])*uy
    a=sorted(projection(point) for point in right.coords)
    overlap=max(0.0,min(left_length,a[1])-max(0.0,a[0]))
    return overlap/max(min(left_length,right_length),1e-12)


def _semantic_segment_classification(lines, metas, metres_per_unit, tolerance):
    """Classify boundary candidates from geometry before polygonization.

    Layer/style metadata is supporting evidence only.  Unknown geometry is
    retained in diagnostics but cannot silently become an architectural wall.
    """
    if not lines: return [],[]
    scale=metres_per_unit or 1.0; tol=max(float(tolerance or .001),1e-9)
    repeated_columns=repeated_compact_column_handles(lines,metas,metres_per_unit)
    for meta in metas:
        source_kind,_=_classify_text(" ".join(str(meta.get(k) or "") for k in ("layer","source_block")))
        if (meta.get("handle") in repeated_columns and not meta.get("pre_topology_object_class")
                and source_kind not in {"duct","shaft","void","lightwell","pipe_shaft","mechanical_shaft","electrical_shaft"}):
            meta["pre_topology_object_class"]="COLUMN"
    source_classes=[classify_source_record(meta) for meta in metas]
    eligible={i for i,c in enumerate(source_classes) if not excludes_from_wall_admission(c)}
    min_thickness=.04/scale; max_thickness=.65/scale
    tree=STRtree(lines); pair_rows=[]
    for index,line in enumerate(lines):
        if index not in eligible: continue
        _,length=_segment_direction(line)
        if length < min_thickness: continue
        for raw in tree.query(line.buffer(max_thickness)):
            other_index=int(raw)
            if other_index<=index or other_index not in eligible: continue
            other=lines[other_index]; distance=line.distance(other)
            if not min_thickness<=distance<=max_thickness: continue
            overlap=_parallel_overlap(line,other)
            if overlap>=.35: pair_rows.append((index,other_index,distance,overlap))
    cluster_step=max(.005/scale,tol)
    clusters=Counter(round(distance/cluster_step) for _,_,distance,_ in pair_rows)
    recurring={bucket for bucket,count in clusters.items() if count>=3}
    paired=defaultdict(list); local_paired=defaultdict(list)
    for left,right,distance,overlap in pair_rows:
        bucket=round(distance/cluster_step)
        local_paired[left].append((right,distance,overlap,bucket)); local_paired[right].append((left,distance,overlap,bucket))
        if bucket in recurring:
            paired[left].append((right,distance,overlap)); paired[right].append((left,distance,overlap))
    endpoint_degree=Counter()
    def node(point): return (round(point[0]/(tol*2)),round(point[1]/(tol*2)))
    for index,line in enumerate(lines):
        if index not in eligible: continue
        coords=list(line.coords); endpoint_degree[node(coords[0])]+=1; endpoint_degree[node(coords[-1])]+=1
    small_coherent=len(lines)<=20 and all(endpoint_degree[node(point)]>=2 for line in lines for point in (list(line.coords)[0],list(line.coords)[-1]))
    records=[]; accepted=[]
    for index,(line,meta) in enumerate(zip(lines,metas)):
        pre_topology=source_classes[index]
        if excludes_from_wall_admission(pre_topology):
            coords=list(line.coords)
            records.append({"segment_id":_stable_id("SEG",[meta.get("handle"),_round_points(coords)]),
                "source_handle":meta.get("handle"),"geometry":coords,
                "source_insert_handle":meta.get("source_insert_handle"), "source_block_path":meta.get("source_block_path"),
                "source_context":{"layer":meta.get("layer"),"entity_type":meta.get("entity_type"),"closed":meta.get("closed")},
                "semantic_class":pre_topology["object_class"],"wall_probability":0.0,
                "wall_evidence_state":"HARD_EXCLUDED_NON_ENCLOSURE_OBJECT",
                "evidence":[{"class":"PRE_TOPOLOGY_OBJECT","value":value}
                            for value in pre_topology["positive_evidence"]],
                "negative_evidence":pre_topology["negative_evidence"],
                "pre_topology_classification":pre_topology,"status":"REJECTED"})
            continue
        context=normalize_text(meta.get("layer")); evidence=[]; negative=[]; semantic="UNKNOWN_GEOMETRY"; probability=0.0; state="WEAK_WALL_CANDIDATE"
        if any(token in context for token in WALL_TOKENS):
            semantic="WALL_FACE"; probability=.95; state="CONFIRMED_WALL"; evidence.append({"class":"SOURCE_CONTEXT","value":meta.get("layer")})
        elif paired[index]:
            semantic="WALL_FACE"; probability=.90; state="CONFIRMED_WALL"
            evidence.append({"class":"RECURRING_PARALLEL_FACE_PAIR","pair_count":len(paired[index]),
                             "thicknesses":[round(row[1]*scale,4) for row in paired[index]]})
        elif local_paired[index]:
            semantic="WALL_CANDIDATE"; probability=.65; state="SUPPORTED_WALL_CANDIDATE"
            evidence.append({"class":"LOCAL_PARALLEL_FACE_PAIR","pair_count":len(local_paired[index]),
                             "thicknesses":[round(row[1]*scale,4) for row in local_paired[index]],
                             "overlaps":[round(row[2],4) for row in local_paired[index]]})
        elif small_coherent:
            semantic="EXTERIOR_BOUNDARY"; probability=.80; state="CONFIRMED_WALL"; evidence.append({"class":"COHERENT_SMALL_SINGLE_LINE_NETWORK"})
        coords=list(line.coords); degrees=[endpoint_degree[node(coords[0])],endpoint_degree[node(coords[-1])]]
        if max(degrees)>=3: evidence.append({"class":"JUNCTION_SUPPORT","endpoint_degrees":degrees})
        if not evidence: negative.append("NO_RECURRING_OR_LOCAL_PARALLEL_PAIR")
        record={"segment_id":_stable_id("SEG",[meta.get("handle"),_round_points(coords)]),
                "source_handle":meta.get("handle"),"geometry":coords,
                "source_insert_handle":meta.get("source_insert_handle"), "source_block_path":meta.get("source_block_path"),
                "source_context":{"layer":meta.get("layer"),"entity_type":meta.get("entity_type"),"closed":meta.get("closed")},
                "semantic_class":semantic,"wall_probability":probability,"wall_evidence_state":state,
                "evidence":evidence,"negative_evidence":negative,
                "pre_topology_classification":pre_topology,
                "status":"ACCEPTED" if state=="CONFIRMED_WALL" else ("PROVISIONAL" if state=="SUPPORTED_WALL_CANDIDATE" else "REJECTED")}
        records.append(record)
        if record["status"]=="ACCEPTED": accepted.append(line)
    return records,accepted


def _exclude_inset_sheet_border_segments(lines, metas, frame, tolerance):
    """Reject a source-native inset print border before wall admission.

    Some consultant files place the inner sheet border on a layer named
    ``WALL``.  Layer semantics alone would then create a full-page wall cycle
    and contaminate every downstream region.  A border is rejected only when
    one closed source entity forms a near-concentric, near-page-sized rectangle
    inside an independently detected print frame.  Ordinary room/building
    rectangles and disconnected linework do not satisfy this signature.
    """
    bounds = frame.get("bounds")
    if not bounds or len(lines) < 4:
        return list(lines), list(metas), []
    frame_width = float(bounds[2] - bounds[0]); frame_height = float(bounds[3] - bounds[1])
    if frame_width <= 0 or frame_height <= 0:
        return list(lines), list(metas), []
    by_handle = defaultdict(list)
    for index, meta in enumerate(metas):
        if meta.get("handle") and meta.get("closed"):
            by_handle[meta["handle"]].append(index)
    excluded = set()
    for indexes in by_handle.values():
        if len(indexes) != 4:
            continue
        polygons = list(polygonize(unary_union([lines[index] for index in indexes])))
        if len(polygons) != 1:
            continue
        min_x, min_y, max_x, max_y = polygons[0].bounds
        width = max_x - min_x; height = max_y - min_y
        width_ratio = width / frame_width; height_ratio = height / frame_height
        if not (0.85 <= width_ratio < 0.985 and 0.85 <= height_ratio < 0.985):
            continue
        margins = (min_x-bounds[0], bounds[2]-max_x, min_y-bounds[1], bounds[3]-max_y)
        if min(margins) <= max(float(tolerance or 0.0), 1e-9):
            continue
        if max(margins[0], margins[1]) > frame_width*.10 or max(margins[2], margins[3]) > frame_height*.10:
            continue
        symmetry_x = abs(margins[0]-margins[1]); symmetry_y = abs(margins[2]-margins[3])
        if symmetry_x > max(float(tolerance or 0.0)*5, frame_width*.01):
            continue
        if symmetry_y > max(float(tolerance or 0.0)*5, frame_height*.01):
            continue
        excluded.update(indexes)
    kept_lines = [line for index, line in enumerate(lines) if index not in excluded]
    kept_metas = [meta for index, meta in enumerate(metas) if index not in excluded]
    records = []
    for index in sorted(excluded):
        line, meta = lines[index], metas[index]
        coords = list(line.coords)
        records.append({
            "segment_id": _stable_id("SEG", [meta.get("handle"), _round_points(coords)]),
            "source_handle": meta.get("handle"), "geometry": coords,
            "source_context": {"layer": meta.get("layer"), "entity_type": meta.get("entity_type"),
                               "closed": meta.get("closed")},
            "semantic_class": "PRINT_BORDER", "wall_probability": 0.0,
            "wall_evidence_state": "SUPPORTED_NON_WALL",
            "evidence": [{"class": "INSET_PRINT_BORDER_GEOMETRY", "frame_id": frame.get("frame_id")}],
            "negative_evidence": ["PAGE_SCALE_NEAR_CONCENTRIC_RECTANGLE"], "status": "REJECTED",
        })
    return kept_lines, kept_metas, records


def _recognized_label_hosts(polygons, texts):
    hosts=[]
    for poly in polygons:
        categories=[]
        for text in texts:
            category,_=_classify_text(text.get("text"))
            if category and poly.covers(Point(text["point"])): categories.append(category)
        if categories: hosts.append(tuple(sorted(set(categories))))
    return sorted(hosts)


def _connected_line_components(lines, tolerance):
    if not lines: return []
    tree=STRtree(lines); parents=list(range(len(lines)))
    def find(value):
        while parents[value]!=value:
            parents[value]=parents[parents[value]]; value=parents[value]
        return value
    def union(left,right):
        left,right=find(left),find(right)
        if left!=right: parents[right]=left
    for index,line in enumerate(lines):
        for raw in tree.query(line.buffer(tolerance)):
            other=int(raw)
            if other>index and line.distance(lines[other])<=tolerance: union(index,other)
    groups=defaultdict(list)
    for index,line in enumerate(lines): groups[find(index)].append(index)
    return list(groups.values())


def _recover_supported_partitions(accepted, classified, frame, tolerance, extracted, metres_per_unit):
    """Bounded, evidence-based recovery of wall candidates lost by seed admission."""
    candidates=[record for record in classified
                if record["status"]!="ACCEPTED"
                and record.get("wall_evidence_state")!="HARD_EXCLUDED_NON_ENCLOSURE_OBJECT"
                and not excludes_from_wall_admission(record.get("pre_topology_classification") or {})]
    lines=[LineString(record["geometry"]) for record in candidates]
    components=_connected_line_components(lines,max(float(tolerance or .001)*2,1e-8))
    current=list(accepted); decisions=[]; iterations=[]; wall_union=unary_union(current) if current else None
    scale=metres_per_unit or 1.0
    thicknesses=[float(value) for record in classified for evidence in record.get("evidence") or []
                 if evidence.get("class") in {"RECURRING_PARALLEL_FACE_PAIR","LOCAL_PARALLEL_FACE_PAIR"}
                 for value in evidence.get("thicknesses") or []]
    local_thickness=(sorted(thicknesses)[len(thicknesses)//2]/scale if thicknesses else .20/scale)
    snap=max(float(tolerance or .001)*5,.03/scale,min(local_thickness*.35,.10/scale))
    bounds=frame.get("bounds") or [-math.inf,-math.inf,math.inf,math.inf]
    label_points=[]
    for text in extracted["texts"]:
        category,_=_classify_text(text.get("text")); point=text.get("point")
        if category and point and bounds[0]<=point[0]<=bounds[2] and bounds[1]<=point[1]<=bounds[3]: label_points.append((Point(point),category))
    diagnostic_lines = [LineString(row["geometry"]) for row in classified]
    diagnostic_tree = STRtree(diagnostic_lines) if diagnostic_lines else None
    component_diagnostics = {}
    pending=list(sorted(components,key=lambda indexes:-sum(lines[i].length for i in indexes))[:400])
    for pass_number in (2,3):
      admitted_this_pass=0
      for component in list(pending):
        component_lines=[lines[i] for i in component]
        endpoints=[Point(point) for line in component_lines for point in (list(line.coords)[0],list(line.coords)[-1])]
        supports=sum(wall_union is not None and wall_union.distance(point)<=snap for point in endpoints)
        axis=max(component_lines,key=lambda line:line.length); a,b=list(axis.coords)[0],list(axis.coords)[-1]
        (ux,uy),axis_length=_segment_direction(axis); normal=(-uy,ux)
        component_points=[point for line in component_lines for point in line.coords]
        projections=[(point[0]-a[0])*ux+(point[1]-a[1])*uy for point in component_points]
        low,high=min(projections),max(projections); local_depth=max(sum(line.length for line in component_lines),axis_length)
        sides=[]
        for point,category in label_points:
            along=(point.x-a[0])*ux+(point.y-a[1])*uy
            signed=(point.x-a[0])*normal[0]+(point.y-a[1])*normal[1]
            if low-max(float(tolerance or .001)*5,1e-8)<=along<=high+max(float(tolerance or .001)*5,1e-8) and abs(signed)<=local_depth:
                if abs(signed)>max(float(tolerance or .001)*5,1e-8): sides.append((1 if signed>0 else -1,category))
        distinct_sides={side for side,_ in sides}; distinct_categories={category for _,category in sides}
        evidence_classes={e.get("class") for i in component for e in candidates[i].get("evidence") or []}
        local_pair="LOCAL_PARALLEL_FACE_PAIR" in evidence_classes
        junction="JUNCTION_SUPPORT" in evidence_classes
        family=False
        if wall_union is not None:
            for admitted in current:
                (vx,vy),_= _segment_direction(admitted)
                if abs(ux*vx+uy*vy)>=math.cos(math.radians(3)) and axis.distance(admitted)<=snap:
                    family=True; break
        geometry_support=(local_pair and supports>=1) or supports>=2 or (family and supports>=1) or (junction and supports>=1 and pass_number==3)
        before=list(polygonize(unary_union(current))) if current else []
        after=list(polygonize(unary_union(current+component_lines)))
        new_regions=max(0,len(after)-len(before)); slivers=0
        for poly in after:
            rectangle=poly.minimum_rotated_rectangle; rc=list(rectangle.exterior.coords)
            sides_len=sorted(math.dist(x,y) for x,y in zip(rc,rc[1:]) if x!=y)
            if sides_len and sides_len[0]<=local_thickness*1.5 and sides_len[-1]/max(sides_len[0],1e-12)>=3: slivers+=1
        topology_ok=new_regions==0 or slivers<len(after)
        support_ids = sorted({classified[int(raw)]["segment_id"] for point in endpoints
                              for raw in (diagnostic_tree.query(point.buffer(snap)) if diagnostic_tree is not None else [])
                              if classified[int(raw)].get("status") == "ACCEPTED"
                              and diagnostic_lines[int(raw)].distance(point) <= snap})
        diagnostic = {"component_segment_ids": sorted(candidates[i]["segment_id"] for i in component),
                      "pass": pass_number, "wall_support_endpoints": supports,
                      "local_parallel_pair": local_pair, "face_family": family, "junction_support": junction,
                      "supporting_source_segment_ids": support_ids, "local_tolerance": snap,
                      "local_wall_thickness": local_thickness, "geometry_support": bool(geometry_support),
                      "topology_ok": bool(topology_ok), "topology_before": len(before),
                      "topology_after": len(after), "new_regions": new_regions, "sliver_count": slivers,
                      "reason": ("MULTI_EVIDENCE_PARTITION_ADMISSION" if geometry_support and topology_ok else
                                 "INSUFFICIENT_INDEPENDENT_WALL_SUPPORT" if not geometry_support else
                                 "TOPOLOGY_ONLY_SLIVERS"), "action": "ADMIT" if geometry_support and topology_ok else "DO_NOT_RECOVER"}
        for index in component: component_diagnostics[candidates[index]["segment_id"]] = diagnostic
        if geometry_support and topology_ok:
            current.extend(component_lines); wall_union=unary_union(current)
            ids=[]
            for index in component:
                record=candidates[index]; previous=record["status"]; record["semantic_class"]="PARTITION_FACE"; record["wall_evidence_state"]="SUPPORTED_WALL_CANDIDATE"; record["wall_probability"]=max(float(record.get("wall_probability") or 0),.72); record["status"]="ACCEPTED"
                record["evidence"].append({"class":"ITERATIVE_PARTITION_RECOVERY","pass":pass_number,"wall_support_endpoints":supports,"local_pair":local_pair,"face_family":family,"junction":junction,"new_regions":new_regions})
                record["admission_trace"]={"admission_id":_stable_id("ADM",[record["segment_id"],pass_number]),"source_handles":[record.get("source_handle")],"previous_status":previous,"final_status":"ACCEPTED","evidence_classes":sorted(evidence_classes|{"ITERATIVE_PARTITION_RECOVERY"}),"negative_evidence":record.get("negative_evidence") or [],"supporting_wall_ids":[],"junction_ids":[],"supporting_source_segment_ids":support_ids,"local_tolerance":snap,"local_thickness_cluster":local_thickness,"topology_before":{"region_count":len(before)},"topology_after":{"region_count":len(after),"sliver_count":slivers},"reason":"MULTI_EVIDENCE_PARTITION_ADMISSION","confidence":record["wall_probability"]}
                ids.append(record["segment_id"])
            decisions.append({"pass":pass_number,"segment_ids":ids,"action":"ADMIT","reason":"MULTI_EVIDENCE_PARTITION_ADMISSION","wall_support_endpoints":supports,"local_parallel_pair":local_pair,"face_family":family,"junction_support":junction,"separated_label_categories":sorted(distinct_categories),"topology_before":len(before),"topology_after":len(after),"sliver_count":slivers})
            pending.remove(component); admitted_this_pass+=len(component)
      iterations.append({"pass":pass_number,"accepted_segment_count":admitted_this_pass,"accepted_total":len(current),"remaining_candidate_components":len(pending)})
      if admitted_this_pass==0: break
    for record in classified:
        if record.get("status") != "ACCEPTED":
            hard_excluded = (record.get("wall_evidence_state") == "HARD_EXCLUDED_NON_ENCLOSURE_OBJECT" or
                             excludes_from_wall_admission(record.get("pre_topology_classification") or {}))
            record["recovery_diagnostic"] = {**component_diagnostics.get(record["segment_id"], {}),
                              "action": "DO_NOT_RECOVER",
                              "reason": "HARD_NON_ENCLOSURE_SOURCE_ROLE" if hard_excluded else
                                        component_diagnostics.get(record["segment_id"], {}).get("reason", "BOUNDED_COMPONENT_LIMIT"),
                              "diagnostic_code": "WHY_NOT_RECOVERED",
                              "negative_evidence": record.get("negative_evidence") or ["INSUFFICIENT_INDEPENDENT_WALL_SUPPORT"],
                              "source_role": (record.get("pre_topology_classification") or {}).get("topology_role")}
    return current,decisions,iterations


def _admit_label_supported_partitions(accepted, classified, frame, tolerance, extracted, metres_per_unit=1.0):
    """Compatibility wrapper for the evidence-based bounded recovery stage."""
    return _recover_supported_partitions(accepted,classified,frame,tolerance,extracted,metres_per_unit)


def _polygonize_spaces(lines, frame, tolerance):
    if frame["frame_type"] not in {"PRIMARY_FLOOR", "ROOF", "SITE", "FURNITURE_PLAN"}: return []
    merged = unary_union(lines)
    cells = []
    for poly in polygonize(merged):
        if not poly.is_valid or poly.area <= max((tolerance or 0.001) ** 2 * 4, 1e-9): continue
        if frame.get("bounds") and not box(*frame["bounds"]).buffer(tolerance or 0).contains(poly.representative_point()): continue
        cells.append(poly)
    # Drop a containing outer frame when it duplicates the union of smaller cells.
    cells.sort(key=lambda p: p.area)
    accepted = []; occupied=None
    for cell in cells:
        # Polygonize can return both real faces and a larger enclosing loop when
        # consultant drawings repeat an outer wall/frame.  An enclosing loop is
        # not a second physical space once it contains a smaller independent
        # face; retaining it duplicates every label inside the floor.
        remainder=cell if occupied is None else cell.difference(occupied)
        fragments=[]
        if remainder.geom_type=="Polygon": fragments=[remainder]
        elif remainder.geom_type=="MultiPolygon": fragments=list(remainder.geoms)
        for fragment in fragments:
            if fragment.is_valid and fragment.area > max((tolerance or .001)**2*4,1e-9):
                accepted.append(fragment)
        occupied=unary_union(accepted) if accepted else None
    return accepted


def _derived_wall_thicknesses(segment_records):
    values=[]
    for record in segment_records:
        for evidence in record.get("evidence") or []:
            if evidence.get("class") in {"RECURRING_PARALLEL_FACE_PAIR", "LOCAL_PARALLEL_FACE_PAIR"}: values.extend(evidence.get("thicknesses") or [])
    if not values: return []
    # The classifier has already established recurring geometric clusters;
    # rounding only deduplicates evidence emitted by both faces.
    return sorted(set(round(float(value),3) for value in values if value>0))


def _wall_material_mask(canonical_walls, tolerance):
    solids=[]; tol=max(float(tolerance or .001),1e-9)
    for wall in canonical_walls or []:
        thickness=wall.get("thickness")
        solid=wall.get("wall_solid") or {}; origin=solid.get("axis_origin"); direction=solid.get("axis_direction")
        if not thickness or not origin or not direction: continue
        for start,end in solid.get("occupied_intervals") or []:
            if end<=start: continue
            line=LineString([(origin[0]+start*direction[0],origin[1]+start*direction[1]),
                             (origin[0]+end*direction[0],origin[1]+end*direction[1])])
            solids.append(line.buffer(float(thickness)/2+tol,cap_style=2,join_style=2))
    return unary_union(solids) if solids else None


def _filter_wall_solid_cells(polygons, segment_records, extracted, metres_per_unit, canonical_walls=None, tolerance=None):
    thicknesses=_derived_wall_thicknesses(segment_records); accepted=[]; rejected=[]; scale=metres_per_unit or 1.0
    material_mask=_wall_material_mask(canonical_walls,tolerance)
    for poly in polygons:
        labels,objects=_evidence_for_cell(poly,extracted)
        rectangle=poly.minimum_rotated_rectangle; coords=list(rectangle.exterior.coords)
        sides=sorted(math.dist(a,b)*scale for a,b in zip(coords,coords[1:]) if a!=b)
        short=sides[0] if sides else 0; long=sides[-1] if sides else 0
        matched=next((value for value in thicknesses if abs(short-value)<=max(value*.25,.01)),None)
        material_overlap=(poly.intersection(material_mask).area/poly.area
                          if material_mask is not None and poly.area>0 else 0.0)
        if material_overlap>=.65 and not labels and not objects:
            rejected.append({"cell_id":_stable_id("CELL",[_round_points(list(poly.exterior.coords))]),
                             "reason":"WALL_MATERIAL_FOOTPRINT","wall_material_overlap_ratio":material_overlap,
                             "status":"REJECTED"})
        elif matched and long/max(short,1e-12)>=2.5 and not labels and not objects:
            rejected.append({"cell_id":_stable_id("CELL",[_round_points(list(poly.exterior.coords))]),
                             "reason":"WALL_SOLID_STRIP","derived_wall_thickness_m":matched,
                             "short_dimension_m":short,"long_dimension_m":long,
                             "status":"REJECTED"})
        else: accepted.append(poly)
    return accepted,rejected


def _evidence_for_cell(poly, extracted):
    labels, objects = [], []
    for text in extracted["texts"]:
        if text.get("pre_topology_role") == "REFERENCE_ONLY": continue
        if not _is_space_label_record(text):
            continue
        if poly.covers(Point(text["point"])):
            category, alias = _classify_text(text["text"])
            if category: labels.append({"category": category, "value": text["text"], "handle": text["handle"], "alias": alias, "point":list(text["point"]),
                                        "source_insert_handle":text.get("source_insert_handle"),
                                        "source_block_path":text.get("source_block_path") or []})
    for obj in extracted["objects"]:
        if obj.get("pre_topology_role") == "REFERENCE_ONLY": continue
        if obj.get("point") and poly.covers(Point(obj["point"])) and obj.get("object_types"):
            objects.append({"types": obj["object_types"], "handle": obj["handle"], "name": obj["name"], "point": obj["point"],
                            "source_insert_handle":obj.get("source_insert_handle"), "source_block_path":obj.get("source_block_path") or [],
                            "hosting_status":"SUPPORTED" if obj.get("footprint") and poly.covers(Polygon(obj["footprint"])) else "POINT_ONLY"})
    return labels, objects


def _label_bindings(spaces, texts, tolerance):
    """Audit every semantic label without arbitrary nearest-room guessing."""
    polygons={s["physical_space_id"]:_space_polygon(s) for s in spaces}
    rows=[]; edge_tolerance=max(float(tolerance or .001)*3,1e-8)
    for text in texts:
        if text.get("pre_topology_role") == "REFERENCE_ONLY": continue
        if not _is_space_label_record(text):
            continue
        category,_=_classify_text(text.get("text")); point=text.get("point")
        if not category or not point: continue
        probe=Point(point)
        exact=sorted(sid for sid,poly in polygons.items() if poly.covers(probe))
        method="POINT_IN_POLYGON"; candidates=exact
        if not candidates:
            edge=sorted(sid for sid,poly in polygons.items() if poly.boundary.distance(probe)<=edge_tolerance)
            candidates=edge; method="UNAMBIGUOUS_EDGE_CONTACT"
        host=candidates[0] if len(candidates)==1 else None
        rows.append({"label_id":_stable_id("LBL",[text.get("handle"),text.get("text"),point,text.get("source_insert_handle"),text.get("source_block_path") or []]),
                     "source_handle":text.get("handle"),"text":text.get("text"),
                     "raw_text":text.get("text"),"normalized_text":normalize_text(text.get("text")),"point":list(point),
                     "source_insert_handle":text.get("source_insert_handle"), "source_block_path":text.get("source_block_path") or [],
                     "semantic_candidate":category,"candidate_space_ids":candidates,
                     "host_space_id":host,"binding_method":method if host else None,
                     "evidence":[{"class":method,"tolerance":edge_tolerance}] if host else [],
                     "status":"VERIFIED" if host and polygons[host].contains(probe) else ("CONFLICT" if candidates else "UNHOSTED")})
    return rows


def _infer_categories(labels, objects):
    evidence = defaultdict(list)
    for label in labels: evidence[label["category"]].append({"class": "TEXT", "handle": label["handle"], "value": label["value"]})
    object_types = {kind for obj in objects if obj.get("hosting_status")=="SUPPORTED" for kind in obj["types"]}
    rules = {
        "bedroom": ({"bed"},), "kitchen": ({"cabinet", "sink"}, {"cabinet", "stove"}),
        "toilet": ({"wc"},), "bathroom": ({"shower"},), "dining": ({"dining_table"},),
        "parking": ({"car"},), "stair": ({"stair"},), "elevator": ({"elevator"},),
    }
    for category, alternatives in rules.items():
        if any(required.issubset(object_types) for required in alternatives):
            evidence[category].append({"class": "OBJECT_SIGNATURE", "objects": sorted(object_types)})
    return evidence


def _associate_dimensions(poly, dimensions, metres_per_unit):
    rows = []
    boundary = poly.boundary
    for dim in dimensions:
        pts = dim.get("witness_points") or []
        if len(pts)!=2 or pts[0]==pts[1]: continue
        reference_tolerance=max(min(math.sqrt(poly.area)*.01,.10),1e-6)
        distances=[boundary.distance(Point(p)) for p in pts]
        midpoint=LineString(pts).interpolate(.5,normalized=True)
        crosses_interior=(poly.buffer(reference_tolerance).covers(midpoint)
                          and boundary.distance(midpoint)>reference_tolerance)
        if max(distances)<=reference_tolerance and crosses_interior:
            references=[list(nearest_points(boundary,Point(p))[0].coords)[0] for p in pts]
            rows.append({"dimension_id": _stable_id("DIM", [dim.get("handle"), dim.get("measurement")]),
                         "measurement": dim["measurement"], "measurement_m": dim["measurement"] * metres_per_unit if metres_per_unit else None,
                         "source_handle": dim.get("handle"), "definition_points": dim.get("definition_points") or [],
                         "witness_points":pts,"bound_reference_points":references,
                         "dimension_type":dim.get("dimension_type"),"text_override": dim.get("text_override"),
                         "association_basis":"TWO_BOUNDARY_WITNESS_POINTS",
                         "status": "VERIFIED_ASSOCIATION" if metres_per_unit else "INPUT_REQUIRED"})
    return rows


def _space_record(poly, frame, source_hash, extracted, metres_per_unit, excluded_label_handles=None,
                  geometry_evidence=None, label_bindings=None):
    ring = _round_points(list(poly.exterior.coords)); holes=sorted(_round_points(list(interior.coords)) for interior in poly.interiors)
    physical_id = _stable_id("PS", [source_hash, frame["frame_id"], ring, holes])
    labels, objects = _evidence_for_cell(poly, extracted)
    excluded_label_handles={str(value) for value in (excluded_label_handles or [])}
    labels=[row for row in labels if str(row.get("handle")) not in excluded_label_handles]
    unresolved_labels=[]
    if label_bindings is not None:
        bindings=list(label_bindings.values()) if isinstance(label_bindings,dict) else label_bindings
        def occurrence(row, handle_key):
            return (str(row.get(handle_key)), tuple(row.get("point") or []),
                    str(row.get("source_insert_handle") or ""), tuple(row.get("source_block_path") or []))
        allowed={occurrence(row,"source_handle") for row in bindings
                 if row.get("host_space_id")==physical_id and row.get("status")=="VERIFIED"}
        unresolved_labels=[row for row in labels if occurrence(row,"handle") not in allowed]
        labels=[row for row in labels if occurrence(row,"handle") in allowed]
    else:
        # A boundary point has no unique semantic host even for direct callers.
        unresolved_labels=[row for row in labels if not poly.contains(Point(row["point"]))]
        labels=[row for row in labels if row not in unresolved_labels]
    proof=dict(geometry_evidence or {})
    if not proof:
        # Direct callers get local source geometry evidence, never drawing-wide handles.
        segments=[]; tol=max(math.sqrt(poly.area)*1e-8,1e-8)
        for primitive in extracted.get("primitives",[]):
            if classify_source_record(primitive).get("object_class")!="ENCLOSURE_CANDIDATE": continue
            points=_primitive_points(primitive)
            if len(points)<2: continue
            pairs=list(zip(points,points[1:]))
            if primitive.get("closed"): pairs.append((points[-1],points[0]))
            for a,b in pairs:
                if a==b: continue
                line=LineString([a,b])
                if poly.boundary.buffer(tol).covers(line):
                    segments.append({"geometry":[a,b],"source_handle":primitive.get("handle"),"source_role":"SOURCE_BOUNDARY"})
        support=unary_union([LineString(row["geometry"]) for row in segments]) if segments else None
        covered=poly.boundary.intersection(support.buffer(tol)).length if support is not None else 0
        ratio=min(1.0,covered/max(poly.length,1e-12))
        proof={"status":"VERIFIED" if ratio>=1-1e-6 else "INPUT_REQUIRED",
               "source_handles":sorted({str(row["source_handle"]) for row in segments if row["source_handle"]}),
               "boundary_segments":segments,"evidence":[{"class":"PHYSICAL_BOUNDARY_SUPPORT","coverage_ratio":ratio,"segments":segments}]}
    # Serialized geometry is the downstream contract. Preserve invalid evidence
    # diagnostically; do not repair topology or promote the valid pre-rounding shape.
    serialized = Polygon(ring, holes)
    if not serialized.is_valid or serialized.is_empty or serialized.area <= 0:
        proof.update(status="INPUT_REQUIRED", candidate_role="INVALID_DIAGNOSTIC")
        proof["negative_evidence"] = sorted(set(proof.get("negative_evidence") or []) | {"SERIALIZED_POLYGON_INVALID"})
    geometry_status=proof.get("status") or "INPUT_REQUIRED"
    semantic = _infer_categories(labels, objects)
    # Service labels identify a local feature, not an arbitrarily containing roof.
    # An independently source-closed host or explicit local host proof is required.
    local_service={"duct","shaft","pipe_shaft","mechanical_shaft","electrical_shaft","lightwell","void"}
    closed_host=False
    tol=float(proof.get("tolerance") or 1e-7)
    if frame.get("frame_type")=="ROOF" and set(semantic)&local_service:
        for primitive in extracted.get("primitives",[]):
            if not primitive.get("closed") or excludes_from_wall_admission(classify_source_record(primitive)): continue
            points=_primitive_points(primitive)
            if len(points)<3: continue
            candidate=Polygon(points)
            source_kind,_=_classify_text(" ".join(str(primitive.get(key) or "") for key in ("layer","source_block","name")))
            if source_kind in local_service and candidate.is_valid and candidate.boundary.hausdorff_distance(poly.boundary)<=tol:
                closed_host=True; break
    unsupported_semantic={}
    if frame.get("frame_type")=="ROOF" and not (closed_host or proof.get("local_semantic_host_verified")):
        for kind in set(semantic)&local_service: unsupported_semantic[kind]=semantic.pop(kind)
    categories = sorted(semantic)
    zones = []
    for category in categories:
        zone_id = _stable_id("FZ", [physical_id, category])
        zones.append({"zone_id": zone_id, "physical_space_id": physical_id, "category": category,
                      "boundary_status": "explicit" if len(categories) == 1 else "approximate",
                      "polygon": ring if len(categories) == 1 else None, "evidence": semantic[category],
                      "status": "VERIFIED" if any(e["class"] == "TEXT" for e in semantic[category]) else "HIGH_CONFIDENCE"})
    category = categories[0] if len(categories) == 1 else ("open_plan" if len(categories) > 1 else "unknown")
    status = "VERIFIED" if len(categories) == 1 and zones[0]["status"] == "VERIFIED" else ("HIGH_CONFIDENCE" if len(categories) == 1 else "INPUT_REQUIRED")
    # Multiple exact labels may describe one legitimate open plan, but labels
    # for enclosed service/sleeping/vertical spaces are evidence that a real
    # separating boundary is still unresolved.  Semantic agreement must never
    # promote unresolved geometry to VERIFIED.
    open_plan_compatible={"living","reception","dining","kitchen","kitchenette","entrance","lobby"}
    incompatible=set(categories)-open_plan_compatible
    if len(categories) > 1:
        status=("VERIFIED" if not incompatible and all(z["status"] == "VERIFIED" for z in zones)
                else "INPUT_REQUIRED")
    semantic_status=status
    if unresolved_labels or unsupported_semantic: semantic_status="INPUT_REQUIRED"
    if geometry_status not in {"VERIFIED","SUPPORTED","HIGH_CONFIDENCE"} or semantic_status=="INPUT_REQUIRED":
        status="INPUT_REQUIRED"
        for zone in zones:
            zone.update(status="INPUT_REQUIRED",polygon=None,boundary_status="approximate")
    minx, miny, maxx, maxy = poly.bounds; scale = metres_per_unit
    dims = _associate_dimensions(poly, extracted["dimensions"], metres_per_unit)
    evidence = [{"class": "CAD_TOPOLOGY", "source_handles": list(proof.get("source_handles") or [])}] + list(proof.get("evidence") or [])
    evidence.extend(e for values in semantic.values() for e in values)
    return {"space_id": physical_id, "physical_space_id": physical_id, "level_id": frame.get("level_candidate"),
            "represented_level_ids": sorted(set(frame.get("represented_levels") or [])), "frame_id": frame["frame_id"],
            "category": category, "use": category, "subtype": None, "polygon": ring, "interior_rings":holes,
            "centroid": [poly.centroid.x, poly.centroid.y], "area_m2": poly.area * scale * scale if scale else None,
            "geometric_area_drawing_units": poly.area, "perimeter_m": poly.length * scale if scale else None,
            "principal_dimensions": {"width_m": (maxx-minx)*scale if scale else None, "length_m": (maxy-miny)*scale if scale else None,
                                     "source": [d["dimension_id"] for d in dims]},
            "openings": [], "windows": [], "adjacent_space_ids": [], "entrances": [], "functional_zones": zones,
            "objects": objects, "dimensions": dims, "confidence": 1.0 if status == "VERIFIED" else (.85 if status == "HIGH_CONFIDENCE" else .0),
            "status": status, "geometry_status":geometry_status, "topology_status":geometry_status,
            "semantic_status":semantic_status, "geometry_evidence":proof,
            "separator_status":proof.get("separator_status", "INPUT_REQUIRED"),
            "material_geometry":False,
            "semantic_candidates":unsupported_semantic, "unresolved_label_evidence":unresolved_labels,
            "evidence": evidence, "source_handles": list(proof.get("source_handles") or []),
            "traceability": {"source_sha256": source_hash, "frame_id": frame["frame_id"], "geometry_fingerprint": sha256(json.dumps(ring).encode()).hexdigest()}}


def _adjacency(spaces, tolerance):
    polygons = {s["physical_space_id"]: _space_polygon(s) for s in spaces}
    for left in spaces:
        p = polygons[left["physical_space_id"]]
        left["adjacent_space_ids"] = sorted(right_id for right_id, q in polygons.items()
                                                   if right_id != left["physical_space_id"] and p.distance(q) <= (tolerance or 1e-7))


def _opening_point(row):
    geometry = row.get("geometry") or {}
    if geometry.get("point"):
        return Point(geometry["point"])
    points = geometry.get("points") or []
    return LineString(points).interpolate(.5, normalized=True) if len(points) >= 2 else None


def _architectural_void_candidates(extracted, frames, source_hash, tolerance, metres_per_unit=None):
    """Qualify source-closed void footprints without granting wall/routing authority.

    A service label selects among existing closed polygons; it never supplies a
    polygon. Noncontained labels require independent source void semantics;
    repeated offsets alone cannot turn structural or drafting geometry into a void.
    """
    closed=[]
    for primitive in extracted.get("primitives") or []:
        source_record=dict(primitive)
        source_class=classify_source_record(source_record)
        if excludes_from_wall_admission(source_class): continue
        if primitive.get("entity_type") not in {"LWPOLYLINE","POLYLINE"} or not primitive.get("closed"): continue
        points=_primitive_points(primitive)
        if len(points)<3: continue
        poly=Polygon(points)
        if not poly.is_valid or poly.area<=max(float(tolerance or .001)**2*4,1e-10): continue
        ring=[(round(x,6),round(y,6)) for x,y in list(poly.exterior.coords)[:-1]]
        rotations=[ring[i:]+ring[:i] for i in range(len(ring))]
        reversed_ring=list(reversed(ring)); rotations += [reversed_ring[i:]+reversed_ring[:i] for i in range(len(ring))]
        key=tuple(min(rotations))
        closed.append((key,poly,primitive,source_class))
    dedup={}
    for key,poly,primitive,source_class in closed:
        row=dedup.setdefault(key,{"polygon":poly,"source_handles":[],"source_segments":[],"source_roles":[],"independent_void_semantics":False})
        row["source_roles"].append(source_class["object_class"])
        context=" ".join(str(primitive.get(field) or "") for field in ("layer","source_block","name"))
        kind,_=_classify_text(context)
        if kind in {"duct","shaft","pipe_shaft","mechanical_shaft","electrical_shaft","void"}:
            row["independent_void_semantics"]=True
        handle=primitive.get("handle")
        if handle and str(handle) not in row["source_handles"]: row["source_handles"].append(str(handle))
        row["source_segments"].append({"source_handle":handle,"layer":primitive.get("layer"),
                                       "block_path":primitive.get("source_block_path") or []})
    candidates=list(dedup.values())
    labels=[]
    for text_row in extracted.get("texts") or []:
        if text_row.get("pre_topology_role") == "REFERENCE_ONLY": continue
        category,_=_classify_text(text_row.get("text"))
        if category=="duct" and text_row.get("point"):
            labels.append(text_row)
    nearest=[]
    for label in labels:
        point=Point(label["point"])
        frame=next((f for f in frames if f.get("bounds") and box(*f["bounds"]).covers(point)),None)
        if frame is None: continue
        minx,miny,maxx,maxy=frame["bounds"]; local_limit=min(maxx-minx,maxy-miny)*.10
        local=[]
        for polyrow in candidates:
            poly=polyrow["polygon"]; bx1,by1,bx2,by2=poly.bounds; width=bx2-bx1; height=by2-by1
            if min(width,height)<=float(tolerance or .001): continue
            if max(width,height)>local_limit or max(width,height)/min(width,height)>4.0: continue
            if not box(*frame["bounds"]).covers(poly.representative_point()): continue
            local.append(polyrow)
        ranked=sorted(
            ((polyrow["polygon"].distance(point),polyrow) for polyrow in local),
            key=lambda item:(item[0],item[1]["polygon"].wkb_hex))
        if not ranked: continue
        distance,row=ranked[0]; second=ranked[1][0] if len(ranked)>1 else float("inf")
        scale=max(math.sqrt(row["polygon"].area),float(tolerance or .001))
        if distance>2.0*scale or second<=distance*2.0: continue
        centroid=row["polygon"].centroid
        nearest.append({"label":label,"candidate":row,"distance":distance,"second_distance":second,
                        "offset":(round(centroid.x-point.x,3),round(centroid.y-point.y,3)),
                        "contained":row["polygon"].contains(point),
                        "boundary_contact":row["polygon"].boundary.distance(point)<=float(tolerance or .001)})
    offset_counts=Counter(row["offset"] for row in nearest)
    output=[]
    for match in nearest:
        if match["boundary_contact"]: continue
        if not match["contained"] and not match["candidate"]["independent_void_semantics"]: continue
        label=match["label"]; row=match["candidate"]; poly=row["polygon"]
        frame=next((f for f in frames if f.get("bounds") and box(*f["bounds"]).covers(Point(label["point"]))),None)
        if frame is None or frame.get("scope_relevance")=="REFERENCE_ONLY": continue
        void_id=_stable_id("VOID",[source_hash,frame["frame_id"],list(poly.exterior.coords)])
        output.append({"void_id":void_id,"frame_id":frame["frame_id"],"void_type":"DUCT_VOID",
                       "boundary":[list(p) for p in poly.exterior.coords],"area":poly.area,
                       "source_handles":sorted(row["source_handles"]),"source_segments":row["source_segments"],
                       "source_roles":sorted(set(row["source_roles"])),"negative_evidence":[],
                       "association_basis":"CONTAINED_LABEL_AND_SOURCE_CLOSED_HOST" if match["contained"] else "INDEPENDENT_VOID_SOURCE_SEMANTICS",
                       "label_evidence":{"source_handle":label.get("handle"),"text":label.get("text"),
                                         "point":label.get("point"),"distance":match["distance"],
                                         "nearest_margin":match["second_distance"]-match["distance"],
                                         "repeated_offset_support":offset_counts[match["offset"]]},
                       "boundary_status":"SOURCE_CLOSED","closure_status":"NOT_REQUIRED",
                       "status":"VERIFIED","material_geometry_authority":"NONE",
                       "topology_authority":"SOURCE_CLOSED_BOUNDARY",
                       "routing_authority":"NONE","vertical_shaft_authority":"NONE"})
    return sorted(output,key=lambda row:row["void_id"])


def _bind_openings(openings, spaces, wall_lines, source_hash, tolerance, canonical_walls=None,
                   internal_wall_gaps=None):
    """Bind openings to a host wall and the spaces they connect.

    An opening with no defensible wall match is explicitly rejected.  A door
    with only one bounded side is exterior; two sides create a portal.  More
    than two candidate sides is a conflict, never an arbitrary nearest-room
    choice.
    """
    tol = max(float(tolerance or 0.001) * 3.0, 1e-6)
    polygons = {s["physical_space_id"]: _space_polygon(s) for s in spaces}
    if canonical_walls is not None:
        walls = [{"wall_id": row["wall_id"], "line": LineString(row["centerline"]), "record": row}
                 for row in canonical_walls]
    else:
        walls = [{"wall_id": _stable_id("WALL", [source_hash, _round_points(list(line.coords))]), "line": line}
                 for line in wall_lines]
    accepted = []
    for row in openings:
        point = _opening_point(row)
        if point is None:
            accepted.append({**row, "status": "REJECTED", "reason": "OPENING_GEOMETRY_MISSING"}); continue
        near_walls = sorted(((w["line"].distance(point), w) for w in walls), key=lambda pair: (pair[0], pair[1]["wall_id"]))
        if not near_walls or near_walls[0][0] > tol:
            accepted.append({**row, "status": "REJECTED", "reason": "ORPHAN_OPENING_NO_HOST_WALL"}); continue
        host = near_walls[0][1]
        # A nearby symbol is not a Portal.  It must coincide with a classified
        # interruption in the same host wall topology; this keeps furniture
        # arcs and symbols drawn over continuous walls diagnostic-only.
        compatible={"door":{"DOOR_GAP"},"window":{"WINDOW_GAP"},
                    "open_passage":{"OPEN_PASSAGE"}}.get(row.get("kind"),set())
        gap_matches=[]
        for gap in internal_wall_gaps or []:
            geometry=gap.get("geometry") or []
            if len(geometry)<2 or host["wall_id"] not in (gap.get("host_wall_ids") or []): continue
            if compatible and gap.get("classification") not in compatible: continue
            # A current review row has already been identity/fingerprint
            # validated by architectural_gap_review.  It may resolve the
            # *meaning* of an existing gap, but it never creates one.
            if gap.get("status") not in {"PROVEN","SUPPORTED","HUMAN_CONFIRMED"}: continue
            gap_line=LineString(geometry)
            limit=max(tol,float(gap.get("gap_width") or 0.0)*.75)
            if gap_line.distance(point)<=limit: gap_matches.append(gap)
        if not gap_matches:
            accepted.append({**row,"host_wall_id":host["wall_id"],"status":"REJECTED",
                             "reason":"OPENING_WITHOUT_CLASSIFIED_HOST_GAP"}); continue
        host_gap=min(gap_matches,key=lambda gap:LineString(gap["geometry"]).distance(point))
        touching = sorted(space_id for space_id, poly in polygons.items() if poly.boundary.distance(point) <= tol)
        if len(touching) > 2:
            accepted.append({**row, "host_wall_id": host["wall_id"], "status": "CONFLICT",
                             "reason": "OPENING_TOUCHES_MORE_THAN_TWO_SPACES", "candidate_space_ids": touching}); continue
        if not touching:
            accepted.append({**row, "host_wall_id": host["wall_id"], "status": "REJECTED",
                             "reason": "ORPHAN_OPENING_NO_SPACE"}); continue
        line = host["line"]; coords = list(line.coords); dx=coords[-1][0]-coords[0][0]; dy=coords[-1][1]-coords[0][1]
        orientation = round((math.degrees(math.atan2(dy, dx)) + 360.0) % 180.0, 3)
        geometry = row.get("geometry") or {}; pts = geometry.get("points") or []
        width = LineString(pts).length if len(pts) >= 2 else None
        portal_id = _stable_id("PORTAL", [source_hash, row["opening_id"], host_gap["gap_id"], host["wall_id"]])
        source_handles=sorted({str(value) for value in
                               ((row.get("source_handles") or [])+
                                ([row.get("source_handle")] if row.get("source_handle") else [])+
                                (host_gap.get("source_handles") or [])) if value})
        evidence_ids=sorted({str(item.get("evidence_id") or item.get("handle") or item.get("class"))
                             for item in row.get("evidence") or [] if item})
        bound = {**row, "portal_id":portal_id,
                 "host_wall_id": host["wall_id"], "host_gap_id":host_gap["gap_id"],
                 "level_id": next((s.get("level_id") for s in spaces if s["physical_space_id"] in touching), None),
                 "space_a": touching[0], "space_b": touching[1] if len(touching) == 2 else "EXTERIOR",
                 "orientation": orientation, "width_drawing_units": width,
                 "opening_geometry": geometry, "portal_geometry":{"points":host_gap.get("geometry")},
                 "source_handles":source_handles,"evidence_ids":evidence_ids,
                 "material_geometry_authority":"SOURCE_GAP_ONLY",
                 "status": "VERIFIED"}
        accepted.append(bound)
        key = "openings" if row["kind"] == "door" else "windows"
        for space in spaces:
            if space["physical_space_id"] in touching: space[key].append(row["opening_id"])
    return accepted, ([w["record"] for w in walls] if canonical_walls is not None else
                      [{"wall_id": w["wall_id"], "geometry": list(w["line"].coords)} for w in walls])


def _coverage(frames, spaces):
    """Measure accounted geometry over reconstructed authoritative regions."""
    per_frame=[]
    for frame in frames:
        if frame.get("scope_relevance") == "REFERENCE_ONLY" or not frame.get("bounds"): continue
        rows=[s for s in spaces if s["frame_id"] == frame["frame_id"]]
        polys=[_space_polygon(s) for s in rows]
        usable=unary_union(polys).area if polys else 0.0
        accounted=unary_union([p for p,s in zip(polys, rows) if s["status"] in {"VERIFIED","HIGH_CONFIDENCE"}]).area if polys else 0.0
        unresolved=max(0.0, usable-accounted)
        summed=sum(p.area for p in polys); overlap=max(0.0, summed-usable)
        gross=box(*frame["bounds"]).area
        unexplained=max(0.0, gross-usable)
        ratio=accounted/usable if usable else 0.0
        per_frame.append({"frame_id":frame["frame_id"], "authoritative_usable_area":usable,
                          "accounted_physical_space_area":accounted, "unresolved_area":unresolved,
                          "overlap_area":overlap, "authoritative_frame_gross_area":gross,
                          "unexplained_frame_area":unexplained, "coverage_ratio":ratio,
                          "status":"PASS" if usable and unresolved <= max(usable*1e-6, 1e-9) and overlap <= max(usable*1e-6,1e-9) else "INPUT_REQUIRED"})
    return {"status":"PASS" if per_frame and all(r["status"]=="PASS" for r in per_frame) else "INPUT_REQUIRED",
            "frames":per_frame,
            "coverage_ratio":sum(r["accounted_physical_space_area"] for r in per_frame)/sum((r["authoritative_usable_area"] for r in per_frame), start=0.0) if sum((r["authoritative_usable_area"] for r in per_frame), start=0.0) else 0.0}


def _dimension_reconciliation(spaces, metres_per_unit, tolerance, dimensions=None):
    rows=[]
    geometric_tol=max((tolerance or .001)*(metres_per_unit or 1.0), .001)
    for space in spaces:
        for dim in space.get("dimensions") or []:
            annotated=dim.get("measurement_m")
            references=dim.get("bound_reference_points") or []
            if annotated is None or len(references)!=2 or dim.get("status")!="VERIFIED_ASSOCIATION": continue
            measured=LineString(references).length*(metres_per_unit or 1.0);delta=abs(measured-annotated)
            allowed=max(geometric_tol, abs(annotated)*.005)
            rows.append({"dimension_id":dim["dimension_id"],"space_id":space["physical_space_id"],
                         "annotated_measurement_m":annotated,"geometric_measurement_m":measured,
                         "difference_m":delta,"tolerance_m":allowed,
                         "association_basis":dim["association_basis"],
                         "status":"PASS" if delta<=allowed else "CONFLICT"})
    associated_ids={row["dimension_id"] for row in rows}
    raw_count=len(dimensions or [])
    status="CONFLICT" if any(r["status"]=="CONFLICT" for r in rows) else ("PASS" if rows else "INPUT_REQUIRED")
    return {"status":status,"rows":rows,"raw_dimension_count":raw_count,
            "verified_association_count":len(associated_ids),
            "unassociated_or_not_evaluated_count":max(0,raw_count-len(associated_ids))}


def _review_payload(spaces, frames, openings, coverage, dimension_reconciliation):
    decisions=[]
    for space in spaces:
        if space["status"] in {"VERIFIED","HIGH_CONFIDENCE"}: continue
        candidates=sorted({z["category"] for z in space.get("functional_zones") or []}) or ["unknown"]
        decisions.append({"region_id":space["physical_space_id"],"frame_id":space["frame_id"],
                          "bounds":list(_space_polygon(space).bounds),"candidate_types":candidates,
                          "evidence":space.get("evidence") or [],"required":True,"status":space["status"]})
    for opening in openings:
        if opening["status"] not in {"VERIFIED","HIGH_CONFIDENCE"}:
            decisions.append({"region_id":opening["opening_id"],"frame_id":None,"candidate_types":[opening["kind"],"reject"],
                              "evidence":opening.get("evidence") or [],"required":opening["kind"]=="door",
                              "status":opening["status"],"reason":opening.get("reason")})
    return {"schema":"architectural-review/1.0","decisions":decisions,
            "verified_items_hidden":True,"blocking":any(d["required"] for d in decisions),
            "coverage":coverage,"dimension_reconciliation":dimension_reconciliation}


def _completeness(frames, spaces, units_known, *, coverage=None, openings=None,
                  dimension_reconciliation=None, subdivision_comparisons=None):
    issues = []
    for frame in frames:
        if frame.get("scope_relevance") == "MECHANICAL_AUTHORITY" and frame["frame_type"] == "UNKNOWN":
            issues.append({"code": "UNKNOWN_FRAME", "frame_id": frame["frame_id"], "status": "INPUT_REQUIRED"})
    for space in spaces:
        if space.get("material_geometry") is not True or space.get("separator_status") != "VERIFIED":
            issues.append({"code": "SEPARATOR_ROLE_REQUIRED", "space_id": space["physical_space_id"], "frame_id": space["frame_id"], "status": "INPUT_REQUIRED"})
        if space["status"] in {"INPUT_REQUIRED", "CONFLICT", "AMBIGUOUS"}:
            issues.append({"code": "UNRESOLVED_SPACE", "space_id": space["physical_space_id"], "frame_id": space["frame_id"], "status": space["status"]})
        if space["area_m2"] is None: issues.append({"code": "UNIT_CALIBRATION_REQUIRED", "space_id": space["physical_space_id"], "status": "INPUT_REQUIRED"})
    if not spaces: issues.append({"code": "NO_PHYSICAL_SPACES_RECONSTRUCTED", "status": "INPUT_REQUIRED"})
    if coverage and coverage.get("status") != "PASS":
        issues.append({"code":"ARCHITECTURAL_GEOMETRIC_COVERAGE_INCOMPLETE","status":"INPUT_REQUIRED"})
    for opening in openings or []:
        if opening.get("kind") == "door" and opening.get("status") != "VERIFIED":
            issues.append({"code":"UNRESOLVED_CRITICAL_DOOR","opening_id":opening.get("opening_id"),"status":"INPUT_REQUIRED"})
    if dimension_reconciliation and dimension_reconciliation.get("status") == "CONFLICT":
        issues.append({"code":"ENGINEERING_DIMENSION_CONFLICT","status":"CONFLICT"})
    governed={frame["frame_id"] for frame in frames
              if frame.get("scope_relevance")=="MECHANICAL_AUTHORITY"}
    for comparison in subdivision_comparisons or []:
        if (comparison.get("frame_id") in governed and
                comparison.get("selected_authority")!="CANONICAL"):
            issues.append({"code":"CANONICAL_TOPOLOGY_REQUIRED",
                           "frame_id":comparison.get("frame_id"),
                           "selected_authority":comparison.get("selected_authority"),
                           "status":"INPUT_REQUIRED"})
    conflicts = [x for x in issues if x["status"] == "CONFLICT"]
    status = "CONFLICT" if conflicts else ("INPUT_REQUIRED" if issues or not units_known else "VERIFIED")
    return {"status": status, "release_allowed": status == "VERIFIED", "downstream_engineering_allowed": status == "VERIFIED",
            "issues": issues, "relevant_space_count": len(spaces), "verified_space_count": sum(s["status"] == "VERIFIED" for s in spaces),
            "input_required_count": sum(x["status"] == "INPUT_REQUIRED" for x in issues)}


def recognition_svg(model):
    frames = model.get("frames") or []; spaces = model.get("physical_spaces") or []
    bounds = next((f["bounds"] for f in frames if f.get("bounds")), [0,0,1,1]); minx,miny,maxx,maxy=bounds
    width=max(maxx-minx,1); height=max(maxy-miny,1)
    rows=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{minx} {-maxy} {width} {height}">',
          '<style>.s{fill-opacity:.22;stroke-width:.006;vector-effect:non-scaling-stroke}.t{font-size:14px;paint-order:stroke;stroke:white;stroke-width:3px}</style>']
    colors={"VERIFIED":"#159f74","HIGH_CONFIDENCE":"#2563eb","INPUT_REQUIRED":"#d89000","CONFLICT":"#d43f3a","AMBIGUOUS":"#a855f7"}
    for space in spaces:
        pts=" ".join(f"{x},{-y}" for x,y in space["polygon"]); color=colors.get(space["status"],"#6b7280")
        rows.append(f'<polygon class="s" points="{pts}" fill="{color}" stroke="{color}"/>')
        x,y=space["centroid"]; area="?" if space["area_m2"] is None else f'{space["area_m2"]:.2f} m²'
        rows.append(f'<text class="t" x="{x}" y="{-y}" fill="#111827">{space["physical_space_id"][-6:]} · {space["category"]} · {area}</text>')
    rows.append('</svg>'); return "".join(rows)


def reconstruct_architecture(path, *, vision_adapter: VisionAdapter | None = None,
                             gap_review_manifest: dict | None = None):
    started = time.perf_counter(); stage_started=started; timings={}
    doc, source = _ingest(path); extracted = _extract(doc, source["source_sha256"]); timings["parsing"]=time.perf_counter()-stage_started
    stage_started=time.perf_counter()
    fallback = _frame_from_extent(extracted, source["source_sha256"])
    frames = _detected_frames(path, source["source_sha256"], fallback)
    source = _calibrate_scale(source, frames, extracted["dimensions"])
    tolerance = _adaptive_tolerance(extracted["boundary_lines"], source["metres_per_unit"])
    timings["frame_and_scale_resolution"]=time.perf_counter()-stage_started; stage_started=time.perf_counter()
    spaces = []; segment_records=[]; accepted_wall_lines=[]; rejected_cells=[]; refinement_decisions=[]; refinement_iterations=[]
    canonical_walls=[]; wall_junctions=[]; thickness_clusters=[]; building_envelopes=[]
    gap_review_validation={"accepted_review_decisions":[],"stale_review_decisions":[],
                           "rejected_review_decisions":[],"review_application_status":"NOT_PROVIDED"}; applied_gap_reviews=[]
    envelope_candidate_diagnostics=[]; plan_regions=[]
    subdivision_results=[]; subdivision_comparisons=[]; wall_admission_funnels=[]; continuity_results=[]
    pre_envelope_opening_evidence=[]; opening_source_inventories=[]; pre_envelope_geometric_candidates=[]
    internal_wall_gaps=[]
    source_role_diagnostics=annotate_source_roles(extracted,frames,source["metres_per_unit"],tolerance)
    pre_topology_objects=standardize_source_records(extracted["primitives"])
    architectural_voids=_architectural_void_candidates(extracted,frames,source["source_sha256"],tolerance,metres_per_unit=source["metres_per_unit"])
    void_label_handles={str(row["label_evidence"]["source_handle"]) for row in architectural_voids
                        if row.get("label_evidence",{}).get("source_handle")}
    explicit_opening_candidates=_opening_candidates(extracted,source["source_sha256"])
    enclosure_candidate_diagnostics = []
    for frame in frames:
        if frame.get("scope_relevance") == "REFERENCE_ONLY":
            continue
        if frame.get("frame_type") in {"SECTION","ELEVATION","DETAIL"}:
            # A closed detail/section cycle is not a floor merely because it
            # can be subdivided.  Keep non-plan views out of Physical Spaces.
            continue
        clip=box(*frame["bounds"]) if frame.get("bounds") else None
        local_lines=[]; local_metas=[]
        for line,meta in zip(extracted["boundary_lines"],extracted["boundary_meta"]):
            if clip is None or not line.intersects(clip): continue
            clipped=line.intersection(clip)
            if clipped.geom_type=="LineString" and not clipped.is_empty: local_lines.append(clipped); local_metas.append(meta)
            elif clipped.geom_type=="MultiLineString":
                for geometry in clipped.geoms:
                    if not geometry.is_empty: local_lines.append(geometry); local_metas.append(meta)
        frame_local_boundary_count=len(local_lines)
        local_lines,local_metas,sheet_border_records=_exclude_inset_sheet_border_segments(
            local_lines,local_metas,frame,tolerance)
        classified,accepted=_semantic_segment_classification(local_lines,local_metas,source["metres_per_unit"],tolerance)
        seed_accepted_count=len(accepted); provisional_count=sum(r["status"]=="PROVISIONAL" for r in classified)
        rejected_unknown_count=sum(r["status"]=="REJECTED" for r in classified)+len(sheet_border_records)
        for record in classified: record["frame_id"]=frame["frame_id"]
        accepted,decisions,iterations=_recover_supported_partitions(accepted,classified,frame,tolerance,extracted,source["metres_per_unit"])
        for record in sheet_border_records: record["frame_id"]=frame["frame_id"]
        classified.extend(sheet_border_records)
        for row in decisions: row["frame_id"]=frame["frame_id"]
        for row in iterations: row["frame_id"]=frame["frame_id"]
        refinement_decisions.extend(decisions); refinement_iterations.extend(iterations)
        segment_records.extend(classified); accepted_wall_lines.extend(accepted)
        wall_result=reconstruct_canonical_walls(classified,frame_id=frame["frame_id"],tolerance=tolerance,
                                                metres_per_unit=source["metres_per_unit"])
        frame_walls=wall_result["walls"]
        segments_by_id={row["segment_id"]:row for row in classified}
        for wall in frame_walls:
            origins=[segments_by_id[sid] for sid in wall.get("source_fragments") or [] if sid in segments_by_id]
            wall["source_roles"]=sorted({(row.get("pre_topology_classification") or {}).get("topology_role","UNRESOLVED") for row in origins})
            wall["source_classifications"]=[row["pre_topology_classification"] for row in origins if row.get("pre_topology_classification")]
            wall["negative_evidence"]=sorted({value for row in origins for value in row.get("negative_evidence") or []})
        canonical_walls.extend(frame_walls); wall_junctions.extend(wall_result["junctions"])
        thickness_clusters.extend(wall_result["thickness_clusters"])
        opening_source_inventories.append(_opening_source_inventory(extracted,frame,source["metres_per_unit"]))
        frame_geometric_candidates=_geometric_door_candidates(
            extracted,accepted,source["source_sha256"],tolerance,source["metres_per_unit"],frame.get("bounds"))
        pre_envelope_geometric_candidates.extend(frame_geometric_candidates)
        frame_opening_candidates=list({row["opening_id"]:row for row in
                                       explicit_opening_candidates+frame_geometric_candidates}.values())
        frame_opening_evidence=_pre_envelope_opening_evidence(
            frame_opening_candidates,frame_walls,frame,tolerance=tolerance)
        pre_envelope_opening_evidence.extend(frame_opening_evidence)
        def in_frame_geometry(row):
            geometry=row.get("geometry") or _primitive_points(row)
            return len(geometry)>=2 and (clip is None or LineString(geometry).intersects(clip))
        raw_frame_count=sum(p.get("entity_type") in {"LINE","LWPOLYLINE","POLYLINE","ARC","SPLINE"} and in_frame_geometry(p) for p in extracted["primitives"])
        extraction_rows=[row for row in extracted.get("boundary_rejections") or [] if in_frame_geometry(row)]
        wall_admission_funnels.append({"frame_id":frame["frame_id"],"raw_dxf_linear_curve":raw_frame_count,
                                       "frame_local_boundary_geometry":frame_local_boundary_count,
                                       "inset_print_border_rejected":len(sheet_border_records),
                                       "boundary_admission_rejected":len(extraction_rows),
                                       "boundary_rejection_reasons":dict(Counter(row["reason"] for row in extraction_rows)),
                                       "glyph_noise_excluded":sum(row["reason"]=="GLYPH_FILTER" for row in extraction_rows),
                                       "semantic_high_confidence_accepted":seed_accepted_count,
                                       "semantic_supported_provisional":provisional_count,
                                       "semantic_rejected_unknown":rejected_unknown_count,
                                       "recovery_admitted":len(accepted)-seed_accepted_count,
                                       "final_admitted_segment":len(accepted),
                                       "canonical_wall_object":len(frame_walls),
                                       "barrier_graph_segment_input":len(frame_walls)})
        frame_labels=[]
        for text in extracted["texts"]:
            if text.get("pre_topology_role") == "REFERENCE_ONLY": continue
            if not _is_space_label_record(text):
                continue
            point=text.get("point")
            if not point or (clip is not None and not clip.buffer(tolerance).covers(Point(point))): continue
            category,_=_classify_text(text.get("text"))
            if category: frame_labels.append({"source_handle":text.get("handle"),"text":text.get("text"),
                                               "point":point,"semantic_candidate":category})
        frame_objects=[row for row in extracted["objects"] if row.get("point") and (clip is None or clip.buffer(tolerance).covers(Point(row["point"])))]
        continuity=canonical_enclosure_continuity(frame_walls,frame_id=frame["frame_id"])
        endpoint_closures=source_supported_endpoint_closures(
            frame_walls,frame_id=frame["frame_id"],tolerance=tolerance)
        all_closures=continuity+endpoint_closures
        frame_gaps=classify_internal_wall_gaps(
            frame_walls,all_closures,frame_opening_evidence,
            frame_id=frame["frame_id"],tolerance=tolerance)
        internal_wall_gaps.extend(frame_gaps)
        if gap_review_manifest and gap_review_manifest.get("frame_id")==frame["frame_id"]:
            reviewed_gap_ids={row.get("gap_id") for row in gap_review_manifest.get("questions") or []}
            current_review=build_review_manifest(
                source_sha256=source["source_sha256"],frame_id=frame["frame_id"],
                dependency_engine_sha=gap_review_manifest.get("dependency_engine_sha") or "",
                gaps=[row for row in frame_gaps if row["gap_id"] in reviewed_gap_ids],walls=frame_walls)
            validation=validate_review_decisions(gap_review_manifest,current_review)
            for key in ("accepted_review_decisions","stale_review_decisions","rejected_review_decisions"):
                gap_review_validation[key].extend(validation[key])
            gap_review_validation["review_application_status"]=validation["review_application_status"]
            applied_gap_reviews.extend(apply_review_decisions(frame_gaps,all_closures,validation))
        promoted=[row for row in all_closures if "ENVELOPE_SUPPORT" in row.get("roles",[])]
        subdivision_promoted=[row for row in all_closures
                              if "ENCLOSURE_BARRIER" in row.get("roles",[])
                              if row.get("gap_classification") in
                                 {"DOOR_GAP","WINDOW_GAP","OPEN_PASSAGE","MISSING_WALL_GEOMETRY",
                                  "DRAFTING_BREAK","HUMAN_CONFIRMED_CONTINUITY"}
                              and row.get("gap_status") in {"PROVEN","SUPPORTED","HUMAN_CONFIRMED"}]
        continuity_results.extend(all_closures)
        envelope,envelope_diagnostic,frame_regions=evidence_based_building_envelope(
            frame_walls,frame_id=frame["frame_id"],tolerance=tolerance,
            semantic_labels=frame_labels,objects=frame_objects,junctions=wall_result["junctions"],
            enclosure_closures=promoted)
        envelope_candidate_diagnostics.append(envelope_diagnostic); plan_regions.extend(frame_regions)
        building_envelopes.append(envelope)
        # Preserve a measured legacy result for internal comparison.  It is
        # never allowed to silently replace a valid canonical subdivision.
        topology_lines=[LineString(w["centerline"]) for w in frame_walls]
        legacy_polygons = _polygonize_spaces(topology_lines or accepted, frame, tolerance)
        if not legacy_polygons and topology_lines:
            # Fail closed to the already classified CAD boundaries when a
            # canonical graph is not yet a closed cycle (for example an
            # isolated rotated outline).  This preserves existing valid
            # geometry without claiming a canonical envelope was proven.
            legacy_polygons = _polygonize_spaces(accepted, frame, tolerance)
        frame_voids=[row for row in architectural_voids if row["frame_id"]==frame["frame_id"] and row["status"]=="VERIFIED"]
        subdivision=canonical_space_subdivision(frame_walls,envelope,frame_id=frame["frame_id"],tolerance=tolerance,
                                                void_boundaries=[row["boundary"] for row in frame_voids],
                                                enclosure_closures=subdivision_promoted)
        subdivision_results.append(subdivision)
        canonical_polygons=[Polygon(row["physical_polygon"],row.get("interior_rings") or []) for row in subdivision["cells"]]
        overlap=sum(canonical_polygons[i].intersection(canonical_polygons[j]).area
                    for i in range(len(canonical_polygons)) for j in range(i+1,len(canonical_polygons)))
        canonical_valid=(subdivision["authority"]=="CANONICAL" and bool(canonical_polygons)
                         and overlap<=max(tolerance*tolerance,1e-12))
        polygons=canonical_polygons if canonical_valid else legacy_polygons
        subdivision_comparisons.append({"frame_id":frame["frame_id"],"legacy_cell_count":len(legacy_polygons),
                                        "canonical_cell_count":len(canonical_polygons),"canonical_overlap_area":overlap,
                                        "selected_authority":"CANONICAL" if canonical_valid else "LEGACY_FALLBACK",
                                        "canonical_status":subdivision["status"],"canonical_reason":subdivision.get("reason")})
        polygons,rejected=_filter_wall_solid_cells(polygons,classified,extracted,source["metres_per_unit"],
                                                   canonical_walls=frame_walls,tolerance=tolerance)
        for row in rejected: row["frame_id"]=frame["frame_id"]
        rejected_cells.extend(rejected)
        def filter_source_candidates(cells):
            kept, discarded = _filter_wall_solid_cells(cells, classified, extracted, source["metres_per_unit"],
                                                       canonical_walls=frame_walls, tolerance=tolerance)
            for row in discarded: row["frame_id"] = frame["frame_id"]
            rejected_cells.extend(discarded)
            return kept
        polygons, candidate_diagnostic = reconcile_enclosure_candidates(
            polygons, classified, frame_walls, subdivision_promoted, tolerance, frame["frame_id"],
            candidate_filter=filter_source_candidates)
        enclosure_candidate_diagnostics.append(candidate_diagnostic)
        candidate_by_geometry = {Polygon(row["polygon"], row["interior_rings"]).normalize().wkb_hex: row
                                 for row in candidate_diagnostic["candidates"] if row["selected"]}
        serializable_polygons = []
        for polygon in polygons:
            ring = _round_points(list(polygon.exterior.coords))
            holes = sorted(_round_points(list(h.coords)) for h in polygon.interiors)
            try:
                serialized = Polygon(ring, holes)
                valid_serialization = serialized.is_valid and not serialized.is_empty and serialized.area > 0
            except (TypeError, ValueError):
                valid_serialization = False
            if valid_serialization:
                serializable_polygons.append(polygon)
            else:
                candidate = candidate_by_geometry[polygon.normalize().wkb_hex]
                candidate.update(selected=False, candidate_role="INVALID_DIAGNOSTIC",
                                 selection_reason="SERIALIZED_POLYGON_INVALID",
                                 serialized_polygon=ring, serialized_interior_rings=holes,
                                 candidate_integrity={"status": "CONFLICT", "reason": "SERIALIZED_POLYGON_INVALID"})
        polygons = serializable_polygons
        candidate_diagnostic["selected_count"] = len(polygons)
        provisional_spaces=[{"physical_space_id":_stable_id("PS",[source["source_sha256"],frame["frame_id"],
            _round_points(list(p.exterior.coords)),sorted(_round_points(list(h.coords)) for h in p.interiors)]),
            "polygon":_round_points(list(p.exterior.coords)),
            "interior_rings":sorted(_round_points(list(h.coords)) for h in p.interiors)} for p in polygons]
        frame_bindings=_label_bindings(provisional_spaces,extracted["texts"],tolerance)
        for polygon in polygons:
            candidate = candidate_by_geometry[polygon.normalize().wkb_hex]
            proof = {**candidate["boundary_evidence"], "candidate_id": candidate["candidate_id"],
                     "candidate_role": candidate["candidate_role"]}
            space = _space_record(polygon, frame, source["source_sha256"], extracted, source["metres_per_unit"],
                                  excluded_label_handles=void_label_handles, geometry_evidence=proof,
                                  label_bindings=frame_bindings)
            space.update(candidate_id=candidate["candidate_id"], candidate_role=space["geometry_evidence"].get("candidate_role", proof["candidate_role"]))
            spaces.append(space)
    timings["polygonization_and_semantics"]=time.perf_counter()-stage_started; stage_started=time.perf_counter()
    spaces.sort(key=lambda s: s["physical_space_id"]); _adjacency(spaces, tolerance)
    label_bindings=_label_bindings(spaces,extracted["texts"],tolerance)
    opening_candidates=list(explicit_opening_candidates)
    opening_candidates.extend(pre_envelope_geometric_candidates)
    opening_candidates=list({row["opening_id"]:row for row in opening_candidates}.values())
    openings,walls=_bind_openings(opening_candidates,spaces,accepted_wall_lines,source["source_sha256"],tolerance,
                                  canonical_walls=canonical_walls,internal_wall_gaps=internal_wall_gaps)
    timings["topology"]=time.perf_counter()-stage_started; stage_started=time.perf_counter()
    coverage=_coverage(frames,spaces)
    dimension_reconciliation=_dimension_reconciliation(spaces,source["metres_per_unit"],tolerance,
                                                        extracted["dimensions"])
    completeness = _completeness(frames, spaces, source["metres_per_unit"] is not None,
                                 coverage=coverage,openings=openings,
                                 dimension_reconciliation=dimension_reconciliation,
                                 subdivision_comparisons=subdivision_comparisons)
    timings["qa_and_completeness"]=time.perf_counter()-stage_started; stage_started=time.perf_counter()
    unresolved = [{"space_id": s["physical_space_id"], "bounds": list(_space_polygon(s).bounds)}
                  for s in spaces if s["status"] != "VERIFIED"]
    envelope_by_frame={row.get("frame_id"):row for row in building_envelopes}
    governed_frames={frame["frame_id"] for frame in frames
                     if "governed_print_frame_detector" in (frame.get("evidence") or [])}
    hybrid_frame_ids={row["frame_id"] for row in subdivision_comparisons
                      if row.get("selected_authority")=="LEGACY_FALLBACK"
                      and row.get("canonical_reason")=="CANONICAL_BUILDING_ENVELOPE_UNPROVEN"
                      and row["frame_id"] in governed_frames
                      and (envelope_by_frame.get(row["frame_id"]) or {}).get("reason")==
                          "INSUFFICIENT_INDEPENDENT_INTERIOR_EVIDENCE"}
    if not unresolved:
        vision = {"provider":"NONE","calls":0,"candidates":[],"status":"NOT_REQUIRED",
                  "policy":"DETERMINISTIC_FIRST_BOUNDED_GLOBAL_THEN_LOCAL","regions":[]}
    else:
        # Imported lazily to keep deterministic CAD ingestion independent from
        # the optional network provider and to avoid a second DXF parse.
        from .architectural_vision_recovery import recover_semantics
        vision = recover_semantics(extracted=extracted,frames=frames,spaces=spaces,
                                   source_hash=source["source_sha256"],segments=segment_records,
                                   tolerance=tolerance,adapter=vision_adapter,canonical_walls=canonical_walls,
                                   hybrid_frame_ids=hybrid_frame_ids)
        vision["regions"] = unresolved
        # Vision can add semantic evidence only.  Every engineering gate is
        # recalculated from the fused canonical model; the provider cannot set
        # completeness or release state directly.
        spaces.sort(key=lambda s:s["physical_space_id"]); _adjacency(spaces,tolerance)
        label_bindings=_label_bindings(spaces,extracted["texts"],tolerance)
        openings,walls=_bind_openings(opening_candidates,spaces,accepted_wall_lines,
                                      source["source_sha256"],tolerance,canonical_walls=canonical_walls,
                                      internal_wall_gaps=internal_wall_gaps)
        coverage=_coverage(frames,spaces)
        dimension_reconciliation=_dimension_reconciliation(spaces,source["metres_per_unit"],tolerance,
                                                            extracted["dimensions"])
        completeness=_completeness(frames,spaces,source["metres_per_unit"] is not None,
                                   coverage=coverage,openings=openings,
                                   dimension_reconciliation=dimension_reconciliation,
                                   subdivision_comparisons=subdivision_comparisons)
        hybrid_frames=((vision.get("hybrid_recovery") or {}).get("frames") or [])
        if hybrid_frames:
            material_questions=[question for result in hybrid_frames for question in result.get("human_questions") or []]
            if material_questions:
                vision["status"]="READY_FOR_USER_TEST_TARGETED_ARCHITECTURE_CONFIRMATION"
                vision["human_questions"]=material_questions
            elif all(result.get("status")=="PASS" for result in hybrid_frames):
                vision["status"]="FASIHI_GROUND_HYBRID_ARCHITECTURE_PASS"
            else:
                vision["status"]="FASIHI_HYBRID_ARCHITECTURE_STILL_BLOCKED"
        elif vision.get("status") == "COMPLETE" and completeness["status"] != "VERIFIED":
            remaining=[s for s in spaces if s["status"] not in {"VERIFIED","HIGH_CONFIDENCE"}]
            limit=int(os.getenv("ARCH_VISION_MAX_TARGETED_QUESTIONS") or 3)
            material_ratio=len(remaining)/max(len(spaces),1)
            if remaining and len(remaining)<=limit and material_ratio<=float(os.getenv("ARCH_VISION_MAX_QUESTION_RATIO") or .15):
                vision["status"]="TARGETED_HUMAN_DECISION"
                vision["human_questions"]=[{"space_id":s["physical_space_id"],"frame_id":s["frame_id"],
                                             "question_type":"SEMANTIC_CHOICE","candidate_types":["unknown"],
                                             "reason":"IRREDUCIBLE_SOURCE_AMBIGUITY"} for s in remaining]
            else:
                vision["status"]="AUTOMATED_RECONSTRUCTION_INSUFFICIENT"
                vision["human_questions"]=[]
            vision["remaining_unresolved_spaces"]=len(remaining)
            vision["remaining_unresolved_ratio"]=material_ratio
    timings["vision_recovery"]=time.perf_counter()-stage_started
    rooms = []
    for space in spaces:
        if space["functional_zones"]:
            for zone in space["functional_zones"]:
                rooms.append({"id": zone["zone_id"], "physical_space_id": space["physical_space_id"], "type": zone["category"],
                              "polygon": space["polygon"], "area": space["geometric_area_drawing_units"], "centroid": space["centroid"],
                              "evidence": zone["evidence"], "status": zone["status"], "plan_id": space["frame_id"]})
        else:
            rooms.append({"id": space["physical_space_id"], "type": "unknown", "polygon": space["polygon"],
                          "area": space["geometric_area_drawing_units"], "centroid": space["centroid"], "evidence": space["evidence"],
                          "status": "INPUT_REQUIRED", "plan_id": space["frame_id"]})
    text_evidence = bind_text_hosts(extracted["text_evidence"], frames=frames, spaces=spaces, tolerance=tolerance)
    for space in spaces:
        space["functional_composition"] = functional_composition(text_evidence, space["physical_space_id"])
        space["text_evidence_ids"] = sorted(
            item["text_evidence_id"] for item in text_evidence.get("items") or []
            if (item.get("host_binding") or {}).get("host_id") == space["physical_space_id"]
        )
    title_block_fields = build_title_block_fields(text_evidence)
    review=_review_payload(spaces,frames,openings,coverage,dimension_reconciliation)
    enclosure_edges=sorted({tuple(sorted((space["physical_space_id"],adjacent))) for space in spaces
                            for adjacent in space.get("adjacent_space_ids") or []})
    access_edge_records=[]
    for opening in openings:
        if opening.get("status")!="VERIFIED" or opening.get("kind") not in {"door","open_passage"}: continue
        if not opening.get("space_a") or not opening.get("space_b"): continue
        access_edge_records.append({"portal_id":opening.get("portal_id"),"gap_id":opening.get("host_gap_id"),
                                    "host_wall_id":opening.get("host_wall_id"),
                                    "space_a":opening["space_a"],"space_b":opening["space_b"],
                                    "source_handles":opening.get("source_handles") or [],
                                    "evidence_ids":opening.get("evidence_ids") or []})
    access_edge_records.sort(key=lambda row:(row.get("portal_id") or "",row["space_a"],row["space_b"]))
    access_nodes=sorted({s["physical_space_id"] for s in spaces}|
                        {side for row in access_edge_records for side in (row["space_a"],row["space_b"])})
    model = {"schema": SCHEMA, "source": source, "frames": frames, "levels": [], "physical_spaces": spaces,
             "functional_zones": [z for s in spaces for z in s["functional_zones"]], "architectural_objects": extracted["objects"],
             "architectural_voids":{"schema":"canonical-architectural-void/1.0","items":architectural_voids},
             "dimensions": extracted["dimensions"], "dimension_reconciliation":dimension_reconciliation,
             "openings":openings,"canonical_walls":walls,"wall_junctions":wall_junctions,
             "wall_thickness_clusters":thickness_clusters,"building_envelopes":building_envelopes,
             "building_envelope_candidates":envelope_candidate_diagnostics,
             "plan_regions":{"schema":"canonical-plan-region-graph/1.0","regions":plan_regions},
             "region_coverage":{"schema":"architectural-region-coverage/1.0",
                                "status":"PASS" if building_envelopes and all(e.get("status") in {"VERIFIED","HIGH_CONFIDENCE"} for e in building_envelopes) else "INPUT_REQUIRED",
                                "building_interior_area":sum(r["area"] for r in plan_regions if r["role"]=="BUILDING_INTERIOR"),
                                "accounted_building_interior_area":sum(r["area"] for r in plan_regions if r["role"]=="BUILDING_INTERIOR" and r["status"] in {"VERIFIED","HIGH_CONFIDENCE"}),
                                "unexplained_building_interior_area":sum(r["area"] for r in plan_regions if r["role"]=="UNKNOWN"),
                                "semi_exterior_area":sum(r["area"] for r in plan_regions if r["role"]=="SEMI_EXTERIOR"),
                                "semi_exterior_accounted_area":sum(r["area"] for r in plan_regions if r["role"]=="SEMI_EXTERIOR" and r["status"] in {"VERIFIED","HIGH_CONFIDENCE"}),
                                "site_exterior_area":sum(r["area"] for r in plan_regions if r["role"]=="SITE_EXTERIOR"),
                                "overlap_area":0.0},
             "label_bindings":label_bindings,
             "text_evidence":text_evidence,
             "title_block_fields":title_block_fields,
             "source_role_diagnostics":source_role_diagnostics,
             "pre_topology_object_standardization":{"schema":"pre-topology-architectural-object-standardization/1.0",
                                                      "items":pre_topology_objects,
                                                      "enclosure_authority":"NONE",
                                                      "stage":"BEFORE_WALL_ADMISSION_AND_POLYGONIZATION"},
             "architectural_segments":segment_records,
             "topology_refinement":{"decisions":refinement_decisions,"iterations":refinement_iterations},
             "wall_admission_funnel":wall_admission_funnels,
             "boundary_extraction_rejections":extracted.get("boundary_rejections") or [],
             "enclosure_continuity":{"schema":"canonical-enclosure-continuity/1.0","closures":continuity_results},
             "pre_envelope_opening_evidence":{"schema":"pre-envelope-opening-evidence/1.0",
                                                "items":pre_envelope_opening_evidence,
                                                "source_inventories":opening_source_inventories,
                                                "authority":"SUPPORTING_EVIDENCE_ONLY"},
             "internal_wall_gaps":{"schema":"canonical-internal-wall-gap/1.0",
                                    "items":internal_wall_gaps,
                                    "classification_precedes_closure":True},
             "gap_human_review":{"schema":"architectural-human-gap-review-result/1.0",
                                 **gap_review_validation,"applied_decisions":applied_gap_reviews,
                                 "authority":"TOPOLOGY_CLASSIFICATION_ONLY"},
             "virtual_opening_closures":[row for result in subdivision_results for row in result.get("closures",[])],
             "enclosure_barrier_graph":{"schema":"canonical-enclosure-barrier-graph/1.0",
                                         "barriers":[row for result in subdivision_results for row in result.get("barriers",[])],
                                         "edges":[row for result in subdivision_results for row in result.get("edges",[])],
                                         "noded":all(result.get("noded") is True for result in subdivision_results)},
             "space_subdivision":{"schema":"canonical-space-subdivision/1.0",
                                  "comparisons":subdivision_comparisons,
                                  "authority":"CANONICAL" if subdivision_comparisons and all(row["selected_authority"]=="CANONICAL" for row in subdivision_comparisons) else "MIXED_OR_LEGACY_FALLBACK"},
             "exterior_face":{"face_id":"EXTERIOR","type":"UNBOUNDED_REGION","status":"CANONICAL"},
             "enclosure_graph":{"nodes":[s["physical_space_id"] for s in spaces]+["EXTERIOR"],"edges":[list(row) for row in enclosure_edges]},
             "access_graph":{"schema":"canonical-access-graph/1.0","nodes":access_nodes,
                              "edges":access_edge_records,
                              "legacy_space_pairs":sorted({tuple(sorted((row["space_a"],row["space_b"])))
                                                           for row in access_edge_records})},
             "enclosure_candidates":enclosure_candidate_diagnostics,
             "rejected_candidate_cells":rejected_cells,"coverage":coverage,"review":review,
             "completeness": completeness, "vision_reconciliation": vision,
             "hybrid_architecture":vision.get("hybrid_recovery"),
             "diagnostics": {"entity_counts": extracted["entity_counts"], "adaptive_tolerance": tolerance,
                             "raw_boundary_segment_count":len(extracted["boundary_lines"]),
                             "accepted_wall_segment_count":sum(r["status"]=="ACCEPTED" for r in segment_records),
                             "canonical_wall_count":len(canonical_walls),"wall_junction_count":len(wall_junctions),
                             "space_candidate_count": len(spaces), "stage_runtime_seconds":{k:round(v,6) for k,v in timings.items()},
                             "dxf_parse_count":1,"runtime_seconds": round(time.perf_counter()-started,6)},
             # Backward-compatible projection; canonical consumers use fields above.
             "version": SCHEMA, "units": source["insunits"], "bounds": fallback["bounds"], "rooms": rooms,
             "walls": [{"start": list(line.coords)[0], "end": list(line.coords)[-1]} for line in extracted["boundary_lines"]],
             "doors": [o for o in openings if o["kind"]=="door"], "windows":[o for o in openings if o["kind"]=="window"], "columns": [],
             "shafts": [{"void_id":row["void_id"],"void_type":row["void_type"],"polygon":row["boundary"],
                         "centroid":list(Polygon(row["boundary"]).centroid.coords)[0],"area":row["area"],
                         "source_handles":row["source_handles"],"routing_authority":"NONE"}
                        for row in architectural_voids if row["status"]=="VERIFIED"],
             "all_inserts": extracted["objects"], "all_texts": legacy_text_records(text_evidence),
             "quality": {"room_count": len(rooms), "rooms_with_polygon": len(rooms), "wall_segments": len(extracted["boundary_lines"]),
                         "canonical_space_count": len(spaces), "status": completeness["status"]}}
    model["recognition_preview_svg"] = recognition_svg(model)
    return model


def require_complete_architecture(model):
    completeness = (model or {}).get("completeness") or {}
    if completeness.get("downstream_engineering_allowed") is not True:
        return {"status": "INPUT_REQUIRED", "allowed": False, "issues": completeness.get("issues") or [
            {"code": "CANONICAL_ARCHITECTURE_MODEL_REQUIRED", "status": "INPUT_REQUIRED"}]}
    return {"status": "PASS", "allowed": True, "issues": []}
