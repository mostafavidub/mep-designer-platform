"""Deterministic architectural-object standardization before topology.

This module classifies source records without granting wall, enclosure or space
authority.  A classification may remove known non-enclosure drafting from the
wall-admission funnel; only the wall engine can positively prove enclosure.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re

from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union


SCHEMA = "pre-topology-architectural-object/1.0"

OBJECT_CLASSES = {
    "SHEET_FRAME", "DIMENSION_CHAIN", "GRID_AXIS", "COLUMN", "STAIR_ASSEMBLY",
    "WINDOW_ASSEMBLY", "DOOR_ASSEMBLY", "DOUBLE_DOOR_ASSEMBLY", "OPEN_PASSAGE",
    "DINING_TABLE_ASSEMBLY", "VEHICLE", "PARKING_BAY", "SECTION_CUT",
    "GENERIC_NON_ENCLOSURE_OBJECT", "ENCLOSURE_CANDIDATE", "UNKNOWN",
}
DOMAINS = {"SHEET_DOMAIN", "ARCHITECTURAL_DOMAIN", "OUTSIDE_ARCHITECTURAL_DOMAIN"}
TOPOLOGY_ROLES = {
    "REFERENCE_ONLY", "OPENING_EVIDENCE_ONLY", "OBSTACLE_EVIDENCE_ONLY",
    "NON_TOPOLOGICAL", "ENCLOSURE_CANDIDATE_ONLY", "UNRESOLVED",
}

_RULES = (
    ("SHEET_FRAME", ("sheet frame", "border", "title block", "titleblock", "کادر", "جدول نقشه"), "SHEET_DOMAIN", "REFERENCE_ONLY"),
    ("DIMENSION_CHAIN", ("dimension", "dim", "اندازه", "اندازه گذاری"), "SHEET_DOMAIN", "NON_TOPOLOGICAL"),
    ("GRID_AXIS", ("grid", "axis", "axes", "محور", "آکس"), "ARCHITECTURAL_DOMAIN", "REFERENCE_ONLY"),
    ("COLUMN", ("column", "col ", "ستون"), "ARCHITECTURAL_DOMAIN", "OBSTACLE_EVIDENCE_ONLY"),
    ("STAIR_ASSEMBLY", ("stair", "step", "tread", "landing", "پله", "پاگرد"), "ARCHITECTURAL_DOMAIN", "OBSTACLE_EVIDENCE_ONLY"),
    ("WINDOW_ASSEMBLY", ("window", "پنجره"), "ARCHITECTURAL_DOMAIN", "OPENING_EVIDENCE_ONLY"),
    ("DOUBLE_DOOR_ASSEMBLY", ("double door", "door double", "درب دو لنگه", "در دو لنگه"), "ARCHITECTURAL_DOMAIN", "OPENING_EVIDENCE_ONLY"),
    ("OPEN_PASSAGE", ("open passage", "passage", "بازشوی بدون در", "گذر باز"), "ARCHITECTURAL_DOMAIN", "OPENING_EVIDENCE_ONLY"),
    ("DOOR_ASSEMBLY", ("door", "درب", " در "), "ARCHITECTURAL_DOMAIN", "OPENING_EVIDENCE_ONLY"),
    ("DINING_TABLE_ASSEMBLY", ("dining", "dining table", "میز ناهار", "ناهارخوری"), "ARCHITECTURAL_DOMAIN", "NON_TOPOLOGICAL"),
    ("VEHICLE", ("vehicle", " car", "automobile", "خودرو", "ماشین"), "ARCHITECTURAL_DOMAIN", "NON_TOPOLOGICAL"),
    ("PARKING_BAY", ("parking bay", "parking stall", "پارکینگ", "محل پارک"), "ARCHITECTURAL_DOMAIN", "NON_TOPOLOGICAL"),
    ("SECTION_CUT", ("section cut", "section marker", "مقطع", "برش"), "SHEET_DOMAIN", "REFERENCE_ONLY"),
    ("GENERIC_NON_ENCLOSURE_OBJECT", ("furniture", "furn", "fixture", "cabinet", "sanitary", "equipment", "annotation", "leader", "hatch", "مبلمان", "کابینت"), "ARCHITECTURAL_DOMAIN", "NON_TOPOLOGICAL"),
)


def _normal(value):
    value = str(value or "").replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه").lower()
    value = value.replace("\u200c", " ").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    return " " + re.sub(r"[^0-9a-zآ-ی]+", " ", value).strip() + " "


def _stable_id(record):
    identity = [record.get("handle") or record.get("source_handle"), record.get("entity_type"),
                record.get("layer"), record.get("source_block"), record.get("geometry")]
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "PTO-" + sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def _token_match(context, token):
    needle = _normal(token).strip()
    return bool(needle and re.search(rf"(?:^| ){re.escape(needle)}(?: |$)", context))


def classify_source_record(record):
    """Return an auditable classification; never return enclosure authority."""
    entity_type = str(record.get("entity_type") or "").upper()
    context = _normal(" ".join(str(record.get(key) or "") for key in ("layer", "source_block", "name")))
    positive, negative = [], []

    geometric_override = record.get("pre_topology_object_class")
    if geometric_override in OBJECT_CLASSES:
        object_class = geometric_override
        domain = "ARCHITECTURAL_DOMAIN"
        role = "OBSTACLE_EVIDENCE_ONLY" if object_class == "COLUMN" else "NON_TOPOLOGICAL"
        positive.append("REPEATED_COMPACT_CLOSED_FOOTPRINT")
        negative.append("NO_WALL_CONTINUITY_EVIDENCE")
    elif entity_type == "DIMENSION":
        object_class, domain, role = "DIMENSION_CHAIN", "SHEET_DOMAIN", "NON_TOPOLOGICAL"
        positive.append("NATIVE_DIMENSION_ENTITY")
    else:
        matched = None
        for object_class, tokens, domain, role in _RULES:
            token = next((item for item in tokens if _token_match(context, item)), None)
            if token:
                matched = (object_class, domain, role, token)
                break
        if matched:
            object_class, domain, role, token = matched
            positive.append("SOURCE_SEMANTIC_TOKEN:" + _normal(token).strip())
        elif entity_type in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF", "LEADER", "MLEADER", "HATCH"}:
            object_class, domain, role = "GENERIC_NON_ENCLOSURE_OBJECT", "SHEET_DOMAIN", "NON_TOPOLOGICAL"
            positive.append("PRESENTATION_ENTITY_TYPE:" + entity_type)
        elif any(_token_match(context, token) for token in ("wall", "a wall", "partition", "دیوار")):
            object_class, domain, role = "ENCLOSURE_CANDIDATE", "ARCHITECTURAL_DOMAIN", "ENCLOSURE_CANDIDATE_ONLY"
            positive.append("SOURCE_WALL_SEMANTIC")
            negative.append("ENCLOSURE_NOT_YET_PROVEN")
        else:
            object_class, domain, role = "UNKNOWN", "ARCHITECTURAL_DOMAIN", "UNRESOLVED"
            negative.extend(("NO_CANONICAL_OBJECT_GRAMMAR_MATCH", "NO_ENCLOSURE_AUTHORITY"))

    return {
        "schema": SCHEMA,
        "classification_id": _stable_id(record),
        "source_handle": record.get("handle") or record.get("source_handle"),
        "object_class": object_class,
        "domain": domain,
        "topology_role": role,
        "positive_evidence": positive,
        "negative_evidence": negative,
        "enclosure_authority": "NONE",
        "deterministic": True,
    }


def standardize_source_records(records):
    rows = [classify_source_record(record) for record in records]
    return sorted(rows, key=lambda row: row["classification_id"])


def excludes_from_wall_admission(classification):
    return classification.get("topology_role") in {
        "REFERENCE_ONLY", "OPENING_EVIDENCE_ONLY", "OBSTACLE_EVIDENCE_ONLY", "NON_TOPOLOGICAL"
    }


def repeated_compact_column_handles(lines, metas, metres_per_unit):
    """Find repeated compact near-square closed footprints without project coordinates.

    One isolated square is deliberately not enough.  At least three source
    entities with matching scale and shape are required, which separates a
    structural column family from an arbitrary small room or detail box.
    """
    scale = float(metres_per_unit or 1.0)
    grouped = {}
    for line, meta in zip(lines, metas):
        handle = meta.get("handle")
        if handle is None or not meta.get("closed"):
            continue
        grouped.setdefault(handle, []).append(line)
    candidates = []
    for handle, members in grouped.items():
        polygons = list(polygonize(unary_union(members)))
        if len(polygons) != 1:
            continue
        polygon = polygons[0]
        min_x, min_y, max_x, max_y = polygon.bounds
        width, height = (max_x-min_x)*scale, (max_y-min_y)*scale
        if not (0.12 <= width <= 0.90 and 0.12 <= height <= 0.90):
            continue
        if min(width, height) / max(width, height) < 0.65:
            continue
        envelope_area = max((max_x-min_x)*(max_y-min_y), 1e-12)
        if polygon.area / envelope_area < 0.82:
            continue
        signature = (round(width/.025), round(height/.025))
        candidates.append((handle, signature))
    counts = {}
    for _, signature in candidates:
        counts[signature] = counts.get(signature, 0) + 1
    return {handle for handle, signature in candidates if counts[signature] >= 3}
