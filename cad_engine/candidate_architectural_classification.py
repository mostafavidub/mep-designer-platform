"""Candidate-driven architectural topology classification.

All geometry in this module is supplied by CAD or a deterministic candidate
generator.  A multimodal provider may classify the stable IDs, but can never
return, move, or create geometry.
"""
from __future__ import annotations

from hashlib import sha256
from itertools import combinations
from typing import Any
import json
import math

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union


REGION_ROLES = {
    "BUILDING_INTERIOR", "SITE_EXTERIOR", "YARD", "SEMI_EXTERIOR",
    "TERRACE", "BALCONY", "COURTYARD", "LIGHTWELL", "VOID", "STAIR",
    "SHAFT", "UNKNOWN",
}
BOUNDARY_ROLES = {
    "BUILDING_SHELL", "INTERIOR_SEPARATOR", "SITE_SEPARATOR",
    "VOID_BOUNDARY", "OPEN_PLAN_TRANSITION", "NOT_ARCHITECTURAL_BOUNDARY",
    "UNKNOWN",
}
EXTERIOR_REGION_ROLES = {
    "SITE_EXTERIOR", "YARD", "SEMI_EXTERIOR", "TERRACE", "BALCONY",
    "COURTYARD", "LIGHTWELL", "VOID",
}
CANDIDATE_KEYS = {"frame_id", "regions", "boundaries", "bridge_decisions"}


