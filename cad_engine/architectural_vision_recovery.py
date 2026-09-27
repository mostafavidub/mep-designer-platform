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

from PIL import Image, ImageDraw
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union


RENDER_VERSION = "architecture-source-render/1"
PROMPT_VERSION = "architecture-recovery/1"
FUSION_VERSION = "architecture-evidence-fusion/1"
VISION_SCHEMA_VERSION = "architectural-vision-evidence/1.0"
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
    "electrical_room", "boiler_room", "janitor", "common_room", "open_plan", "unknown",
}


class RecoveryStage(str, Enum):
    SOURCE_INGESTION = "SOURCE_INGESTION"
    FRAME_AND_LEVEL_ISOLATION = "FRAME_AND_LEVEL_ISOLATION"
    DETERMINISTIC_CAD_RECONSTRUCTION = "DETERMINISTIC_CAD_RECONSTRUCTION"
    DETERMINISTIC_SEMANTIC_FUSION = "DETERMINISTIC_SEMANTIC_FUSION"
    COMPLETENESS_GATE_1 = "COMPLETENESS_GATE_1"
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
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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


def render_source_frame(*, extracted: dict, frame: dict, source_hash: str,
                        cache_dir: str | Path | None = None, width_px: int = 1800) -> dict:
    """Render raw source primitives without using reconstructed model output."""
    bounds = frame.get("bounds")
    if not bounds or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        raise VisionRecoveryError("INVALID_FRAME_BOUNDS", "A valid CAD frame is required for rendering")
    ratio = max(.35, min(2.8, (bounds[3] - bounds[1]) / max(bounds[2] - bounds[0], 1e-9)))
    height_px = max(900, min(2600, int(width_px * ratio)))
    transform = RenderTransform(*map(float, bounds), width_px, height_px)
    key = sha256(json.dumps([source_hash, frame.get("frame_id"), bounds, RENDER_VERSION, width_px],
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
    for text in extracted.get("texts") or []:
        point = text.get("point")
        if not point:
            continue
        px = transform.cad_to_pixel(point)
        if 0 <= px[0] <= width_px and 0 <= px[1] <= height_px:
            draw.text(px, str(text.get("text") or "")[:80], fill=(25, 25, 25))
    image.save(image_path, format="PNG", optimize=True)
    manifest = {"image_path": str(image_path), "cache_key": key, "frame_id": frame.get("frame_id"),
                "source_sha256": source_hash, "render_version": RENDER_VERSION,
                "transform": transform.as_dict(), "primitive_count": count}
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


GLOBAL_KEYS = {"frame_id", "physical_spaces", "functional_zones", "doors", "windows",
               "open_passages", "stairs", "shafts", "suspected_false_boundaries",
               "suspected_missing_boundaries", "unresolved_regions"}

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
GLOBAL_JSON_SCHEMA={"type":"object","additionalProperties":False,"required":sorted(GLOBAL_KEYS),"properties":{
    "frame_id":{"type":"string"},
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


def validate_global_payload(payload: Any, *, frame_id: str) -> dict:
    """Strictly validate the geometry-bearing global Vision contract."""
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

    def analyze(self, *, image_path: str, frame_id: str, regions: list[dict],
                context: dict[str, Any] | None = None):
        started = time.perf_counter()
        image_bytes = Path(image_path).read_bytes()
        encoded_size = ((len(image_bytes) + 2) // 3) * 4
        if len(image_bytes) > MAX_INLINE_IMAGE_BYTES:
            raise VisionRecoveryError("VISION_IMAGE_TOO_LARGE", "Rendered floor exceeds inline image limits")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        region_contract = [{"region_id": row["region_id"], "pixel_bounds": row.get("pixel_bounds"),
                            "cad_bounds": row.get("bounds")} for row in regions]
        prompt = ("Inspect this raw architectural floor render as supporting evidence for exact CAD. "
                  "Return frame_id exactly as supplied; FRAME_ID=" + json.dumps(frame_id) + ". "
                  "Return JSON with EXACTLY these top-level keys: frame_id, physical_spaces, functional_zones, "
                  "doors, windows, open_passages, stairs, shafts, suspected_false_boundaries, "
                  "suspected_missing_boundaries, unresolved_regions. Each physical_space must contain EXACTLY "
                  "vision_space_id, polygon_px, semantic_candidates[{type,confidence}], objects_seen, labels_seen, "
                  "boundary_evidence, uncertainties. Portal rows contain EXACTLY geometry_px, connects, evidence, "
                  "confidence. Functional-zone rows contain EXACTLY zone_id, geometry_px, semantic_type, evidence, "
                  "confidence. Stair, shaft and suspected-boundary rows contain EXACTLY geometry_px, evidence, "
                  "confidence. Unresolved-region rows contain EXACTLY geometry_px, reason. Coordinates are image "
                  "pixels. Do not invent dimensions. Use empty arrays rather than "
                  "guessing. Known CAD regions are context, not required output identities.\nREGIONS=" +
                  json.dumps(region_contract, ensure_ascii=False, separators=(",", ":")))
        if encoded_size + len(prompt.encode("utf-8")) > MAX_REQUEST_BODY_BYTES:
            raise VisionRecoveryError("VISION_IMAGE_TOO_LARGE", "Rendered floor exceeds request body limits")
        identity = {"provider": self.provider, "model": self.model, "prompt_version": PROMPT_VERSION,
                    "schema_version": VISION_SCHEMA_VERSION, "transform_version": TRANSFORM_VERSION,
                    "render_version": RENDER_VERSION,
                    "frame_id": frame_id, "render_sha256": sha256(image_bytes).hexdigest(),
                    "source_sha256": (context or {}).get("source_sha256"),
                    "render_cache_key": (context or {}).get("render_cache_key"),
                    "scope": (context or {}).get("scope"), "regions": region_contract}
        cache_key = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        cache_root = Path(os.getenv("ARCH_VISION_CACHE_DIR") or "/tmp/planha-architecture-vision")
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_path = cache_root / f"vision-{cache_key}.json"
        if cache_path.exists():
            self.last_call_metadata = {**identity, "cache_key": cache_key, "cache_hit": True,
                                       "latency_seconds": round(time.perf_counter() - started, 6)}
            return validate_global_payload(json.loads(cache_path.read_text(encoding="utf-8")), frame_id=frame_id)
        response = None
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
                if not transient or attempt >= self.max_retries:
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
                         segments: list[dict], source_hash: str, tolerance: float) -> dict:
    """Reconcile Vision polygons with CAD and apply only CAD-approved repairs."""
    frame_id = analysis["frame_id"]
    frame_spaces = [space for space in spaces if space.get("frame_id") == frame_id]
    polygons = {space["physical_space_id"]: Polygon(space["polygon"], space.get("interior_rings") or [])
                for space in frame_spaces}
    repairs = []; outcomes = []; proposed_portals = []
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
                near = [segment for segment in segments if segment.get("status") == "ACCEPTED" and
                        LineString(segment["geometry"]).distance(line) <= tolerance * 5]
            accepted = float(portal["confidence"]) >= .90 and bool(near)
            repair = {"repair_id": sha256(f"PORTAL:{frame_id}:{kind}:{index}:{mapped}".encode()).hexdigest()[:20],
                      "repair_type": {"doors":"CREATE_DOOR_CANDIDATE", "windows":"CREATE_WINDOW_CANDIDATE",
                                      "open_passages":"CREATE_OPEN_PASSAGE_CANDIDATE"}[kind],
                      "affected_spaces": portal["connects"], "vision_evidence": portal,
                      "cad_evidence": {"near_wall_segment_ids": [row["segment_id"] for row in near]},
                      "source_handles": [row.get("source_handle") for row in near if row.get("source_handle")],
                      "before_state": None, "proposed_state": {"geometry": mapped},
                      "validation_result": "PASS" if accepted else "INSUFFICIENT_EVIDENCE",
                      "accepted": accepted, "reason": "CAD_WALL_HOST_SUPPORT" if accepted else "NO_DEFENSIBLE_CAD_HOST"}
            repairs.append(repair)
            if accepted: proposed_portals.append({"kind": kind[:-1] if kind.endswith("s") else kind, "geometry": mapped,
                                                   "repair_id": repair["repair_id"], "status": "CANDIDATE"})
    return {"outcomes": outcomes, "repairs": repairs, "portal_candidates": proposed_portals,
            "accepted_repairs": sum(row["accepted"] for row in repairs),
            "rejected_repairs": sum(not row["accepted"] for row in repairs)}


def recover_semantics(*, extracted: dict, frames: list[dict], spaces: list[dict], source_hash: str,
                      segments: list[dict] | None = None, tolerance: float | None = None,
                      adapter=None, cache_dir=None) -> dict:
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
    for frame in frames:
        frame_spaces = [s for s in spaces if s.get("frame_id") == frame.get("frame_id") and s.get("status") != "VERIFIED"]
        if not frame_spaces or not frame.get("bounds"):
            continue
        manifest = render_source_frame(extracted=extracted, frame=frame, source_hash=source_hash, cache_dir=cache_dir)
        events.append({"stage": RecoveryStage.AUTHORITATIVE_FLOOR_RENDER.value, "frame_id": frame["frame_id"]})
        transform = RenderTransform(*manifest["transform"]["cad_bounds"], *manifest["transform"]["pixel_size"],
                                    manifest["transform"]["padding_px"])
        regions = _region_rows(frame_spaces, transform)
        try:
            first = adapter.analyze(image_path=manifest["image_path"], frame_id=frame["frame_id"], regions=regions,
                                    context={"source_sha256":source_hash,"render_cache_key":manifest["cache_key"],
                                             "scope":"GLOBAL"})
            calls.append({"scope": "GLOBAL", "frame_id": frame["frame_id"], "region_count": len(regions),
                          "image_cache_key": manifest["cache_key"], "vision_space_count": len(first["physical_spaces"]),
                          "provider_call":dict(getattr(adapter,"last_call_metadata",{}) or {})})
            analyses.append({"scope":"GLOBAL", "frame_id":frame["frame_id"], "analysis":first,
                             "render_hash":manifest["cache_key"]})
            events.append({"stage": RecoveryStage.GLOBAL_VISION_ANALYSIS.value, "frame_id": frame["frame_id"]})
            fused = reconcile_and_repair(analysis=first, spaces=spaces, transform=transform,
                                         segments=segments or [], source_hash=source_hash,
                                         tolerance=max(float(tolerance or .001), 1e-8))
            repairs.extend(fused["repairs"]); portal_candidates.extend(fused["portal_candidates"])
            events.extend(({"stage":RecoveryStage.CAD_VISION_RECONCILIATION_1.value,"frame_id":frame["frame_id"]},
                           {"stage":RecoveryStage.TOPOLOGY_REPAIR_1.value,"frame_id":frame["frame_id"],
                            "accepted_repairs":fused["accepted_repairs"]},
                           {"stage":RecoveryStage.RECONSTRUCTION_RERUN.value,"frame_id":frame["frame_id"]},
                           {"stage":RecoveryStage.COMPLETENESS_GATE_2.value,"frame_id":frame["frame_id"]}))
            unresolved_after = [space for space in spaces if space.get("frame_id") == frame["frame_id"] and
                                space.get("status") not in {"VERIFIED", "HIGH_CONFIDENCE"}]
            if unresolved_after:
                bounds = [Polygon(space["polygon"]).bounds for space in unresolved_after]
                minx=min(row[0] for row in bounds); miny=min(row[1] for row in bounds)
                maxx=max(row[2] for row in bounds); maxy=max(row[3] for row in bounds)
                margin=max(maxx-minx,maxy-miny)*.08 or 1.0
                local_frame={**frame,"bounds":[minx-margin,miny-margin,maxx+margin,maxy+margin]}
                local_manifest=render_source_frame(extracted=extracted,frame=local_frame,source_hash=source_hash,
                                                   cache_dir=cache_dir,width_px=1400)
                local_transform=RenderTransform(*local_manifest["transform"]["cad_bounds"],
                                                *local_manifest["transform"]["pixel_size"],
                                                local_manifest["transform"]["padding_px"])
                local_regions=_region_rows(unresolved_after,local_transform)
                events.append({"stage":RecoveryStage.LOCAL_AMBIGUITY_RENDERING.value,"frame_id":frame["frame_id"]})
                second=adapter.analyze(image_path=local_manifest["image_path"],frame_id=frame["frame_id"],regions=local_regions,
                                       context={"source_sha256":source_hash,"render_cache_key":local_manifest["cache_key"],
                                                "scope":"LOCAL"})
                calls.append({"scope":"LOCAL","frame_id":frame["frame_id"],"region_count":len(local_regions),
                              "image_cache_key":local_manifest["cache_key"],"vision_space_count":len(second["physical_spaces"]),
                              "provider_call":dict(getattr(adapter,"last_call_metadata",{}) or {})})
                analyses.append({"scope":"LOCAL","frame_id":frame["frame_id"],"analysis":second,
                                 "render_hash":local_manifest["cache_key"]})
                events.append({"stage":RecoveryStage.LOCAL_VISION_ANALYSIS.value,"frame_id":frame["frame_id"]})
                local_fused=reconcile_and_repair(analysis=second,spaces=spaces,transform=local_transform,
                                                 segments=segments or [],source_hash=source_hash,
                                                 tolerance=max(float(tolerance or .001),1e-8))
                repairs.extend(local_fused["repairs"]); portal_candidates.extend(local_fused["portal_candidates"])
                events.extend(({"stage":RecoveryStage.CAD_VISION_RECONCILIATION_2.value,"frame_id":frame["frame_id"]},
                               {"stage":RecoveryStage.TARGETED_TOPOLOGY_REPAIR_2.value,"frame_id":frame["frame_id"],
                                "accepted_repairs":local_fused["accepted_repairs"]},
                               {"stage":RecoveryStage.FINAL_RECONSTRUCTION_RERUN.value,"frame_id":frame["frame_id"]}))
        except VisionRecoveryError as exc:
            events.append({"stage": RecoveryStage.FAILED.value, "frame_id": frame["frame_id"], "error_code": exc.code})
            return {"provider": getattr(adapter,"provider",type(adapter).__name__), "model": getattr(adapter, "model", None), "calls": len(calls),
                    "call_log": calls, "analyses": analyses, "repairs": repairs, "status": "FAILED", "error_code": exc.code,
                    "message": str(exc), "events": events, "policy": "DETERMINISTIC_FIRST_BOUNDED_GLOBAL_THEN_LOCAL",
                    "runtime_seconds": round(time.perf_counter()-started, 6)}
    events.append({"stage": RecoveryStage.FINAL_COMPLETENESS_GATE.value})
    return {"provider": getattr(adapter,"provider",type(adapter).__name__), "model": getattr(adapter, "model", None), "calls": len(calls),
            "call_log": calls, "analyses": analyses, "repairs": repairs, "portal_candidates":portal_candidates,
            "vision_repairs_proposed":len(repairs),"vision_repairs_accepted":sum(row["accepted"] for row in repairs),
            "vision_repairs_rejected":sum(not row["accepted"] for row in repairs),
            "status": "COMPLETE", "events": events,
            "policy": "DETERMINISTIC_FIRST_BOUNDED_GLOBAL_THEN_LOCAL", "prompt_version": PROMPT_VERSION,
            "fusion_version": FUSION_VERSION, "runtime_seconds": round(time.perf_counter()-started, 6)}
