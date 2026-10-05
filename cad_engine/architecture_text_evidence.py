"""Canonical architectural text evidence and bounded semantic authority.

Text in this module can describe an existing source fact and an independently
reconstructed host.  It never creates engineering geometry, scale, north, a
space, a separator, a void, an aperture, or a routing obstacle.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
import re
import unicodedata

from shapely.geometry import Point, Polygon, box


SCHEMA = "planha-architectural-text-evidence/1.0"
CONTRACT_VERSION = "planha-canonical-architecture/3.1"
EXACT_TYPES = {"TEXT", "MTEXT", "ATTRIB"}
TEMPLATE_TYPES = {"ATTDEF"}

SPACE_ONTOLOGY = {
    "bedroom": ("bedroom", "bed room", "اتاق خواب", "خواب"),
    "master_bedroom": ("master bedroom", "master", "اتاق مستر", "خواب مستر"),
    "living": ("living", "family living", "نشیمن"),
    "reception": ("reception", "پذیرایی"),
    "dining": ("dining", "ناهارخوری", "غذاخوری"),
    "kitchen": ("kitchen", "آشپزخانه", "اشپزخانه"),
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
    "void": ("void", "فضای خالی"),
    "balcony": ("balcony", "بالکن"),
    "terrace": ("terrace", "تراس"),
    "patio": ("patio",),
    "yard": ("yard", "حیاط"),
    "backyard": ("backyard", "حیاط پشتی", "حیاط خلوت"),
    "courtyard": ("courtyard", "حیاط مرکزی"),
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

TITLE_TOKENS = ("architectural plan", "floor plan", "site plan", "roof plan", "پلان معماری", "پلان طبقه", "پلان بام", "پلان پارکینگ")
LEVEL_TOKENS = ("ground floor", "first floor", "second floor", "roof", "basement", "همکف", "طبقه اول", "طبقه دوم", "بام", "زیرزمین")
SECTION_TOKENS = ("section", "elevation", "detail", "برش", "مقطع", "نما", "دیتیل")
SCALE_RE = re.compile(r"(?:\bscale\b|مقیاس|\bsc\b)\s*[:=]?\s*1\s*[:/]\s*\d+", re.I)
NORTH_RE = re.compile(r"^(?:north|n|شمال)$", re.I)

TAG_ROLES = {
    "TITLE": "DRAWING_TYPE_TITLE", "DRAWING_TITLE": "DRAWING_TYPE_TITLE",
    "SHEET_TITLE": "DRAWING_TYPE_TITLE", "PLAN_TITLE": "PLAN_TITLE",
    "LEVEL": "LEVEL_TITLE", "FLOOR": "LEVEL_TITLE",
    "DRAWING_NO": "DRAWING_NUMBER", "DRAWING_NUMBER": "DRAWING_NUMBER",
    "SHEET_NO": "DRAWING_NUMBER", "REV": "REVISION", "REVISION": "REVISION",
    "DATE": "DATE", "SCALE": "SCALE_TEXT", "DISCIPLINE": "DISCIPLINE",
    "PROJECT": "PROJECT_METADATA", "PROJECT_NAME": "PROJECT_METADATA",
    "CLIENT": "PROJECT_METADATA", "ARCHITECT": "DESIGNER_OR_COMPANY_METADATA",
    "DESIGNER": "DESIGNER_OR_COMPANY_METADATA", "CONSULTANT": "DESIGNER_OR_COMPANY_METADATA",
}


def _hash(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def normalize_text(value: object) -> str:
    """Deterministic Persian/Arabic/English normalization; raw text is retained separately."""
    value = unicodedata.normalize("NFC", str(value or ""))
    value = value.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک").replace("ۀ", "ه")
    value = value.replace("\u200c", " ").replace("\ufeff", " ")
    value = value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    value = re.sub(r"\\[A-Za-z][^;]*;|[{}]", " ", value)
    value = value.replace("\r", " ").replace("\n", " ")
    value = re.sub(r"[،؛,;()\[\]{}]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


def semantic_candidates(value: object) -> list[str]:
    text = normalize_text(value)
    matches = []
    for category, aliases in SPACE_ONTOLOGY.items():
        for alias in aliases:
            token = normalize_text(alias)
            if not token:
                continue
            if text == token or re.search(rf"(?:^|\s){re.escape(token)}(?:$|\s|\d)", text):
                matches.append((len(token), category))
    if not matches:
        return []
    longest = max(length for length, _ in matches)
    return sorted({category for length, category in matches if length == longest})


def role_candidates(value: object, *, entity_type: str, attribute_tag: str | None = None) -> list[dict]:
    text = normalize_text(value)
    rows = []
    tag = normalize_text(attribute_tag).upper().replace(" ", "_") if attribute_tag else ""
    if tag in TAG_ROLES:
        rows.append({"role": TAG_ROLES[tag], "evidence": "EXACT_ATTRIBUTE_TAG", "status": "VERIFIED"})
    if any(token in text for token in TITLE_TOKENS):
        rows.append({"role": "PLAN_TITLE", "evidence": "DETERMINISTIC_TITLE_LEXICON", "status": "SUPPORTED"})
    if any(token in text for token in LEVEL_TOKENS):
        rows.append({"role": "LEVEL_TITLE", "evidence": "DETERMINISTIC_LEVEL_LEXICON", "status": "SUPPORTED"})
    if any(token in text for token in SECTION_TOKENS):
        rows.append({"role": "SECTION_ELEVATION_LABEL", "evidence": "DETERMINISTIC_VIEW_LEXICON", "status": "SUPPORTED"})
    if SCALE_RE.search(text):
        rows.append({"role": "SCALE_TEXT", "evidence": "DETERMINISTIC_SCALE_SYNTAX", "status": "SUPPORTED"})
    if NORTH_RE.fullmatch(text):
        rows.append({"role": "DRAFTING_ANNOTATION", "evidence": "NORTH_TEXT_ONLY", "status": "SUPPORTED"})
    if semantic_candidates(text):
        rows.append({"role": "SPACE_LABEL", "evidence": "CANONICAL_SPACE_ONTOLOGY", "status": "SUPPORTED"})
    if not rows:
        rows.append({"role": "UNKNOWN_TEXT", "evidence": "NO_DETERMINISTIC_ROLE", "status": "AMBIGUOUS"})
    unique = {(row["role"], row["evidence"]): row for row in rows}
    return [unique[key] for key in sorted(unique)]


def _source_entity(entity):
    return getattr(entity, "source_of_copy", None) or getattr(entity, "origin_of_copy", None) or entity


def _handle(entity) -> str | None:
    source = _source_entity(entity)
    value = getattr(getattr(source, "dxf", None), "handle", None)
    return str(value) if value else None


def _point(entity) -> list[float] | None:
    try:
        value = entity.dxf.insert
        point = [float(value.x), float(value.y)]
        if all(math.isfinite(x) and abs(x) <= 1e12 for x in point):
            return point
    except Exception:
        pass
    return None


def _text_values(entity) -> tuple[str, str]:
    kind = entity.dxftype()
    try:
        if kind == "MTEXT":
            raw = str(getattr(entity, "text", "") or getattr(entity.dxf, "text", "") or "")
            return raw, str(entity.plain_text() or "")
        raw = str(getattr(entity.dxf, "text", "") or "")
        return raw, raw
    except Exception:
        return "", ""


def _matrix_fingerprint(insert) -> str:
    try:
        matrix = insert.matrix44()
        values = [round(float(value), 10) for row in matrix.rows() for value in row]
    except Exception:
        values = []
    return _hash(values)


def extract_text_evidence(doc, *, source_sha256: str) -> dict:
    """Extract exact text occurrences with INSERT-instance identity and transforms."""
    records = []

    def add(entity, *, instance_path, insert_handle_path, block_path, source_insert_handle, transform_fingerprint,
            occurrence_kind=None, instance_value_authority=None):
        kind = entity.dxftype()
        if kind not in EXACT_TYPES | TEMPLATE_TYPES:
            return
        raw, plain = _text_values(entity)
        point = _point(entity)
        if not plain.strip() or point is None:
            return
        source = _source_entity(entity)
        tag = str(getattr(getattr(entity, "dxf", None), "tag", "") or
                  getattr(getattr(source, "dxf", None), "tag", "") or "") or None
        source_handle = _handle(entity)
        owner_handle = str(getattr(getattr(source, "dxf", None), "owner", "") or "") or None
        occurrence_kind = occurrence_kind or ("TEMPLATE_DEFINITION" if kind == "ATTDEF" else "SOURCE_OCCURRENCE")
        instance_value_authority = bool(instance_value_authority) if instance_value_authority is not None else kind != "ATTDEF"
        identity = [source_sha256, kind, source_handle, owner_handle, tag, instance_path, insert_handle_path,
                    [round(x, 8) for x in point], raw, transform_fingerprint]
        evidence_id = "TEXT-EV-" + _hash(identity)[:20].upper()
        candidates = role_candidates(plain, entity_type=kind, attribute_tag=tag)
        records.append({
            "text_evidence_id": evidence_id, "source_sha256": source_sha256,
            "entity_type": kind, "entity_handle": source_handle, "owner_handle": owner_handle,
            "attribute_tag": tag, "source_insert_handle": source_insert_handle,
            "instance_path": list(instance_path), "insert_handle_path": list(insert_handle_path),
            "block_path": list(block_path),
            "raw_text": raw, "plain_text": plain, "normalized_text": normalize_text(plain),
            "position": point, "rotation": float(getattr(entity.dxf, "rotation", 0.0) or 0.0),
            "layer": str(getattr(entity.dxf, "layer", "0") or "0"),
            "style": str(getattr(entity.dxf, "style", "") or "") or None,
            "transform_fingerprint": transform_fingerprint,
            "position_fingerprint": _hash([point, transform_fingerprint]),
            "occurrence_kind": occurrence_kind,
            "instance_value_authority": instance_value_authority,
            "extraction_authority": "EXACT_DXF_ATTRIBUTE" if kind == "ATTRIB" else
                                    "TEMPLATE_DEFINITION" if kind == "ATTDEF" else "EXACT_DXF_TEXT",
            "role_candidates": candidates,
            "role_status": "VERIFIED" if any(x["status"] == "VERIFIED" for x in candidates) else
                           "SUPPORTED" if len(candidates) == 1 and candidates[0]["role"] != "UNKNOWN_TEXT" else "AMBIGUOUS",
            "semantic_candidates": semantic_candidates(plain),
            "semantic_status": "SUPPORTED" if semantic_candidates(plain) else "INPUT_REQUIRED",
            "host_binding": {"status": "INPUT_REQUIRED", "host_id": None, "method": None},
            "authority": {"semantic": False, "document_metadata": False, "material_geometry": False,
                          "engineering_scale": False, "north": False},
            "provenance_fingerprint": _hash(identity),
        })

    def visit(entity, *, depth=0, instance_path=(), insert_handle_path=(), block_path=(), root_insert_handle=None):
        if depth > 12:
            return
        kind = entity.dxftype()
        if kind in EXACT_TYPES | TEMPLATE_TYPES:
            add(entity, instance_path=instance_path, insert_handle_path=insert_handle_path, block_path=block_path,
                source_insert_handle=root_insert_handle,
                transform_fingerprint=_hash(instance_path),
                occurrence_kind="TEMPLATE_DEFINITION" if kind == "ATTDEF" else "SOURCE_OCCURRENCE",
                instance_value_authority=kind != "ATTDEF")
            return
        if kind != "INSERT":
            return
        source_handle = _handle(entity)
        name = str(getattr(entity.dxf, "name", "") or "")
        insert_token = "INSERT-" + _hash([source_handle, name, _point(entity), _matrix_fingerprint(entity), instance_path])[:16].upper()
        current_path = tuple(instance_path) + (insert_token,)
        current_handles = tuple(insert_handle_path) + (source_handle or insert_token,)
        current_blocks = tuple(block_path) + (name,)
        root = root_insert_handle or source_handle or insert_token
        transform = _matrix_fingerprint(entity)
        # Attached ATTRIB values are instance occurrences and outrank ATTDEF templates.
        for attribute in list(getattr(entity, "attribs", []) or []):
            add(attribute, instance_path=current_path, insert_handle_path=current_handles, block_path=current_blocks,
                source_insert_handle=root, transform_fingerprint=transform,
                occurrence_kind="ATTRIBUTE_INSTANCE", instance_value_authority=True)
        try:
            children = list(entity.virtual_entities())
        except Exception:
            children = []
        for child in children:
            visit(child, depth=depth + 1, instance_path=current_path, insert_handle_path=current_handles,
                  block_path=current_blocks, root_insert_handle=root)

    # ATTDEF is block-template evidence, never an INSERT occurrence.  ezdxf's
    # virtual_entities() intentionally omits it once ATTRIB values exist, so
    # catalogue definitions directly and keep them outside every instance path.
    for block in doc.blocks:
        block_name = str(getattr(block, "name", "") or "")
        if block_name.startswith("*"):
            continue
        for entity in block:
            if entity.dxftype() == "ATTDEF":
                add(entity, instance_path=(), insert_handle_path=(), block_path=(block_name,),
                    source_insert_handle=None,
                    transform_fingerprint=_hash(["BLOCK_DEFINITION", block_name]),
                    occurrence_kind="TEMPLATE_DEFINITION", instance_value_authority=False)

    for entity in doc.modelspace():
        visit(entity)
    records.sort(key=lambda row: row["text_evidence_id"])
    return {"schema": SCHEMA, "contract_version": CONTRACT_VERSION,
            "items": records, "metrics": {
                "exact_occurrence_count": sum(r["occurrence_kind"] != "TEMPLATE_DEFINITION" for r in records),
                "template_definition_count": sum(r["occurrence_kind"] == "TEMPLATE_DEFINITION" for r in records),
                "attribute_instance_count": sum(r["occurrence_kind"] == "ATTRIBUTE_INSTANCE" for r in records),
                "geometry_authority_count": sum(bool(r["authority"]["material_geometry"]) for r in records),
            }}


def legacy_text_records(contract: dict) -> list[dict]:
    """Compatibility projection; canonical consumers use text evidence IDs."""
    rows = []
    for item in contract.get("items") or []:
        if item.get("occurrence_kind") == "TEMPLATE_DEFINITION":
            continue
        rows.append({"entity_type": item["entity_type"], "handle": item.get("entity_handle") or item["text_evidence_id"],
                     "layer": item.get("layer"), "source_block": (item.get("block_path") or [None])[-1],
                     "source_insert_handle": item.get("source_insert_handle"),
                     "source_insert_handle_path": deepcopy(item.get("insert_handle_path") or []),
                     "source_block_path": deepcopy(item.get("block_path") or []),
                     "text": item.get("plain_text"), "point": tuple(item.get("position") or []),
                     "text_evidence_id": item["text_evidence_id"],
                     "role_candidates": deepcopy(item.get("role_candidates") or [])})
    return rows


def bind_text_hosts(contract: dict, *, frames: list[dict], spaces: list[dict], tolerance: float) -> dict:
    """Bind exact text to existing hosts; no nearest-centroid authority exists."""
    result = deepcopy(contract)
    frame_polys = {f.get("frame_id"): box(*f["bounds"]) for f in frames if f.get("frame_id") and f.get("bounds")}
    space_polys = {s.get("physical_space_id"): Polygon(s["polygon"], s.get("interior_rings") or [])
                   for s in spaces if s.get("physical_space_id") and s.get("polygon")}
    edge_tolerance = max(float(tolerance or 0.0) * 3.0, 1e-8)
    for item in result.get("items") or []:
        point = Point(item["position"])
        frame_ids = sorted(fid for fid, poly in frame_polys.items() if poly.covers(point))
        roles = {row["role"] for row in item.get("role_candidates") or []}
        document_roles = roles.intersection({"TITLE_BLOCK_KEY", "TITLE_BLOCK_VALUE", "PROJECT_METADATA",
                                             "DRAWING_TYPE_TITLE", "PLAN_TITLE", "LEVEL_TITLE",
                                             "DRAWING_NUMBER", "REVISION", "DATE", "SCALE_TEXT",
                                             "DISCIPLINE", "DESIGNER_OR_COMPANY_METADATA"})
        if document_roles:
            host_ids = frame_ids
            host_kind = "FRAME"
        elif "SPACE_LABEL" in roles:
            exact = sorted(sid for sid, poly in space_polys.items() if poly.contains(point))
            edge = [] if exact else sorted(sid for sid, poly in space_polys.items() if poly.boundary.distance(point) <= edge_tolerance)
            host_ids = exact or edge
            host_kind = "PHYSICAL_SPACE"
        else:
            host_ids = frame_ids
            host_kind = "FRAME"
        verified = len(host_ids) == 1
        item["host_binding"] = {"status": "VERIFIED" if verified else "CONFLICT" if len(host_ids) > 1 else "INPUT_REQUIRED",
                                "host_id": host_ids[0] if verified else None, "candidate_host_ids": host_ids,
                                "host_kind": host_kind, "method": "EXACT_CONTAINMENT" if verified else None,
                                "binding_fingerprint": _hash([item["text_evidence_id"], host_kind, host_ids])}
        item["authority"]["semantic"] = bool(verified and host_kind == "PHYSICAL_SPACE" and
                                              item.get("semantic_candidates") and item.get("instance_value_authority"))
        item["authority"]["document_metadata"] = bool(verified and host_kind == "FRAME" and
                                                       document_roles and item.get("instance_value_authority"))
    result["metrics"] = {**(result.get("metrics") or {}),
                         "hosted_count": sum(x["host_binding"]["status"] == "VERIFIED" for x in result.get("items") or []),
                         "unresolved_host_count": sum(x["host_binding"]["status"] != "VERIFIED" for x in result.get("items") or [])}
    return result


def functional_composition(contract: dict, physical_space_id: str) -> list[str]:
    values = set()
    for item in contract.get("items") or []:
        binding = item.get("host_binding") or {}
        if binding.get("status") == "VERIFIED" and binding.get("host_id") == physical_space_id and item.get("authority", {}).get("semantic"):
            values.update(item.get("semantic_candidates") or [])
    return sorted(values)


def build_title_block_fields(contract: dict) -> list[dict]:
    fields = []
    for item in contract.get("items") or []:
        if item.get("occurrence_kind") != "ATTRIBUTE_INSTANCE" or not item.get("instance_value_authority"):
            continue
        verified = [row["role"] for row in item.get("role_candidates") or [] if row["evidence"] == "EXACT_ATTRIBUTE_TAG"]
        for role in verified:
            hosted = (item.get("host_binding") or {}).get("status") == "VERIFIED"
            fields.append({"title_block_field_id": "TB-" + _hash([item["text_evidence_id"], role])[:20].upper(),
                           "field_role": role, "value": item.get("plain_text"),
                           "text_evidence_id": item["text_evidence_id"],
                           "source_insert_handle": item.get("source_insert_handle"),
                           "frame_id": (item.get("host_binding") or {}).get("host_id"),
                           "status": "VERIFIED" if hosted else "INPUT_REQUIRED",
                           "authority": {"document_metadata": hosted, "material_geometry": False,
                                         "engineering_scale": False, "north": False}})
    return sorted(fields, key=lambda row: row["title_block_field_id"])


def text_review_identity(item: dict, *, question_scope: str, frame_id: str | None = None,
                         host_fingerprint: str | None = None) -> dict:
    identity = {"source_sha256": item.get("source_sha256"), "frame_id": frame_id,
                "text_evidence_id": item.get("text_evidence_id"),
                "entity_handle": item.get("entity_handle"), "source_insert_handle": item.get("source_insert_handle"),
                "instance_path": deepcopy(item.get("instance_path") or []),
                "insert_handle_path": deepcopy(item.get("insert_handle_path") or []),
                "position_fingerprint": item.get("position_fingerprint"),
                "provenance_fingerprint": item.get("provenance_fingerprint"),
                "host_fingerprint": host_fingerprint, "question_scope": question_scope}
    return {**identity, "review_fingerprint": _hash(identity)}


def review_is_current(expected: dict, supplied: dict) -> bool:
    keys = ("source_sha256", "frame_id", "text_evidence_id", "entity_handle", "source_insert_handle",
            "instance_path", "insert_handle_path", "position_fingerprint", "provenance_fingerprint", "host_fingerprint",
            "question_scope", "review_fingerprint")
    return all(supplied.get(key) == expected.get(key) for key in keys)


def create_text_review_item(item: dict, *, question_scope: str, frame_id: str | None,
                            host_fingerprint: str | None, allowed_answers: list[str]) -> dict:
    """Create a bounded review of an existing text fact, never a geometry edit."""
    identity = text_review_identity(item, question_scope=question_scope, frame_id=frame_id,
                                    host_fingerprint=host_fingerprint)
    answers = sorted(set(str(value) for value in allowed_answers))
    return {"review_item_id": "TEXT-REVIEW-" + identity["review_fingerprint"][:20].upper(),
            **identity, "allowed_answers": answers,
            "authority_scope": "SOURCE_TEXT_INTERPRETATION_ONLY",
            "geometry_creation_allowed": False}


def apply_text_review_decision(contract: dict, review_item: dict, decision: dict) -> dict:
    """Apply only the exact reviewed interpretation to the source-bound occurrence."""
    result = deepcopy(contract)
    target = next((row for row in result.get("items") or []
                   if row.get("text_evidence_id") == review_item.get("text_evidence_id")), None)
    if target is None:
        return {"status": "REJECTED", "errors": ["TEXT_REVIEW_TARGET_MISSING"], "text_evidence": result}
    expected = text_review_identity(
        target, question_scope=review_item.get("question_scope"), frame_id=review_item.get("frame_id"),
        host_fingerprint=review_item.get("host_fingerprint"))
    supplied = {key: decision.get(key, review_item.get(key)) for key in expected}
    answer = decision.get("answer")
    errors = []
    if not review_is_current(expected, supplied):
        errors.append("TEXT_REVIEW_STALE")
    if answer not in (review_item.get("allowed_answers") or []):
        errors.append("TEXT_REVIEW_ANSWER_OUT_OF_SCOPE")
    if review_item.get("geometry_creation_allowed") is not False:
        errors.append("TEXT_REVIEW_GEOMETRY_SCOPE_INVALID")
    if errors:
        return {"status": "REJECTED", "errors": errors, "text_evidence": result}
    target["human_review"] = {"review_item_id": review_item["review_item_id"], "answer": answer,
                              "authority": "HUMAN_SOURCE_INTERPRETATION",
                              "binding": expected, "question_scope": review_item["question_scope"],
                              "material_geometry": False, "geometry_created": False}
    return {"status": "APPLIED", "errors": [], "text_evidence": result}


def validate_text_contract(contract: dict, *, source_sha256: str) -> list[dict]:
    errors = []
    ids = set()
    for item in contract.get("items") or []:
        text_id = item.get("text_evidence_id")
        if not text_id or text_id in ids:
            errors.append({"code": "TEXT_EVIDENCE_ID_INVALID", "text_evidence_id": text_id})
        ids.add(text_id)
        if item.get("source_sha256") != source_sha256:
            errors.append({"code": "TEXT_SOURCE_BINDING_INVALID", "text_evidence_id": text_id})
        if item.get("occurrence_kind") == "TEMPLATE_DEFINITION" and item.get("instance_value_authority"):
            errors.append({"code": "ATTDEF_INSTANCE_AUTHORITY_FORBIDDEN", "text_evidence_id": text_id})
        authority = item.get("authority") or {}
        if any(authority.get(key) for key in ("material_geometry", "engineering_scale", "north")):
            errors.append({"code": "TEXT_ENGINEERING_AUTHORITY_FORBIDDEN", "text_evidence_id": text_id})
        if authority.get("semantic") and (item.get("host_binding") or {}).get("status") != "VERIFIED":
            errors.append({"code": "TEXT_SEMANTIC_HOST_REQUIRED", "text_evidence_id": text_id})
        review = item.get("human_review")
        if review:
            binding = review.get("binding") or {}
            expected = text_review_identity(item, question_scope=review.get("question_scope"),
                                            frame_id=binding.get("frame_id"),
                                            host_fingerprint=binding.get("host_fingerprint"))
            if not review_is_current(expected, binding):
                errors.append({"code": "TEXT_REVIEW_STALE", "text_evidence_id": text_id})
            if review.get("material_geometry") or review.get("geometry_created"):
                errors.append({"code": "TEXT_REVIEW_GEOMETRY_AUTHORITY_FORBIDDEN",
                               "text_evidence_id": text_id})
    return errors


def compare_text_evidence(contract: dict, truth: dict) -> dict:
    """Dimension-specific metrics against independently curated text truth."""
    if truth.get("schema") != "planha-architectural-text-truth/1.0" or not truth.get("review_source"):
        raise ValueError("INDEPENDENT_TEXT_TRUTH_REQUIRED")
    predicted = {row["text_evidence_id"]: row for row in contract.get("items") or []}
    dimensions = {name: {"correct": 0, "total": 0} for name in
                  ("extraction", "role_classification", "host_binding", "semantic_classification",
                   "title_block_extraction")}
    for row in truth.get("items") or []:
        item = predicted.get(row.get("text_evidence_id"))
        dimensions["extraction"]["total"] += 1
        dimensions["extraction"]["correct"] += int(item is not None)
        for name, predicted_value, truth_key in (
            ("role_classification", sorted(x["role"] for x in (item or {}).get("role_candidates") or []), "roles"),
            ("host_binding", (item or {}).get("host_binding", {}).get("host_id"), "host_id"),
            ("semantic_classification", sorted((item or {}).get("semantic_candidates") or []), "semantics"),
            ("title_block_extraction", bool(any(x["evidence"] == "EXACT_ATTRIBUTE_TAG" for x in
                                                (item or {}).get("role_candidates") or [])), "is_title_field"),
        ):
            if truth_key not in row:
                continue
            dimensions[name]["total"] += 1
            dimensions[name]["correct"] += int(predicted_value == row[truth_key])
    for value in dimensions.values():
        value["accuracy"] = value["correct"] / value["total"] if value["total"] else None
    return {"schema": "planha-architectural-text-benchmark/1.0", "metrics": dimensions,
            "overall_accuracy": None, "golden_source": truth["review_source"]}
