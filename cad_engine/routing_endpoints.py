"""Project-geometry-derived proposed connection points for routing.

These points are design proposals used when the architecture proves a room role
but does not provide trustworthy installed fixture coordinates. They must never
be presented as detected/installed source facts.
"""
from __future__ import annotations

import math


def _room_anchor(room: dict):
    value = room.get("label_point") or room.get("centroid") or room.get("point")
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError):
        return None


def _inside_polygon(point, polygon) -> bool:
    if not polygon or len(polygon) < 3:
        return False
    x, y = point
    hit = False
    j = len(polygon) - 1
    for i, raw in enumerate(polygon):
        xi, yi = float(raw[0]), float(raw[1])
        xj, yj = float(polygon[j][0]), float(polygon[j][1])
        if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            hit = not hit
        j = i
    return hit


def _key(point):
    return round(float(point[0]), 6), round(float(point[1]), 6)


def _bounded(point, bounds):
    if not bounds or len(bounds) != 4:
        return point
    x, y = point
    return min(max(x, float(bounds[0])), float(bounds[2])), min(max(y, float(bounds[1])), float(bounds[3]))


def _polygon_candidates(room: dict, anchor):
    polygon = room.get("polygon") or []
    if len(polygon) < 3:
        return []
    xs = [float(p[0]) for p in polygon]
    ys = [float(p[1]) for p in polygon]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 <= x0 or y1 <= y0:
        return []
    fractions = (0.2, 0.35, 0.5, 0.65, 0.8)
    candidates = []
    for fy in fractions:
        for fx in fractions:
            point = (x0 + (x1 - x0) * fx, y0 + (y1 - y0) * fy)
            if _inside_polygon(point, polygon):
                candidates.append(point)
    # Keep proposed points close to the architectural room label/centroid while
    # preserving a deterministic secondary order.
    return sorted({_key(point): point for point in candidates}.values(), key=lambda p: (math.dist(anchor, p), p[1], p[0]))


def _plan_fanout_candidates(anchor, bounds):
    if not bounds or len(bounds) != 4:
        return []
    width = max(float(bounds[2]) - float(bounds[0]), 0.0)
    height = max(float(bounds[3]) - float(bounds[1]), 0.0)
    span = min(value for value in (width, height) if value > 0) if width > 0 and height > 0 else max(width, height)
    if span <= 0:
        return []
    # A dimensionless fraction of the actual plan extent is used only to make
    # proposed logical endpoints graphically/routably distinct. It is not a
    # fixture-clearance or construction-spacing rule.
    step = span * 0.0125
    directions = (
        (-1, -1), (1, -1), (-1, 1), (1, 1),
        (0, -1), (0, 1), (-1, 0), (1, 0),
        (-2, -1), (2, -1), (-2, 1), (2, 1),
        (-1, -2), (1, -2), (-1, 2), (1, 2),
    )
    rows = []
    for dx, dy in directions:
        rows.append(_bounded((anchor[0] + dx * step, anchor[1] + dy * step), bounds))
    return list({_key(point): point for point in rows}.values())


def propose_connection_point(room: dict, plan_bounds, ordinal: int = 0, occupied=()) -> dict | None:
    """Return a distinct, explicitly non-authoritative design connection point.

    If a reconstructed room polygon exists, the point is constrained to it. If
    only a semantic room label is available, a small plan-relative fanout is
    used and the result is marked as requiring fixture-location coordination.
    """
    anchor = _room_anchor(room)
    if anchor is None:
        return None
    occupied_keys = {_key(point) for point in occupied if point is not None}
    polygon = room.get("polygon") or []
    candidates = _polygon_candidates(room, anchor)
    boundary_known = bool(candidates)
    basis = "RECONSTRUCTED_ROOM_POLYGON_PROPOSAL" if boundary_known else "ROOM_LABEL_PLAN_RELATIVE_PROPOSAL"
    if not candidates:
        candidates = _plan_fanout_candidates(anchor, plan_bounds)
    if not candidates:
        candidates = [anchor]
    available = [point for point in candidates if _key(point) not in occupied_keys]
    if not available:
        return None
    point = available[int(ordinal) % len(available)]
    return {
        "point": point,
        "placement_basis": basis,
        "location_authority": "PROPOSED_NOT_SOURCE_DETECTED",
        "room_boundary_known": boundary_known,
        "requires_fixture_coordination": True,
    }
