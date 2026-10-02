"""Read-only independent validation for Planha Canonical Architecture v2."""
from __future__ import annotations

from copy import deepcopy
import math
import re

from shapely.geometry import Polygon

from .architecture_contract import ORIGINS, SCHEMA, STATUSES, content_hash


VALIDATOR_ID = "planha.architecture-validator"
VALIDATOR_VERSION = "1.0.0"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _add(collection, code, **context):
    collection.append({"code": code, **context})


def _polygon(points, holes=None):
    try:
        polygon = Polygon(points or [], holes or [])
        finite = all(math.isfinite(float(v)) for point in (points or []) for v in point)
        return polygon if finite else None
    except Exception:
        return None


def _unique(rows, key, errors, code):
    seen = set()
    for row in rows:
        value = row.get(key)
        if not value:
            _add(errors, "MISSING_ID", field=key)
        elif value in seen:
            _add(errors, code, identifier=value)
        seen.add(value)
    return seen


def _authority_valid(row, errors, entity_id):
    authority = row.get("authority") or {}
    if authority.get("status") not in STATUSES:
        _add(errors, "UNKNOWN_AUTHORITY_STATUS", entity_id=entity_id, value=authority.get("status"))
    origins = authority.get("origins") or []
    unknown = sorted(set(origins) - ORIGINS)
    if unknown:
        _add(errors, "UNKNOWN_AUTHORITY_ORIGIN", entity_id=entity_id, origins=unknown)
    if set(origins) == {"VISION_SUPPORT_ONLY"} and any(authority.get(key) for key in
            ("material_geometry", "wall", "portal", "access", "routing", "release")):
        _add(errors, "VISION_ONLY_AUTHORITY_FORBIDDEN", entity_id=entity_id)


