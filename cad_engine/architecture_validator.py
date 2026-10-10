"""Read-only independent validation for Planha Canonical Architecture v2."""
from __future__ import annotations

from copy import deepcopy
import math
import re

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from .architecture_contract import ORIGINS, SCHEMA, STATUSES, canonical_model_hash, content_hash
from .architecture_text_evidence import CONTRACT_VERSION as TEXT_CONTRACT_VERSION, validate_text_contract
from .architecture_structural_obstacles import canonical_column_ring, column_content_fingerprint


VALIDATOR_ID = "planha.architecture-validator"
VALIDATOR_VERSION = "1.0.0"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_validator_report_integrity(report, expected_input_hash=None):
    candidate = deepcopy(report)
    supplied = candidate.pop("report_hash", None)
    errors = []
    if supplied != content_hash(candidate):
        errors.append("VALIDATOR_REPORT_HASH_INVALID")
    if expected_input_hash and report.get("input_hash_before") != expected_input_hash:
        errors.append("VALIDATOR_REPORT_INPUT_MISMATCH")
    if report.get("input_hash_before") != report.get("input_hash_after"):
        errors.append("VALIDATOR_REPORT_MUTATION_DETECTED")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors}


def _add(collection, code, **context):
    collection.append({"code": code, **context})


def _polygon(points, holes=None):
    try:
        polygon = Polygon(points or [], holes or [])
        finite = all(math.isfinite(float(v)) for ring in [points or []] + list(holes or [])
                     for point in ring for v in point)
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
    grants = ("material_geometry", "wall", "portal", "access", "routing", "release")
    if authority.get("status") in {"AMBIGUOUS", "INPUT_REQUIRED", "CONFLICT", "REJECTED"} and any(
            authority.get(key) for key in grants):
        _add(errors, "UNRESOLVED_ENGINEERING_AUTHORITY_FORBIDDEN", entity_id=entity_id,
             status=authority.get("status"))
    entity_status = row.get("status") or row.get("topology_status") or row.get("geometry_status") or row.get("semantic_status")
    if row.get("physical_space_id") and not row.get("zone_id"):
        entity_status = row.get("independent_space_status") or (row.get("geometry_evidence") or {}).get("separator_status", "INPUT_REQUIRED")
    if entity_status in STATUSES and authority.get("status") != entity_status:
        _add(errors, "ENTITY_AUTHORITY_STATUS_MISMATCH", entity_id=entity_id,
             entity_status=entity_status, authority_status=authority.get("status"))


def _source_roles(row):
    """Read explicit classifications and contradictory evidence, not labels."""
    roles = set()
    def collect(value):
        if isinstance(value, str):
            roles.update(re.findall(r"[A-Z][A-Z0-9_]*", value.upper()))
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for key in ("role", "source_role", "classification", "code", "reason", "evidence"):
                collect(value.get(key))
    for key in ("source_roles", "classifications", "source_role", "negative_evidence", "frame_type", "role"):
        collect(row.get(key))
    return roles


