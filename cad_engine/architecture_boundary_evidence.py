"""Local, geometry-only enclosure evidence for semantic hosting.

This does not infer boundaries. It measures source/derived boundary coverage and
retains unresolved interior partitions instead of letting a label certify them.
"""
from shapely.geometry import LineString
import json
from shapely.ops import unary_union

from .pre_topology_object_classifier import excludes_from_wall_admission


_POSITIVE = {"SOURCE_CONTEXT", "RECURRING_PARALLEL_FACE_PAIR", "LOCAL_PARALLEL_FACE_PAIR"}


def _occurrence_identity(row):
    """Exact source occurrence identity; a handle alone is intentionally insufficient."""
    segment_id = row.get("segment_id")
    if segment_id:
        return ("SEGMENT", str(segment_id))
    transform = row.get("source_transform")
    return ("OCCURRENCE", str(row.get("source_handle")),
            str(row.get("source_insert_handle")),
            json.dumps(row.get("source_block_path"), sort_keys=True),
            json.dumps(transform, sort_keys=True),
            str(row.get("primitive_geometry_fingerprint") or
                row.get("source_geometry_fingerprint")))


def _wall_source_identities(wall):
    identities = {("SEGMENT", str(value)) for value in wall.get("source_fragments") or []}
    for row in wall.get("source_lineage") or []:
        if isinstance(row, dict):
            identities.add(_occurrence_identity(row))
    return identities


def _clip_line_to_material_intervals(points, solid, tolerance):
    """Return original-face subsegments whose axis projection has occupied material."""
    if not points or len(points) != 2:
        return [], []
    origin, direction = solid.get("axis_origin"), solid.get("axis_direction")
    if not origin or not direction:
        return [], [points]
    line = LineString(points)
    if line.length <= tolerance:
        return [], [points]
    projected = [((point[0] - origin[0]) * direction[0] +
                  (point[1] - origin[1]) * direction[1]) for point in points]
    delta = projected[1] - projected[0]
    if abs(delta) <= tolerance:
        return [], [points]
    supported = []
    for start, end in solid.get("occupied_intervals") or []:
        low, high = sorted((float(start), float(end)))
        overlap_start = max(min(projected), low)
        overlap_end = min(max(projected), high)
        if overlap_end - overlap_start <= tolerance:
            continue
        values = (overlap_start, overlap_end) if delta > 0 else (overlap_end, overlap_start)
        clipped = []
        for value in values:
            fraction = (value - projected[0]) / delta
            clipped.append([float(points[0][axis] + fraction *
                                  (points[1][axis] - points[0][axis])) for axis in (0, 1)])
        supported.append(clipped)
    qualified = unary_union([LineString(row) for row in supported]) if supported else None
    residual = line if qualified is None else line.difference(qualified.buffer(tolerance * 1e-6))
    parts = list(residual.geoms) if hasattr(residual, "geoms") else [residual]
    unsupported = [list(map(list, part.coords)) for part in parts
                   if not part.is_empty and part.geom_type == "LineString" and part.length > tolerance]
    return supported, unsupported