def validate_architecture(model):
    """Validate without mutation; critical failures always dominate status."""
    before = content_hash(model)
    data = deepcopy(model)
    hard = []; required = []; warnings = []; controls = []

    def control(control_id, passed, severity="HARD", detail=None):
        controls.append({"control_id": control_id, "status": "PASS" if passed else severity,
                         "detail": detail})

    if data.get("schema") != SCHEMA:
        _add(hard, "SCHEMA_MISMATCH", expected=SCHEMA, actual=data.get("schema"))
    source = data.get("source") or {}
    source_sha = source.get("source_sha256")
    if not isinstance(source_sha, str) or not SHA256_RE.fullmatch(source_sha):
        _add(hard, "SOURCE_SHA256_MISSING_OR_INVALID")
    if source.get("source_revision_identity") != source_sha:
        _add(hard, "SOURCE_REVISION_IDENTITY_MISMATCH")
    if source.get("effective_scale") is None:
        _add(required, "EFFECTIVE_SCALE_REQUIRED")
    if (source.get("adapter") or {}).get("adapter_id") is None:
        _add(hard, "ADAPTER_IDENTITY_MISSING")
    linear_tolerance = max(1e-9, abs(float(source.get("effective_scale") or 1.0)) * 1e-7)
    control("SOURCE_IDENTITY", not any(x["code"].startswith("SOURCE_") for x in hard))

    frames = data.get("frames") or []; levels = data.get("levels") or []
    walls = data.get("walls") or []; spaces = data.get("physical_spaces") or []
    zones = data.get("functional_zones") or []; apertures = data.get("apertures") or []
    portals = data.get("portals") or []; voids = data.get("voids") or []
    dimensions = data.get("dimensions") or []
    frame_ids = _unique(frames, "frame_id", hard, "DUPLICATE_FRAME_ID")
    level_ids = _unique(levels, "level_id", hard, "DUPLICATE_LEVEL_ID")
    wall_ids = _unique(walls, "wall_id", hard, "DUPLICATE_WALL_ID")
    space_ids = _unique(spaces, "physical_space_id", hard, "DUPLICATE_PHYSICAL_SPACE_ID")
    zone_ids = _unique(zones, "zone_id", hard, "DUPLICATE_FUNCTIONAL_ZONE_ID")
    aperture_ids = _unique(apertures, "aperture_id", hard, "DUPLICATE_APERTURE_ID")
    void_ids = _unique(voids, "void_id", hard, "DUPLICATE_VOID_ID")
    opening_ids = _unique(portals, "opening_id", hard, "DUPLICATE_OPENING_ID")
    verified_portal_ids = {p.get("portal_id") for p in portals if p.get("status") == "VERIFIED" and p.get("portal_id")}
    control("IDENTITY_UNIQUENESS", not any(x["code"].startswith("DUPLICATE_") for x in hard))

    for frame in frames:
        if frame.get("level_id") not in level_ids:
            _add(required, "FRAME_LEVEL_UNRESOLVED", frame_id=frame.get("frame_id"))
    for wall in walls:
        wid = wall.get("wall_id"); _authority_valid(wall, hard, wid)
        if wall.get("frame_id") not in frame_ids:
            _add(hard, "WALL_FRAME_REFERENCE_INVALID", wall_id=wid)
        centerline = wall.get("centerline") or []
        if len(centerline) < 2 or any(not math.isfinite(float(v)) for p in centerline for v in p):
            _add(hard, "WALL_GEOMETRY_INVALID", wall_id=wid)
        if not wall.get("source_handles"):
            _add(required, "WALL_SOURCE_PROVENANCE_REQUIRED", wall_id=wid)
        if (wall.get("authority") or {}).get("material_geometry") and "VISION_SUPPORT_ONLY" in (wall.get("authority") or {}).get("origins", []):
            _add(hard, "UNSUPPORTED_MATERIAL_GEOMETRY_AUTHORITY", wall_id=wid)

    space_polygons = {}
    for space in spaces:
        sid = space.get("physical_space_id"); _authority_valid(space, hard, sid)
        polygon = _polygon(space.get("polygon"), space.get("interior_rings"))
        if polygon is None or not polygon.is_valid or polygon.area <= 0:
            _add(hard, "PHYSICAL_SPACE_POLYGON_INVALID", physical_space_id=sid); continue
        space_polygons[sid] = polygon
        if space.get("frame_id") not in frame_ids:
            _add(hard, "SPACE_FRAME_REFERENCE_INVALID", physical_space_id=sid)
        for hole in space.get("interior_rings") or []:
            hole_poly = _polygon(hole)
            if hole_poly is None or not polygon.envelope.covers(hole_poly):
                _add(hard, "SPACE_INTERIOR_RING_INVALID", physical_space_id=sid)
    ordered = sorted(space_polygons)
    overlap = 0.0
    for index, left_id in enumerate(ordered):
        for right_id in ordered[index + 1:]:
            left = space_polygons[left_id]; right = space_polygons[right_id]
            if next((s.get("frame_id") for s in spaces if s.get("physical_space_id") == left_id), None) != next(
                    (s.get("frame_id") for s in spaces if s.get("physical_space_id") == right_id), None):
                continue
            area = left.intersection(right).area
            overlap += area
            overlap_tolerance = linear_tolerance * max(left.length, right.length, 1.0)
            if area > overlap_tolerance:
                _add(hard, "ILLEGAL_PHYSICAL_SPACE_OVERLAP", space_a=left_id, space_b=right_id, area=area)
    control("PHYSICAL_SPACE_GEOMETRY", not any("SPACE" in x["code"] and x["code"] != "FRAME_LEVEL_UNRESOLVED" for x in hard))

    for zone in zones:
        zid = zone.get("zone_id"); _authority_valid(zone, hard, zid)
        if zone.get("physical_space_id") not in space_ids:
            _add(hard, "FUNCTIONAL_ZONE_SPACE_REFERENCE_INVALID", zone_id=zid)
        if zone.get("boundary_status") == "approximate" and ((zone.get("authority") or {}).get("material_geometry") or zone.get("polygon")):
            _add(hard, "APPROXIMATE_ZONE_MATERIAL_AUTHORITY_FORBIDDEN", zone_id=zid)

    for aperture in apertures:
        if aperture.get("host_wall_ids") and not set(aperture["host_wall_ids"]).issubset(wall_ids):
            _add(hard, "APERTURE_WALL_REFERENCE_INVALID", aperture_id=aperture.get("aperture_id"))

    portal_by_id = {}
    for portal in portals:
        oid = portal.get("opening_id"); pid = portal.get("portal_id"); _authority_valid(portal, hard, oid)
        if pid: portal_by_id[pid] = portal
        if portal.get("status") != "VERIFIED":
            continue
        if portal.get("host_wall_id") not in wall_ids:
            _add(hard, "PORTAL_HOST_WALL_INVALID", opening_id=oid)
        if not portal.get("host_aperture_id") or portal.get("host_aperture_id") not in aperture_ids:
            _add(hard, "PORTAL_HOST_APERTURE_INVALID", opening_id=oid)
        sides = [portal.get("space_a"), portal.get("space_b")]
        if any(side != "EXTERIOR" and side not in space_ids for side in sides):
            _add(hard, "PORTAL_SIDE_REFERENCE_INVALID", opening_id=oid)
        referenced_frames = {next((s.get("frame_id") for s in spaces if s.get("physical_space_id") == side), None)
                             for side in sides if side != "EXTERIOR"}
        if len(referenced_frames) > 1:
            _add(hard, "CROSS_LEVEL_PORTAL_FORBIDDEN", opening_id=oid)
        if portal.get("type") == "WINDOW" and (portal.get("authority") or {}).get("access"):
            _add(hard, "WINDOW_ACCESS_AUTHORITY_FORBIDDEN", opening_id=oid)

    void_polygons = {}
    for void in voids:
        vid = void.get("void_id"); _authority_valid(void, hard, vid)
        polygon = _polygon(void.get("boundary"))
        if polygon is None or not polygon.is_valid or polygon.area <= 0:
            _add(hard, "VOID_GEOMETRY_INVALID", void_id=vid); continue
        void_polygons[vid] = polygon
        if not void.get("source_handles"):
            _add(hard, "VOID_SOURCE_GEOMETRY_REQUIRED", void_id=vid)
        origins = (void.get("authority") or {}).get("origins") or []
        if set(origins).issubset({"SOURCE_SEMANTIC", "VISION_SUPPORT_ONLY"}):
            _add(hard, "LABEL_OR_VISION_DERIVED_VOID_FORBIDDEN", void_id=vid)
        for sid, space_polygon in space_polygons.items():
            area = polygon.intersection(space_polygon).area
            overlap_tolerance = linear_tolerance * max(polygon.length, space_polygon.length, 1.0)
            if area > overlap_tolerance:
                _add(hard, "VOID_OCCUPIED_SPACE_OVERLAP", void_id=vid, physical_space_id=sid, area=area)

    access_edges = (data.get("graphs") or {}).get("access") or []
    for edge in access_edges:
        pid = edge.get("portal_id") if isinstance(edge, dict) else None
        portal = portal_by_id.get(pid)
        if portal is None or pid not in verified_portal_ids:
            _add(hard, "ACCESS_EDGE_PORTAL_REFERENCE_INVALID", portal_id=pid)
            continue
        if portal.get("type") == "WINDOW":
            _add(hard, "WINDOW_ACCESS_EDGE_FORBIDDEN", portal_id=pid)
        if not edge.get("gap_id") or not edge.get("host_wall_id") or not edge.get("source_handles"):
            _add(hard, "ACCESS_EDGE_PROVENANCE_MISSING", portal_id=pid)
    for edge in (data.get("graphs") or {}).get("enclosure") or []:
        refs = edge if isinstance(edge, list) else [edge.get("space_a"), edge.get("space_b")]
        if any(ref not in space_ids and ref != "EXTERIOR" for ref in refs):
            _add(hard, "ENCLOSURE_GRAPH_REFERENCE_INVALID", edge=edge)

    for dimension in dimensions:
        did = dimension.get("dimension_id")
        if dimension.get("association_status") == "VERIFIED" and not dimension.get("semantic_association"):
            _add(hard, "DIMENSION_FALSE_VERIFIED_ASSOCIATION", dimension_id=did)
        _authority_valid(dimension, hard, did)

    review = data.get("review_registry") or {}
    if review.get("stale_review_decisions"):
        for row in review.get("stale_review_decisions"):
            if row.get("review_authority"):
                _add(hard, "STALE_REVIEW_AUTHORITY_FORBIDDEN", question_id=row.get("question_id"))
    if data.get("release", {}).get("status") == "INPUT_REQUIRED":
        _add(required, "ARCHITECTURE_RELEASE_INPUT_REQUIRED")
    if data.get("canonical_model_hash"):
        supplied = data["canonical_model_hash"]
        candidate = deepcopy(data); candidate.pop("canonical_model_hash", None)
        if supplied != content_hash(candidate):
            _add(hard, "CANONICAL_MODEL_HASH_MISMATCH")

    after = content_hash(model)
    if before != after:
        _add(hard, "VALIDATOR_MUTATED_INPUT")
    if hard:
        status = "FAIL"
    elif required:
        status = "INPUT_REQUIRED"
    elif data.get("release", {}).get("status") == "CONFLICT":
        status = "CONFLICT"
    elif data.get("release", {}).get("status") == "INPUT_REQUIRED":
        status = "INPUT_REQUIRED"
    else:
        status = "PASS"
    return {"schema": "planha-architecture-validation-report/1.0",
            "validator_id": VALIDATOR_ID, "validator_version": VALIDATOR_VERSION,
            "status": status, "hard_errors": hard, "input_requirements": required,
            "warnings": warnings, "control_results": controls,
            "metrics": {"physical_spaces": len(spaces), "walls": len(walls), "portals": len(portals),
                        "voids": len(voids), "illegal_overlap_area": overlap,
                        "hard_error_count": len(hard), "input_requirement_count": len(required)},
            "critical_score_masking": False, "input_hash_before": before, "input_hash_after": after,
            "report_hash": content_hash({"hard_errors": hard, "input_requirements": required,
                                         "warnings": warnings, "control_results": controls})}