def _physical_boundary_valid(space, polygon, errors, tolerance, scale):
    sid = space.get("physical_space_id")
    authority = space.get("authority") or {}
    verified = space.get("geometry_status", space.get("status", authority.get("status"))) == "VERIFIED"
    if not (verified or authority.get("material_geometry")):
        return
    role = space.get("candidate_role") or (space.get("geometry_evidence") or {}).get("candidate_role")
    if role in {"PARENT_CONTAINER", "BUILDING_ENVELOPE", "INVALID_DIAGNOSTIC", "OVERLAPPING_UNRESOLVED", "REPEATED_CELL_ARRAY", "MATERIAL_INTERIOR_CONFLICT", "WALL_MATERIAL_CONFLICT"}:
        _add(errors, "NON_PHYSICAL_CANDIDATE_AUTHORITY_FORBIDDEN", physical_space_id=sid, candidate_role=role)
    origins = set(authority.get("origins") or [])
    if not origins.intersection({"SOURCE_GEOMETRIC", "SOURCE_EXPLICIT"}):
        _add(errors, "SEMANTIC_ONLY_PHYSICAL_GEOMETRY_FORBIDDEN", physical_space_id=sid)
    geometry = space.get("geometry_evidence")
    if not space.get("source_handles"):
        _add(errors, "PHYSICAL_BOUNDARY_SOURCE_REQUIRED", physical_space_id=sid)
    if geometry is None:
        return  # Legacy source-backed canonical geometry predates the evidence extension.
    if not isinstance(geometry, dict) or geometry.get("status") != "VERIFIED" or not geometry.get("source_handles"):
        _add(errors, "PHYSICAL_BOUNDARY_EVIDENCE_UNSUPPORTED", physical_space_id=sid)
        return
    if geometry.get("negative_evidence") or geometry.get("unresolved_internal_segment_ids"):
        _add(errors, "PHYSICAL_BOUNDARY_EVIDENCE_CONTRADICTORY", physical_space_id=sid)
    if "segments" not in geometry:
        _add(errors, "PHYSICAL_BOUNDARY_EVIDENCE_UNSUPPORTED", physical_space_id=sid)
        return
    # Independently recompute boundary coverage; upstream status cannot prove closure.
    try:
        # Reconstruction already permits four times its maximum .05 m uncertainty.
        # Bound that existing uncertainty independently; a claimed tolerance cannot
        # expand authority beyond the reconstruction contract's .2 m ceiling.
        claimed_tolerance = float(geometry.get("tolerance", tolerance))
        if not math.isfinite(claimed_tolerance) or claimed_tolerance <= 0:
            raise ValueError("invalid tolerance")
        boundary_tolerance = max(tolerance, min(claimed_tolerance, .2 / scale))
        if polygon.buffer(-boundary_tolerance*2).is_empty:
            _add(errors, "PHYSICAL_SPACE_INTERIOR_UNRESOLVABLE", physical_space_id=sid)
        segments = []
        for segment in geometry["segments"]:
            points = segment.get("geometry") if isinstance(segment, dict) else segment
            if len(points) < 2 or any(not math.isfinite(float(v)) for p in points for v in p):
                raise ValueError("invalid segment")
            line = LineString(points)
            if line.length <= 0:
                raise ValueError("degenerate segment")
            segments.append(line)
        supported = bool(segments) and polygon.boundary.difference(
            unary_union(segments).buffer(boundary_tolerance)).length <= tolerance
    except (TypeError, ValueError, AttributeError):
        supported = False
    if not supported:
        _add(errors, "PHYSICAL_BOUNDARY_GEOMETRY_UNSUPPORTED", physical_space_id=sid)


def _review_overlay_valid(row, errors, entity_id, source_sha):
    if row.get("review_status") != "CONFIRMED":
        return
    if row.get("review_authority") != "HUMAN_SOURCE_INTERPRETATION":
        _add(errors, "REVIEW_AUTHORITY_INVALID", entity_id=entity_id)
    traces = row.get("review_trace") or []
    if not traces:
        _add(errors, "REVIEW_TRACE_REQUIRED", entity_id=entity_id)
    for trace in traces:
        if trace.get("source_sha256") != source_sha or not trace.get("review_item_id") or not trace.get("review_fingerprint"):
            _add(errors, "REVIEW_TRACE_IDENTITY_INVALID", entity_id=entity_id)


