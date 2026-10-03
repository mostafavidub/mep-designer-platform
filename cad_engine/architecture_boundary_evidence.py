"""Local, geometry-only enclosure evidence for semantic hosting.

This does not infer boundaries. It measures source/derived boundary coverage and
retains unresolved interior partitions instead of letting a label certify them.
"""
from shapely.geometry import LineString
from shapely.ops import unary_union

from .pre_topology_object_classifier import excludes_from_wall_admission


_POSITIVE = {"SOURCE_CONTEXT", "RECURRING_PARALLEL_FACE_PAIR", "LOCAL_PARALLEL_FACE_PAIR"}


def physical_boundary_evidence(poly, classified, walls, closures, tolerance):
    tol = max(float(tolerance or .001) * 4, 1e-6)
    boundary = poly.boundary
    positive = []
    for row in classified:
        if row.get("status") != "ACCEPTED" or excludes_from_wall_admission(row.get("pre_topology_classification") or {}):
            continue
        classes = {e.get("class") for e in row.get("evidence") or []}
        if not classes & _POSITIVE:
            continue
        positive.append(row)
    by_id = {row["segment_id"]: row for row in positive}
    segments, handles, wall_ids = [], set(), set()
    boundary_fragments = set()
    for row in positive:
        line = LineString(row["geometry"])
        if line.intersection(boundary.buffer(tol)).length > tol:
            segments.append(row["geometry"])
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
        for start, end in solid.get("occupied_intervals") or []:
            points = [[origin[0]+v*direction[0], origin[1]+v*direction[1]] for v in (start,end)]
            line = LineString(points)
            if line.intersection(boundary.buffer(tol)).length > tol:
                segments.append(points); handles.update(wall.get("source_handles") or []); wall_ids.add(wall["wall_id"]); boundary_fragments.update(fragments)
        for key in ("face_a", "face_b"):
            if wall.get(key) and LineString(wall[key]).intersection(boundary.buffer(tol)).length > tol:
                segments.append(wall[key]); handles.update(wall.get("source_handles") or []); wall_ids.add(wall["wall_id"]); boundary_fragments.update(fragments)
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
    missing = boundary.length if support is None else boundary.difference(support.buffer(tol)).length
    interior = poly.buffer(-tol*2)
    interior_ids = sorted(row["segment_id"] for row in positive
                          if row["segment_id"] not in boundary_fragments and not interior.is_empty and LineString(row["geometry"]).intersection(interior).length > tol*2)
    reasons = []
    if missing > tol: reasons.append("PHYSICAL_BOUNDARY_UNSUPPORTED")
    if interior_ids: reasons.append("UNRESOLVED_INTERIOR_WALL_EVIDENCE")
    status = "INPUT_REQUIRED" if reasons else "VERIFIED"
    return {"status": status, "source_handles": sorted(handles), "segments": segments,
            "wall_ids": sorted(wall_ids), "closure_ids": sorted(x for x in closure_ids if x),
            "tolerance": tol, "uncovered_length": missing,
            "coverage_ratio": max(0.0, 1-missing/max(boundary.length,1e-12)),
            "unresolved_internal_segment_ids": interior_ids, "negative_evidence": reasons,
            "evidence": [{"class": "LOCAL_PHYSICAL_BOUNDARY_COVERAGE", "source_handles": sorted(handles),
                          "wall_ids": sorted(wall_ids), "uncovered_length": missing}]}
