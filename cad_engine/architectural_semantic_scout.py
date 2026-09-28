"""Whole-floor architectural semantics without engineering geometry authority.

Vision output in this module is deliberately approximate.  It can guide an
engineering pre-analysis, but cannot create walls, physical spaces, routing
obstacles, or final design authority.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any
import base64
import json
import math
import os
import time


SEMANTIC_MAP_SCHEMA = "architectural-semantic-map/1.0"
SEMANTIC_PROMPT_VERSION = "whole-floor-semantic-scout/1"
COMPACT_SEMANTIC_SCHEMA = "architectural-semantic-hint/2.0"
COMPACT_PROMPT_VERSION = "compact-multi-pass-semantic-scout/2"
COMPACT_RESPONSE_BUDGET = 1800
SEMANTIC_AUTHORITY = "VISION_SEMANTIC_HINT"
SEMANTIC_TYPES = {
    "BEDROOM", "MASTER_BEDROOM", "LIVING", "RECEPTION", "DINING", "OPEN_PLAN",
    "KITCHEN", "KITCHENETTE", "BATHROOM", "SHOWER", "TOILET", "ENTRANCE",
    "VESTIBULE", "CORRIDOR", "LOBBY", "CLOSET", "STORAGE", "LAUNDRY",
    "UTILITY", "STAIR", "STAIR_LANDING", "ELEVATOR", "ELEVATOR_LOBBY",
    "SHAFT", "DUCT", "BALCONY", "TERRACE", "PATIO", "YARD", "BACKYARD",
    "COURTYARD", "LIGHTWELL", "PARKING", "DRIVEWAY", "RAMP", "MECHANICAL_ROOM",
    "ELECTRICAL_ROOM", "VOID", "UNKNOWN",
}
EVIDENCE_CLASSES = {
    "EXACT_DXF_LABEL", "VISUAL_TEXT", "FIXTURE", "FURNITURE", "SPATIAL_LAYOUT",
    "STAIR_PATTERN", "EXTERIOR_RELATION", "OTHER",
}
MEP_GROUPS = {
    "BATHROOM": ["WET_AREA"], "SHOWER": ["WET_AREA"], "TOILET": ["WET_AREA"],
    "KITCHEN": ["FOOD_PREPARATION", "SERVICE_AREA"],
    "KITCHENETTE": ["FOOD_PREPARATION", "SERVICE_AREA"],
    "BEDROOM": ["HABITABLE_ROOM"], "MASTER_BEDROOM": ["HABITABLE_ROOM"],
    "LIVING": ["HABITABLE_ROOM"], "RECEPTION": ["HABITABLE_ROOM"],
    "DINING": ["HABITABLE_ROOM"], "OPEN_PLAN": ["HABITABLE_ROOM"],
    "ENTRANCE": ["CIRCULATION"], "VESTIBULE": ["CIRCULATION"],
    "CORRIDOR": ["CIRCULATION"], "LOBBY": ["CIRCULATION"],
    "STAIR": ["VERTICAL_CORE", "CIRCULATION"],
    "STAIR_LANDING": ["VERTICAL_CORE", "CIRCULATION"],
    "ELEVATOR": ["VERTICAL_CORE"], "ELEVATOR_LOBBY": ["VERTICAL_CORE", "CIRCULATION"],
    "SHAFT": ["VERTICAL_CORE", "SERVICE_AREA"], "DUCT": ["VERTICAL_CORE", "SERVICE_AREA"],
    "BALCONY": ["EXTERIOR_OR_SEMI_EXTERIOR"], "TERRACE": ["EXTERIOR_OR_SEMI_EXTERIOR"],
    "PATIO": ["EXTERIOR_OR_SEMI_EXTERIOR"], "YARD": ["EXTERIOR_OR_SEMI_EXTERIOR"],
    "BACKYARD": ["EXTERIOR_OR_SEMI_EXTERIOR"], "COURTYARD": ["EXTERIOR_OR_SEMI_EXTERIOR"],
    "LIGHTWELL": ["EXTERIOR_OR_SEMI_EXTERIOR"],
    "PARKING": ["VEHICLE_AREA"], "DRIVEWAY": ["VEHICLE_AREA"], "RAMP": ["VEHICLE_AREA"],
    "STORAGE": ["SERVICE_AREA"], "LAUNDRY": ["SERVICE_AREA"], "UTILITY": ["SERVICE_AREA"],
    "MECHANICAL_ROOM": ["SERVICE_AREA"], "ELECTRICAL_ROOM": ["SERVICE_AREA"],
}


class SemanticScoutError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _stable(prefix: str, value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"{prefix}-" + sha256(raw.encode()).hexdigest()[:12].upper()


def _point(value: Any, name: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 2:
        raise SemanticScoutError("SEMANTIC_LOCATION_INVALID", f"{name} must contain two coordinates")
    result = [float(value[0]), float(value[1])]
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in result):
        raise SemanticScoutError("SEMANTIC_LOCATION_INVALID", f"{name} must be normalized")
    return result


def validate_semantic_item(item: dict[str, Any]) -> dict[str, Any]:
    allowed = {"semantic_type", "confidence", "approx_center_norm", "approx_bbox_norm",
               "evidence_classes", "observed_text", "objects_seen", "uncertainty"}
    if not isinstance(item, dict) or set(item) != allowed:
        raise SemanticScoutError("SEMANTIC_ITEM_INVALID", "Semantic item fields are not canonical")
    semantic_type = str(item["semantic_type"]).upper()
    if semantic_type not in SEMANTIC_TYPES:
        raise SemanticScoutError("SEMANTIC_TYPE_INVALID", semantic_type)
    confidence = float(item["confidence"])
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise SemanticScoutError("SEMANTIC_CONFIDENCE_INVALID", str(confidence))
    center = _point(item["approx_center_norm"], "approx_center_norm")
    bbox = item["approx_bbox_norm"]
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise SemanticScoutError("SEMANTIC_BBOX_INVALID", "bbox must contain four coordinates")
    bbox = [float(x) for x in bbox]
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in bbox) or not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        raise SemanticScoutError("SEMANTIC_BBOX_INVALID", "bbox is invalid or not normalized")
    if not (bbox[0] <= center[0] <= bbox[2] and bbox[1] <= center[1] <= bbox[3]):
        raise SemanticScoutError("SEMANTIC_CENTER_OUTSIDE_BBOX", "center must be inside bbox")
    evidence = [str(x).upper() for x in item["evidence_classes"]]
    if not evidence or any(x not in EVIDENCE_CLASSES for x in evidence):
        raise SemanticScoutError("SEMANTIC_EVIDENCE_INVALID", "Evidence is empty or unsupported")
    result = dict(item)
    result.update({"semantic_type": semantic_type, "confidence": confidence,
                   "approx_center_norm": center, "approx_bbox_norm": bbox,
                   "evidence_classes": sorted(set(evidence)),
                   "observed_text": [str(x) for x in item["observed_text"]],
                   "objects_seen": [str(x) for x in item["objects_seen"]],
                   "uncertainty": [str(x) for x in item["uncertainty"]]})
    return result


def assign_hint_ids(items: list[dict[str, Any]], *, source_sha256: str, frame_id: str,
                    call_hash: str) -> list[dict[str, Any]]:
    result = []
    for item in items:
        row = validate_semantic_item(item)
        identity = [source_sha256, frame_id, call_hash, row["semantic_type"],
                    [round(x, 5) for x in row["approx_center_norm"]]]
        result.append({"semantic_hint_id": _stable("SEM", identity), **row,
                       "mep_groups": MEP_GROUPS.get(row["semantic_type"], []),
                       "authority": SEMANTIC_AUTHORITY, "material_geometry": None,
                       "routing_authority": "NONE", "engineering_geometry": False})
    return result


def build_text_sidecar(graph: dict[str, Any]) -> list[dict[str, Any]]:
    bounds = graph["frame_bounds"]
    diagnostics = (graph.get("preauthority") or {}).get("label_host_diagnostics") or []
    diagnostic_points = {str(item.get("label_id")): item.get("point") for item in diagnostics
                         if item.get("label_id") and item.get("point")}
    rows = []
    for item in diagnostics:
        point = item.get("point")
        text = item.get("text") or item.get("exact_text")
        if point and text:
            rows.append({"text": str(text), "normalized_position": cad_to_normalized(point, bounds),
                         "source_class": "EXACT_DXF_TEXT"})
    if not rows:
        seen = set()
        for region in graph.get("regions") or []:
            for evidence in region.get("exact_text_evidence") or []:
                text = evidence.get("text")
                if not text or text in seen:
                    continue
                seen.add(text)
                point = diagnostic_points.get(str(evidence.get("source_handle"))) or region["centroid"]
                rows.append({"text": str(text),
                             "normalized_position": cad_to_normalized(point, bounds),
                             "source_class": "EXACT_DXF_TEXT"})
    return sorted(rows, key=lambda x: (x["normalized_position"], x["text"]))


def build_object_sidecar(graph: dict[str, Any]) -> list[dict[str, Any]]:
    bounds = graph["frame_bounds"]
    rows, seen = [], set()
    for region in graph.get("regions") or []:
        for evidence in region.get("object_evidence") or []:
            kind = evidence.get("type") or evidence.get("object_type") or evidence.get("semantic_candidate")
            key = (kind, evidence.get("source_handle"), tuple(region["centroid"]))
            if not kind or key in seen:
                continue
            seen.add(key)
            rows.append({"type": str(kind).upper(),
                         "normalized_position": cad_to_normalized(region["centroid"], bounds),
                         "confidence": float(evidence.get("confidence", 0.7)),
                         "source_class": "DETERMINISTIC_CAD_OBJECT"})
    return rows


def cad_to_normalized(point: list[float] | tuple[float, float], bounds: list[float]) -> list[float]:
    minx, miny, maxx, maxy = map(float, bounds)
    return [(float(point[0]) - minx) / max(maxx - minx, 1e-12),
            (maxy - float(point[1])) / max(maxy - miny, 1e-12)]


def normalized_to_cad(point: list[float], bounds: list[float]) -> list[float]:
    x, y = _point(point, "normalized point")
    minx, miny, maxx, maxy = map(float, bounds)
    return [minx + x * (maxx - minx), maxy - y * (maxy - miny)]


def normalized_bbox_to_cad(bbox: list[float], bounds: list[float]) -> list[float]:
    probe = validate_semantic_item({"semantic_type": "UNKNOWN", "confidence": 0,
        "approx_center_norm": [(bbox[0]+bbox[2])/2, (bbox[1]+bbox[3])/2],
        "approx_bbox_norm": bbox, "evidence_classes": ["OTHER"], "observed_text": [],
        "objects_seen": [], "uncertainty": []})["approx_bbox_norm"]
    left_top = normalized_to_cad(probe[:2], bounds)
    right_bottom = normalized_to_cad(probe[2:], bounds)
    return [left_top[0], right_bottom[1], right_bottom[0], left_top[1]]


def semantic_output_schema() -> dict[str, Any]:
    item = {"type": "object", "additionalProperties": False,
        "required": ["semantic_type", "confidence", "approx_center_norm", "approx_bbox_norm",
                     "evidence_classes", "observed_text", "objects_seen", "uncertainty"],
        "properties": {
            "semantic_type": {"type": "string", "enum": sorted(SEMANTIC_TYPES)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "approx_center_norm": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
            "approx_bbox_norm": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
            "evidence_classes": {"type": "array", "items": {"type": "string", "enum": sorted(EVIDENCE_CLASSES)}},
            "observed_text": {"type": "array", "items": {"type": "string"}},
            "objects_seen": {"type": "array", "items": {"type": "string"}},
            "uncertainty": {"type": "array", "items": {"type": "string"}},
        }}
    return {"type": "object", "additionalProperties": False,
            "required": ["frame_id", "semantic_zones", "unclassified_areas", "overall_confidence"],
            "properties": {"frame_id": {"type": "string"},
                "semantic_zones": {"type": "array", "items": item},
                "unclassified_areas": {"type": "array", "items": item},
                "overall_confidence": {"type": "number", "minimum": 0, "maximum": 1}}}


def semantic_prompt(frame_id: str, labels: list[dict], objects: list[dict], *, local_area=None) -> str:
    scope = ("Identify every architectural function visible in the highlighted local area; use the "
             "whole-floor image for orientation." if local_area else
             "Inspect the entire floor systematically and identify every architectural function you can reasonably recognize.")
    return ("You are reviewing a complete architectural floor plan as an architectural semantic reviewer. "
            "You are not a CAD geometry generator. " + scope + " Return approximate normalized image locations only. "
            "Bounding boxes are semantic localization, never wall boundaries, rooms, routing obstacles, or engineering geometry. "
            "Use UNKNOWN when function is unclear. Exact DXF labels supplied below outrank OCR and visual inference. "
            "Pay special attention to kitchens, wet areas, bedrooms, living/reception, circulation, stairs, shafts, "
            "yards, parking, entrances, balconies and terraces. Return structured data only. "
            f"FRAME_ID={frame_id}; EXACT_DXF_LABELS={json.dumps(labels, ensure_ascii=False, separators=(',',':'))}; "
            f"CAD_OBJECT_EVIDENCE={json.dumps(objects, ensure_ascii=False, separators=(',',':'))}; "
            f"LOCAL_AREA={json.dumps(local_area, separators=(',',':')) if local_area else 'NONE'}")


def validate_provider_payload(payload: dict[str, Any], *, frame_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"frame_id", "semantic_zones", "unclassified_areas", "overall_confidence"}:
        raise SemanticScoutError("SEMANTIC_RESPONSE_INVALID", "Response root fields are not canonical")
    if payload["frame_id"] != frame_id:
        raise SemanticScoutError("SEMANTIC_FRAME_MISMATCH", "Provider returned a different frame")
    confidence = float(payload["overall_confidence"])
    if not 0 <= confidence <= 1:
        raise SemanticScoutError("SEMANTIC_CONFIDENCE_INVALID", "overall confidence is invalid")
    return {"frame_id": frame_id,
            "semantic_zones": [validate_semantic_item(x) for x in payload["semantic_zones"]],
            "unclassified_areas": [validate_semantic_item(x) for x in payload["unclassified_areas"]],
            "overall_confidence": confidence}


def _bbox_iou(a: list[float], b: list[float]) -> float:
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union else 0.0


def reconcile_observations(global_hints: list[dict], local_hints: list[dict], *, source_sha256: str,
                           frame_id: str, call_hash: str) -> dict[str, Any]:
    merged, conflicts = [], []
    for row in [*global_hints, *local_hints]:
        row = validate_semantic_item({k: row[k] for k in {"semantic_type", "confidence", "approx_center_norm",
            "approx_bbox_norm", "evidence_classes", "observed_text", "objects_seen", "uncertainty"}})
        match = next((x for x in merged if x["semantic_type"] == row["semantic_type"] and
                      (_bbox_iou(x["approx_bbox_norm"], row["approx_bbox_norm"]) >= .25 or
                       math.dist(x["approx_center_norm"], row["approx_center_norm"]) <= .09)), None)
        if match:
            match["confidence"] = max(match["confidence"], row["confidence"])
            for key in ("evidence_classes", "observed_text", "objects_seen", "uncertainty"):
                match[key] = sorted(set(match[key]) | set(row[key]))
            match["cross_pass_agreement"] = True
        else:
            for other in merged:
                if other["semantic_type"] != row["semantic_type"] and _bbox_iou(other["approx_bbox_norm"], row["approx_bbox_norm"]) > .65:
                    conflicts.append({"left_type": other["semantic_type"], "right_type": row["semantic_type"],
                                      "reason": "OVERLAPPING_DIFFERENT_SEMANTICS"})
            merged.append({**row, "cross_pass_agreement": False})
    canonical = [{k: x[k] for k in ("semantic_type", "confidence", "approx_center_norm", "approx_bbox_norm",
        "evidence_classes", "observed_text", "objects_seen", "uncertainty")} for x in merged]
    assigned = assign_hint_ids(canonical, source_sha256=source_sha256,
                               frame_id=frame_id, call_hash=call_hash)
    for output, source in zip(assigned, merged):
        output["cross_pass_agreement"] = source["cross_pass_agreement"]
    return {"semantic_zones": assigned, "conflicts": conflicts}


def coverage_audit(hints: list[dict], labels: list[dict], *, grid_size: int = 8) -> dict[str, Any]:
    covered = set()
    for hint in hints:
        x0, y0, x1, y1 = hint["approx_bbox_norm"]
        for row in range(grid_size):
            for col in range(grid_size):
                cx, cy = (col+.5)/grid_size, (row+.5)/grid_size
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    covered.add((row, col))
    explained, unexplained = [], []
    for label in labels:
        if any(h["approx_bbox_norm"][0] <= label["normalized_position"][0] <= h["approx_bbox_norm"][2] and
               h["approx_bbox_norm"][1] <= label["normalized_position"][1] <= h["approx_bbox_norm"][3] for h in hints):
            explained.append(label["text"])
        else:
            unexplained.append(label["text"])
    gaps = [{"grid_cell": [r, c], "reason": "SEMANTIC_COVERAGE_GAP"}
            for r in range(grid_size) for c in range(grid_size) if (r, c) not in covered]
    return {"grid_size": grid_size, "coverage_estimate": len(covered)/(grid_size*grid_size),
            "covered_cells": len(covered), "coverage_gaps": gaps,
            "exact_labels_explained": explained, "exact_labels_unexplained": unexplained}


def adaptive_local_triggers(coverage: dict, hints: list[dict], labels: list[dict]) -> list[dict[str, Any]]:
    triggers = []
    for label in labels:
        if label["text"] in coverage["exact_labels_unexplained"]:
            x, y = label["normalized_position"]
            triggers.append({"reason": "UNEXPLAINED_EXACT_LABEL", "label": label["text"],
                             "bbox_norm": [max(0,x-.12), max(0,y-.12), min(1,x+.12), min(1,y+.12)]})
    for hint in hints:
        if hint["confidence"] < .5 and hint["semantic_type"] in {"KITCHEN", "BATHROOM", "TOILET", "STAIR", "SHAFT", "UNKNOWN"}:
            triggers.append({"reason": "LOW_CONFIDENCE_MEP_CRITICAL", "semantic_hint_id": hint.get("semantic_hint_id"),
                             "bbox_norm": hint["approx_bbox_norm"]})
    return triggers


def map_hints_to_candidates(hints: list[dict], graph: dict[str, Any]) -> list[dict[str, Any]]:
    from shapely.geometry import box as shapely_box, Polygon
    result = []
    for hint in hints:
        cad_bbox = normalized_bbox_to_cad(hint["approx_bbox_norm"], graph["frame_bounds"])
        semantic_box = shapely_box(*cad_bbox)
        overlaps = []
        for region in graph.get("regions") or []:
            polygon = Polygon(region["polygon"])
            area = polygon.intersection(semantic_box).area
            if area > 0:
                overlaps.append({"candidate_id": region["region_id"],
                                 "candidate_overlap": area/max(polygon.area, 1e-12),
                                 "hint_overlap": area/max(semantic_box.area, 1e-12)})
        strong = [x for x in overlaps if x["candidate_overlap"] >= .5 or x["hint_overlap"] >= .5]
        status = "STRONG_MATCH" if len(strong) == 1 else ("MULTIPLE_CANDIDATES" if overlaps else "NO_CANDIDATE_MATCH")
        result.append({"semantic_hint_id": hint["semantic_hint_id"], "semantic_type": hint["semantic_type"],
                       "approx_cad_bbox": cad_bbox, "overlapping_candidates": overlaps,
                       "mapping_status": status, "engineering_geometry": False})
    return result


def fuse_semantic_evidence(hints: list[dict], labels: list[dict], objects: list[dict]) -> list[dict[str, Any]]:
    result = []
    for hint in hints:
        bbox = hint["approx_bbox_norm"]
        nearby_labels = [x["text"] for x in labels if bbox[0] <= x["normalized_position"][0] <= bbox[2]
                         and bbox[1] <= x["normalized_position"][1] <= bbox[3]]
        nearby_objects = [x["type"] for x in objects if bbox[0] <= x["normalized_position"][0] <= bbox[2]
                          and bbox[1] <= x["normalized_position"][1] <= bbox[3]]
        independent = bool(nearby_labels or nearby_objects)
        status = "STRONGLY_SUPPORTED" if nearby_labels else ("MULTI_EVIDENCE_SUPPORTED" if nearby_objects else SEMANTIC_AUTHORITY)
        result.append({"semantic_hint_id": hint["semantic_hint_id"], "semantic_type": hint["semantic_type"],
                       "semantic_status": status, "geometry_status": "INPUT_REQUIRED",
                       "label_support": nearby_labels, "object_support": nearby_objects,
                       "independent_support": independent})
    return result


def build_mep_preanalysis(hints: list[dict], fused: list[dict]) -> dict[str, Any]:
    groups: dict[str, list[str]] = {}
    for hint in hints:
        for group in hint.get("mep_groups") or []:
            groups.setdefault(group, []).append(hint["semantic_hint_id"])
    return {"mode": "MEP_PREANALYSIS", "semantic_hint_groups": groups,
            "priority_verification_ids": sorted({x["semantic_hint_id"] for x in fused
                                                  if x["semantic_type"] in {"BATHROOM","TOILET","KITCHEN","SHAFT"}}),
            "allowed_uses": ["FIXTURE_SEARCH", "WET_CORE_SEARCH", "SHAFT_SEARCH", "WORKFLOW_SELECTION", "INPUT_PLANNING"],
            "forbidden_uses": ["FINAL_ROUTING", "FINAL_EQUIPMENT_PLACEMENT", "FINAL_LOADS", "ENGINEER_READY_OUTPUT"],
            "engineering_authority": False}


def build_semantic_map(*, graph: dict, provider_payload: dict, provider: str, model: str,
                       render_hash: str, call_hash: str, local_payloads: list[dict] | None = None) -> dict[str, Any]:
    validated = validate_provider_payload(provider_payload, frame_id=graph["frame_id"])
    local_items = []
    for payload in local_payloads or []:
        local_items.extend(validate_provider_payload(payload, frame_id=graph["frame_id"])["semantic_zones"])
    reconciliation = reconcile_observations(validated["semantic_zones"], local_items,
        source_sha256=graph["source_sha256"], frame_id=graph["frame_id"], call_hash=call_hash)
    labels, objects = build_text_sidecar(graph), build_object_sidecar(graph)
    hints = reconciliation["semantic_zones"]
    coverage = coverage_audit(hints, labels)
    mappings = map_hints_to_candidates(hints, graph)
    fused = fuse_semantic_evidence(hints, labels, objects)
    return {"schema": SEMANTIC_MAP_SCHEMA, "frame_id": graph["frame_id"],
        "source_sha256": graph["source_sha256"], "render_hash": render_hash,
        "provider": provider, "model": model, "semantic_zones": hints,
        "architectural_features": objects, "unclassified_areas": validated["unclassified_areas"],
        "overall_confidence": validated["overall_confidence"], "semantic_coverage": coverage,
        "conflicts": reconciliation["conflicts"], "candidate_mapping": mappings,
        "semantic_fusion": fused, "mep_preanalysis": build_mep_preanalysis(hints, fused),
        "adaptive_local_triggers": adaptive_local_triggers(coverage, hints, labels),
        "evidence": {"exact_dxf_text": labels, "objects": objects},
        "authority": SEMANTIC_AUTHORITY, "engineering_geometry": False}


def _encode_image(path: str | Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def render_clean_whole_floor(graph: dict, output_path: str | Path, *, width: int = 1800,
                             height: int = 1800) -> dict[str, Any]:
    """Render source-derived architectural evidence with no candidate/debug overlay."""
    from PIL import Image, ImageDraw
    bounds = graph["frame_bounds"]
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    def pixel(point):
        x, y = cad_to_normalized(point, bounds)
        return (x * width, y * height)
    count = 0
    for segment in (graph.get("preauthority") or {}).get("source_segments") or []:
        geometry = segment.get("geometry") or []
        if len(geometry) < 2 or segment.get("authority_tier") == "HARD_EXCLUDED_NON_ARCHITECTURAL":
            continue
        color = (31, 41, 55) if segment.get("authority_tier") == "HARD_ACCEPTED_ARCHITECTURAL" else (107, 114, 128)
        draw.line([pixel(point) for point in geometry], fill=color, width=2)
        count += 1
    for label in build_text_sidecar(graph):
        x, y = label["normalized_position"]
        draw.text((x*width, y*height), label["text"], fill=(17,24,39), anchor="mm")
    output_path = Path(output_path); image.save(output_path)
    return {"path": str(output_path), "render_hash": sha256(output_path.read_bytes()).hexdigest(),
            "width": width, "height": height, "source_segment_count": count,
            "candidate_overlay": False, "debug_overlay": False}


def render_global_local_semantic_context(source_path: str | Path, bbox_norm: list[float],
                                         output_path: str | Path) -> dict[str, Any]:
    """Create global orientation plus a large clean local crop for adaptive review."""
    from PIL import Image, ImageDraw
    probe = validate_semantic_item({"semantic_type":"UNKNOWN","confidence":0,
        "approx_center_norm":[(bbox_norm[0]+bbox_norm[2])/2,(bbox_norm[1]+bbox_norm[3])/2],
        "approx_bbox_norm":bbox_norm,"evidence_classes":["OTHER"],"observed_text":[],
        "objects_seen":[],"uncertainty":[]})
    image = Image.open(source_path).convert("RGB")
    x0,y0,x1,y1 = probe["approx_bbox_norm"]
    pixel_box=(int(x0*image.width),int(y0*image.height),int(x1*image.width),int(y1*image.height))
    local=image.crop(pixel_box); global_view=image.copy(); marker=ImageDraw.Draw(global_view)
    marker.rectangle(pixel_box,outline=(220,38,38),width=max(3,image.width//400))
    canvas=Image.new("RGB",(image.width*2,image.height),"white")
    canvas.paste(global_view,(0,0)); canvas.paste(local.resize(image.size),(image.width,0))
    output_path=Path(output_path); canvas.save(output_path)
    return {"path":str(output_path),"render_hash":sha256(output_path.read_bytes()).hexdigest(),
            "bbox_norm":bbox_norm,"global_context":True,"local_detail":True}


class DeepSeekSemanticScout:
    """One-call strict semantic transport; no retries and no engineering geometry."""
    def __init__(self, *, api_key: str | None = None, model: str = "deepseek-flash", client=None):
        credential = api_key or os.getenv("DEEPSEEK_API_KEY")
        if client is None:
            if not credential:
                raise SemanticScoutError("PROVIDER_CONFIG_REQUIRED", "DEEPSEEK_API_KEY is missing")
            from openai import OpenAI
            client = OpenAI(api_key=credential, base_url="https://api.deepseek.com/beta", timeout=120, max_retries=0)
        self.client, self.model, self.last_call_metadata = client, model, {}

    def analyze(self, *, image_paths: list[str], frame_id: str, labels: list[dict], objects: list[dict],
                local_area: list[float] | None = None) -> dict[str, Any]:
        if not image_paths or len(image_paths) > 2:
            raise SemanticScoutError("SEMANTIC_IMAGE_COUNT_INVALID", "One global image or global+local images required")
        prompt = semantic_prompt(frame_id, labels, objects, local_area=local_area)
        schema = semantic_output_schema()
        tool_name = "submit_architectural_semantic_map_v1"
        content = [{"type": "text", "text": prompt}]
        for path in image_paths:
            content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64,"+_encode_image(path), "detail": "original"}})
        request_hash = sha256((prompt + json.dumps(schema, sort_keys=True) +
                              "".join(sha256(Path(p).read_bytes()).hexdigest() for p in image_paths)).encode()).hexdigest()
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(model=self.model,
                messages=[{"role": "user", "content": content}],
                tools=[{"type": "function", "function": {"name": tool_name, "strict": True,
                    "description": "Submit approximate whole-floor architectural semantics only.", "parameters": schema}}],
                tool_choice={"type": "function", "function": {"name": tool_name}},
                extra_body={"thinking": {"type": "disabled"}})
        except Exception as exc:
            self.last_call_metadata = {"request_hash": request_hash, "latency_seconds": time.perf_counter()-started,
                                       "error": type(exc).__name__}
            raise SemanticScoutError("SEMANTIC_PROVIDER_FAILED", "DeepSeek semantic call failed") from exc
        calls = getattr(getattr((getattr(response, "choices", None) or [None])[0], "message", None), "tool_calls", None) or []
        raw = getattr(getattr(calls[0], "function", None), "arguments", None) if len(calls) == 1 else None
        usage = getattr(response, "usage", None)
        self.last_call_metadata = {"request_hash": request_hash, "request_id": getattr(response, "id", None),
            "latency_seconds": round(time.perf_counter()-started, 6), "tool_call_count": len(calls),
            "prompt_version": SEMANTIC_PROMPT_VERSION, "schema_version": SEMANTIC_MAP_SCHEMA,
            "usage": {key: getattr(usage, key) for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                      if usage is not None and getattr(usage, key, None) is not None},
            "response_bytes": len(raw.encode()) if isinstance(raw, str) else 0}
        if len(calls) != 1 or getattr(getattr(calls[0], "function", None), "name", None) != tool_name or not isinstance(raw, str):
            raise SemanticScoutError("SEMANTIC_TOOL_CALL_INVALID", "DeepSeek did not return the forced semantic tool")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SemanticScoutError("SEMANTIC_JSON_INVALID", "DeepSeek returned malformed JSON") from exc
        return validate_provider_payload(payload, frame_id=frame_id)


def render_semantic_overlay(source_path: str | Path, hints: list[dict], output_path: str | Path,
                            *, show_evidence: bool = False, unknown_only: bool = False) -> dict[str, Any]:
    from PIL import Image, ImageDraw, ImageFont
    image = Image.open(source_path).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0,0,0,0)); draw = ImageDraw.Draw(overlay)
    colors = {"UNKNOWN": (128,128,128,90), "KITCHEN": (245,158,11,80), "BATHROOM": (14,165,233,80),
              "TOILET": (6,182,212,80), "BEDROOM": (139,92,246,80), "LIVING": (34,197,94,80),
              "STAIR": (239,68,68,80), "SHAFT": (71,85,105,80), "YARD": (132,204,22,70),
              "PARKING": (100,116,139,80)}
    for hint in hints:
        if unknown_only and hint["semantic_type"] != "UNKNOWN":
            continue
        x0,y0,x1,y1 = hint["approx_bbox_norm"]
        box_px = [x0*image.width, y0*image.height, x1*image.width, y1*image.height]
        color = colors.get(hint["semantic_type"], (249,115,22,75))
        draw.rectangle(box_px, fill=color, outline=color[:3]+(220,), width=4)
        label = f"{hint['semantic_type']} — APPROXIMATE SEMANTIC HINT"
        if show_evidence:
            label += " — " + ",".join(hint.get("evidence_classes") or [])
        draw.text((box_px[0]+4, box_px[1]+4), label, fill=(17,24,39,255))
    result = Image.alpha_composite(image, overlay).convert("RGB")
    result.save(output_path)
    return {"path": str(output_path), "render_hash": sha256(Path(output_path).read_bytes()).hexdigest()}


# Compact multi-pass provider transport.  These abbreviated fields are transport
# only; canonical records are enriched locally after strict validation.
SEMANTIC_GROUPS = {
    "WET_SERVICE": {"KITCHEN", "KITCHENETTE", "BATHROOM", "SHOWER", "TOILET",
                    "LAUNDRY", "UTILITY", "STORAGE", "MECHANICAL_ROOM", "ELECTRICAL_ROOM",
                    "SHAFT", "DUCT"},
    "HABITABLE": {"BEDROOM", "MASTER_BEDROOM", "LIVING", "RECEPTION", "DINING", "OPEN_PLAN"},
    "CIRCULATION_CORE": {"ENTRANCE", "VESTIBULE", "CORRIDOR", "LOBBY", "STAIR",
                         "STAIR_LANDING", "ELEVATOR", "ELEVATOR_LOBBY"},
    "EXTERIOR_SITE": {"BALCONY", "TERRACE", "PATIO", "YARD", "BACKYARD", "COURTYARD",
                      "LIGHTWELL", "PARKING", "DRIVEWAY", "RAMP"},
}


def compact_inventory_schema() -> dict[str, Any]:
    item = {"type": "object", "additionalProperties": False, "required": ["t", "n", "c"],
            "properties": {"t": {"type": "string", "enum": sorted(SEMANTIC_TYPES)},
                           "n": {"type": "integer", "minimum": 0, "maximum": 99},
                           "c": {"type": "number", "minimum": 0, "maximum": 1}}}
    return {"type": "object", "additionalProperties": False, "required": ["f", "types"],
            "properties": {"f": {"type": "string"},
                           "types": {"type": "array", "maxItems": len(SEMANTIC_TYPES), "items": item}}}


def compact_localization_schema(allowed_types: set[str] | list[str]) -> dict[str, Any]:
    allowed = sorted(set(allowed_types))
    item = {"type": "object", "additionalProperties": False, "required": ["t", "b", "c"],
            "properties": {"t": {"type": "string", "enum": allowed},
                           "b": {"type": "array", "items": {"type": "number", "minimum": 0,
                                                                 "maximum": 1},
                                 "minItems": 4, "maxItems": 4},
                           "c": {"type": "number", "minimum": 0, "maximum": 1}}}
    return {"type": "object", "additionalProperties": False, "required": ["f", "z"],
            "properties": {"f": {"type": "string"},
                           "z": {"type": "array", "items": item}}}


def estimate_compact_response_bytes(*, task_type: str, expected_hints: int = 0,
                                    expected_types: int = 0, safety_margin: float = 1.35) -> dict[str, Any]:
    # Measured conservative ASCII JSON upper bounds. Values deliberately include
    # long semantic enum names and maximum decimal representations.
    root_bytes = 96
    per_item = 82 if task_type == "LOCALIZATION" else 58
    count = expected_hints if task_type == "LOCALIZATION" else expected_types
    raw = root_bytes + count * per_item
    estimated = int(math.ceil(raw * safety_margin))
    return {"task_type": task_type, "root_bytes": root_bytes, "max_item_bytes": per_item,
            "item_count": count, "safety_margin": safety_margin,
            "estimated_response_bytes": estimated, "budget_bytes": COMPACT_RESPONSE_BUDGET,
            "within_budget": estimated <= COMPACT_RESPONSE_BUDGET}


def validate_compact_inventory(payload: dict[str, Any], *, frame_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"f", "types"} or payload["f"] != frame_id:
        raise SemanticScoutError("COMPACT_INVENTORY_INVALID", "Inventory root or frame is invalid")
    if not isinstance(payload["types"], list):
        raise SemanticScoutError("COMPACT_INVENTORY_INVALID", "Inventory types must be an array")
    result, seen = [], set()
    for row in payload["types"]:
        if not isinstance(row, dict) or set(row) != {"t", "n", "c"}:
            raise SemanticScoutError("COMPACT_INVENTORY_INVALID", "Inventory item fields are invalid")
        kind = str(row["t"]).upper()
        if kind not in SEMANTIC_TYPES or kind in seen or isinstance(row["n"], bool):
            raise SemanticScoutError("COMPACT_INVENTORY_INVALID", "Inventory type/count is invalid")
        count, confidence = int(row["n"]), float(row["c"])
        if count != row["n"] or not 0 <= count <= 99 or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise SemanticScoutError("COMPACT_INVENTORY_INVALID", "Inventory values are invalid")
        seen.add(kind); result.append({"t": kind, "n": count, "c": confidence})
    return {"f": frame_id, "types": result}


def validate_compact_localization(payload: dict[str, Any], *, frame_id: str,
                                  allowed_types: set[str] | list[str]) -> dict[str, Any]:
    allowed = set(allowed_types)
    if not isinstance(payload, dict) or set(payload) != {"f", "z"} or payload["f"] != frame_id:
        raise SemanticScoutError("COMPACT_LOCALIZATION_INVALID", "Localization root or frame is invalid")
    if not isinstance(payload["z"], list):
        raise SemanticScoutError("COMPACT_LOCALIZATION_INVALID", "Localization zones must be an array")
    rows = []
    for row in payload["z"]:
        if not isinstance(row, dict) or set(row) != {"t", "b", "c"}:
            raise SemanticScoutError("COMPACT_LOCALIZATION_INVALID", "Provider prose or extra fields are forbidden")
        kind, bbox, confidence = str(row["t"]).upper(), row["b"], float(row["c"])
        if kind not in allowed or not isinstance(bbox, list) or len(bbox) != 4:
            raise SemanticScoutError("COMPACT_LOCALIZATION_INVALID", "Type or bbox is invalid")
        bbox = [float(x) for x in bbox]
        if (not all(math.isfinite(x) and 0 <= x <= 1 for x in bbox)
                or not bbox[0] < bbox[2] or not bbox[1] < bbox[3]
                or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise SemanticScoutError("COMPACT_LOCALIZATION_INVALID", "Localization values are invalid")
        rows.append({"t": kind, "b": bbox, "c": confidence})
    return {"f": frame_id, "z": rows}


def _label_semantic_candidates(text: str) -> set[str]:
    value = str(text).strip().lower()
    mapping = {"آشپز": "KITCHEN", "حمام": "BATHROOM", "توالت": "TOILET", "سرویس": "TOILET",
               "خواب": "BEDROOM", "پذیرایی": "LIVING", "نشیمن": "LIVING", "راه پله": "STAIR",
               "پله": "STAIR", "آسانسور": "ELEVATOR", "داکت": "DUCT", "حیاط": "YARD",
               "پارکینگ": "PARKING", "بالکن": "BALCONY", "تراس": "TERRACE"}
    return {kind for token, kind in mapping.items() if token in value}


def plan_compact_calls(inventory: dict[str, Any], labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggested = {row["t"] for row in inventory["types"] if row["n"] > 0 and row["c"] >= .25}
    for label in labels:
        suggested.update(_label_semantic_candidates(label.get("text", "")))
    plans = []
    for group_name, group_types in SEMANTIC_GROUPS.items():
        relevant = sorted(suggested & group_types)
        if not relevant:
            continue
        expected = max(len(relevant), sum(row["n"] for row in inventory["types"] if row["t"] in relevant))
        estimate = estimate_compact_response_bytes(task_type="LOCALIZATION", expected_hints=expected)
        if estimate["within_budget"]:
            plans.append({"group": group_name, "types": relevant, "expected_hints": expected,
                          "estimate": estimate})
            continue
        # Deterministic semantic-subset split, never random batching.
        current = []
        for kind in relevant:
            candidate = current + [kind]
            candidate_count = max(len(candidate), sum(row["n"] for row in inventory["types"] if row["t"] in candidate))
            if current and not estimate_compact_response_bytes(task_type="LOCALIZATION", expected_hints=candidate_count)["within_budget"]:
                count = max(len(current), sum(row["n"] for row in inventory["types"] if row["t"] in current))
                plans.append({"group": f"{group_name}_{len(plans)+1}", "types": current,
                              "expected_hints": count,
                              "estimate": estimate_compact_response_bytes(task_type="LOCALIZATION", expected_hints=count)})
                current = [kind]
            else:
                current = candidate
        if current:
            count = max(len(current), sum(row["n"] for row in inventory["types"] if row["t"] in current))
            plans.append({"group": f"{group_name}_{len(plans)+1}", "types": current,
                          "expected_hints": count,
                          "estimate": estimate_compact_response_bytes(task_type="LOCALIZATION", expected_hints=count)})
    return plans


def enrich_compact_hints(rows: list[dict[str, Any]], *, source_sha256: str, frame_id: str,
                         source_call_id: str, labels: list[dict], objects: list[dict]) -> list[dict[str, Any]]:
    enriched = []
    for row in rows:
        x0, y0, x1, y1 = row["b"]
        inside_labels = [x["text"] for x in labels if x0 <= x["normalized_position"][0] <= x1
                         and y0 <= x["normalized_position"][1] <= y1]
        inside_objects = [x["type"] for x in objects if x0 <= x["normalized_position"][0] <= x1
                          and y0 <= x["normalized_position"][1] <= y1]
        label_candidates = set().union(*(_label_semantic_candidates(x) for x in inside_labels)) if inside_labels else set()
        conflict = bool(label_candidates and row["t"] not in label_candidates)
        status = ("CONFLICT" if conflict else "MULTI_EVIDENCE_SUPPORTED" if inside_labels and inside_objects
                  else "VISION_PLUS_LABEL" if inside_labels else "VISION_PLUS_OBJECT" if inside_objects else "VISION_ONLY")
        identity = [source_sha256, frame_id, source_call_id, row["t"], [round(x, 5) for x in row["b"]]]
        enriched.append({"semantic_hint_id": _stable("SEM", identity), "semantic_type": row["t"],
                         "confidence": row["c"], "approx_bbox_norm": row["b"],
                         "approx_center_norm": [(x0+x1)/2, (y0+y1)/2], "dxf_labels": inside_labels,
                         "cad_objects": inside_objects, "mep_groups": MEP_GROUPS.get(row["t"], []),
                         "semantic_status": status, "source_call_id": source_call_id,
                         "authority": SEMANTIC_AUTHORITY, "material_geometry": None,
                         "routing_authority": "NONE", "engineering_geometry": False})
    return enriched


def compact_semantic_completeness(inventory: dict, hints: list[dict], labels: list[dict]) -> dict[str, Any]:
    localized = {}
    for hint in hints:
        localized[hint["semantic_type"]] = localized.get(hint["semantic_type"], 0) + 1
    expected = {x["t"]: x["n"] for x in inventory["types"] if x["n"] > 0}
    explained = set(label for hint in hints for label in hint.get("dxf_labels", []))
    return {"inventory_counts": expected, "localized_counts": localized,
            "count_gaps": {k: expected[k]-localized.get(k, 0) for k in expected if localized.get(k, 0) < expected[k]},
            "exact_labels_explained": sorted(explained),
            "exact_labels_unexplained": sorted({x["text"] for x in labels} - explained),
            "complete_required_set": all(localized.get(k, 0) >= min(v, 1) for k, v in expected.items())}


class DeepSeekCompactSemanticScout:
    """Strict compact multi-pass transport with zero retry/fallback."""
    def __init__(self, *, api_key: str | None = None, model: str = "deepseek-flash", client=None):
        credential = api_key or os.getenv("DEEPSEEK_API_KEY")
        if client is None:
            if not credential:
                raise SemanticScoutError("PROVIDER_CONFIG_REQUIRED", "DEEPSEEK_API_KEY is missing")
            from openai import OpenAI
            client = OpenAI(api_key=credential, base_url="https://api.deepseek.com/beta", timeout=120, max_retries=0)
        self.client, self.model, self.call_metadata = client, model, []

    def _call(self, *, image_path: str, frame_id: str, labels: list[dict], objects: list[dict],
              task_type: str, group: str, allowed_types: list[str] | None = None,
              expected_items: int = 0) -> dict[str, Any]:
        inventory = task_type == "INVENTORY"
        schema = compact_inventory_schema() if inventory else compact_localization_schema(allowed_types or [])
        task = ("Identify only which architectural functions appear and their approximate counts. Do not return coordinates. "
                if inventory else f"Locate only these functional types: {','.join(allowed_types or [])}. ")
        prompt = ("Read the complete architectural floor plan. " + task +
                  "Do not explain reasoning. Do not repeat supplied labels. Return only the compact tool fields. "
                  "Under-count rather than invent. Approximate bboxes are semantic hints, never engineering geometry. "
                  f"FRAME={frame_id}; LABELS={json.dumps(labels, ensure_ascii=False, separators=(',',':'))}; "
                  f"OBJECTS={json.dumps(objects, ensure_ascii=False, separators=(',',':'))}")
        tool_name = "submit_compact_semantic_inventory_v2" if inventory else "submit_compact_semantic_localization_v2"
        image_hash = sha256(Path(image_path).read_bytes()).hexdigest()
        request_hash = sha256((prompt + json.dumps(schema, sort_keys=True) + image_hash).encode()).hexdigest()
        call_id = _stable("CALL", [frame_id, task_type, group, request_hash])
        estimate = estimate_compact_response_bytes(task_type=task_type,
            expected_types=expected_items if inventory else 0,
            expected_hints=expected_items if not inventory else 0)
        if not estimate["within_budget"]:
            raise SemanticScoutError("SEMANTIC_RESPONSE_BUDGET_EXCEEDED", group)
        started = time.perf_counter(); response = None; raw = None
        metadata = {"call_id": call_id, "task_type": task_type, "semantic_group": group,
                    "request_hash": request_hash, "render_hash": image_hash,
                    "prompt_version": COMPACT_PROMPT_VERSION, "schema_version": COMPACT_SEMANTIC_SCHEMA,
                    "estimated_response_bytes": estimate["estimated_response_bytes"],
                    "json_validation_status": "NOT_RUN"}
        try:
            response = self.client.chat.completions.create(model=self.model,
                messages=[{"role":"user","content":[{"type":"text","text":prompt},
                    {"type":"image_url","image_url":{"url":"data:image/png;base64,"+_encode_image(image_path),"detail":"original"}}]}],
                tools=[{"type":"function","function":{"name":tool_name,"strict":True,
                    "description":"Return compact architectural semantic evidence only.","parameters":schema}}],
                tool_choice={"type":"function","function":{"name":tool_name}},
                extra_body={"thinking":{"type":"disabled"}})
            choice = (getattr(response, "choices", None) or [None])[0]
            calls = getattr(getattr(choice, "message", None), "tool_calls", None) or []
            raw = getattr(getattr(calls[0], "function", None), "arguments", None) if len(calls) == 1 else None
            usage = getattr(response, "usage", None)
            metadata.update({"finish_reason": getattr(choice, "finish_reason", None),
                "actual_response_bytes": len(raw.encode()) if isinstance(raw, str) else 0,
                "latency_seconds": round(time.perf_counter()-started, 6),
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None), "tool_call_count":len(calls)})
            if len(calls) != 1 or getattr(getattr(calls[0], "function", None), "name", None) != tool_name or not isinstance(raw, str):
                raise SemanticScoutError("COMPACT_TOOL_CALL_INVALID", "Expected exactly one compact tool call")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                metadata.update({"json_error_position": exc.pos, "json_validation_status":"MALFORMED"})
                raise SemanticScoutError("SEMANTIC_RESPONSE_BUDGET_EXCEEDED", "Compact response JSON was malformed") from exc
            validated = (validate_compact_inventory(payload, frame_id=frame_id) if inventory else
                         validate_compact_localization(payload, frame_id=frame_id, allowed_types=allowed_types or []))
            metadata["json_validation_status"] = "VALID"
            return {"call_id":call_id,"payload":validated}
        except SemanticScoutError:
            raise
        except Exception as exc:
            metadata.update({"latency_seconds":round(time.perf_counter()-started,6),
                             "provider_error":type(exc).__name__,"json_validation_status":"PROVIDER_FAILED"})
            raise SemanticScoutError("SEMANTIC_PROVIDER_FAILED", "Compact semantic call failed") from exc
        finally:
            self.call_metadata.append(metadata)