def physical_boundary_evidence(poly, classified, walls, closures, tolerance):
    tol = max(float(tolerance or .001) * 4, 1e-6)
    boundary = poly.boundary
    interior = poly.buffer(-tol*2)
    positive = []
    for row in classified:
        if row.get("status") != "ACCEPTED" or excludes_from_wall_admission(row.get("pre_topology_classification") or {}):
            continue
        classes = {e.get("class") for e in row.get("evidence") or []}
        if not classes & _POSITIVE:
            continue
        positive.append(row)
    by_id = {row["segment_id"]: row for row in positive}
    walls_by_identity = {}
    for wall in walls:
        if wall.get("representation") != "DOUBLE_FACE":
            continue
        for identity in _wall_source_identities(wall):
            walls_by_identity.setdefault(identity, []).append(wall)
    segments, handles, wall_ids = [], set(), set()
    boundary_fragments = set()
    witness_support = {}
    witness_unsupported = {}
    witness_origins = {}
    material_local_support = []
    unsupported_face_extensions = []
    for row in positive:
        line = LineString(row["geometry"])
        mapped = walls_by_identity.get(_occurrence_identity(row), [])
        # A raw occurrence represented by one canonical wall is governed by
        # that wall's material intervals. Ambiguous mappings fail closed.
        if len(mapped) == 1:
            qualified, unsupported = _clip_line_to_material_intervals(
                row["geometry"], mapped[0].get("wall_solid") or {}, tol)
            witness_support[row["segment_id"]] = qualified
            witness_unsupported[row["segment_id"]] = unsupported
            witness_origins[row["segment_id"]] = "MATERIAL_LOCAL_SOURCE_FACE"
            qualified_lines = [LineString(points) for points in qualified]
            boundary_length = sum(part.intersection(boundary.buffer(tol)).length
                                  for part in qualified_lines)
            interior_length = (0 if interior.is_empty else
                               sum(part.intersection(interior).length
                                   for part in qualified_lines))
            if not unsupported and boundary_length > tol and interior_length <= tol * 2:
                boundary_fragments.add(row["segment_id"])
            continue
        if len(mapped) > 1:
            witness_support[row["segment_id"]] = []
            witness_unsupported[row["segment_id"]] = [row["geometry"]]
            witness_origins[row["segment_id"]] = "AMBIGUOUS_CANONICAL_MAPPING"
            continue
        if line.intersection(boundary.buffer(tol)).length > tol:
            segments.append(row["geometry"])
            witness_support[row["segment_id"]] = [row["geometry"]]
            witness_unsupported[row["segment_id"]] = []
            witness_origins[row["segment_id"]] = "INDEPENDENT_SOURCE_GEOMETRY"
            if row.get("source_handle"): handles.add(row["source_handle"])
    for wall in walls:
        fragments = wall.get("source_fragments") or []
        if not fragments or not all(sid in by_id for sid in fragments):
            continue
        # Only occupied material intervals may support derived axes. Never use
        # a stitched axis spanning an unresolved interruption as a closure.
        solid = wall.get("wall_solid") or {}
        origin, direction = solid.get("axis_origin"), solid.get("axis_direction")
        if not origin or not direction: continue
        for key in ("face_a", "face_b"):
            if not wall.get(key):
                continue
            qualified, unsupported = _clip_line_to_material_intervals(wall[key], solid, tol)
            for points in qualified:
                if LineString(points).intersection(boundary.buffer(tol)).length > tol:
                    segments.append(points); handles.update(wall.get("source_handles") or []); wall_ids.add(wall["wall_id"])
                    material_local_support.append({"wall_id": wall["wall_id"], "face": key,
                                                   "geometry": points,
                                                   "source_handles": sorted(wall.get("source_handles") or [])})
            if unsupported:
                unsupported_face_extensions.append({"wall_id": wall["wall_id"], "face": key,
                                                    "geometry": unsupported,
                                                    "source_handles": sorted(wall.get("source_handles") or [])})
    closure_ids = []
    for row in closures:
        if row.get("gap_status") not in {"PROVEN", "SUPPORTED", "HUMAN_CONFIRMED"}: continue
        if not row.get("geometry") or "ENCLOSURE_BARRIER" not in (row.get("roles") or []): continue
        line = LineString(row["geometry"])
        if line.intersection(boundary.buffer(tol)).length > tol:
            segments.append(row["geometry"]); closure_ids.append(row.get("closure_id"))
    unique = {tuple(tuple(p) for p in points): points for points in segments}
    segments = [unique[key] for key in sorted(unique)]
    support = unary_union([LineString(points) for points in segments]) if segments else None
    uncovered = boundary if support is None else boundary.difference(support.buffer(tol))
    missing = uncovered.length
    uncovered_parts = list(uncovered.geoms) if hasattr(uncovered, "geoms") else [uncovered]
    uncovered_segments = sorted([list(map(list, part.coords)) for part in uncovered_parts
                                 if not part.is_empty and part.geom_type in {"LineString", "LinearRing"}])
    interior_ids = sorted(row["segment_id"] for row in positive
                          if row["segment_id"] not in boundary_fragments and not interior.is_empty and LineString(row["geometry"]).intersection(interior).length > tol*2)
    reasons = []
    if interior.is_empty: reasons.append("NO_RESOLVABLE_INTERIOR_AT_EVIDENCE_TOLERANCE")
    if missing > 1e-9: reasons.append("PHYSICAL_BOUNDARY_UNSUPPORTED")
    if interior_ids: reasons.append("UNRESOLVED_INTERIOR_WALL_EVIDENCE")
    status = "INPUT_REQUIRED" if reasons else "VERIFIED"
    return {"status": status, "separator_status": "AMBIGUOUS",
            "source_witness_records": [dict(
                {key: row.get(key) for key in ("segment_id", "source_handle", "geometry", "source_insert_handle", "source_block_path", "source_transform", "evidence", "negative_evidence", "pre_topology_classification")},
                boundary_support_segments=witness_support.get(row["segment_id"], []),
                unsupported_geometry=witness_unsupported.get(row["segment_id"], []),
                boundary_support_origin=witness_origins.get(row["segment_id"], "NONE"))
                for row in sorted(positive, key=lambda value: json.dumps(value, sort_keys=True))
                if LineString(row["geometry"]).intersection(boundary.buffer(tol)).length > tol],
            "source_handles": sorted(handles), "segments": segments,
            "wall_ids": sorted(wall_ids), "closure_ids": sorted(x for x in closure_ids if x),
            "material_local_support": sorted(material_local_support, key=lambda row: json.dumps(row, sort_keys=True)),
            "unsupported_face_extensions": sorted(unsupported_face_extensions, key=lambda row: json.dumps(row, sort_keys=True)),
            "boundary_fragment_ids": sorted(boundary_fragments),
            "tolerance": tol, "uncovered_length": missing,
            "coverage_ratio": max(0.0, 1-missing/max(boundary.length,1e-12)),
            "uncovered_boundary_segments": uncovered_segments,
            "gap_classification": "UNSUPPORTED_SOURCE_BOUNDARY" if missing > 1e-9 else "NONE",
            "unresolved_internal_segment_ids": interior_ids, "negative_evidence": reasons,
            "evidence": [{"class": "LOCAL_PHYSICAL_BOUNDARY_COVERAGE", "source_handles": sorted(handles),
                          "wall_ids": sorted(wall_ids), "uncovered_length": missing}]}