def validate_architecture(model):
    """Validate without mutation; critical failures always dominate status."""
    before = canonical_model_hash(model)
    representation_before = content_hash(model)
    data = deepcopy(model)
    hard = []; required = []; warnings = []; controls = []
    from .architecture_separator_validator import separator_errors
    for code, entity_id in separator_errors(data):
        _add(hard, code, entity_id=entity_id)
    for space in data.get("physical_spaces") or []:
        separator = (space.get("geometry_evidence") or {}).get("separator_status")
        if separator not in {"VERIFIED", "REJECTED"} and space.get("independent_space_status") != "REJECTED":
            _add(required, "SEPARATOR_ROLE_REQUIRED", physical_space_id=space.get("physical_space_id"))

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

    text_evidence = data.get("text_evidence") or {}
    if text_evidence.get("contract_version") != TEXT_CONTRACT_VERSION:
        _add(hard, "TEXT_CONTRACT_VERSION_MISMATCH",
             expected=TEXT_CONTRACT_VERSION, actual=text_evidence.get("contract_version"))
    for error in validate_text_contract(text_evidence, source_sha256=source_sha):
        _add(hard, error.pop("code"), **error)
    text_ids = {row.get("text_evidence_id") for row in text_evidence.get("items") or []}
    for field in data.get("title_block_fields") or []:
        if field.get("text_evidence_id") not in text_ids:
            _add(hard, "TITLE_FIELD_TEXT_EVIDENCE_REFERENCE_INVALID",
                 title_block_field_id=field.get("title_block_field_id"))
        authority = field.get("authority") or {}
        if any(authority.get(key) for key in ("material_geometry", "engineering_scale", "north")):
            _add(hard, "TITLE_FIELD_ENGINEERING_AUTHORITY_FORBIDDEN",
                 title_block_field_id=field.get("title_block_field_id"))
    control("TEXT_AUTHORITY_INTEGRITY", not any(x["code"].startswith(("TEXT_", "TITLE_FIELD_")) for x in hard))

    frames = data.get("frames") or []; levels = data.get("levels") or []
    walls = data.get("walls") or []; spaces = data.get("physical_spaces") or []
    zones = data.get("functional_zones") or []; apertures = data.get("apertures") or []
    portals = data.get("portals") or []; voids = data.get("voids") or []
    dimensions = data.get("dimensions") or []; structural_obstacles = data.get("structural_obstacles") or []
    frame_ids = _unique(frames, "frame_id", hard, "DUPLICATE_FRAME_ID")
    level_ids = _unique(levels, "level_id", hard, "DUPLICATE_LEVEL_ID")
    wall_ids = _unique(walls, "wall_id", hard, "DUPLICATE_WALL_ID")
    space_ids = _unique(spaces, "physical_space_id", hard, "DUPLICATE_PHYSICAL_SPACE_ID")
    zone_ids = _unique(zones, "zone_id", hard, "DUPLICATE_FUNCTIONAL_ZONE_ID")
    aperture_ids = _unique(apertures, "aperture_id", hard, "DUPLICATE_APERTURE_ID")
    void_ids = _unique(voids, "void_id", hard, "DUPLICATE_VOID_ID")
    opening_ids = _unique(portals, "opening_id", hard, "DUPLICATE_OPENING_ID")
    portal_ids = _unique([row for row in portals if row.get("portal_id")], "portal_id", hard, "DUPLICATE_PORTAL_ID")
    dimension_ids = _unique(dimensions, "dimension_id", hard, "DUPLICATE_DIMENSION_ID")
    obstacle_ids = _unique(structural_obstacles, "structural_obstacle_id", hard,
                           "DUPLICATE_STRUCTURAL_OBSTACLE_ID")
    evidence_ids = _unique(data.get("evidence_registry") or [], "evidence_id", hard, "DUPLICATE_EVIDENCE_ID")
    _unique(data.get("unresolved_items") or [], "unresolved_item_id", hard, "DUPLICATE_UNRESOLVED_ITEM_ID")
    verified_portal_ids = {p.get("portal_id") for p in portals if p.get("status") == "VERIFIED" and p.get("portal_id")}
    control("IDENTITY_UNIQUENESS", not any(x["code"].startswith("DUPLICATE_") for x in hard))

    for frame in frames:
        represented = frame.get("represented_level_ids") or []
        if len(represented) != len(set(represented)):
            _add(hard, "FRAME_REPRESENTED_LEVEL_DUPLICATE", frame_id=frame.get("frame_id"))
        if not set(represented).issubset(level_ids):
            _add(hard, "FRAME_REPRESENTED_LEVEL_REFERENCE_INVALID", frame_id=frame.get("frame_id"))
        if frame.get("primary_level_id") and frame.get("primary_level_id") not in represented:
            _add(hard, "FRAME_PRIMARY_LEVEL_CONTRADICTION", frame_id=frame.get("frame_id"))
        if frame.get("level_relationship") == "TYPICAL" and len(represented) < 2:
            _add(hard, "TYPICAL_FRAME_LEVELS_INSUFFICIENT", frame_id=frame.get("frame_id"))
        if frame.get("level_id") not in level_ids and not represented:
            _add(required, "FRAME_LEVEL_UNRESOLVED", frame_id=frame.get("frame_id"))
    for wall in walls:
        wid = wall.get("wall_id"); _authority_valid(wall, hard, wid)
        frame = next((f for f in frames if f.get("frame_id") == wall.get("frame_id")), {})
        if (wall.get("authority") or {}).get("material_geometry") and (_source_roles(wall) | _source_roles(frame)).intersection(
                {"DETAIL", "REFERENCE_ONLY", "DETAIL_REFERENCE", "DETAIL_REFERENCE_ONLY"}):
            _add(hard, "REFERENCE_DETAIL_MATERIAL_WALL_FORBIDDEN", wall_id=wid)
        _review_overlay_valid(wall, hard, wid, source_sha)
        if wall.get("frame_id") not in frame_ids:
            _add(hard, "WALL_FRAME_REFERENCE_INVALID", wall_id=wid)
        centerline = wall.get("centerline") or []
        if len(centerline) < 2 or any(not math.isfinite(float(v)) for p in centerline for v in p):
            _add(hard, "WALL_GEOMETRY_INVALID", wall_id=wid)
        if not wall.get("source_handles"):
            _add(required, "WALL_SOURCE_PROVENANCE_REQUIRED", wall_id=wid)
        if not set(wall.get("evidence_ids") or []).issubset(evidence_ids):
            _add(hard, "ENTITY_EVIDENCE_REFERENCE_INVALID", entity_id=wid)
        if (wall.get("authority") or {}).get("material_geometry") and "VISION_SUPPORT_ONLY" in (wall.get("authority") or {}).get("origins", []):
            _add(hard, "UNSUPPORTED_MATERIAL_GEOMETRY_AUTHORITY", wall_id=wid)

    space_polygons = {}
    for space in spaces:
        sid = space.get("physical_space_id"); _authority_valid(space, hard, sid)
        _review_overlay_valid(space, hard, sid, source_sha)
        polygon = _polygon(space.get("polygon"), space.get("interior_rings"))
        if polygon is None or not polygon.is_valid or polygon.area <= 0:
            _add(hard, "PHYSICAL_SPACE_POLYGON_INVALID", physical_space_id=sid); continue
        space_polygons[sid] = polygon
        _physical_boundary_valid(space, polygon, hard, linear_tolerance,
                                 max(abs(float(source.get("effective_scale") or 1.0)), 1e-9))
        if space.get("frame_id") not in frame_ids:
            _add(hard, "SPACE_FRAME_REFERENCE_INVALID", physical_space_id=sid)
        if not set(space.get("evidence_ids") or []).issubset(evidence_ids):
            _add(hard, "ENTITY_EVIDENCE_REFERENCE_INVALID", entity_id=sid)
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
        _review_overlay_valid(zone, hard, zid, source_sha)
        if zone.get("physical_space_id") not in space_ids:
            _add(hard, "FUNCTIONAL_ZONE_SPACE_REFERENCE_INVALID", zone_id=zid)
        if zone.get("boundary_status") == "approximate" and ((zone.get("authority") or {}).get("material_geometry") or zone.get("polygon")):
            _add(hard, "APPROXIMATE_ZONE_MATERIAL_AUTHORITY_FORBIDDEN", zone_id=zid)

    for aperture in apertures:
        _review_overlay_valid(aperture, hard, aperture.get("aperture_id"), source_sha)
        if aperture.get("host_wall_ids") and not set(aperture["host_wall_ids"]).issubset(wall_ids):
            _add(hard, "APERTURE_WALL_REFERENCE_INVALID", aperture_id=aperture.get("aperture_id"))

    portal_by_id = {}
    for portal in portals:
        oid = portal.get("opening_id"); pid = portal.get("portal_id"); _authority_valid(portal, hard, oid)
        _review_overlay_valid(portal, hard, oid, source_sha)
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
        if "COLUMN" in _source_roles(void) and (void.get("geometry_status") == "VERIFIED" or
                void.get("status") == "VERIFIED" or (void.get("authority") or {}).get("status") == "VERIFIED"):
            _add(hard, "COLUMN_AS_VERIFIED_VOID_FORBIDDEN", void_id=vid)
        _review_overlay_valid(void, hard, vid, source_sha)
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

    for obstacle in structural_obstacles:
        oid = obstacle.get("structural_obstacle_id")
        _authority_valid(obstacle, hard, oid)
        if obstacle.get("obstacle_type") != "COLUMN":
            _add(hard, "STRUCTURAL_OBSTACLE_TYPE_INVALID", structural_obstacle_id=oid)
        polygon = _polygon(obstacle.get("footprint"))
        if polygon is None or not polygon.is_valid or polygon.area <= 0:
            _add(hard, "STRUCTURAL_OBSTACLE_GEOMETRY_INVALID", structural_obstacle_id=oid)
        if (not obstacle.get("source_occurrence_id") or not obstacle.get("source_geometry_fingerprint") or
                not isinstance(obstacle.get("source_lineage"), dict) or
                not obstacle.get("world_coordinates")):
            _add(hard, "STRUCTURAL_OBSTACLE_SOURCE_IDENTITY_REQUIRED", structural_obstacle_id=oid)
        footprint = canonical_column_ring(obstacle.get("footprint"))
        world = canonical_column_ring(obstacle.get("world_coordinates"))
        lineage = obstacle.get("source_lineage") or {}
        lineage_footprint = canonical_column_ring(lineage.get("world_footprint")) if isinstance(lineage, dict) else None
        if footprint is None or world != footprint or lineage_footprint != footprint:
            _add(hard, "COLUMN_GEOMETRY_REPRESENTATION_MISMATCH", structural_obstacle_id=oid)
        if footprint is not None:
            expected_fingerprint = "COL-GEO-" + column_content_fingerprint(footprint)[:20].upper()
            if obstacle.get("source_geometry_fingerprint") != expected_fingerprint:
                _add(hard, "COLUMN_GEOMETRY_FINGERPRINT_INVALID", structural_obstacle_id=oid)
        lineage_fields = {
            "source_occurrence_id": obstacle.get("source_occurrence_id"),
            "source_handle": obstacle.get("source_handle"),
            "source_block_path": obstacle.get("source_block_path") or [],
            "source_insert_handle": obstacle.get("source_insert_handle"),
            "source_transform": obstacle.get("source_transform"),
        }
        if isinstance(lineage, dict) and all(key in lineage for key in
                ("source_sha256", "source_occurrence_id", "source_handle", "source_block_path",
                 "source_insert_handle", "source_transform", "world_footprint")):
            if (lineage.get("source_sha256") != source_sha or
                    any(lineage.get(key) != value for key, value in lineage_fields.items())):
                _add(hard, "COLUMN_SOURCE_LINEAGE_MISMATCH", structural_obstacle_id=oid)
            expected_identity = "COLUMN-" + column_content_fingerprint({
                "source_sha256": lineage.get("source_sha256"), **lineage_fields,
                "world_footprint": footprint,
            })[:20].upper()
            if oid != expected_identity:
                _add(hard, "COLUMN_IDENTITY_INVALID", structural_obstacle_id=oid)
        if obstacle.get("frame_id") not in frame_ids:
            _add(hard, "STRUCTURAL_OBSTACLE_FRAME_REFERENCE_INVALID", structural_obstacle_id=oid)
        else:
            obstacle_frame = next((row for row in frames if row.get("frame_id") == obstacle.get("frame_id")), {})
            if (obstacle_frame.get("scope_relevance") == "REFERENCE_ONLY" or
                    obstacle_frame.get("status") == "REFERENCE_ONLY"):
                _add(hard, "COLUMN_FRAME_SCOPE_INVALID", structural_obstacle_id=oid,
                     frame_id=obstacle.get("frame_id"))
        authority = obstacle.get("authority") or {}
        if any(authority.get(key) for key in
               ("material_geometry", "wall", "portal", "access", "routing", "release", "envelope")):
            _add(hard, "COLUMN_ENGINEERING_AUTHORITY_FORBIDDEN", structural_obstacle_id=oid)
        if obstacle.get("obstacle_classification") != "OBSTACLE_EVIDENCE_ONLY":
            _add(hard, "COLUMN_OBSTACLE_CLASSIFICATION_INVALID", structural_obstacle_id=oid)

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
    critical_unresolved = [row for row in data.get("unresolved_items") or []
                           if row.get("downstream_impact") != "NONCRITICAL_DIAGNOSTIC"]
    release = data.get("release") or {}
    if release.get("release_allowed") and critical_unresolved:
        _add(hard, "UNRESOLVED_CRITICAL_RELEASE_FORBIDDEN", count=len(critical_unresolved))
    if release.get("status") == "VERIFIED" and not (release.get("release_allowed") and
                                                      release.get("downstream_engineering_allowed")):
        _add(hard, "RELEASE_STATE_INCONSISTENT")
    if data.get("release", {}).get("status") == "INPUT_REQUIRED":
        _add(required, "ARCHITECTURE_RELEASE_INPUT_REQUIRED")
    if data.get("canonical_model_hash"):
        supplied = data["canonical_model_hash"]
        if supplied != canonical_model_hash(data):
            _add(hard, "CANONICAL_MODEL_HASH_MISMATCH")

    representation_after = content_hash(model)
    if representation_before != representation_after:
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
    report = {"schema": "planha-architecture-validation-report/1.0",
            "validator_id": VALIDATOR_ID, "validator_version": VALIDATOR_VERSION,
            "status": status, "hard_errors": hard, "input_requirements": required,
            "warnings": warnings, "control_results": controls,
            "metrics": {"physical_spaces": len(spaces), "walls": len(walls), "portals": len(portals),
                        "structural_obstacles": len(structural_obstacles),
                        "voids": len(voids), "illegal_overlap_area": overlap,
                        "hard_error_count": len(hard), "input_requirement_count": len(required)},
            "critical_score_masking": False, "input_hash_before": before, "input_hash_after": canonical_model_hash(model)}
    report["report_hash"] = content_hash(report)
    return report
