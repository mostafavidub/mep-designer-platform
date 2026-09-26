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
import re
import time

import ezdxf
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import polygonize, unary_union


SCHEMA = "canonical-architectural-model/1.0"
STATUSES = {"VERIFIED", "HIGH_CONFIDENCE", "AMBIGUOUS", "INPUT_REQUIRED", "CONFLICT", "REJECTED"}

SPACE_ONTOLOGY = {
    "bedroom": ("bedroom", "bed room", "اتاق خواب", "خواب"),
    "master_bedroom": ("master bedroom", "master", "اتاق مستر", "خواب مستر"),
    "living": ("living", "family living", "نشیمن"),
    "reception": ("reception", "پذیرایی"),
    "dining": ("dining", "ناهارخوری", "غذاخوری"),
    "kitchen": ("kitchen", "آشپزخانه"),
    "kitchenette": ("kitchenette", "آبدارخانه"),
    "bathroom": ("bathroom", "bath", "حمام"),
    "shower": ("shower", "دوش"),
    "toilet": ("toilet", "w.c", "wc", "دستشویی", "توالت", "سرویس"),
    "entrance": ("entrance", "entry", "ورودی"),
    "vestibule": ("vestibule", "هشتی"),
    "shoe_area": ("shoe area", "کفش کن", "کفش‌کن"),
    "corridor": ("corridor", "hallway", "راهرو"),
    "lobby": ("lobby", "لابی"),
    "closet": ("closet", "wardrobe", "کمد"),
    "storage": ("storage", "store", "انباری"),
    "laundry": ("laundry", "رختشویخانه", "لباسشویی"),
    "utility": ("utility", "خدمات"),
    "stair": ("stair", "stairs", "پله", "راه پله", "راه‌پله"),
    "stair_landing": ("stair landing", "پاگرد"),
    "elevator": ("elevator", "lift", "آسانسور"),
    "elevator_lobby": ("elevator lobby", "لابی آسانسور"),
    "shaft": ("shaft", "شفت"),
    "duct": ("duct", "داکت"),
    "pipe_shaft": ("pipe shaft", "شفت لوله"),
    "mechanical_shaft": ("mechanical shaft", "شفت مکانیک"),
    "electrical_shaft": ("electrical shaft", "شفت برق"),
    "void": ("void", "بازشو", "فضای خالی"),
    "balcony": ("balcony", "بالکن"),
    "terrace": ("terrace", "تراس"),
    "patio": ("patio", "حیاط خلوت"),
    "yard": ("yard", "حیاط"),
    "backyard": ("backyard", "حیاط پشتی"),
    "lightwell": ("lightwell", "نورگیر"),
    "roof_terrace": ("roof terrace", "تراس بام"),
    "parking": ("parking", "پارکینگ"),
    "parking_stall": ("parking stall", "محل پارک"),
    "ramp": ("ramp", "رمپ"),
    "driveway": ("driveway", "مسیر خودرو"),
    "office": ("office", "اداری", "دفتر"),
    "shop": ("shop", "فروشگاه", "مغازه"),
    "commercial": ("commercial", "تجاری"),
    "mechanical_room": ("mechanical room", "موتورخانه"),
    "electrical_room": ("electrical room", "اتاق برق"),
    "boiler_room": ("boiler room", "دیگ خانه", "دیگ‌خانه"),
    "janitor": ("janitor", "سرایداری"),
    "common_room": ("common room", "فضای مشترک"),
}

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
    value = str(value or "").replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    value = value.replace("\u200c", " ").lower()
    value = value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    value = re.sub(r"[_.:/\\,;()\[\]{}\-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


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
    normalized = normalize_text(text)
    matches = []
    for category, aliases in SPACE_ONTOLOGY.items():
        for alias in aliases:
            token = normalize_text(alias)
            if token and (normalized == token or re.search(rf"(?:^|\s){re.escape(token)}(?:$|\s|\d)", normalized)):
                matches.append((len(token), category, token))
    return max(matches)[1:] if matches else (None, None)


def _classify_object(name, layer):
    text = normalize_text(f"{name} {layer}")
    found = []
    for kind, aliases in OBJECT_TERMS.items():
        if any(normalize_text(alias) in text for alias in aliases): found.append(kind)
    return sorted(set(found))


def _is_boundary_geometry(layer, source_block, entity_type):
    """Conservative wall-boundary admission policy.

    Exploded furniture, sanitary fixtures, SHX glyphs and door swings are a
    major source of phantom cells.  Top-level straight/polyline drafting can
    participate unless explicitly non-architectural.  Nested geometry and
    curves need positive wall evidence.
    """
    context=normalize_text(f"{layer} {source_block or ''}")
    if any(token in context for token in NON_BOUNDARY_TOKENS): return False
    wall_evidence=any(token in context for token in WALL_TOKENS)
    if source_block and not wall_evidence: return False
    if entity_type in {"ARC","SPLINE"} and not wall_evidence: return False
    return True


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
    def analyze(self, *, image_path: str, frame_id: str, regions: list[dict]) -> list[VisionCandidate]: ...


class NoVisionAdapter:
    def analyze(self, *, image_path: str, frame_id: str, regions: list[dict]) -> list[VisionCandidate]:
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
        kinds = set(obj.get("object_types") or [])
        if not kinds.intersection({"door", "window"}):
            continue
        for kind in sorted(kinds.intersection({"door", "window"})):
            rows.append({"opening_id": _stable_id(kind.upper(), [source_hash, obj.get("handle"), obj.get("point")]),
                         "kind": kind, "geometry": {"point": obj.get("point"), "bounds": obj.get("bounds")},
                         "source_handle": obj.get("handle"), "evidence": [{"class": "CAD_BLOCK", "name": obj.get("name"), "layer": obj.get("layer")}],
                         "status": "CANDIDATE"})
    for primitive in extracted["primitives"]:
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


def _extract(doc):
    primitives, texts, objects, dimensions, boundary_lines, boundary_meta = [], [], [], [], [], []
    counts = Counter(); seen_nested = set()

    def visit(entity, transform_source=None, depth=0):
        if depth > 12: return
        kind = entity.dxftype(); counts[kind] += 1; layer = _layer(entity); handle = _handle(entity)
        record = {"entity_type": kind, "handle": handle, "layer": layer, "source_block": transform_source}
        if kind == "LINE":
            a, b = _point(entity, "start"), _point(entity, "end")
            if a and b and a != b:
                record.update(start=a, end=b); primitives.append(record)
                if _is_boundary_geometry(layer, transform_source, kind):
                    boundary_lines.append(LineString([a, b])); boundary_meta.append({"layer":layer,"entity_type":kind,"handle":handle})
        elif kind in {"LWPOLYLINE", "POLYLINE"}:
            try:
                pts = ([(float(x), float(y)) for x, y, *_ in entity.get_points()] if kind == "LWPOLYLINE"
                       else [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices])
            except Exception: pts = []
            if len(pts) >= 2:
                closed = bool(getattr(entity, "closed", False)) or pts[0] == pts[-1]
                record.update(points=pts, closed=closed); primitives.append(record)
                if _is_boundary_geometry(layer, transform_source, kind):
                    for a, b in zip(pts, pts[1:] + ([pts[0]] if closed else [])):
                        if a != b:
                            boundary_lines.append(LineString([a, b])); boundary_meta.append({"layer":layer,"entity_type":kind,"handle":handle})
        elif kind == "ARC":
            try:
                pts = [(float(p.x), float(p.y)) for p in entity.flattening(0.5)]
            except Exception: pts = []
            if len(pts) >= 2:
                record["points"] = pts; primitives.append(record)
                if _is_boundary_geometry(layer, transform_source, kind):
                    boundary_lines.append(LineString(pts)); boundary_meta.append({"layer":layer,"entity_type":kind,"handle":handle})
        elif kind in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}:
            value = _entity_text(entity).strip(); p = _point(entity)
            if value and p: record.update(text=value, point=p); texts.append(record); primitives.append(record)
        elif kind == "DIMENSION":
            try:
                measurement = float(entity.get_measurement())
                defpoints = [p for p in (_point(entity, name) for name in ("defpoint", "defpoint2", "defpoint3", "defpoint4")) if p]
                row = {**record, "measurement": measurement, "definition_points": defpoints,
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
                for child in children: visit(child, name, depth + 1)
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
    retained=[(line,meta) for line,meta in zip(boundary_lines,boundary_meta) if meta["layer"] not in glyph_layers]
    boundary_lines=[line for line,_ in retained]; boundary_meta=[meta for _,meta in retained]
    return {"primitives": primitives, "texts": texts, "objects": objects, "dimensions": dimensions,
            "boundary_lines": boundary_lines, "boundary_meta":boundary_meta,
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


def _evidence_for_cell(poly, extracted):
    labels, objects = [], []
    for text in extracted["texts"]:
        if poly.covers(Point(text["point"])):
            category, alias = _classify_text(text["text"])
            if category: labels.append({"category": category, "value": text["text"], "handle": text["handle"], "alias": alias})
    for obj in extracted["objects"]:
        if obj.get("point") and poly.covers(Point(obj["point"])) and obj.get("object_types"):
            objects.append({"types": obj["object_types"], "handle": obj["handle"], "name": obj["name"], "point": obj["point"]})
    return labels, objects


def _infer_categories(labels, objects):
    evidence = defaultdict(list)
    for label in labels: evidence[label["category"]].append({"class": "TEXT", "handle": label["handle"], "value": label["value"]})
    object_types = {kind for obj in objects for kind in obj["types"]}
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
        pts = dim.get("definition_points") or []
        if not pts: continue
        if min(boundary.distance(Point(p)) for p in pts) <= max(math.sqrt(poly.area) * .15, 1e-6):
            rows.append({"dimension_id": _stable_id("DIM", [dim.get("handle"), dim.get("measurement")]),
                         "measurement": dim["measurement"], "measurement_m": dim["measurement"] * metres_per_unit if metres_per_unit else None,
                         "source_handle": dim.get("handle"), "definition_points": pts, "text_override": dim.get("text_override"),
                         "status": "VERIFIED" if metres_per_unit else "INPUT_REQUIRED"})
    return rows


def _space_record(poly, frame, source_hash, extracted, metres_per_unit):
    ring = _round_points(list(poly.exterior.coords)); holes=sorted(_round_points(list(interior.coords)) for interior in poly.interiors)
    physical_id = _stable_id("PS", [source_hash, frame["frame_id"], ring, holes])
    labels, objects = _evidence_for_cell(poly, extracted); semantic = _infer_categories(labels, objects)
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
    if len(categories) > 1: status = "VERIFIED" if all(z["status"] == "VERIFIED" for z in zones) else "INPUT_REQUIRED"
    minx, miny, maxx, maxy = poly.bounds; scale = metres_per_unit
    dims = _associate_dimensions(poly, extracted["dimensions"], metres_per_unit)
    evidence = [{"class": "CAD_TOPOLOGY", "source_handles": sorted({p.get("handle") for p in extracted["primitives"] if p.get("handle")})}]
    evidence.extend(e for values in semantic.values() for e in values)
    return {"space_id": physical_id, "physical_space_id": physical_id, "level_id": frame.get("level_candidate"), "frame_id": frame["frame_id"],
            "category": category, "use": category, "subtype": None, "polygon": ring, "interior_rings":holes,
            "centroid": [poly.centroid.x, poly.centroid.y], "area_m2": poly.area * scale * scale if scale else None,
            "geometric_area_drawing_units": poly.area, "perimeter_m": poly.length * scale if scale else None,
            "principal_dimensions": {"width_m": (maxx-minx)*scale if scale else None, "length_m": (maxy-miny)*scale if scale else None,
                                     "source": [d["dimension_id"] for d in dims]},
            "openings": [], "windows": [], "adjacent_space_ids": [], "entrances": [], "functional_zones": zones,
            "objects": objects, "dimensions": dims, "confidence": 1.0 if status == "VERIFIED" else (.85 if status == "HIGH_CONFIDENCE" else .0),
            "status": status, "evidence": evidence, "source_handles": sorted({x.get("handle") for x in labels + objects if x.get("handle")}),
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


def _bind_openings(openings, spaces, wall_lines, source_hash, tolerance):
    """Bind openings to a host wall and the spaces they connect.

    An opening with no defensible wall match is explicitly rejected.  A door
    with only one bounded side is exterior; two sides create a portal.  More
    than two candidate sides is a conflict, never an arbitrary nearest-room
    choice.
    """
    tol = max(float(tolerance or 0.001) * 3.0, 1e-6)
    polygons = {s["physical_space_id"]: _space_polygon(s) for s in spaces}
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
        bound = {**row, "host_wall_id": host["wall_id"], "level_id": next((s.get("level_id") for s in spaces if s["physical_space_id"] in touching), None),
                 "space_a": touching[0], "space_b": touching[1] if len(touching) == 2 else "EXTERIOR",
                 "orientation": orientation, "width_drawing_units": width,
                 "opening_geometry": geometry, "status": "VERIFIED"}
        accepted.append(bound)
        key = "openings" if row["kind"] == "door" else "windows"
        for space in spaces:
            if space["physical_space_id"] in touching: space[key].append(row["opening_id"])
    return accepted, [{"wall_id": w["wall_id"], "geometry": list(w["line"].coords)} for w in walls]


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


def _dimension_reconciliation(spaces, metres_per_unit, tolerance):
    rows=[]
    geometric_tol=max((tolerance or .001)*(metres_per_unit or 1.0), .001)
    for space in spaces:
        poly=_space_polygon(space); minx,miny,maxx,maxy=poly.bounds
        candidates=[(maxx-minx)*(metres_per_unit or 1.0),(maxy-miny)*(metres_per_unit or 1.0)]
        for dim in space.get("dimensions") or []:
            annotated=dim.get("measurement_m")
            if annotated is None: continue
            nearest=min(candidates,key=lambda value:abs(value-annotated)); delta=abs(nearest-annotated)
            allowed=max(geometric_tol, abs(annotated)*.005)
            rows.append({"dimension_id":dim["dimension_id"],"space_id":space["physical_space_id"],
                         "annotated_measurement_m":annotated,"geometric_measurement_m":nearest,
                         "difference_m":delta,"tolerance_m":allowed,
                         "status":"PASS" if delta<=allowed else "CONFLICT"})
    return {"status":"CONFLICT" if any(r["status"]=="CONFLICT" for r in rows) else "PASS", "rows":rows}


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


def _completeness(frames, spaces, units_known, *, coverage=None, openings=None, dimension_reconciliation=None):
    issues = []
    for frame in frames:
        if frame.get("scope_relevance") == "MECHANICAL_AUTHORITY" and frame["frame_type"] == "UNKNOWN":
            issues.append({"code": "UNKNOWN_FRAME", "frame_id": frame["frame_id"], "status": "INPUT_REQUIRED"})
    for space in spaces:
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


def reconstruct_architecture(path, *, vision_adapter: VisionAdapter | None = None):
    started = time.perf_counter(); stage_started=started; timings={}
    doc, source = _ingest(path); extracted = _extract(doc); timings["parsing"]=time.perf_counter()-stage_started
    stage_started=time.perf_counter()
    fallback = _frame_from_extent(extracted, source["source_sha256"])
    frames = _detected_frames(path, source["source_sha256"], fallback)
    source = _calibrate_scale(source, frames, extracted["dimensions"])
    tolerance = _adaptive_tolerance(extracted["boundary_lines"], source["metres_per_unit"])
    timings["frame_and_scale_resolution"]=time.perf_counter()-stage_started; stage_started=time.perf_counter()
    spaces = []
    for frame in frames:
        if frame.get("scope_relevance") == "REFERENCE_ONLY":
            continue
        clip=box(*frame["bounds"]) if frame.get("bounds") else None
        local_lines=[]
        for line in extracted["boundary_lines"]:
            if clip is None or not line.intersects(clip): continue
            clipped=line.intersection(clip)
            if clipped.geom_type=="LineString" and not clipped.is_empty: local_lines.append(clipped)
            elif clipped.geom_type=="MultiLineString": local_lines.extend(g for g in clipped.geoms if not g.is_empty)
        polygons = _polygonize_spaces(local_lines, frame, tolerance)
        spaces.extend(_space_record(p, frame, source["source_sha256"], extracted, source["metres_per_unit"]) for p in polygons)
    timings["polygonization_and_semantics"]=time.perf_counter()-stage_started; stage_started=time.perf_counter()
    spaces.sort(key=lambda s: s["physical_space_id"]); _adjacency(spaces, tolerance)
    opening_candidates=_opening_candidates(extracted, source["source_sha256"])
    openings,walls=_bind_openings(opening_candidates,spaces,extracted["boundary_lines"],source["source_sha256"],tolerance)
    timings["topology"]=time.perf_counter()-stage_started; stage_started=time.perf_counter()
    coverage=_coverage(frames,spaces)
    dimension_reconciliation=_dimension_reconciliation(spaces,source["metres_per_unit"],tolerance)
    completeness = _completeness(frames, spaces, source["metres_per_unit"] is not None,
                                 coverage=coverage,openings=openings,dimension_reconciliation=dimension_reconciliation)
    timings["qa_and_completeness"]=time.perf_counter()-stage_started; stage_started=time.perf_counter()
    # Vision remains an explicit, optional reconciliation dependency.  It is
    # never invoked for facts already verified from CAD.
    unresolved = [{"space_id": s["physical_space_id"], "bounds": list(_space_polygon(s).bounds)} for s in spaces if s["status"] != "VERIFIED"]
    adapter=vision_adapter or NoVisionAdapter()
    vision = {"provider": type(adapter).__name__, "calls": 0, "candidates": [],
              "status": "NOT_REQUIRED" if not unresolved else ("CONFIG_REQUIRED" if isinstance(adapter,NoVisionAdapter) else "READY"),
              "policy":"DETERMINISTIC_FIRST_LOCALIZED_REGIONS_ONLY","regions":unresolved}
    timings["vision_preparation"]=time.perf_counter()-stage_started
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
    review=_review_payload(spaces,frames,openings,coverage,dimension_reconciliation)
    model = {"schema": SCHEMA, "source": source, "frames": frames, "levels": [], "physical_spaces": spaces,
             "functional_zones": [z for s in spaces for z in s["functional_zones"]], "architectural_objects": extracted["objects"],
             "dimensions": extracted["dimensions"], "dimension_reconciliation":dimension_reconciliation,
             "openings":openings,"canonical_walls":walls,"coverage":coverage,"review":review,
             "completeness": completeness, "vision_reconciliation": vision,
             "diagnostics": {"entity_counts": extracted["entity_counts"], "adaptive_tolerance": tolerance,
                             "space_candidate_count": len(spaces), "stage_runtime_seconds":{k:round(v,6) for k,v in timings.items()},
                             "dxf_parse_count":1,"runtime_seconds": round(time.perf_counter()-started,6)},
             # Backward-compatible projection; canonical consumers use fields above.
             "version": SCHEMA, "units": source["insunits"], "bounds": fallback["bounds"], "rooms": rooms,
             "walls": [{"start": list(line.coords)[0], "end": list(line.coords)[-1]} for line in extracted["boundary_lines"]],
             "doors": [o for o in openings if o["kind"]=="door"], "windows":[o for o in openings if o["kind"]=="window"], "columns": [], "shafts": [],
             "all_inserts": extracted["objects"], "all_texts": extracted["texts"],
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