class CandidateClassificationError(ValueError):
    def __init__(self, code: str, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _stable_id(prefix: str, value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    # A 40-bit content suffix is compact enough to remain legible on the
    # authoritative overlay while retaining negligible collision risk for the
    # bounded (<= 160 item) candidate set.
    return f"{prefix}-" + sha256(raw.encode()).hexdigest()[:10].upper()


def _normalized_line(points: list[list[float]], precision: int = 8) -> list[list[float]]:
    ends = [[round(float(v), precision) for v in point[:2]] for point in (points[0], points[-1])]
    return sorted(ends)


def candidate_classification_schema(*, region_ids: list[str], boundary_ids: list[str], ambiguity_options: dict[str, list[str]]) -> dict:
    """Return a strict, ID-only schema.  It intentionally contains no point type."""
    region_enum = sorted(set(region_ids)) or ["NO_REGION_CANDIDATES"]
    boundary_enum = sorted(set(boundary_ids)) or ["NO_BOUNDARY_CANDIDATES"]
    ambiguity_enum = sorted(ambiguity_options) or ["NO_BRIDGE_AMBIGUITIES"]
    option_enum = sorted({option for values in ambiguity_options.values() for option in values} | {"UNKNOWN"})
    region_item = {"type": "object", "additionalProperties": False,
        "required": ["region_id", "role", "confidence", "evidence", "uncertainty"],
        "properties": {"region_id": {"type": "string", "enum": region_enum},
            "role": {"type": "string", "enum": sorted(REGION_ROLES)},
            "confidence": {"type": "number"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "uncertainty": {"type": "string"}}}
    boundary_item = {"type": "object", "additionalProperties": False,
        "required": ["boundary_id", "role", "confidence", "evidence"],
        "properties": {"boundary_id": {"type": "string", "enum": boundary_enum},
            "role": {"type": "string", "enum": sorted(BOUNDARY_ROLES)},
            "confidence": {"type": "number"},
            "evidence": {"type": "array", "items": {"type": "string"}}}}
    bridge_item = {"type": "object", "additionalProperties": False,
        "required": ["ambiguity_id", "selected_option", "confidence", "evidence"],
        "properties": {"ambiguity_id": {"type": "string", "enum": ambiguity_enum},
            "selected_option": {"type": "string", "enum": option_enum},
            "confidence": {"type": "number"},
            "evidence": {"type": "array", "items": {"type": "string"}}}}
    return {"type": "object", "additionalProperties": False,
        "required": sorted(CANDIDATE_KEYS), "properties": {
            "frame_id": {"type": "string"},
            "regions": {"type": "array", "items": region_item},
            "boundaries": {"type": "array", "items": boundary_item},
            "bridge_decisions": {"type": "array", "items": bridge_item}}}


def validate_candidate_classification(payload: dict, graph: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) != CANDIDATE_KEYS:
        raise CandidateClassificationError("CANDIDATE_SCHEMA_INVALID", "Candidate response has invalid root fields")
    if payload.get("frame_id") != graph.get("frame_id"):
        raise CandidateClassificationError("CANDIDATE_FRAME_MISMATCH", "Candidate response frame does not match")
    supplied_regions = {row["region_id"] for row in graph.get("regions") or []}
    supplied_boundaries = {row["boundary_id"] for row in graph.get("boundaries") or []}
    supplied_ambiguities = {row["ambiguity_id"]: {option["option_id"] for option in row["options"]}
                            | {"NO_BOUNDARY", "UNKNOWN"} for row in graph.get("bridges") or []}
    seen = set()
    for row in payload.get("regions") or []:
        if set(row) != {"region_id", "role", "confidence", "evidence", "uncertainty"}:
            raise CandidateClassificationError("CANDIDATE_SCHEMA_INVALID", "Region response has invalid fields")
        if row["region_id"] not in supplied_regions or row["region_id"] in seen:
            raise CandidateClassificationError("UNKNOWN_CANDIDATE_ID", "Unknown or duplicate region ID")
        if row["role"] not in REGION_ROLES or not 0 <= float(row["confidence"]) <= 1:
            raise CandidateClassificationError("CANDIDATE_VALUE_INVALID", "Invalid region classification")
        seen.add(row["region_id"])
    seen.clear()
    for row in payload.get("boundaries") or []:
        if set(row) != {"boundary_id", "role", "confidence", "evidence"}:
            raise CandidateClassificationError("CANDIDATE_SCHEMA_INVALID", "Boundary response has invalid fields")
        if row["boundary_id"] not in supplied_boundaries or row["boundary_id"] in seen:
            raise CandidateClassificationError("UNKNOWN_CANDIDATE_ID", "Unknown or duplicate boundary ID")
        if row["role"] not in BOUNDARY_ROLES or not 0 <= float(row["confidence"]) <= 1:
            raise CandidateClassificationError("CANDIDATE_VALUE_INVALID", "Invalid boundary classification")
        seen.add(row["boundary_id"])
    seen.clear()
    for row in payload.get("bridge_decisions") or []:
        if set(row) != {"ambiguity_id", "selected_option", "confidence", "evidence"}:
            raise CandidateClassificationError("CANDIDATE_SCHEMA_INVALID", "Bridge response has invalid fields")
        identity = row["ambiguity_id"]
        if identity not in supplied_ambiguities or identity in seen or row["selected_option"] not in supplied_ambiguities[identity]:
            raise CandidateClassificationError("UNKNOWN_CANDIDATE_ID", "Unknown bridge ambiguity or option")
        if not 0 <= float(row["confidence"]) <= 1:
            raise CandidateClassificationError("CANDIDATE_VALUE_INVALID", "Invalid bridge confidence")
        seen.add(identity)
    return payload


def _candidate_regions(model: dict, frame_id: str) -> list[dict]:
    source = (model.get("plan_regions") or {}).get("regions") or []
    rows = []
    for item in source:
        if item.get("frame_id") != frame_id:
            continue
        polygon = Polygon(item.get("geometry") or [])
        if not polygon.is_valid or polygon.area <= 0:
            continue
        identity = _stable_id("R", [frame_id, list(polygon.exterior.coords)])
        rows.append({"region_id": identity, "polygon": [list(p) for p in polygon.exterior.coords],
                     "centroid": [polygon.centroid.x, polygon.centroid.y], "area": polygon.area,
                     "source_provenance": {"type": "PLAN_REGION_GRAPH", "source_region_id": item.get("region_id"),
                                           "candidate_id": item.get("candidate_id")},
                     "exact_text_evidence": [], "object_evidence": []})
    rows.sort(key=lambda row: (-row["area"], row["region_id"]))
    return rows


def _bind_independent_evidence(regions: list[dict], *, texts: list[dict], objects: list[dict]) -> None:
    geometries = [(row, Polygon(row["polygon"])) for row in regions]
    for text in texts:
        point = text.get("point")
        if not point:
            continue
        hosts = [(row, poly) for row, poly in geometries if poly.covers(Point(point))]
        if len(hosts) == 1:
            hosts[0][0]["exact_text_evidence"].append({"text": text.get("text"), "source_handle": text.get("handle")})
    for obj in objects:
        point = obj.get("point")
        if not point:
            continue
        hosts = [(row, poly) for row, poly in geometries if poly.covers(Point(point))]
        if len(hosts) == 1:
            hosts[0][0]["object_evidence"].append({"kind": obj.get("kind") or obj.get("name") or "UNKNOWN",
                                                   "source_handle": obj.get("handle")})


def _candidate_boundaries(regions: list[dict], walls: list[dict], tolerance: float) -> list[dict]:
    wall_lines = [(wall, LineString(wall["centerline"])) for wall in walls if len(wall.get("centerline") or []) >= 2]
    records: dict[tuple, dict] = {}
    polygons = [(row, Polygon(row["polygon"])) for row in regions]
    for row, polygon in polygons:
        coords = list(polygon.exterior.coords)
        for a, b in zip(coords, coords[1:]):
            line = LineString([a, b])
            adjacent = [other["region_id"] for other, other_poly in polygons
                        if other["region_id"] != row["region_id"]
                        and other_poly.boundary.intersection(line).length > max(tolerance, line.length * .8)]
            key = tuple(tuple(p) for p in _normalized_line([a, b]))
            support = [wall for wall, wall_line in wall_lines if wall_line.distance(line) <= max(tolerance * 4, 1e-7)
                       and wall_line.intersection(line.buffer(max(tolerance * 3, line.length * .002))).length > line.length * .35]
            current = records.setdefault(key, {"boundary_id": _stable_id("B", [row.get("frame_id"), key]),
                "geometry": [list(a), list(b)], "source_type": "PLAN_REGION_EDGE",
                "adjacent_region_ids": set(), "cad_authority": "CAD_CONFIRMED" if support else "CANDIDATE_ONLY",
                "support_handles": set(), "wall_ids": set()})
            current["adjacent_region_ids"].add(row["region_id"])
            current["adjacent_region_ids"].update(adjacent)
            for wall in support:
                current["support_handles"].update(wall.get("source_handles") or [])
                current["wall_ids"].add(wall["wall_id"])
    result = []
    for row in records.values():
        result.append({**row, "adjacent_region_ids": sorted(row["adjacent_region_ids"]),
                       "support_handles": sorted(row["support_handles"]), "wall_ids": sorted(row["wall_ids"])})
    return sorted(result, key=lambda row: row["boundary_id"])


def _bridge_candidates(boundaries: list[dict], *, tolerance: float, max_candidates: int = 12) -> list[dict]:
    endpoints = []
    for row in boundaries:
        line = LineString(row["geometry"])
        if row["cad_authority"] == "CAD_CONFIRMED":
            endpoints.append((row, tuple(line.coords[0]), tuple(line.coords[-1])))
            endpoints.append((row, tuple(line.coords[-1]), tuple(line.coords[0])))
    proposals = []
    max_gap = max(tolerance * 40, 1e-5)
    for (left, point_a, other_a), (right, point_b, other_b) in combinations(endpoints, 2):
        if left["boundary_id"] == right["boundary_id"]:
            continue
        gap = math.dist(point_a, point_b)
        if gap <= tolerance or gap > max_gap:
            continue
        va = (point_a[0] - other_a[0], point_a[1] - other_a[1])
        vb = (point_b[0] - other_b[0], point_b[1] - other_b[1])
        bridge = (point_b[0] - point_a[0], point_b[1] - point_a[1])
        def alignment(vector):
            size = max(math.hypot(*vector) * max(gap, 1e-12), 1e-12)
            return abs((vector[0] * bridge[0] + vector[1] * bridge[1]) / size)
        if max(alignment(va), alignment(vb)) < .985:
            continue
        option_id = _stable_id("BRIDGE", [left["boundary_id"], right["boundary_id"], point_a, point_b])
        proposals.append({"ambiguity_id": _stable_id("A", [point_a, point_b]), "options": [
            {"option_id": option_id, "geometry": [list(point_a), list(point_b)],
             "material_geometry": "NONE", "evidence": ["ALIGNED_CAD_ENDPOINTS"]},
            {"option_id": "NO_BOUNDARY", "geometry": [], "material_geometry": "NONE", "evidence": []}],
            "status": "AMBIGUOUS"})
    proposals.sort(key=lambda row: row["ambiguity_id"])
    return proposals[:max_candidates]


def build_candidate_graph(model: dict, *, frame_id: str, max_regions: int = 60,
                          max_boundaries: int = 160, max_bridges: int = 12) -> dict:
    frame = next((row for row in model.get("frames") or [] if row.get("frame_id") == frame_id), None)
    if not frame:
        raise CandidateClassificationError("FRAME_NOT_FOUND", "Requested frame is absent")
    tolerance = float((model.get("diagnostics") or {}).get("adaptive_tolerance") or 1e-6)
    regions = _candidate_regions(model, frame_id)
    _bind_independent_evidence(regions, texts=model.get("all_texts") or [], objects=model.get("architectural_objects") or [])
    walls = [row for row in model.get("canonical_walls") or [] if row.get("frame_id") == frame_id]
    boundaries = _candidate_boundaries(regions, walls, tolerance)
    bridges = _bridge_candidates(boundaries, tolerance=tolerance, max_candidates=max_bridges)
    frame_polygon = box(*frame["bounds"])
    union = unary_union([Polygon(row["polygon"]) for row in regions]) if regions else Polygon()
    coverage = union.area / max(frame_polygon.area, 1e-12)
    largest = max((row["area"] for row in regions), default=0) / max(frame_polygon.area, 1e-12)
    reasons = []
    if len(regions) < 2: reasons.append("TOO_FEW_REGION_CANDIDATES")
    if len(regions) > max_regions: reasons.append("REGION_SET_NOT_BOUNDED")
    if len(boundaries) > max_boundaries: reasons.append("BOUNDARY_SET_NOT_BOUNDED")
    if coverage < .20: reasons.append("INSUFFICIENT_FRAME_REGION_COVERAGE")
    if largest < .01: reasons.append("NO_MAJOR_PLAN_REGION")
    if not any(row["exact_text_evidence"] or row["object_evidence"] for row in regions):
        reasons.append("NO_INDEPENDENT_SEMANTIC_EVIDENCE_HOSTED")
    return {"schema": "candidate-architectural-topology/1.0", "frame_id": frame_id,
            "source_sha256": (model.get("source") or {}).get("source_sha256"),
            "frame_bounds": frame["bounds"], "regions": regions, "boundaries": boundaries,
            "bridges": bridges, "metrics": {"frame_area": frame_polygon.area,
                "candidate_union_area": union.area, "candidate_frame_coverage": coverage,
                "largest_region_frame_ratio": largest, "region_count": len(regions),
                "boundary_count": len(boundaries), "bridge_count": len(bridges)},
            "provider_eligible": not reasons, "status": "PASS" if not reasons else "FASIHI_CANDIDATE_GRAPH_INSUFFICIENT",
            "blocking_reasons": reasons}


def fuse_region_classifications(graph: dict, payload: dict) -> dict:
    validate_candidate_classification(payload, graph)
    classified = {row["region_id"]: row for row in payload["regions"]}
    fused = []
    conflicts = []
    for region in graph["regions"]:
        vision = classified.get(region["region_id"])
        if not vision:
            fused.append({"region_id": region["region_id"], "role": "UNKNOWN", "authority": "UNRESOLVED"})
            continue
        text = " ".join((item.get("text") or "") for item in region["exact_text_evidence"])
        label_yard = any(value in text for value in ("حیاط", "yard"))
        contradiction = label_yard and vision["role"] == "BUILDING_INTERIOR"
        if contradiction:
            conflicts.append({"region_id": region["region_id"], "code": "EXACT_LABEL_ROLE_CONFLICT"})
        independent = bool(region["exact_text_evidence"] or region["object_evidence"])
        authority = "MULTI_EVIDENCE_SUPPORTED" if independent and not contradiction else "UNRESOLVED"
        fused.append({"region_id": region["region_id"], "role": vision["role"], "authority": authority,
                      "vision_confidence": vision["confidence"], "independent_support": independent,
                      "conflict": contradiction})
    return {"frame_id": graph["frame_id"], "regions": fused, "conflicts": conflicts,
            "status": "CONFLICT" if conflicts else "PASS"}


def derive_shell_candidates(graph: dict, fusion: dict) -> dict:
    roles = {row["region_id"]: row for row in fusion.get("regions") or []}
    shell = []
    unresolved = []
    for boundary in graph.get("boundaries") or []:
        adjacent = [roles.get(identity) for identity in boundary["adjacent_region_ids"]]
        adjacent = [row for row in adjacent if row]
        role_set = {row["role"] for row in adjacent}
        supported = all(row["authority"] == "MULTI_EVIDENCE_SUPPORTED" for row in adjacent)
        if "BUILDING_INTERIOR" in role_set and role_set & EXTERIOR_REGION_ROLES and supported:
            shell.append({**boundary, "role": "BUILDING_SHELL", "authority": "MULTI_EVIDENCE_INFERRED_TOPOLOGY",
                          "material_geometry": "PHYSICAL_WALL" if boundary["cad_authority"] == "CAD_CONFIRMED" else "NONE"})
        elif (role_set == {"BUILDING_INTERIOR"} and len(adjacent) == 1 and supported
              and boundary["cad_authority"] == "CAD_CONFIRMED"):
            shell.append({**boundary, "role": "BUILDING_SHELL", "authority": "CAD_CONFIRMED",
                          "material_geometry": "PHYSICAL_WALL"})
        elif "BUILDING_INTERIOR" in role_set and (len(adjacent) < 2 or "UNKNOWN" in role_set or not supported):
            unresolved.append(boundary["boundary_id"])
    return {"frame_id": graph["frame_id"], "shell_boundaries": shell,
            "unresolved_boundary_ids": sorted(unresolved),
            "status": "PASS" if shell and not unresolved else "INPUT_REQUIRED"}
