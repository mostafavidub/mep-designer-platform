"""Fail-closed qualification of source-backed architectural spatial facts.

This module never reconstructs geometry from text.  It qualifies geometry that
already exists in the DXF extraction/canonical model and publishes granular
capability grants for downstream engineering consumers.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from hashlib import sha256
import json
import math

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union


SPATIAL_SCHEMA = "planha-architecture-spatial-authority/1.0"
AUTHORITY_LEVELS = (
    "TEXT_ONLY", "GEOMETRY_CANDIDATE", "BOUNDARY_SUPPORTED",
    "PHYSICAL_SPACE_VERIFIED", "SEMANTICALLY_HOSTED", "TOPOLOGY_VERIFIED",
    "ENGINEERING_READY",
)
SPACE_GEOMETRY_TYPES = {
    "ENCLOSED_INTERIOR", "COVERED_SEMI_OPEN", "EXTERIOR_SITE_SPACE",
    "INTERNAL_VOID", "VERTICAL_CIRCULATION", "SERVICE_VOID", "OTHER",
}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _fingerprint(value):
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_id(prefix, value):
    return f"{prefix}-{_fingerprint(value)[:20].upper()}"


def _points(record):
    pts = record.get("points") or record.get("vertices") or []
    if len(pts) >= 2:
        return [[float(p[0]), float(p[1])] for p in pts]
    start, end = record.get("start"), record.get("end")
    if start is not None and end is not None:
        return [[float(start[0]), float(start[1])], [float(end[0]), float(end[1])]]
    return []


def _valid_polygon(ring, holes=None):
    try:
        polygon = Polygon(ring or [], holes or [])
    except (TypeError, ValueError):
        return None
    return polygon if polygon.is_valid and not polygon.is_empty and polygon.area > 0 else None


def _source_closed_rings(extracted):
    rows = []
    for record in extracted.get("primitives") or []:
        pts = _points(record)
        if not record.get("closed") or len(pts) < 3:
            continue
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        polygon = _valid_polygon(pts)
        if polygon is None:
            continue
        rows.append({
            "polygon": polygon,
            "ring": [[round(x, 6), round(y, 6)] for x, y in polygon.exterior.coords],
            "source_handles": [str(record["handle"])] if record.get("handle") else [],
            "layer": str(record.get("layer") or ""),
            "entity_type": record.get("entity_type"),
        })
    return rows


def _frame_polygon(frame):
    bounds = frame.get("bounds") or []
    if len(bounds) != 4:
        return None
    return Polygon([(bounds[0], bounds[1]), (bounds[2], bounds[1]),
                    (bounds[2], bounds[3]), (bounds[0], bounds[3])])


def _envelope_rows(model):
    rows = {}
    for row in model.get("building_envelopes") or []:
        ring = row.get("outer_ring") or row.get("polygon") or row.get("boundary")
        polygon = _valid_polygon(ring, row.get("interior_rings"))
        if polygon is not None and row.get("status") in {"VERIFIED", "HIGH_CONFIDENCE"}:
            rows[row.get("frame_id")] = (row, polygon)
    return rows


def _site_boundaries(model, extracted, tolerance):
    closed = _source_closed_rings(extracted)
    envelopes = _envelope_rows(model)
    results = []
    for frame in model.get("frames") or []:
        frame_id = frame.get("frame_id")
        envelope_pair = envelopes.get(frame_id)
        if envelope_pair is None:
            results.append({"site_boundary_id": _stable_id("SITE", [frame_id, "NO_ENVELOPE"]),
                            "frame_id": frame_id, "status": "INPUT_REQUIRED",
                            "reason": "VERIFIED_BUILDING_ENVELOPE_REQUIRED", "polygon": None,
                            "source_handles": [], "authority": "NONE"})
            continue
        _, envelope = envelope_pair
        frame_polygon = _frame_polygon(frame)
        candidates = []
        for row in closed:
            polygon = row["polygon"]
            if polygon.area <= envelope.area * 1.02 or not polygon.buffer(tolerance).covers(envelope):
                continue
            if frame_polygon is not None and polygon.symmetric_difference(frame_polygon).area <= max(tolerance, frame_polygon.area * 1e-8):
                continue
            layer = row["layer"].casefold()
            semantic = any(token in layer for token in ("site", "property", "plot", "حد", "زمین", "ملک"))
            candidates.append((0 if semantic else 1, polygon.area, row))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]["source_handles"]))
        if not candidates:
            results.append({"site_boundary_id": _stable_id("SITE", [frame_id, "MISSING"]),
                            "frame_id": frame_id, "status": "INPUT_REQUIRED",
                            "reason": "SOURCE_SITE_BOUNDARY_REQUIRED", "polygon": None,
                            "source_handles": [], "authority": "NONE"})
            continue
        preferred = [item for item in candidates if item[0] == candidates[0][0]]
        ambiguous = len(preferred) > 1 and preferred[1][1] / preferred[0][1] < 1.05
        chosen = candidates[0][2]
        results.append({"site_boundary_id": _stable_id("SITE", [frame_id, chosen["ring"], chosen["source_handles"]]),
                        "frame_id": frame_id, "status": "AMBIGUOUS" if ambiguous else "VERIFIED",
                        "reason": "MULTIPLE_SOURCE_SITE_BOUNDARIES" if ambiguous else "SOURCE_CLOSED_BOUNDARY_CONTAINING_BUILDING",
                        "polygon": chosen["ring"], "source_handles": chosen["source_handles"],
                        "authority": "NONE" if ambiguous else "SOURCE_GEOMETRY",
                        "provenance_fingerprint": _fingerprint([chosen["ring"], chosen["source_handles"]])})
    return results


def _site_spaces(model, site_boundaries):
    envelopes = _envelope_rows(model)
    rows = []
    for site in site_boundaries:
        if site.get("status") != "VERIFIED" or not site.get("polygon"):
            continue
        envelope_pair = envelopes.get(site.get("frame_id"))
        if envelope_pair is None:
            continue
        site_polygon = _valid_polygon(site["polygon"])
        envelope = envelope_pair[1]
        difference = site_polygon.difference(envelope)
        polygons = [difference] if difference.geom_type == "Polygon" else list(getattr(difference, "geoms", []))
        for polygon in polygons:
            if polygon.is_empty or polygon.area <= 0:
                continue
            ring = [[round(x, 6), round(y, 6)] for x, y in polygon.exterior.coords]
            rows.append({"site_space_id": _stable_id("SITE-SPACE", [site["site_boundary_id"], ring]),
                         "frame_id": site["frame_id"], "space_geometry_type": "EXTERIOR_SITE_SPACE",
                         "polygon": ring,
                         "interior_rings": [[[round(x, 6), round(y, 6)] for x, y in hole.coords]
                                            for hole in polygon.interiors],
                         "status": "VERIFIED", "geometry_status": "VERIFIED",
                         "semantic_status": "INPUT_REQUIRED", "source_handles": site["source_handles"],
                         "authority_level": "PHYSICAL_SPACE_VERIFIED",
                         "provenance_fingerprint": _fingerprint([site["site_boundary_id"], ring])})
    return sorted(rows, key=lambda row: row["site_space_id"])


def _line_records(extracted):
    rows = []
    for record in extracted.get("primitives") or []:
        pts = _points(record)
        pairs = list(zip(pts, pts[1:]))
        if record.get("closed") and len(pts) > 2:
            pairs.append((pts[-1], pts[0]))
        for index, (a, b) in enumerate(pairs):
            line = LineString([a, b])
            if line.length <= 0:
                continue
            angle = math.atan2(b[1] - a[1], b[0] - a[0]) % math.pi
            rows.append({"line": line, "angle": angle, "length": line.length,
                         "source_handle": str(record.get("handle") or ""), "segment_index": index,
                         "source_closed": bool(record.get("closed"))})
    return rows


def _angle_distance(a, b):
    delta = abs(a - b) % math.pi
    return min(delta, math.pi - delta)


def _stair_assemblies(model, extracted, tolerance):
    lines = _line_records(extracted)
    groups = defaultdict(list)
    for row in lines:
        if row["source_closed"]:
            continue
        groups[round(row["angle"] / math.radians(3))].append(row)
    assemblies = []
    closed = _source_closed_rings(extracted)
    for group in groups.values():
        if len(group) < 4:
            continue
        lengths = sorted(row["length"] for row in group)
        median = lengths[len(lengths) // 2]
        treads = [row for row in group if median * .7 <= row["length"] <= median * 1.3]
        if len(treads) < 4:
            continue
        angle = treads[0]["angle"]
        normal = (-math.sin(angle), math.cos(angle))
        offsets = sorted(sum(p[i] * normal[i] for i in (0, 1)) / 2
                         for row in treads for p in [row["line"].centroid.coords[0]])
        gaps = [b - a for a, b in zip(offsets, offsets[1:]) if b - a > tolerance]
        if len(gaps) < 3:
            continue
        mean_gap = sum(gaps) / len(gaps)
        cv = (sum((gap - mean_gap) ** 2 for gap in gaps) / len(gaps)) ** .5 / max(mean_gap, tolerance)
        if cv > .25:
            continue
        tread_union = unary_union([row["line"] for row in treads])
        bounds_polygon = tread_union.envelope.buffer(tolerance)
        rails = [row for row in lines if _angle_distance(row["angle"], angle) > math.radians(70)
                 and row["line"].intersects(bounds_polygon)]
        source_core = [row for row in closed if row["polygon"].buffer(tolerance).covers(tread_union)]
        all_handles = sorted({row["source_handle"] for row in treads + rails if row["source_handle"]})
        status = "VERIFIED" if len(rails) >= 2 and source_core else "INPUT_REQUIRED"
        core = min(source_core, key=lambda row: row["polygon"].area) if source_core else None
        identity = [all_handles, [round(v, 6) for v in tread_union.bounds]]
        assemblies.append({
            "stair_assembly_id": _stable_id("STAIR", identity),
            "frame_id": next((f.get("frame_id") for f in model.get("frames") or []
                              if (_frame_polygon(f) and _frame_polygon(f).buffer(tolerance).covers(tread_union))), None),
            "status": status,
            "reason": "SOURCE_CORE_AND_REGULAR_TREAD_PATTERN" if status == "VERIFIED" else
                      "STAIR_CORE_OR_SIDE_BOUNDARIES_REQUIRED",
            "core_polygon": deepcopy(core["ring"]) if core else None,
            "core_source_handles": deepcopy(core["source_handles"]) if core else [],
            "flights": [{"flight_id": _stable_id("FLIGHT", identity), "status": status,
                         "tread_line_ids": [_stable_id("TREAD", [r["source_handle"], r["segment_index"]]) for r in treads],
                         "source_handles": sorted({r["source_handle"] for r in treads if r["source_handle"]}),
                         "regular_spacing_cv": round(cv, 6)}],
            "landings": [],
            "tread_riser_lines": [{"line_id": _stable_id("TREAD", [r["source_handle"], r["segment_index"]]),
                                    "geometry": [[round(x, 6), round(y, 6)] for x, y in r["line"].coords],
                                    "source_handle": r["source_handle"], "status": "VERIFIED"}
                                   for r in treads],
            "source_handles": all_handles,
            "negative_controls": {"minimum_treads": True, "regular_spacing": True,
                                  "two_side_boundaries": len(rails) >= 2,
                                  "source_closed_core": bool(source_core)},
            "authority": "SOURCE_GEOMETRY" if status == "VERIFIED" else "NONE",
            "provenance_fingerprint": _fingerprint(identity),
        })
    unique = {row["stair_assembly_id"]: row for row in assemblies}
    return sorted(unique.values(), key=lambda row: row["stair_assembly_id"])


def _boundary_segments(space):
    ring = space.get("polygon") or []
    proof = space.get("geometry_evidence") or {}
    handles = sorted({str(value) for value in (proof.get("source_handles") or space.get("source_handles") or []) if value})
    witnesses = []
    for row in proof.get("segments") or []:
        points = row.get("geometry") if isinstance(row, dict) else row
        if not isinstance(points, (list, tuple)) or len(points) < 2:
            continue
        try:
            line = LineString(points)
        except (TypeError, ValueError):
            continue
        source_handle = row.get("source_handle") if isinstance(row, dict) else None
        source_handles = row.get("source_handles") if isinstance(row, dict) else None
        witness_handles = list(source_handles or []) + ([source_handle] if source_handle else [])
        opposite = row.get("opposite_space_id") if isinstance(row, dict) else None
        witnesses.append((line, sorted({str(value) for value in witness_handles if value}), opposite))
    segments = []
    for index, (a, b) in enumerate(zip(ring, ring[1:])):
        edge = LineString([a, b])
        tolerance = max(edge.length * 1e-7, 1e-8)
        matching = [(row_handles, opposite) for line, row_handles, opposite in witnesses
                                 if line.buffer(tolerance).covers(edge) or edge.buffer(tolerance).covers(line)
                    ]
        source_handles = sorted({handle for row_handles, _ in matching for handle in row_handles})
        opposites = sorted({opposite for _, opposite in matching if opposite})
        if not witnesses and len(handles) == 1:
            source_handles = handles
        segments.append({"boundary_segment_id": _stable_id("BOUNDARY", [space.get("physical_space_id"), index, a, b]),
                         "geometry": [a, b], "source_handles": source_handles,
                         "opposite_space_id": opposites[0] if len(opposites) == 1 else None,
                         "status": "VERIFIED" if source_handles else "INPUT_REQUIRED",
                         "reason": "EXACT_SOURCE_HANDLE" if source_handles else "PER_SEGMENT_SOURCE_HANDLE_REQUIRED"})
    return segments


def _qualify_spaces(model, stairs):
    stair_polygons = [(row, _valid_polygon(row.get("core_polygon"))) for row in stairs
                      if row.get("status") == "VERIFIED" and row.get("core_polygon")]
    for space in model.get("physical_spaces") or []:
        polygon = _valid_polygon(space.get("polygon"), space.get("interior_rings"))
        geometry_verified = space.get("geometry_status") == "VERIFIED" and polygon is not None
        segments = _boundary_segments(space)
        boundary_verified = bool(segments) and all(row["status"] == "VERIFIED" for row in segments)
        geometry_type = "ENCLOSED_INTERIOR"
        related_stair = None
        if polygon is not None:
            related_stair = next((row for row, core in stair_polygons if core and core.intersection(polygon).area > 0), None)
        if related_stair:
            geometry_type = "VERTICAL_CIRCULATION"
        semantic_hosted = bool(space.get("text_evidence_ids") or space.get("functional_zones"))
        topology_verified = space.get("topology_status") == "VERIFIED"
        metric_authority = space.get("area_m2") is not None and bool((model.get("source") or {}).get("metres_per_unit"))
        if geometry_verified and boundary_verified and topology_verified and metric_authority:
            level = "ENGINEERING_READY"
        elif geometry_verified and topology_verified:
            level = "TOPOLOGY_VERIFIED"
        elif geometry_verified and semantic_hosted:
            level = "SEMANTICALLY_HOSTED"
        elif geometry_verified:
            level = "PHYSICAL_SPACE_VERIFIED"
        elif boundary_verified:
            level = "BOUNDARY_SUPPORTED"
        else:
            level = "GEOMETRY_CANDIDATE"
        space.update({"space_geometry_type": geometry_type, "boundary_segments": segments,
                      "authority_level": level, "area_authority": "METRIC" if metric_authority else "NONE",
                      "centroid": list(polygon.centroid.coords)[0] if polygon is not None else None,
                      "bounding_box": list(polygon.bounds) if polygon is not None else None,
                      "provenance_fingerprint": _fingerprint([space.get("physical_space_id"), ring_or_none(space), segments]),
                      "stair_assembly_ids": [related_stair["stair_assembly_id"]] if related_stair else []})


def ring_or_none(space):
    return space.get("polygon") if _valid_polygon(space.get("polygon"), space.get("interior_rings")) else None


def _graph_qualification(model):
    space_ids = {row.get("physical_space_id") for row in model.get("physical_spaces") or []}
    portals = {row.get("portal_id"): row for row in model.get("openings") or []}
    legacy_enclosure_edges = (model.get("enclosure_graph") or {}).get("edges") or []
    access_edges = (model.get("access_graph") or {}).get("edges") or []
    enclosure_edges = []
    for space in model.get("physical_spaces") or []:
        for segment in space.get("boundary_segments") or []:
            enclosure_edges.append({"space_id": space.get("physical_space_id"),
                                    "boundary_segment_id": segment.get("boundary_segment_id"),
                                    "opposite_space_id": segment.get("opposite_space_id"),
                                    "source_handles": segment.get("source_handles") or [],
                                    "status": segment.get("status")})
    legacy_refs_ok = all(len(edge) == 2 and edge[0] in space_ids | {"EXTERIOR"}
                         and edge[1] in space_ids | {"EXTERIOR"} for edge in legacy_enclosure_edges)
    enclosure_ok = bool(enclosure_edges) and legacy_refs_ok and all(
        edge["status"] == "VERIFIED" and edge["source_handles"]
        and edge["opposite_space_id"] in space_ids | {"EXTERIOR"} for edge in enclosure_edges
    )
    access_ok = bool(access_edges) and all(
        row.get("portal_id") in portals and portals[row.get("portal_id")].get("status") == "VERIFIED"
        and portals[row.get("portal_id")].get("host_wall_id") for row in access_edges
    )
    return {"enclosure_graph": {"status": "VERIFIED" if enclosure_ok else "INPUT_REQUIRED",
                                 "reason": "SOURCE_BACKED_SPACE_SEPARATOR_RELATIONS" if enclosure_ok else "PER_SEGMENT_OPPOSITE_SPACE_REQUIRED",
                                 "edges": enclosure_edges},
            "access_graph": {"status": "VERIFIED" if access_ok else "INPUT_REQUIRED",
                              "reason": "HOSTED_VERIFIED_PORTALS_ONLY" if access_ok else "HOSTED_PORTAL_EVIDENCE_REQUIRED",
                              "edges": deepcopy(access_edges)}}


def _authority_matrix(model, site_boundaries, stairs, graph):
    spaces = model.get("physical_spaces") or []
    grants = {
        "ROOM_POLYGON": bool(spaces) and all(s.get("authority_level") in {"PHYSICAL_SPACE_VERIFIED", "SEMANTICALLY_HOSTED", "TOPOLOGY_VERIFIED", "ENGINEERING_READY"} for s in spaces),
        "METRIC_AREA": bool(spaces) and all(s.get("area_authority") == "METRIC" for s in spaces),
        "SITE_RELATION": bool(site_boundaries) and all(s.get("status") == "VERIFIED" for s in site_boundaries),
        "ENCLOSURE_TOPOLOGY": graph["enclosure_graph"]["status"] == "VERIFIED",
        "ACCESS_TOPOLOGY": graph["access_graph"]["status"] == "VERIFIED",
        "VERTICAL_CIRCULATION": bool(stairs) and all(s.get("status") == "VERIFIED" for s in stairs),
    }
    prerequisites = {
        "MECHANICAL_ROOM_LOAD": ["ROOM_POLYGON", "METRIC_AREA"],
        "EXTERIOR_WALL_LOAD": ["ROOM_POLYGON", "METRIC_AREA", "SITE_RELATION", "ENCLOSURE_TOPOLOGY"],
        "MECHANICAL_ROUTING": ["ROOM_POLYGON", "ENCLOSURE_TOPOLOGY", "ACCESS_TOPOLOGY"],
        "VERTICAL_ROUTING": ["ROOM_POLYGON", "ACCESS_TOPOLOGY", "VERTICAL_CIRCULATION"],
    }
    consumers = {}
    for consumer, required in prerequisites.items():
        missing = [name for name in required if not grants[name]]
        consumers[consumer] = {"status": "VERIFIED" if not missing else "INPUT_REQUIRED",
                               "allowed": not missing, "required_authorities": required,
                               "missing_authorities": missing}
    return {"facts": {name: {"status": "VERIFIED" if value else "INPUT_REQUIRED", "granted": value}
                       for name, value in grants.items()}, "consumers": consumers}


def qualify_spatial_understanding(model, extracted, tolerance):
    """Attach spatial facts and capability gates without promoting missing evidence."""
    site_boundaries = _site_boundaries(model, extracted, tolerance)
    site_spaces = _site_spaces(model, site_boundaries)
    stairs = _stair_assemblies(model, extracted, tolerance)
    _qualify_spaces(model, stairs)
    graph = _graph_qualification(model)
    matrix = _authority_matrix(model, site_boundaries, stairs, graph)
    unsupported_verified = sum(
        1 for space in model.get("physical_spaces") or []
        if space.get("geometry_status") == "VERIFIED" and
        (not space.get("polygon") or any(s.get("status") != "VERIFIED" for s in space.get("boundary_segments") or []))
    )
    model["spatial_authority"] = {
        "schema": SPATIAL_SCHEMA,
        "authority_levels": list(AUTHORITY_LEVELS),
        "space_geometry_types": sorted(SPACE_GEOMETRY_TYPES),
        "text_creates_geometry": False,
        "vision_geometry_authority": False,
        "site_boundaries": site_boundaries,
        "site_spaces": site_spaces,
        "vertical_circulation": {"stair_assemblies": stairs, "elevators": [], "shafts": []},
        "graph_qualification": graph,
        "engineering_authority_matrix": matrix,
        "counters": {"unsupported_verified_geometry": unsupported_verified,
                     "text_created_verified_geometry": 0,
                     "unsupported_verified_stairs": sum(1 for row in stairs if row.get("status") == "VERIFIED" and not row.get("core_source_handles"))},
        "status": "VERIFIED" if unsupported_verified == 0 and all(
            value.get("granted") for value in matrix["facts"].values()) else "INPUT_REQUIRED",
    }
    return model


def require_architecture_authorities(model, consumer):
    matrix = ((model or {}).get("spatial_authority") or {}).get("engineering_authority_matrix") or {}
    decision = deepcopy((matrix.get("consumers") or {}).get(consumer))
    if not decision:
        return {"status": "INPUT_REQUIRED", "allowed": False,
                "missing_authorities": ["DECLARED_CONSUMER_PREREQUISITES"]}
    return decision
