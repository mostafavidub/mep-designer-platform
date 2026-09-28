"""Bounded multimodal recovery for the canonical architecture engine.

Vision is supporting evidence.  It may classify an already reconstructed CAD
space, but it cannot invent final geometry or override contradictory CAD facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any
import base64
import json
import os
import time

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .architectural_topology_quality import host_portal_on_walls


RENDER_VERSION = "architecture-source-render/2"
VIEWPORT_VERSION = "architecture-vision-viewport/1"
PROMPT_VERSION = "architecture-hybrid-boundary-recovery/1"
FUSION_VERSION = "architecture-boundary-evidence-fusion/2"
VISION_SCHEMA_VERSION = "architectural-vision-evidence/2.0"
SHELL_BOUNDARIES_SCHEMA_VERSION = "architectural-shell-boundaries/1.0"
SHELL_BOUNDARIES_PROMPT_VERSION = "shell-boundaries/1"
TRANSFORM_VERSION = "cad-pixel-transform/1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MAX_INLINE_IMAGE_BYTES = 32 * 1024 * 1024
MAX_REQUEST_BODY_BYTES = 48 * 1024 * 1024
ALLOWED_SEMANTICS = {
    "bedroom", "master_bedroom", "living", "reception", "dining", "kitchen",
    "kitchenette", "bathroom", "shower", "toilet", "entrance", "vestibule",
    "corridor", "lobby", "closet", "storage", "laundry", "utility", "stair",
    "stair_landing", "elevator", "elevator_lobby", "shaft", "duct", "void",
    "balcony", "terrace", "patio", "yard", "backyard", "lightwell", "parking",
    "ramp", "driveway", "office", "shop", "commercial", "mechanical_room",
    "electrical_room", "boiler_room", "janitor", "common_room", "open_plan", "roof", "unknown",
}


class RecoveryStage(str, Enum):
    SOURCE_INGESTION = "SOURCE_INGESTION"
    FRAME_AND_LEVEL_ISOLATION = "FRAME_AND_LEVEL_ISOLATION"
    DETERMINISTIC_CAD_RECONSTRUCTION = "DETERMINISTIC_CAD_RECONSTRUCTION"
    DETERMINISTIC_SEMANTIC_FUSION = "DETERMINISTIC_SEMANTIC_FUSION"
    COMPLETENESS_GATE_1 = "COMPLETENESS_GATE_1"
    ARCHITECTURAL_VISION_VIEWPORT_SELECTION = "ARCHITECTURAL_VISION_VIEWPORT_SELECTION"
    AUTHORITATIVE_FLOOR_RENDER = "AUTHORITATIVE_FLOOR_RENDER"
    GLOBAL_VISION_ANALYSIS = "GLOBAL_VISION_ANALYSIS"
    CAD_VISION_RECONCILIATION_1 = "CAD_VISION_RECONCILIATION_1"
    TOPOLOGY_REPAIR_1 = "TOPOLOGY_REPAIR_1"
    RECONSTRUCTION_RERUN = "RECONSTRUCTION_RERUN"
    COMPLETENESS_GATE_2 = "COMPLETENESS_GATE_2"
    LOCAL_AMBIGUITY_RENDERING = "LOCAL_AMBIGUITY_RENDERING"
    LOCAL_VISION_ANALYSIS = "LOCAL_VISION_ANALYSIS"
    CAD_VISION_RECONCILIATION_2 = "CAD_VISION_RECONCILIATION_2"
    TARGETED_TOPOLOGY_REPAIR_2 = "TARGETED_TOPOLOGY_REPAIR_2"
    FINAL_RECONSTRUCTION_RERUN = "FINAL_RECONSTRUCTION_RERUN"
    FINAL_COMPLETENESS_GATE = "FINAL_COMPLETENESS_GATE"
    TARGETED_HUMAN_DECISION = "TARGETED_HUMAN_DECISION"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    FAILED = "FAILED"


class VisionRecoveryError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class RenderTransform:
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    width_px: int
    height_px: int
    padding_px: int = 36

    @property
    def scale(self) -> float:
        usable_w = max(1, self.width_px - 2 * self.padding_px)
        usable_h = max(1, self.height_px - 2 * self.padding_px)
        return min(usable_w / max(self.max_x - self.min_x, 1e-12),
                   usable_h / max(self.max_y - self.min_y, 1e-12))

    def cad_to_pixel(self, point: tuple[float, float] | list[float]) -> tuple[float, float]:
        x, y = float(point[0]), float(point[1])
        return (self.padding_px + (x - self.min_x) * self.scale,
                self.height_px - self.padding_px - (y - self.min_y) * self.scale)

    def pixel_to_cad(self, point: tuple[float, float] | list[float]) -> tuple[float, float]:
        x, y = float(point[0]), float(point[1])
        return ((x - self.padding_px) / self.scale + self.min_x,
                (self.height_px - self.padding_px - y) / self.scale + self.min_y)

    def as_dict(self) -> dict[str, Any]:
        return {"cad_bounds": [self.min_x, self.min_y, self.max_x, self.max_y],
                "pixel_size": [self.width_px, self.height_px], "padding_px": self.padding_px,
                "scale_px_per_drawing_unit": self.scale, "y_axis_inverted": True}


def _primitive_points(record: dict) -> list:
    if record.get("start") and record.get("end"):
        return [record["start"], record["end"]]
    return list(record.get("points") or [])


def _bounds_area(bounds: list[float] | tuple[float, ...]) -> float:
    return max(0.0, float(bounds[2]) - float(bounds[0])) * max(0.0, float(bounds[3]) - float(bounds[1]))


def _unicode_font(size: int):
    """Use an available Unicode font without adding a font asset to the repository."""
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/local/share/fonts/DejaVuSans.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _geometry_lines(extracted: dict, frame_bounds: list[float]) -> list[dict]:
    frame_box = box(*frame_bounds); rows = []
    for record in extracted.get("primitives") or []:
        points = _primitive_points(record)
        if len(points) < 2:
            continue
        try:
            line = LineString(points)
        except (TypeError, ValueError):
            continue
        if line.is_empty or not line.intersects(frame_box):
            continue
        clipped = line.intersection(frame_box)
        parts = list(clipped.geoms) if clipped.geom_type == "MultiLineString" else [clipped]
        for part in parts:
            if part.geom_type == "LineString" and part.length > 0:
                rows.append({"geometry": part, "record": record})
    return rows


def select_vision_viewport(*, extracted: dict, frame: dict) -> dict:
    """Select plan content from raw DXF evidence, never reconstructed spaces."""
    raw_bounds = [float(value) for value in frame.get("bounds") or []]
    if len(raw_bounds) != 4 or _bounds_area(raw_bounds) <= 0:
        raise VisionRecoveryError("INVALID_FRAME_BOUNDS", "A valid CAD frame is required for viewport selection")
    started = time.perf_counter(); lines = _geometry_lines(extracted, raw_bounds)
    width=raw_bounds[2]-raw_bounds[0]; height=raw_bounds[3]-raw_bounds[1]
    span=max(width,height); diagonal=max((width*width+height*height)**.5,1e-9)
    lengths=sorted(row["geometry"].length for row in lines)
    median=lengths[len(lengths)//2] if lengths else 0.0
    # Sheet borders and long isolated datum lines must not dominate the viewport.
    preliminary_connection=max(diagonal*.001,min(max(median*.04,diagonal*.0003),diagonal*.01))
    def frame_like(row):
        length=row["geometry"].length
        if length>=span*.72:
            return True
        if length<span*.55:
            return False
        support=sum(other is not row and other["geometry"].distance(row["geometry"])<=preliminary_connection
                    for other in lines)
        return support<4
    usable=[row for row in lines if not frame_like(row)]
    excluded_long=len(lines)-len(usable)
    if not usable:
        usable=lines[:]
    connection=max(diagonal*.0015,min(max(median*.08,diagonal*.0004),diagonal*.02))
    merged=unary_union([row["geometry"].buffer(connection,cap_style=2) for row in usable]) if usable else None
    components=[] if merged is None or merged.is_empty else (list(merged.geoms) if merged.geom_type=="MultiPolygon" else [merged])
    texts=extracted.get("texts") or []; objects=extracted.get("objects") or []; dimensions=extracted.get("dimensions") or []
    scored=[]
    for component in components:
        component_bounds=list(component.bounds); region=box(*component_bounds)
        members=[row for row in usable if row["geometry"].intersects(region)]
        text_count=sum(region.covers(Point(float(t["point"][0]),float(t["point"][1])))
                       for t in texts if t.get("point"))
        object_count=sum(region.buffer(connection).covers(Point(float(o["point"][0]),float(o["point"][1])))
                         for o in objects if o.get("point"))
        dimension_count=sum(any(region.buffer(connection).covers(Point(float(p[0]),float(p[1])))
                                for p in d.get("definition_points") or []) for d in dimensions)
        total_length=sum(row["geometry"].length for row in members)
        wall_like=sum(any(token in str(row["record"].get("layer","")).lower()
                          for token in ("wall","a-wall","دیوار")) for row in members)
        annotation_like=sum(any(token in str(row["record"].get("layer","")).lower()
                                for token in ("title","border","frame","legend","sheet","کادر","جدول"))
                            for row in members)
        compactness=total_length/max((_bounds_area(component_bounds)**.5),connection)
        raw_score=len(members)*2+total_length/max(median,connection)+text_count*3+object_count*4+dimension_count*2+wall_like*2+compactness
        score=raw_score*(.12 if annotation_like and annotation_like>=len(members)*.5 else 1.0)
        scored.append({"geometry":component,"bounds":component_bounds,"entity_count":len(members),
                       "geometry_length":total_length,"text_count":text_count,"object_count":object_count,
                       "dimension_count":dimension_count,"wall_like_count":wall_like,
                       "annotation_like_count":annotation_like,"score":score})
    scored.sort(key=lambda row:row["score"],reverse=True)
    selected=[]
    if scored:
        primary=scored[0]; proximity=max(connection*8,span*.035)
        selected=[row for row in scored if row["score"]>=primary["score"]*.12 and
                  box(*row["bounds"]).distance(box(*primary["bounds"]))<=proximity]
    if selected:
        content=unary_union([row["geometry"] for row in selected]).bounds
        content_bounds=[float(value) for value in content]
    else:
        content_bounds=raw_bounds[:]
    content_span=max(content_bounds[2]-content_bounds[0],content_bounds[3]-content_bounds[1])
    margin=max(connection*4,content_span*.065)
    vision_bounds=[max(raw_bounds[0],content_bounds[0]-margin),max(raw_bounds[1],content_bounds[1]-margin),
                   min(raw_bounds[2],content_bounds[2]+margin),min(raw_bounds[3],content_bounds[3]+margin)]
    if _bounds_area(vision_bounds)<=0:
        vision_bounds=raw_bounds[:]
    frame_area=_bounds_area(raw_bounds); content_area=_bounds_area(content_bounds); vision_area=_bounds_area(vision_bounds)
    in_view_lines=[row for row in lines if row["geometry"].intersects(box(*vision_bounds))]
    in_view_texts=[row for row in texts if row.get("point") and box(*vision_bounds).covers(
        Point(float(row["point"][0]),float(row["point"][1])))]
    wall_like=sum(any(token in str(row["record"].get("layer","")).lower() for token in ("wall","a-wall","دیوار"))
                  for row in in_view_lines)
    return {"viewport_version":VIEWPORT_VERSION,"authoritative_frame_bounds":raw_bounds,
            "architectural_content_bounds":content_bounds,"vision_bounds":vision_bounds,
            "safe_margin_drawing_units":margin,"selection_evidence":{"component_count":len(scored),
                "selected_component_count":len(selected),"raw_geometry_count":len(lines),
                "retained_geometry_count":len(in_view_lines),"excluded_long_frame_geometry":excluded_long,
                "raw_text_count":len(texts),"retained_text_count":len(in_view_texts),
                "dimension_count":len(dimensions),"wall_like_geometry_count":wall_like},
            "metrics":{"frame_bbox_area":frame_area,"architectural_content_bbox_area":content_area,
                "vision_bbox_area":vision_area,"content_to_frame_ratio":content_area/max(frame_area,1e-12),
                "vision_to_frame_ratio":vision_area/max(frame_area,1e-12),
                "white_space_ratio_estimate":max(0.0,1-content_area/max(frame_area,1e-12)),
                "rendered_content_pixel_ratio":content_area/max(vision_area,1e-12),
                "focused_white_space_ratio_estimate":max(0.0,1-content_area/max(vision_area,1e-12)),
                "primitive_density":len(in_view_lines)/max(vision_area,1e-12),
                "text_density":len(in_view_texts)/max(vision_area,1e-12),
                "wall_like_density":wall_like/max(vision_area,1e-12)},
            "confidence":.9 if selected and len(in_view_lines)>=10 else .45,
            "status":"SELECTED" if selected else "FALLBACK_FULL_FRAME",
            "runtime_seconds":round(time.perf_counter()-started,6)}


def render_source_frame(*, extracted: dict, frame: dict, source_hash: str,
                        cache_dir: str | Path | None = None, width_px: int = 1800,
                        viewport: dict | None = None, render_role: str = "FULL_FRAME") -> dict:
    """Render raw source primitives without using reconstructed model output."""
    bounds = (viewport or {}).get("vision_bounds") or frame.get("bounds")
    if not bounds or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        raise VisionRecoveryError("INVALID_FRAME_BOUNDS", "A valid CAD frame is required for rendering")
    ratio = max(.35, min(2.8, (bounds[3] - bounds[1]) / max(bounds[2] - bounds[0], 1e-9)))
    height_px = max(900, min(2600, int(width_px * ratio)))
    transform = RenderTransform(*map(float, bounds), width_px, height_px)
    key = sha256(json.dumps([source_hash, frame.get("frame_id"), bounds, RENDER_VERSION, width_px, render_role],
                            sort_keys=True).encode()).hexdigest()
    root = Path(cache_dir or os.getenv("ARCH_VISION_CACHE_DIR") or "/tmp/planha-architecture-vision")
    root.mkdir(parents=True, exist_ok=True)
    image_path = root / f"{key}.png"
    manifest_path = root / f"{key}.json"
    if image_path.exists() and manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    image = Image.new("RGB", (width_px, height_px), "white")
    draw = ImageDraw.Draw(image)
    count = 0
    for record in extracted.get("primitives") or []:
        points = _primitive_points(record)
        if len(points) < 2:
            continue
        pixel_points = [transform.cad_to_pixel(point) for point in points]
        if max(p[0] for p in pixel_points) < 0 or min(p[0] for p in pixel_points) > width_px:
            continue
        if max(p[1] for p in pixel_points) < 0 or min(p[1] for p in pixel_points) > height_px:
            continue
        draw.line(pixel_points, fill=(55, 65, 81), width=2)
        count += 1
    font=_unicode_font(max(16,min(28,width_px//75)))
    rendered_texts=[]
    for text in extracted.get("texts") or []:
        point = text.get("point")
        if not point:
            continue
        px = transform.cad_to_pixel(point)
        if 0 <= px[0] <= width_px and 0 <= px[1] <= height_px:
            value=str(text.get("text") or "")[:80]
            try:
                draw.text(px,value,fill=(15,15,15),font=font,direction="rtl" if any("\u0600"<=c<="\u06ff" for c in value) else None)
            except (KeyError,TypeError,ValueError):
                draw.text(px,value,fill=(15,15,15),font=font)
            rendered_texts.append({"text":value,"cad_point":list(point),"pixel_point":[round(px[0],3),round(px[1],3)]})
    image.save(image_path, format="PNG", optimize=True)
    manifest = {"image_path": str(image_path), "cache_key": key, "frame_id": frame.get("frame_id"),
                "source_sha256": source_hash, "render_version": RENDER_VERSION,
                "transform": transform.as_dict(), "primitive_count": count,"render_role":render_role,
                "raw_text_evidence":rendered_texts,"viewport":viewport or {"vision_bounds":bounds}}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return manifest


def _validate_payload(payload: Any, expected_region_ids: set[str]) -> list[dict]:
    if not isinstance(payload, dict) or set(payload) - {"schema", "regions", "notes"}:
        raise VisionRecoveryError("VISION_SCHEMA_INVALID", "Unexpected top-level response fields")
    if payload.get("schema") != "architectural-vision-evidence/1.0" or not isinstance(payload.get("regions"), list):
        raise VisionRecoveryError("VISION_SCHEMA_INVALID", "Invalid vision response schema")
    result = []
    seen = set()
    for row in payload["regions"]:
        required = {"region_id", "semantic_type", "confidence", "evidence", "uncertainty"}
        if not isinstance(row, dict) or set(row) != required:
            raise VisionRecoveryError("VISION_SCHEMA_INVALID", "Invalid region response fields")
        region_id = str(row["region_id"])
        if region_id not in expected_region_ids or region_id in seen:
            raise VisionRecoveryError("VISION_REGION_INVALID", "Unknown or duplicate region identity")
        semantic = str(row["semantic_type"])
        confidence = float(row["confidence"])
        evidence = row["evidence"]
        if semantic not in ALLOWED_SEMANTICS or not 0 <= confidence <= 1 or not isinstance(evidence, list):
            raise VisionRecoveryError("VISION_VALUE_INVALID", "Invalid semantic evidence")
        result.append({"region_id": region_id, "semantic_type": semantic, "confidence": confidence,
                       "evidence": [str(item)[:300] for item in evidence[:12]],
                       "uncertainty": str(row["uncertainty"] or "")[:500]})
        seen.add(region_id)
    return result


GLOBAL_KEYS = {"frame_id", "building_shells", "boundary_hypotheses", "region_roles",
               "physical_spaces", "functional_zones", "doors", "windows",
               "open_passages", "stairs", "shafts", "suspected_false_boundaries",
               "suspected_missing_boundaries", "unresolved_regions"}
LEGACY_GLOBAL_KEYS = GLOBAL_KEYS - {"building_shells", "boundary_hypotheses", "region_roles"}

BOUNDARY_ROLES = {"EXTERIOR_SHELL", "INTERIOR_SEPARATOR", "OPEN_PLAN_TRANSITION",
                  "COURTYARD_EDGE", "SHAFT_EDGE", "STAIR_EDGE", "UNKNOWN"}
REGION_ROLES = {"BUILDING_INTERIOR", "SITE_EXTERIOR", "SEMI_EXTERIOR", "COURTYARD",
                "LIGHTWELL", "SHAFT", "STAIR", "UNKNOWN"}

_GEOMETRY_EVIDENCE_SCHEMA = {"type":"object","additionalProperties":False,
    "required":["geometry_px","evidence","confidence"],"properties":{
        "geometry_px":{"type":"array","items":{"type":"array","minItems":2,"maxItems":2,
                                                     "items":{"type":"number"}}},
        "evidence":{"type":"array","items":{"type":"string"}},
        "confidence":{"type":"number","minimum":0,"maximum":1}}}
_FUNCTIONAL_ZONE_SCHEMA = {"type":"object","additionalProperties":False,
    "required":["zone_id","geometry_px","semantic_type","evidence","confidence"],"properties":{
        "zone_id":{"type":"string"},
        "geometry_px":{"type":"array","items":{"type":"array","minItems":2,"maxItems":2,
                                                     "items":{"type":"number"}}},
        "semantic_type":{"type":"string","enum":sorted(ALLOWED_SEMANTICS)},
        "evidence":{"type":"array","items":{"type":"string"}},
        "confidence":{"type":"number","minimum":0,"maximum":1}}}
_UNRESOLVED_SCHEMA = {"type":"object","additionalProperties":False,
    "required":["geometry_px","reason"],"properties":{
        "geometry_px":{"type":"array","items":{"type":"array","minItems":2,"maxItems":2,
                                                     "items":{"type":"number"}}},
        "reason":{"type":"string"}}}
_PORTAL_SCHEMA = {"type":"object","additionalProperties":False,
                  "required":["geometry_px","connects","evidence","confidence"],
                  "properties":{"geometry_px":{"type":"array","items":{"type":"array","minItems":2,"maxItems":2,
                                                                             "items":{"type":"number"}}},
                                "connects":{"type":"array","items":{"type":"string"}},
                                "evidence":{"type":"array","items":{"type":"string"}},
                                "confidence":{"type":"number","minimum":0,"maximum":1}}}
_BOUNDARY_SCHEMA = {"type":"object","additionalProperties":False,
    "required":["boundary_id","geometry_px","role","adjacent_regions","evidence","confidence","uncertainties"],
    "properties":{"boundary_id":{"type":"string"},
      "geometry_px":{"type":"array","minItems":2,"items":{"type":"array","minItems":2,"maxItems":2,
                                                                   "items":{"type":"number"}}},
      "role":{"type":"string","enum":sorted(BOUNDARY_ROLES)},
      "adjacent_regions":{"type":"array","items":{"type":"string"}},
      "evidence":{"type":"array","items":{"type":"string"}},
      "confidence":{"type":"number","minimum":0,"maximum":1},
      "uncertainties":{"type":"array","items":{"type":"string"}}}}
_SHELL_SCHEMA = {"type":"object","additionalProperties":False,
    "required":["shell_id","outer_ring_px","inner_rings_px","evidence","confidence","uncertainties"],
    "properties":{"shell_id":{"type":"string"},
      "outer_ring_px":{"type":"array","minItems":3,"items":{"type":"array","minItems":2,"maxItems":2,
                                                                    "items":{"type":"number"}}},
      "inner_rings_px":{"type":"array","items":{"type":"array","minItems":3,
        "items":{"type":"array","minItems":2,"maxItems":2,"items":{"type":"number"}}}},
      "evidence":{"type":"array","items":{"type":"string"}},
      "confidence":{"type":"number","minimum":0,"maximum":1},
      "uncertainties":{"type":"array","items":{"type":"string"}}}}
_REGION_ROLE_SCHEMA = {"type":"object","additionalProperties":False,
    "required":["region_id","polygon_px","role","evidence","confidence","uncertainties"],
    "properties":{"region_id":{"type":"string"},
      "polygon_px":{"type":"array","minItems":3,"items":{"type":"array","minItems":2,"maxItems":2,
                                                                  "items":{"type":"number"}}},
      "role":{"type":"string","enum":sorted(REGION_ROLES)},
      "evidence":{"type":"array","items":{"type":"string"}},
      "confidence":{"type":"number","minimum":0,"maximum":1},
      "uncertainties":{"type":"array","items":{"type":"string"}}}}
GLOBAL_JSON_SCHEMA={"type":"object","additionalProperties":False,"required":sorted(GLOBAL_KEYS),"properties":{
    "frame_id":{"type":"string"},
    "building_shells":{"type":"array","items":_SHELL_SCHEMA},
    "boundary_hypotheses":{"type":"array","items":_BOUNDARY_SCHEMA},
    "region_roles":{"type":"array","items":_REGION_ROLE_SCHEMA},
    "physical_spaces":{"type":"array","items":{"type":"object","additionalProperties":False,
        "required":["vision_space_id","polygon_px","semantic_candidates","objects_seen","labels_seen","boundary_evidence","uncertainties"],
        "properties":{"vision_space_id":{"type":"string"},
                      "polygon_px":{"type":"array","minItems":3,"items":{"type":"array","minItems":2,"maxItems":2,"items":{"type":"number"}}},
                      "semantic_candidates":{"type":"array","items":{"type":"object","additionalProperties":False,
                          "required":["type","confidence"],"properties":{"type":{"type":"string","enum":sorted(ALLOWED_SEMANTICS)},
                                                                            "confidence":{"type":"number","minimum":0,"maximum":1}}}},
                      "objects_seen":{"type":"array","items":{"type":"string"}},
                      "labels_seen":{"type":"array","items":{"type":"string"}},
                      "boundary_evidence":{"type":"array","items":{"type":"string"}},
                      "uncertainties":{"type":"array","items":{"type":"string"}}}}},
    "functional_zones":{"type":"array","items":_FUNCTIONAL_ZONE_SCHEMA},"doors":{"type":"array","items":_PORTAL_SCHEMA},
    "windows":{"type":"array","items":_PORTAL_SCHEMA},"open_passages":{"type":"array","items":_PORTAL_SCHEMA},
    "stairs":{"type":"array","items":_GEOMETRY_EVIDENCE_SCHEMA},
    "shafts":{"type":"array","items":_GEOMETRY_EVIDENCE_SCHEMA},
    "suspected_false_boundaries":{"type":"array","items":_GEOMETRY_EVIDENCE_SCHEMA},
    "suspected_missing_boundaries":{"type":"array","items":_GEOMETRY_EVIDENCE_SCHEMA},
    "unresolved_regions":{"type":"array","items":_UNRESOLVED_SCHEMA}}}

SHELL_BOUNDARIES_KEYS={"frame_id","building_shells","boundary_segments","exterior_regions","uncertainties"}
SHELL_BOUNDARY_ROLES={"BUILDING_SHELL","INTERIOR_SEPARATOR","SITE_SEPARATOR","VOID_BOUNDARY","UNKNOWN"}
EXTERIOR_REGION_ROLES={"YARD","SITE_EXTERIOR","TERRACE","BALCONY","LIGHTWELL","UNKNOWN"}
_V1_POINT={"type":"array","minItems":2,"maxItems":2,"items":{"type":"number"}}
_V1_EVIDENCE={"type":"array","maxItems":5,"items":{"type":"string","maxLength":160}}
SHELL_BOUNDARIES_JSON_SCHEMA={"type":"object","additionalProperties":False,
  "required":sorted(SHELL_BOUNDARIES_KEYS),"properties":{
    "frame_id":{"type":"string"},
    "building_shells":{"type":"array","maxItems":3,"items":{"type":"object","additionalProperties":False,
      "required":["shell_id","polygon_px","confidence","evidence","uncertainties"],"properties":{
        "shell_id":{"type":"string"},"polygon_px":{"type":"array","minItems":3,"items":_V1_POINT},
        "confidence":{"type":"number","minimum":0,"maximum":1},"evidence":_V1_EVIDENCE,
        "uncertainties":_V1_EVIDENCE}}},
    "boundary_segments":{"type":"array","maxItems":40,"items":{"type":"object","additionalProperties":False,
      "required":["boundary_id","geometry_px","role","confidence","evidence"],"properties":{
        "boundary_id":{"type":"string"},"geometry_px":{"type":"array","minItems":2,"items":_V1_POINT},
        "role":{"type":"string","enum":sorted(SHELL_BOUNDARY_ROLES)},
        "confidence":{"type":"number","minimum":0,"maximum":1},"evidence":_V1_EVIDENCE}}},
    "exterior_regions":{"type":"array","maxItems":10,"items":{"type":"object","additionalProperties":False,
      "required":["region_id","polygon_px","role","confidence"],"properties":{
        "region_id":{"type":"string"},"polygon_px":{"type":"array","minItems":3,"items":_V1_POINT},
        "role":{"type":"string","enum":sorted(EXTERIOR_REGION_ROLES)},
        "confidence":{"type":"number","minimum":0,"maximum":1}}}},
    "uncertainties":{"type":"array","maxItems":10,"items":{"type":"object","additionalProperties":False,
      "required":["geometry_px","reason"],"properties":{
        "geometry_px":{"type":"array","minItems":2,"items":_V1_POINT},
        "reason":{"type":"string","maxLength":240}}}}}}


def validate_shell_boundaries_payload(payload: Any, *, frame_id: str) -> dict:
    """Validate the bounded V1 enclosure contract without accepting extra semantics."""
    if not isinstance(payload,dict) or set(payload)!=SHELL_BOUNDARIES_KEYS or payload.get("frame_id")!=frame_id:
        raise VisionRecoveryError("VISION_SCHEMA_INVALID","V1 response fields or frame identity are invalid")
    limits={"building_shells":3,"boundary_segments":40,"exterior_regions":10,"uncertainties":10}
    if any(not isinstance(payload.get(key),list) or len(payload[key])>limit for key,limit in limits.items()):
        raise VisionRecoveryError("VISION_SCHEMA_INVALID","V1 collections exceed their bounded contract")
    for row in payload["building_shells"]:
        if not isinstance(row,dict) or set(row)!={"shell_id","polygon_px","confidence","evidence","uncertainties"}:
            raise VisionRecoveryError("VISION_SCHEMA_INVALID","Invalid V1 building shell")
        if len(row["polygon_px"])<3 or not 0<=float(row["confidence"])<=1:
            raise VisionRecoveryError("VISION_GEOMETRY_INVALID","Invalid V1 building shell geometry")
        if any(not isinstance(row[key],list) or len(row[key])>5 for key in ("evidence","uncertainties")):
            raise VisionRecoveryError("VISION_SCHEMA_INVALID","V1 shell evidence is not bounded")
    for row in payload["boundary_segments"]:
        if not isinstance(row,dict) or set(row)!={"boundary_id","geometry_px","role","confidence","evidence"}:
            raise VisionRecoveryError("VISION_SCHEMA_INVALID","Invalid V1 boundary segment")
        if len(row["geometry_px"])<2 or row["role"] not in SHELL_BOUNDARY_ROLES or not 0<=float(row["confidence"])<=1:
            raise VisionRecoveryError("VISION_VALUE_INVALID","Invalid V1 boundary value")
        if not isinstance(row["evidence"],list) or len(row["evidence"])>5:
            raise VisionRecoveryError("VISION_SCHEMA_INVALID","V1 boundary evidence is not bounded")
    exterior_keys={"region_id","polygon_px","role","confidence"}
    for index,row in enumerate(payload["exterior_regions"]):
        actual_keys=set(row) if isinstance(row,dict) else set()
        if not isinstance(row,dict) or actual_keys!=exterior_keys:
            raise VisionRecoveryError("VISION_SCHEMA_INVALID","Invalid V1 exterior region",
                details={"collection":"exterior_regions","index":index,"validation_path":f"$.exterior_regions[{index}]",
                         "expected_keys":sorted(exterior_keys),"actual_keys":sorted(actual_keys),
                         "missing_keys":sorted(exterior_keys-actual_keys),"extra_keys":sorted(actual_keys-exterior_keys),
                         "type_mismatch":None if isinstance(row,dict) else type(row).__name__})
        polygon=row["polygon_px"]
        invalid_geometry=(not isinstance(polygon,list) or len(polygon)<3 or any(
            not isinstance(point,list) or len(point)!=2 or not all(isinstance(value,(int,float)) for value in point)
            for point in polygon))
        if invalid_geometry or row["role"] not in EXTERIOR_REGION_ROLES or not isinstance(row["confidence"],(int,float)) or not 0<=float(row["confidence"])<=1:
            raise VisionRecoveryError("VISION_VALUE_INVALID","Invalid V1 exterior-region value",
                details={"collection":"exterior_regions","index":index,"validation_path":f"$.exterior_regions[{index}]",
                         "invalid_role":row["role"] if row["role"] not in EXTERIOR_REGION_ROLES else None,
                         "invalid_geometry":invalid_geometry,
                         "type_mismatch":None if isinstance(row["confidence"],(int,float)) else "confidence"})
    for row in payload["uncertainties"]:
        if not isinstance(row,dict) or set(row)!={"geometry_px","reason"} or len(row["geometry_px"])<2:
            raise VisionRecoveryError("VISION_SCHEMA_INVALID","Invalid V1 uncertainty")
    return payload


def _store_invalid_v1_diagnostic(*, raw: str, metadata: dict[str, Any], error: VisionRecoveryError) -> str:
    """Persist invalid provider output outside the successful cache, without secrets or image data."""
    root=Path(os.getenv("ARCH_VISION_DIAGNOSTIC_DIR") or "/tmp/planha-architecture-vision/failures")
    root.mkdir(parents=True,exist_ok=True)
    identity={key:metadata.get(key) for key in (
        "provider","model","request_id","task_type","task_prompt_version","task_schema_version",
        "render_sha256","source_sha256","latency_seconds","usage","response_bytes")}
    name=sha256(json.dumps([identity,raw,error.code,error.details],sort_keys=True,default=str).encode()).hexdigest()
    path=root/f"v1-invalid-{name}.json"
    try:
        raw_json=json.loads(raw)
    except json.JSONDecodeError:
        raw_json={"malformed_json":True,"raw_utf8":raw[:200000]}
    artifact={**identity,"raw_response_json":raw_json,"validation_error":error.code,
              "validation_message":str(error),"validation_path":error.details.get("validation_path"),
              "validation_details":error.details}
    path.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    return str(path)


def validate_global_payload(payload: Any, *, frame_id: str) -> dict:
    """Strictly validate the geometry-bearing global Vision contract."""
    if isinstance(payload, dict) and set(payload) == LEGACY_GLOBAL_KEYS:
        # Version 1 cache remains readable as raw hypotheses, but it carries no
        # shell/boundary authority and therefore cannot by itself close Hybrid topology.
        payload = {**payload, "building_shells": [], "boundary_hypotheses": [], "region_roles": []}
    if not isinstance(payload, dict) or set(payload) != GLOBAL_KEYS or payload.get("frame_id") != frame_id:
        raise VisionRecoveryError("VISION_SCHEMA_INVALID", "Global response fields or frame identity are invalid")
    list_fields = GLOBAL_KEYS - {"frame_id"}
    if any(not isinstance(payload.get(key), list) for key in list_fields):
        raise VisionRecoveryError("VISION_SCHEMA_INVALID", "Every global response collection must be a list")
    spaces = []
    for row in payload["physical_spaces"]:
        required = {"vision_space_id", "polygon_px", "semantic_candidates", "objects_seen",
                    "labels_seen", "boundary_evidence", "uncertainties"}
        if not isinstance(row, dict) or set(row) != required:
            raise VisionRecoveryError("VISION_SCHEMA_INVALID", "Invalid physical-space record")
        polygon = row["polygon_px"]
        if not isinstance(polygon, list) or len(polygon) < 3 or any(
                not isinstance(p, list) or len(p) != 2 or not all(isinstance(v, (int, float)) for v in p)
                for p in polygon):
            raise VisionRecoveryError("VISION_GEOMETRY_INVALID", "Vision polygon is invalid")
        candidates = row["semantic_candidates"]
        if not isinstance(candidates, list) or any(
                not isinstance(c, dict) or set(c) != {"type", "confidence"} or
                c["type"] not in ALLOWED_SEMANTICS or not 0 <= float(c["confidence"]) <= 1
                for c in candidates):
            raise VisionRecoveryError("VISION_VALUE_INVALID", "Semantic candidates are invalid")
        if any(not isinstance(row[key], list) for key in ("objects_seen", "labels_seen", "boundary_evidence", "uncertainties")):
            raise VisionRecoveryError("VISION_SCHEMA_INVALID", "Space evidence must be arrays")
        spaces.append(row)
    for portal_key in ("doors", "windows", "open_passages"):
        for portal in payload[portal_key]:
            required = {"geometry_px", "connects", "evidence", "confidence"}
            if not isinstance(portal, dict) or set(portal) != required or not isinstance(portal["geometry_px"], list):
                raise VisionRecoveryError("VISION_SCHEMA_INVALID", f"Invalid {portal_key} record")
            if not 0 <= float(portal["confidence"]) <= 1 or not isinstance(portal["connects"], list) or not isinstance(portal["evidence"], list):
                raise VisionRecoveryError("VISION_VALUE_INVALID", f"Invalid {portal_key} evidence")
    for shell in payload["building_shells"]:
        if not isinstance(shell, dict) or set(shell) != set(_SHELL_SCHEMA["required"]):
            raise VisionRecoveryError("VISION_SCHEMA_INVALID", "Invalid building-shell record")
        if len(shell["outer_ring_px"]) < 3 or not 0 <= float(shell["confidence"]) <= 1:
            raise VisionRecoveryError("VISION_GEOMETRY_INVALID", "Building-shell geometry is invalid")
    for boundary in payload["boundary_hypotheses"]:
        if not isinstance(boundary, dict) or set(boundary) != set(_BOUNDARY_SCHEMA["required"]):
            raise VisionRecoveryError("VISION_SCHEMA_INVALID", "Invalid boundary-hypothesis record")
        if boundary["role"] not in BOUNDARY_ROLES or len(boundary["geometry_px"]) < 2:
            raise VisionRecoveryError("VISION_VALUE_INVALID", "Boundary hypothesis is invalid")
    for region in payload["region_roles"]:
        if not isinstance(region, dict) or set(region) != set(_REGION_ROLE_SCHEMA["required"]):
            raise VisionRecoveryError("VISION_SCHEMA_INVALID", "Invalid region-role record")
        if region["role"] not in REGION_ROLES or len(region["polygon_px"]) < 3:
            raise VisionRecoveryError("VISION_VALUE_INVALID", "Region-role hypothesis is invalid")
    return payload


def _safe_provider_error(exc: Exception) -> tuple[str, str, bool]:
    """Normalize SDK/network failures without leaking request bodies or credentials."""
    name = type(exc).__name__.lower()
    status = getattr(exc, "status_code", None)
    if status in {401, 403} or "authentication" in name or "permission" in name:
        return "VISION_AUTH_ERROR", "Vision provider authentication failed", False
    if status == 402 or "insufficient_balance" in str(exc).lower() or "quota" in name:
        return "VISION_BUDGET_LIMIT", "Vision provider budget or quota is unavailable", False
    if status == 413:
        return "VISION_IMAGE_TOO_LARGE", "Vision request exceeds provider image limits", False
    if status == 429 or "ratelimit" in name or "rate_limit" in name:
        return "VISION_RATE_LIMIT", "Vision provider rate limit reached", True
    if "timeout" in name:
        return "VISION_TIMEOUT", "Vision provider request timed out", True
    if (isinstance(status, int) and status >= 500) or "connection" in name or "unavailable" in name:
        return "VISION_PROVIDER_UNAVAILABLE", "Vision provider is temporarily unavailable", True
    return "VISION_PROVIDER_ERROR", "Vision provider request failed", False


class OpenAICompatibleVisionAdapter:
    """Shared Responses API transport for provider-neutral architectural evidence."""
    def __init__(self, *, provider: str, api_key: str | None, model: str | None,
                 base_url: str | None = None, client=None, timeout_seconds: float | None = None,
                 max_retries: int | None = None):
        self.provider = provider
        self.model = model or os.getenv("ARCH_VISION_MODEL")
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_seconds = float(timeout_seconds or os.getenv("ARCH_VISION_TIMEOUT_SECONDS") or 90)
        configured_retries = int(max_retries if max_retries is not None else
                                 (os.getenv("ARCH_VISION_MAX_RETRIES") or 1))
        self.max_retries = min(max(configured_retries, 0), 1)
        self.last_call_metadata: dict[str, Any] = {}
        if not self.model:
            raise VisionRecoveryError("VISION_MODEL_NOT_CONFIGURED", "ARCH_VISION_MODEL is required")
        if client is None and not self.api_key:
            raise VisionRecoveryError("VISION_CREDENTIAL_NOT_CONFIGURED",
                                      f"{provider.upper()} vision credential is required")
        if client is None:
            from openai import OpenAI
            options = {"api_key": self.api_key, "timeout": self.timeout_seconds, "max_retries": 0}
            if self.base_url:
                options["base_url"] = self.base_url
            client = OpenAI(**options)
        self.client = client

    def analyze_shell_boundaries(self, *, image_path: str, frame_id: str,
                                 context: dict[str, Any] | None = None) -> dict:
        """Run the bounded V1 enclosure task against the authoritative full-floor render."""
        started=time.perf_counter(); context=context or {}
        image_bytes=Path(image_path).read_bytes()
        if len(image_bytes)>MAX_INLINE_IMAGE_BYTES:
            raise VisionRecoveryError("VISION_IMAGE_TOO_LARGE","Rendered floor exceeds inline image limits")
        prompt=("Analyze only the architectural enclosure of this floor. Identify the apparent building shell, "
                "major architectural boundary segments, and exterior or semi-exterior regions such as yard, "
                "terrace, balcony or lightwell. Do not identify doors, windows, room names, furniture, fixtures "
                "or equipment. Do not invent a boundary merely to close a polygon. Coordinates are image pixels. "
                "Keep evidence short and return only the strict schema. FRAME_ID="+json.dumps(frame_id)+". ")
        raw_texts=((context.get("source_context") or {}).get("raw_texts") or [])[:40]
        if raw_texts:
            prompt+="Visible source labels are optional orientation evidence only: "+json.dumps(
                [{"text":str(row.get("text") or "")[:80],"pixel_point":row.get("pixel_point")} for row in raw_texts],
                ensure_ascii=False,separators=(",",":"))
        encoded=base64.b64encode(image_bytes).decode("ascii")
        schema_json=json.dumps(SHELL_BOUNDARIES_JSON_SCHEMA,sort_keys=True,separators=(",",":"))
        request_bytes=((len(image_bytes)+2)//3)*4+len(prompt.encode("utf-8"))+len(schema_json.encode("utf-8"))
        if request_bytes>MAX_REQUEST_BODY_BYTES:
            raise VisionRecoveryError("VISION_IMAGE_TOO_LARGE","Rendered floor exceeds request body limits")
        identity={"provider":self.provider,"model":self.model,"task_type":"SHELL_BOUNDARIES_V1",
                  "task_prompt_version":SHELL_BOUNDARIES_PROMPT_VERSION,
                  "task_schema_version":SHELL_BOUNDARIES_SCHEMA_VERSION,
                  "transform_version":TRANSFORM_VERSION,"render_version":RENDER_VERSION,
                  "frame_id":frame_id,"render_sha256":sha256(image_bytes).hexdigest(),
                  "source_sha256":context.get("source_sha256"),"render_cache_key":context.get("render_cache_key")}
        cache_key=sha256(json.dumps(identity,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        cache_root=Path(os.getenv("ARCH_VISION_CACHE_DIR") or "/tmp/planha-architecture-vision")
        cache_root.mkdir(parents=True,exist_ok=True); cache_path=cache_root/f"vision-{cache_key}.json"
        common={**identity,"cache_key":cache_key,"image_bytes":len(image_bytes),"prompt_characters":len(prompt),
                "schema_bytes":len(schema_json.encode("utf-8")),"request_bytes":request_bytes}
        if cache_path.exists():
            payload=validate_shell_boundaries_payload(json.loads(cache_path.read_text(encoding="utf-8")),frame_id=frame_id)
            self.last_call_metadata={**common,"cache_hit":True,"attempt_count":0,"attempt_errors":[],
                                     "response_bytes":cache_path.stat().st_size,
                                     "latency_seconds":round(time.perf_counter()-started,6)}
            return payload
        try:
            response=self.client.responses.create(model=self.model,input=[{"role":"user","content":[
                {"type":"input_text","text":prompt},{"type":"input_image",
                 "image_url":f"data:image/png;base64,{encoded}","detail":"original"}]}],
                text={"format":{"type":"json_schema","name":"architectural_shell_boundaries",
                                "schema":SHELL_BOUNDARIES_JSON_SCHEMA,"strict":True}})
        except Exception as exc:
            code,message,_transient=_safe_provider_error(exc)
            self.last_call_metadata={**common,"cache_hit":False,"attempt_count":1,"attempt_errors":[code],
                                     "provider_http_status":getattr(exc,"status_code",None),
                                     "latency_seconds":round(time.perf_counter()-started,6)}
            raise VisionRecoveryError(code,message) from exc
        if getattr(response,"status",None)=="incomplete":
            raise VisionRecoveryError("VISION_RESPONSE_INCOMPLETE","Vision provider response is incomplete")
        raw=getattr(response,"output_text",None)
        if not raw:
            raise VisionRecoveryError("VISION_EMPTY_RESPONSE","Vision provider returned no structured output")
        usage=getattr(response,"usage",None)
        usage_fields={field:getattr(usage,field) for field in ("input_tokens","output_tokens","total_tokens")
                      if usage is not None and getattr(usage,field,None) is not None}
        self.last_call_metadata={**common,"cache_hit":False,"request_id":getattr(response,"id",None),
                                 "usage":usage_fields,"attempt_count":1,"attempt_errors":[],
                                 "response_bytes":len(raw.encode("utf-8")),
                                 "latency_seconds":round(time.perf_counter()-started,6)}
        try:
            parsed=json.loads(raw)
            payload=validate_shell_boundaries_payload(parsed,frame_id=frame_id)
        except json.JSONDecodeError as exc:
            error=VisionRecoveryError("VISION_JSON_INVALID","Vision provider returned malformed JSON",
                                      details={"validation_path":"$"})
            diagnostic_path=_store_invalid_v1_diagnostic(raw=raw,metadata=self.last_call_metadata,error=error)
            self.last_call_metadata["diagnostic_path"]=diagnostic_path
            raise error from exc
        except VisionRecoveryError as error:
            diagnostic_path=_store_invalid_v1_diagnostic(raw=raw,metadata=self.last_call_metadata,error=error)
            self.last_call_metadata["diagnostic_path"]=diagnostic_path
            raise
        cache_path.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True),encoding="utf-8")
        return payload

    def analyze(self, *, image_path: str, frame_id: str, regions: list[dict],
                context: dict[str, Any] | None = None):
        started = time.perf_counter()
        image_bytes = Path(image_path).read_bytes()
        encoded_size = ((len(image_bytes) + 2) // 3) * 4
        if len(image_bytes) > MAX_INLINE_IMAGE_BYTES:
            raise VisionRecoveryError("VISION_IMAGE_TOO_LARGE", "Rendered floor exceeds inline image limits")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        region_contract = [{"region_id": row["region_id"], "pixel_bounds": row.get("pixel_bounds"),
                            "cad_bounds": row.get("bounds"),
                            "geometry_authority": "LEGACY_DIAGNOSTIC_ONLY"
                                if (context or {}).get("legacy_regions_diagnostic_only") else "CANONICAL_CAD"}
                           for row in regions]
        source_context=(context or {}).get("source_context") or {}
        prompt = ("Inspect this raw architectural floor render and return architectural HYPOTHESES only. "
                  "You are not authoritative for physical wall material. Distinguish a physical space from "
                  "functional zones inside an open-plan space. Identify the building shell, site/yard, "
                  "semi-exterior regions, courtyards, shafts and stairs. Decompose visible separators into "
                  "boundary hypotheses; do not invent boundaries merely to close polygons. "
                  "Return frame_id exactly as supplied; FRAME_ID=" + json.dumps(frame_id) + ". "
                  "Return JSON with EXACTLY these top-level keys: frame_id, building_shells, "
                  "boundary_hypotheses, region_roles, physical_spaces, functional_zones, "
                  "doors, windows, open_passages, stairs, shafts, suspected_false_boundaries, "
                  "suspected_missing_boundaries, unresolved_regions. A building_shell contains shell_id, "
                  "outer_ring_px, inner_rings_px, evidence, confidence, uncertainties. A boundary_hypothesis "
                  "contains boundary_id, geometry_px, role, adjacent_regions, evidence, confidence, uncertainties; "
                  "role is EXTERIOR_SHELL, INTERIOR_SEPARATOR, OPEN_PLAN_TRANSITION, COURTYARD_EDGE, SHAFT_EDGE, "
                  "STAIR_EDGE or UNKNOWN. A region_role contains region_id, polygon_px, role, evidence, confidence, "
                  "uncertainties; role is BUILDING_INTERIOR, SITE_EXTERIOR, SEMI_EXTERIOR, COURTYARD, LIGHTWELL, "
                  "SHAFT, STAIR or UNKNOWN. Each physical_space must contain EXACTLY "
                  "vision_space_id, polygon_px, semantic_candidates[{type,confidence}], objects_seen, labels_seen, "
                  "boundary_evidence, uncertainties. Portal rows contain EXACTLY geometry_px, connects, evidence, "
                  "confidence. Functional-zone rows contain EXACTLY zone_id, geometry_px, semantic_type, evidence, "
                  "confidence. Stair, shaft and suspected-boundary rows contain EXACTLY geometry_px, evidence, "
                  "confidence. Unresolved-region rows contain EXACTLY geometry_px, reason. Coordinates are image "
                  "pixels. Do not invent dimensions. Use empty arrays rather than "
                  "guessing. Regions marked LEGACY_DIAGNOSTIC_ONLY are not truth and must not bias shell or "
                  "room topology. Known CAD regions are context, not required output identities. "
                  "Be concise: emit exactly one record per distinct architectural object, never duplicate a "
                  "space or portal, keep every evidence/label/object/uncertainty array to at most five short "
                  "items, and report at most ten unresolved regions ordered by architectural importance. "
                  "Every record is VISION_HYPOTHESIS, never VERIFIED. Do not enumerate dimension ticks, stair "
                  "tread numbers, furniture strokes, or annotation "
                  "fragments as spaces or unresolved regions.\nREGIONS=" +
                  json.dumps(region_contract, ensure_ascii=False, separators=(",", ":"))+
                  "\nRAW_SOURCE_CONTEXT="+json.dumps(source_context,ensure_ascii=False,separators=(",",":")))
        if encoded_size + len(prompt.encode("utf-8")) > MAX_REQUEST_BODY_BYTES:
            raise VisionRecoveryError("VISION_IMAGE_TOO_LARGE", "Rendered floor exceeds request body limits")
        identity = {"provider": self.provider, "model": self.model, "prompt_version": PROMPT_VERSION,
                    "schema_version": VISION_SCHEMA_VERSION, "transform_version": TRANSFORM_VERSION,
                    "render_version": RENDER_VERSION,
                    "frame_id": frame_id, "render_sha256": sha256(image_bytes).hexdigest(),
                    "source_sha256": (context or {}).get("source_sha256"),
                    "render_cache_key": (context or {}).get("render_cache_key"),
                    "scope": (context or {}).get("scope"), "regions": region_contract,
                    "source_context":source_context}
        cache_key = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        cache_root = Path(os.getenv("ARCH_VISION_CACHE_DIR") or "/tmp/planha-architecture-vision")
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_path = cache_root / f"vision-{cache_key}.json"
        if cache_path.exists():
            self.last_call_metadata = {**identity, "cache_key": cache_key, "cache_hit": True,
                                       "attempt_count":0,"attempt_errors":[],
                                       "latency_seconds": round(time.perf_counter() - started, 6)}
            return validate_global_payload(json.loads(cache_path.read_text(encoding="utf-8")), frame_id=frame_id)
        response = None; attempt_errors=[]
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.responses.create(
                    model=self.model,
                    input=[{"role": "user", "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": f"data:image/png;base64,{encoded}",
                         "detail": "original"},
                    ]}],
                    text={"format": {"type":"json_schema","name":"architectural_vision_evidence",
                                      "schema":GLOBAL_JSON_SCHEMA,"strict":True}},
                )
                break
            except Exception as exc:
                code, message, transient = _safe_provider_error(exc)
                attempt_errors.append(code)
                if not transient or attempt >= self.max_retries:
                    self.last_call_metadata={**identity,"cache_key":cache_key,"cache_hit":False,
                                             "attempt_count":attempt+1,"attempt_errors":attempt_errors,
                                             "latency_seconds":round(time.perf_counter()-started,6)}
                    raise VisionRecoveryError(code, message) from exc
        try:
            if getattr(response, "status", None) == "incomplete":
                raise VisionRecoveryError("VISION_RESPONSE_INCOMPLETE", "Vision provider response is incomplete")
            raw = getattr(response, "output_text", None)
            if not raw:
                raise VisionRecoveryError("VISION_EMPTY_RESPONSE", "Vision provider returned no structured output")
            payload = validate_global_payload(json.loads(raw), frame_id=frame_id)
            cache_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            usage = getattr(response, "usage", None)
            usage_fields = {}
            for field in ("input_tokens", "output_tokens", "total_tokens"):
                value = getattr(usage, field, None) if usage is not None else None
                if value is not None:
                    usage_fields[field] = value
            self.last_call_metadata = {**identity, "cache_key": cache_key, "cache_hit": False,
                                       "request_id": getattr(response, "id", None), "usage": usage_fields,
                                       "attempt_count":len(attempt_errors)+1,"attempt_errors":attempt_errors,
                                       "latency_seconds": round(time.perf_counter() - started, 6)}
            return payload
        except VisionRecoveryError:
            raise
        except json.JSONDecodeError as exc:
            raise VisionRecoveryError("VISION_JSON_INVALID", str(exc)) from exc
        except Exception as exc:
            raise VisionRecoveryError("VISION_RESPONSE_INVALID", "Vision provider response could not be validated") from exc


class OpenAIVisionAdapter(OpenAICompatibleVisionAdapter):
    def __init__(self, *, api_key: str | None = None, model: str | None = None, client=None,
                 timeout_seconds: float | None = None, max_retries: int | None = None):
        super().__init__(provider="openai", api_key=api_key or os.getenv("OPENAI_API_KEY"), model=model,
                         client=client, timeout_seconds=timeout_seconds, max_retries=max_retries)


class DeepSeekVisionAdapter(OpenAICompatibleVisionAdapter):
    def __init__(self, *, api_key: str | None = None, model: str | None = None, client=None,
                 timeout_seconds: float | None = None, max_retries: int | None = None,
                 base_url: str = DEEPSEEK_BASE_URL):
        super().__init__(provider="deepseek", api_key=api_key or os.getenv("DEEPSEEK_API_KEY"), model=model,
                         base_url=base_url, client=client, timeout_seconds=timeout_seconds,
                         max_retries=max_retries)


def configured_vision_adapter():
    provider = (os.getenv("ARCH_VISION_PROVIDER") or "disabled").strip().lower()
    if provider in {"", "disabled", "none", "off"}:
        return None, {"status": "CONFIG_REQUIRED", "error_code": "VISION_PROVIDER_NOT_CONFIGURED"}
    if provider not in {"openai", "deepseek"}:
        return None, {"status": "CONFIG_REQUIRED", "error_code": "VISION_PROVIDER_UNSUPPORTED"}
    try:
        return (OpenAIVisionAdapter() if provider == "openai" else DeepSeekVisionAdapter()), None
    except VisionRecoveryError as exc:
        return None, {"status": "CONFIG_REQUIRED", "error_code": exc.code, "message": str(exc)}


def _region_rows(spaces: list[dict], transform: RenderTransform) -> list[dict]:
    rows = []
    for space in spaces:
        if space.get("status") == "VERIFIED":
            continue
        xs = [p[0] for p in space["polygon"]]; ys = [p[1] for p in space["polygon"]]
        a = transform.cad_to_pixel((min(xs), min(ys))); b = transform.cad_to_pixel((max(xs), max(ys)))
        rows.append({"region_id": space["physical_space_id"], "bounds": [min(xs), min(ys), max(xs), max(ys)],
                     "pixel_bounds": [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]})
    return rows


def _raw_source_context(extracted: dict, manifest: dict) -> dict:
    """Bounded source-only context; contains no inferred semantics or Golden data."""
    transform=RenderTransform(*manifest["transform"]["cad_bounds"],*manifest["transform"]["pixel_size"],
                              manifest["transform"]["padding_px"])
    viewport=box(*manifest["transform"]["cad_bounds"])
    texts=[]
    for row in extracted.get("texts") or []:
        point=row.get("point")
        if point and viewport.covers(Point(float(point[0]),float(point[1]))):
            pixel=transform.cad_to_pixel(point)
            texts.append({"text":str(row.get("text") or "")[:160],"cad_point":[float(point[0]),float(point[1])],
                          "pixel_point":[round(pixel[0],3),round(pixel[1],3)]})
    dimensions=[]
    for row in extracted.get("dimensions") or []:
        points=[p for p in row.get("definition_points") or [] if viewport.covers(Point(float(p[0]),float(p[1])))]
        if points:
            dimensions.append({"measurement":row.get("measurement"),"definition_points":points[:4],
                               "text_override":str(row.get("text_override") or "")[:80]})
    return {"frame_id":manifest.get("frame_id"),"units":"SOURCE_DRAWING_UNITS",
            "viewport":manifest.get("viewport"),"raw_texts":texts[:250],"raw_dimensions":dimensions[:250]}


def _cad_polygon(pixel_polygon: list, transform: RenderTransform) -> Polygon | None:
    polygon = Polygon([transform.pixel_to_cad(point) for point in pixel_polygon])
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return polygon if polygon.geom_type == "Polygon" and polygon.area > 0 else None


def _top_semantic(row: dict) -> tuple[str, float]:
    candidates = sorted(row.get("semantic_candidates") or [], key=lambda item: -float(item["confidence"]))
    return (str(candidates[0]["type"]), float(candidates[0]["confidence"])) if candidates else ("unknown", 0.0)


def _strong_shared_wall(left: Polygon, right: Polygon, segments: list[dict], tolerance: float) -> tuple[bool, list[str]]:
    shared = left.boundary.intersection(right.boundary)
    if shared.is_empty or shared.length <= tolerance:
        return False, []
    handles = []
    for segment in segments:
        if segment.get("status") != "ACCEPTED" or not segment.get("geometry"):
            continue
        line = LineString(segment["geometry"])
        overlap = line.buffer(tolerance).intersection(shared).length
        if overlap >= max(shared.length * .45, tolerance * 2):
            handles.append(segment.get("source_handle"))
    return bool(handles), sorted(handle for handle in handles if handle)


def reconcile_and_repair(*, analysis: dict, spaces: list[dict], transform: RenderTransform,
                         segments: list[dict], source_hash: str, tolerance: float,
                         canonical_walls: list[dict] | None = None) -> dict:
    """Reconcile Vision polygons with CAD and apply only CAD-approved repairs."""
    frame_id = analysis["frame_id"]
    frame_spaces = [space for space in spaces if space.get("frame_id") == frame_id]
    polygons = {space["physical_space_id"]: Polygon(space["polygon"], space.get("interior_rings") or [])
                for space in frame_spaces}
    repairs = []; outcomes = []; proposed_portals = []
    accepted_segments = [segment for segment in segments if segment.get("status") == "ACCEPTED"]
    accepted_lines = [LineString(segment["geometry"]) for segment in accepted_segments]
    segment_tree = STRtree(accepted_lines) if accepted_lines else None
    segment_by_geometry = {id(geometry): segment for geometry, segment in zip(accepted_lines, accepted_segments)}
    for vision in analysis["physical_spaces"]:
        vpoly = _cad_polygon(vision["polygon_px"], transform)
        if vpoly is None:
            outcomes.append({"vision_space_id": vision["vision_space_id"], "outcome": "REJECTED",
                             "reason": "INVALID_MAPPED_POLYGON"}); continue
        overlaps = []
        for space_id, poly in polygons.items():
            intersection = vpoly.intersection(poly).area
            if intersection > 0:
                overlaps.append((intersection / max(poly.area, 1e-9), intersection / max(vpoly.area, 1e-9), space_id))
        overlaps.sort(reverse=True)
        matched = [space_id for cad_share, vision_share, space_id in overlaps if cad_share >= .20 and vision_share >= .08]
        semantic, confidence = _top_semantic(vision)
        if len(matched) == 1:
            space = next(item for item in spaces if item["physical_space_id"] == matched[0])
            iou = vpoly.intersection(polygons[matched[0]]).area / max(vpoly.union(polygons[matched[0]]).area, 1e-9)
            accepted = iou >= .55 and semantic != "unknown" and confidence >= .90 and not vision["uncertainties"]
            repair = {"repair_id": sha256(f"RECLASSIFY:{frame_id}:{matched[0]}:{semantic}".encode()).hexdigest()[:20],
                      "repair_type": "RECLASSIFY_SPACE", "affected_spaces": matched,
                      "vision_evidence": {"vision_space_id": vision["vision_space_id"], "iou": iou,
                                          "semantic": semantic, "confidence": confidence},
                      "cad_evidence": {"polygon_identity": matched[0]}, "source_handles": space.get("source_handles") or [],
                      "before_state": {"category": space.get("category"), "status": space.get("status")},
                      "proposed_state": {"category": semantic, "status": "HIGH_CONFIDENCE"},
                      "validation_result": "PASS" if accepted else "INSUFFICIENT_EVIDENCE",
                      "accepted": accepted, "reason": "POLYGON_AGREEMENT_AND_SEMANTIC_EVIDENCE" if accepted else "INSUFFICIENT_POLYGON_OR_SEMANTIC_EVIDENCE"}
            repairs.append(repair)
            if accepted:
                space["category"] = semantic; space["use"] = semantic; space["status"] = "HIGH_CONFIDENCE"
                space["confidence"] = confidence
                space["evidence"].append({"class": "VISION_CAD_RECONCILIATION", "vision_space_id": vision["vision_space_id"],
                                          "iou": iou, "confidence": confidence, "authority": "SUPPORTING_EVIDENCE"})
            outcomes.append({"vision_space_id": vision["vision_space_id"], "outcome": "CONFIRMED" if accepted else "INSUFFICIENT_EVIDENCE",
                             "matched_spaces": matched, "iou": iou})
        elif len(matched) > 1:
            selected = [polygons[space_id] for space_id in matched]
            union = unary_union(selected); iou = vpoly.intersection(union).area / max(vpoly.union(union).area, 1e-9)
            strong = []; handles = []
            for index, left in enumerate(selected):
                for right in selected[index + 1:]:
                    is_strong, source_handles = _strong_shared_wall(left, right, segments, tolerance)
                    strong.append(is_strong); handles.extend(source_handles)
            merged_geometry = union.geom_type == "Polygon"
            accepted = iou >= .70 and merged_geometry and not any(strong) and confidence >= .88 and not vision["uncertainties"]
            repair = {"repair_id": sha256(f"MERGE:{frame_id}:{','.join(sorted(matched))}".encode()).hexdigest()[:20],
                      "repair_type": "MERGE_CELLS", "affected_spaces": sorted(matched),
                      "vision_evidence": {"vision_space_id": vision["vision_space_id"], "union_iou": iou,
                                          "semantic": semantic, "confidence": confidence},
                      "cad_evidence": {"strong_shared_wall": any(strong), "shared_wall_handles": sorted(set(handles))},
                      "source_handles": sorted(set(handles)), "before_state": {"space_ids": sorted(matched)},
                      "proposed_state": {"geometry_type": union.geom_type, "semantic": semantic},
                      "validation_result": "PASS" if accepted else "REJECTED",
                      "accepted": accepted,
                      "reason": "WEAK_BOUNDARIES_AND_UNION_AGREEMENT" if accepted else "STRONG_WALL_OR_GEOMETRY_CONFLICT"}
            repairs.append(repair)
            if accepted:
                members = [next(item for item in spaces if item["physical_space_id"] == space_id) for space_id in matched]
                base = members[0]; ring = [[float(x), float(y)] for x, y in list(union.exterior.coords)[:-1]]
                new_id = "SPACE-" + sha256(json.dumps([source_hash, frame_id, ring], sort_keys=True).encode()).hexdigest()[:16].upper()
                base.update({"physical_space_id": new_id, "space_id": new_id, "polygon": ring,
                             "interior_rings": [[[float(x), float(y)] for x, y in list(hole.coords)[:-1]] for hole in union.interiors],
                             "centroid": [union.centroid.x, union.centroid.y], "geometric_area_drawing_units": union.area,
                             "category": semantic, "use": semantic, "status": "HIGH_CONFIDENCE", "confidence": confidence,
                             "source_handles": sorted({handle for item in members for handle in item.get("source_handles") or []})})
                base["evidence"].append({"class": "VISION_ASSISTED_WEAK_BOUNDARY_MERGE", "repair_id": repair["repair_id"],
                                         "authority": "CAD_APPROVED_REPAIR"})
                spaces[:] = [item for item in spaces if item not in members[1:]]
            outcomes.append({"vision_space_id": vision["vision_space_id"], "outcome": "SUPPORTED_REPAIR" if accepted else "CONFLICT",
                             "matched_spaces": matched, "union_iou": iou})
        else:
            outcomes.append({"vision_space_id": vision["vision_space_id"], "outcome": "INSUFFICIENT_EVIDENCE",
                             "reason": "NO_CAD_SPACE_OVERLAP"})
    for kind in ("doors", "windows", "open_passages"):
        for index, portal in enumerate(analysis[kind]):
            points = portal["geometry_px"]
            mapped = [transform.pixel_to_cad(point) for point in points if isinstance(point, list) and len(point) == 2]
            near = []
            if len(mapped) >= 2:
                line = LineString(mapped)
                pixel_error_tolerance=6/max(transform.scale,1e-12)
                search_tolerance=max(tolerance*5,pixel_error_tolerance)
                candidates = segment_tree.query(line.buffer(search_tolerance)) if segment_tree is not None else []
                # Shapely 2 returns indices, while Shapely 1 returns geometry objects.
                candidate_rows = [accepted_segments[int(item)] if hasattr(item, "__index__") else
                                  segment_by_geometry.get(id(item)) for item in candidates]
                near = [segment for segment in candidate_rows if segment is not None and
                        LineString(segment["geometry"]).distance(line) <= search_tolerance]
            else:
                search_tolerance=max(tolerance*5,6/max(transform.scale,1e-12))
            continuous_wall=bool(near) and any(LineString(row["geometry"]).intersection(line.buffer(search_tolerance)).length>
                                               max(tolerance*2,line.length*.35) for row in near)
            host=None; host_reason=None; host_candidates=[]
            if len(mapped)>=2 and canonical_walls:
                host,host_reason,host_candidates=host_portal_on_walls(
                    line,[wall for wall in canonical_walls if wall.get("frame_id")==frame_id],
                    tolerance=tolerance,pixel_tolerance=pixel_error_tolerance)
            accepted = float(portal["confidence"]) >= .90 and host is not None
            if host is None and canonical_walls: rejection=host_reason
            elif not near: rejection="NO_NEARBY_WALL"
            elif continuous_wall: rejection="NO_WALL_GAP"
            elif float(portal["confidence"])<.90: rejection="OTHER"
            else: rejection=None
            repair = {"repair_id": sha256(f"PORTAL:{frame_id}:{kind}:{index}:{mapped}".encode()).hexdigest()[:20],
                      "repair_type": {"doors":"CREATE_DOOR_CANDIDATE", "windows":"CREATE_WINDOW_CANDIDATE",
                                      "open_passages":"CREATE_OPEN_PASSAGE_CANDIDATE"}[kind],
                      "affected_spaces": portal["connects"], "vision_evidence": portal,
                      "cad_evidence": {"near_wall_segment_ids": [row["segment_id"] for row in near],
                                       "host_wall_id":host.get("wall_id") if host else None,
                                       "candidate_host_wall_ids":host_candidates,
                                       "search_tolerance":search_tolerance,"continuous_wall":continuous_wall,
                                       "rejection_category":rejection},
                      "source_handles": [row.get("source_handle") for row in near if row.get("source_handle")],
                      "before_state": None, "proposed_state": {"geometry": mapped},
                      "validation_result": "PASS" if accepted else "INSUFFICIENT_EVIDENCE",
                      "accepted": accepted, "reason": "CANONICAL_WALL_GAP_SUPPORT" if accepted else rejection}
            repairs.append(repair)
            if accepted: proposed_portals.append({"kind": kind[:-1] if kind.endswith("s") else kind, "geometry": mapped,
                                                   "repair_id": repair["repair_id"], "status": "CANDIDATE"})
    return {"outcomes": outcomes, "repairs": repairs, "portal_candidates": proposed_portals,
            "accepted_repairs": sum(row["accepted"] for row in repairs),
            "rejected_repairs": sum(not row["accepted"] for row in repairs)}


def recover_semantics(*, extracted: dict, frames: list[dict], spaces: list[dict], source_hash: str,
                      segments: list[dict] | None = None, tolerance: float | None = None,
                      adapter=None, cache_dir=None, canonical_walls: list[dict] | None = None,
                      hybrid_frame_ids: set[str] | None = None) -> dict:
    """Run one global pass and at most one localized pass per unresolved frame."""
    events = []; calls = []; analyses = []; repairs = []; portal_candidates = []; started = time.perf_counter()
    for stage in (RecoveryStage.SOURCE_INGESTION, RecoveryStage.FRAME_AND_LEVEL_ISOLATION,
                  RecoveryStage.DETERMINISTIC_CAD_RECONSTRUCTION, RecoveryStage.DETERMINISTIC_SEMANTIC_FUSION,
                  RecoveryStage.COMPLETENESS_GATE_1):
        events.append({"stage": stage.value, "at_seconds": round(time.perf_counter()-started, 6)})
    if adapter is None:
        adapter, configuration_error = configured_vision_adapter()
        if adapter is None:
            return {"provider": "NONE", "calls": 0, "analyses": [], "repairs": [], "status": "CONFIG_REQUIRED",
                    "policy": "DETERMINISTIC_FIRST_BOUNDED_GLOBAL_THEN_LOCAL", "events": events,
                    "error": configuration_error, "runtime_seconds": round(time.perf_counter()-started, 6)}
    hybrid_frame_ids=set(hybrid_frame_ids or [])
    candidate_frames=list(frames)
    if hybrid_frame_ids:
        candidate_frames=[frame for frame in frames if frame.get("frame_id") in hybrid_frame_ids]
        # Ground-first is semantic, not coordinate/project-specific.
        candidate_frames.sort(key=lambda frame:(frame.get("level_candidate")!="GROUND",frame.get("frame_id")))
        candidate_frames=candidate_frames[:1]
    hybrid_results=[]
    for frame in candidate_frames:
        frame_spaces = [s for s in spaces if s.get("frame_id") == frame.get("frame_id") and s.get("status") != "VERIFIED"]
        hybrid_mode=frame.get("frame_id") in hybrid_frame_ids
        if (not frame_spaces and not hybrid_mode) or not frame.get("bounds"):
            continue
        full_manifest=render_source_frame(extracted=extracted,frame=frame,source_hash=source_hash,
                                          cache_dir=cache_dir,width_px=1100,render_role="CONTEXT_FULL_FRAME")
        viewport=select_vision_viewport(extracted=extracted,frame=frame)
        events.append({"stage":RecoveryStage.ARCHITECTURAL_VISION_VIEWPORT_SELECTION.value,
                       "frame_id":frame["frame_id"],"status":viewport["status"]})
        manifest = render_source_frame(extracted=extracted, frame=frame, source_hash=source_hash, cache_dir=cache_dir,
                                       viewport=viewport,render_role="FOCUSED_PLAN")
        events.append({"stage": RecoveryStage.AUTHORITATIVE_FLOOR_RENDER.value, "frame_id": frame["frame_id"]})
        transform = RenderTransform(*manifest["transform"]["cad_bounds"], *manifest["transform"]["pixel_size"],
                                    manifest["transform"]["padding_px"])
        regions = _region_rows(frame_spaces, transform)
        source_context=_raw_source_context(extracted,manifest)
        try:
            first = adapter.analyze(image_path=manifest["image_path"], frame_id=frame["frame_id"], regions=regions,
                                    context={"source_sha256":source_hash,"render_cache_key":manifest["cache_key"],
                                             "scope":"GLOBAL","source_context":source_context,
                                             "legacy_regions_diagnostic_only":hybrid_mode})
            calls.append({"scope": "GLOBAL", "frame_id": frame["frame_id"], "region_count": len(regions),
                          "image_cache_key": manifest["cache_key"], "vision_space_count": len(first["physical_spaces"]),
                          "context_image_path":full_manifest["image_path"],"focused_image_path":manifest["image_path"],
                          "input_resolution":manifest["transform"]["pixel_size"],
                          "plan_occupancy_ratio":viewport["metrics"]["rendered_content_pixel_ratio"],
                          "content_bounds":viewport["architectural_content_bounds"],
                          "full_frame_bounds":viewport["authoritative_frame_bounds"],
                          "raw_text_count":len(source_context["raw_texts"]),
                          "dimension_count":len(source_context["raw_dimensions"]),"viewport":viewport,
                          "provider_call":dict(getattr(adapter,"last_call_metadata",{}) or {})})
            analyses.append({"scope":"GLOBAL", "frame_id":frame["frame_id"], "analysis":first,
                             "render_hash":manifest["cache_key"]})
            events.append({"stage": RecoveryStage.GLOBAL_VISION_ANALYSIS.value, "frame_id": frame["frame_id"]})
            if hybrid_mode:
                from .hybrid_architectural_recovery import (
                    build_boundary_evidence_graph, construct_hybrid_topology, map_hypotheses_to_cad)
                mapped=map_hypotheses_to_cad(first,transform,source_sha256=source_hash,
                    render_hash=manifest["cache_key"],provider=getattr(adapter,"provider",None),
                    model=getattr(adapter,"model",None),prompt_version=PROMPT_VERSION,
                    schema_version=VISION_SCHEMA_VERSION)
                evidence=build_boundary_evidence_graph(mapped=mapped,segments=segments or [],
                    texts=extracted.get("texts") or [],dimensions=extracted.get("dimensions") or [],
                    source_sha256=source_hash,tolerance=max(float(tolerance or .001),1e-8))
                topology=construct_hybrid_topology(mapped=mapped,boundary_analysis=evidence,
                    source_sha256=source_hash,tolerance=max(float(tolerance or .001),1e-8))
                topology["evidence_graph"]=evidence["evidence_graph"]
                topology["mapped_hypotheses"]=mapped
                hybrid_results.append(topology)
                if topology["physical_spaces"] and topology["overlap_area"]<=max(float(tolerance or .001)**2,1e-12):
                    spaces[:]=[space for space in spaces if space.get("frame_id")!=frame["frame_id"]]
                    spaces.extend(topology["physical_spaces"])
                events.extend(({"stage":"HYBRID_EVIDENCE_GRAPH","frame_id":frame["frame_id"]},
                               {"stage":"HYBRID_TOPOLOGY_RECONSTRUCTION","frame_id":frame["frame_id"],
                                "status":topology["status"]}))
                # Hybrid mode permits one global call. A local provider call is
                # never automatic; unresolved material decisions become minimal questions.
                continue
            fused = reconcile_and_repair(analysis=first, spaces=spaces, transform=transform,
                                         segments=segments or [], source_hash=source_hash,
                                         tolerance=max(float(tolerance or .001), 1e-8),
                                         canonical_walls=canonical_walls)
            repairs.extend(fused["repairs"]); portal_candidates.extend(fused["portal_candidates"])
            events.extend(({"stage":RecoveryStage.CAD_VISION_RECONCILIATION_1.value,"frame_id":frame["frame_id"]},
                           {"stage":RecoveryStage.TOPOLOGY_REPAIR_1.value,"frame_id":frame["frame_id"],
                            "accepted_repairs":fused["accepted_repairs"]},
                           {"stage":RecoveryStage.RECONSTRUCTION_RERUN.value,"frame_id":frame["frame_id"]},
                           {"stage":RecoveryStage.COMPLETENESS_GATE_2.value,"frame_id":frame["frame_id"]}))
            unresolved_after = [space for space in spaces if space.get("frame_id") == frame["frame_id"] and
                                space.get("status") not in {"VERIFIED", "HIGH_CONFIDENCE"}]
            if unresolved_after:
                # The second pass uses the same raw-evidence viewport.  It must
                # never crop around the engine's current room predictions.
                local_manifest=manifest
                local_transform=RenderTransform(*local_manifest["transform"]["cad_bounds"],
                                                *local_manifest["transform"]["pixel_size"],
                                                local_manifest["transform"]["padding_px"])
                local_regions=_region_rows(unresolved_after,local_transform)
                events.append({"stage":RecoveryStage.LOCAL_AMBIGUITY_RENDERING.value,"frame_id":frame["frame_id"]})
                second=adapter.analyze(image_path=local_manifest["image_path"],frame_id=frame["frame_id"],regions=local_regions,
                                       context={"source_sha256":source_hash,"render_cache_key":local_manifest["cache_key"],
                                                "scope":"LOCAL","source_context":source_context})
                calls.append({"scope":"LOCAL","frame_id":frame["frame_id"],"region_count":len(local_regions),
                              "image_cache_key":local_manifest["cache_key"],"vision_space_count":len(second["physical_spaces"]),
                              "context_image_path":full_manifest["image_path"],"focused_image_path":local_manifest["image_path"],
                              "input_resolution":local_manifest["transform"]["pixel_size"],
                              "plan_occupancy_ratio":viewport["metrics"]["rendered_content_pixel_ratio"],
                              "content_bounds":viewport["architectural_content_bounds"],
                              "full_frame_bounds":viewport["authoritative_frame_bounds"],
                              "raw_text_count":len(source_context["raw_texts"]),
                              "dimension_count":len(source_context["raw_dimensions"]),"viewport":viewport,
                              "provider_call":dict(getattr(adapter,"last_call_metadata",{}) or {})})
                analyses.append({"scope":"LOCAL","frame_id":frame["frame_id"],"analysis":second,
                                 "render_hash":local_manifest["cache_key"]})
                events.append({"stage":RecoveryStage.LOCAL_VISION_ANALYSIS.value,"frame_id":frame["frame_id"]})
                local_fused=reconcile_and_repair(analysis=second,spaces=spaces,transform=local_transform,
                                                 segments=segments or [],source_hash=source_hash,
                                                 tolerance=max(float(tolerance or .001),1e-8),
                                                 canonical_walls=canonical_walls)
                repairs.extend(local_fused["repairs"]); portal_candidates.extend(local_fused["portal_candidates"])
                events.extend(({"stage":RecoveryStage.CAD_VISION_RECONCILIATION_2.value,"frame_id":frame["frame_id"]},
                               {"stage":RecoveryStage.TARGETED_TOPOLOGY_REPAIR_2.value,"frame_id":frame["frame_id"],
                                "accepted_repairs":local_fused["accepted_repairs"]},
                               {"stage":RecoveryStage.FINAL_RECONSTRUCTION_RERUN.value,"frame_id":frame["frame_id"]}))
        except VisionRecoveryError as exc:
            events.append({"stage": RecoveryStage.FAILED.value, "frame_id": frame["frame_id"], "error_code": exc.code})
            return {"provider": getattr(adapter,"provider",type(adapter).__name__), "model": getattr(adapter, "model", None), "calls": len(calls),
                    "call_log": calls, "analyses": analyses, "repairs": repairs, "status": "FAILED", "error_code": exc.code,
                    "message": str(exc), "events": events,"last_provider_call":dict(getattr(adapter,"last_call_metadata",{}) or {}),
                    "policy": "DETERMINISTIC_FIRST_BOUNDED_GLOBAL_THEN_LOCAL",
                    "runtime_seconds": round(time.perf_counter()-started, 6)}
    events.append({"stage": RecoveryStage.FINAL_COMPLETENESS_GATE.value})
    return {"provider": getattr(adapter,"provider",type(adapter).__name__), "model": getattr(adapter, "model", None), "calls": len(calls),
            "call_log": calls, "analyses": analyses, "repairs": repairs, "portal_candidates":portal_candidates,
            "hybrid_recovery":{"trigger":"SOURCE_ARCHITECTURE_GEOMETRY_INSUFFICIENT",
                               "mode":"HYBRID_ARCHITECTURAL_RECOVERY","frames":hybrid_results}
                              if hybrid_frame_ids else None,
            "vision_repairs_proposed":len(repairs),"vision_repairs_accepted":sum(row["accepted"] for row in repairs),
            "vision_repairs_rejected":sum(not row["accepted"] for row in repairs),
            "status": "COMPLETE", "events": events,
            "policy": "DETERMINISTIC_FIRST_BOUNDED_GLOBAL_THEN_LOCAL", "prompt_version": PROMPT_VERSION,
            "fusion_version": FUSION_VERSION, "runtime_seconds": round(time.perf_counter()-started, 6)}
