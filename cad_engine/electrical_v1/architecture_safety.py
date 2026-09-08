"""Evidence-safe postprocessing for Electrical architectural reconstruction.

This module deliberately wraps the existing reconstruction engine instead of
introducing a second architectural model. It resolves a narrow class of
high-confidence unit-header conflicts and refuses to promote shared helper
rectangles to room geometry.
"""
from __future__ import annotations

import statistics
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import ezdxf

from .architecture import reconstruct_architecture as _base_reconstruct
from .models import ArchitecturalModel, EngineeringStatus, EvidenceValue, Room

Point = Tuple[float, float]
Polygon = List[Point]


def _inside(point: Point, polygon: Optional[Polygon]) -> bool:
    if not polygon:
        return False
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _area(poly: Optional[Polygon]) -> float:
    if not poly or len(poly) < 3:
        return 0.0
    return abs(
        sum(
            poly[i][0] * poly[(i + 1) % len(poly)][1]
            - poly[(i + 1) % len(poly)][0] * poly[i][1]
            for i in range(len(poly))
        )
        / 2.0
    )


def _measurement_note(label: str | None) -> bool:
    text = str(label or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").lower()
    normalized = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    return any(token in text for token in ("ارتفاع دیوار", "wall height")) and any(ch.isdigit() for ch in normalized)


def _dimension_measurements(path: str | Path) -> List[float]:
    values: List[float] = []
    doc = ezdxf.readfile(str(path))
    for entity in doc.modelspace().query("DIMENSION"):
        try:
            value = abs(float(entity.get_measurement()))
        except Exception:
            continue
        if 0.001 <= value <= 100000:
            values.append(value)
    return values


def _effective_scale(model: ArchitecturalModel, path: str | Path) -> Tuple[EvidenceValue, Optional[float], Optional[str]]:
    raw = str(model.units.value or "").lower()
    scale = {"mm": 0.001, "cm": 0.01, "m": 1.0}.get(raw)
    values = _dimension_measurements(path)
    if not values:
        return model.units, scale, None
    median = statistics.median(values)
    if raw == "mm" and 0.20 <= median <= 50.0:
        return (
            EvidenceValue.final("m", "architectural_evidence", 0.98, reference="dimension_measurement_override_mm_header_to_m"),
            1.0,
            f"unit_header_conflict_resolved:mm_to_m:median_dimension={median:.6g}",
        )
    if raw == "m" and 200.0 <= median <= 50000.0:
        return (
            EvidenceValue.final("mm", "architectural_evidence", 0.98, reference="dimension_measurement_override_m_header_to_mm"),
            0.001,
            f"unit_header_conflict_resolved:m_to_mm:median_dimension={median:.6g}",
        )
    return model.units, scale, None


def _segment_overlap(a1: float, a2: float, b1: float, b2: float) -> float:
    lo = max(min(a1, a2), min(b1, b2))
    hi = min(max(a1, a2), max(b1, b2))
    return max(0.0, hi - lo)


def _recover_orthogonal_room(
    room: Room,
    frame_bounds: Tuple[float, float, float, float],
    line_entities: Iterable,
    peer_points: List[Point],
    scale_to_m: Optional[float],
) -> Optional[Polygon]:
    if not room.label_point or not scale_to_m:
        return None
    x, y = room.label_point
    coord_tol = 0.04 / scale_to_m
    overlap_tol = 0.08 / scale_to_m
    min_span = 0.50 / scale_to_m
    horizontal = []
    vertical = []
    for entity in line_entities:
        geometry = entity.geometry or {}
        try:
            a = tuple(geometry["a"])
            b = tuple(geometry["b"])
        except Exception:
            continue
        dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
        if dy <= coord_tol and dx >= min_span and _segment_overlap(a[0], b[0], x - overlap_tol, x + overlap_tol) > 0:
            horizontal.append(((a[1] + b[1]) / 2.0, a, b))
        if dx <= coord_tol and dy >= min_span and _segment_overlap(a[1], b[1], y - overlap_tol, y + overlap_tol) > 0:
            vertical.append(((a[0] + b[0]) / 2.0, a, b))
    below = [row for row in horizontal if row[0] < y - coord_tol]
    above = [row for row in horizontal if row[0] > y + coord_tol]
    left = [row for row in vertical if row[0] < x - coord_tol]
    right = [row for row in vertical if row[0] > x + coord_tol]
    if not (below and above and left and right):
        return None
    bottom = max(below, key=lambda row: row[0])[0]
    top = min(above, key=lambda row: row[0])[0]
    west = max(left, key=lambda row: row[0])[0]
    east = min(right, key=lambda row: row[0])[0]
    if east - west < min_span or top - bottom < min_span:
        return None
    if not (frame_bounds[0] <= west < east <= frame_bounds[2] and frame_bounds[1] <= bottom < top <= frame_bounds[3]):
        return None
    polygon = [(west, bottom), (east, bottom), (east, top), (west, top)]
    owned = [point for point in peer_points if _inside(point, polygon)]
    return polygon if len(owned) == 1 else None




def _cluster_axis_rows(rows, coordinate_tolerance: float):
    """Group near-collinear wall fragments without relying on layer semantics."""
    rows = sorted(rows, key=lambda row: row[0])
    groups = []
    for row in rows:
        if not groups:
            groups.append([row])
            continue
        current = groups[-1]
        center = sum(item[0] * item[3] for item in current) / max(sum(item[3] for item in current), 1e-12)
        if abs(row[0] - center) <= coordinate_tolerance:
            current.append(row)
        else:
            groups.append([row])
    clustered = []
    for group in groups:
        total = max(sum(item[3] for item in group), 1e-12)
        center = sum(item[0] * item[3] for item in group) / total
        clustered.append((center, [(item[1], item[2]) for item in group]))
    return clustered


def _interval_coverage(intervals, start: float, end: float, merge_tolerance: float) -> float:
    if end <= start:
        return 0.0
    clipped = []
    for a, b in intervals:
        lo, hi = max(start, min(a, b)), min(end, max(a, b))
        if hi > lo:
            clipped.append((lo, hi))
    if not clipped:
        return 0.0
    clipped.sort()
    lo, hi = clipped[0]
    total = 0.0
    for a, b in clipped[1:]:
        if a <= hi + merge_tolerance:
            hi = max(hi, b)
        else:
            total += hi - lo
            lo, hi = a, b
    total += hi - lo
    return min(1.0, total / (end - start))


def _recover_wall_supported_room(
    room: Room,
    frame_bounds: Tuple[float, float, float, float],
    line_entities: Iterable,
    peer_points: List[Point],
    scale_to_m: Optional[float],
) -> Optional[Polygon]:
    """Recover a unique orthogonal enclosure from fragmented wall evidence.

    Door/window openings often split a wall into multiple LINE fragments, so a
    segment does not necessarily cross the room-label coordinate.  The older
    nearest-four-lines resolver intentionally fails in that case.  This second
    pass groups near-collinear fragments, measures actual side coverage, and
    promotes geometry only when one room label owns the candidate.  Shared/open
    plan enclosures remain unresolved rather than being arbitrarily partitioned.
    """
    if not room.label_point or not scale_to_m:
        return None
    x, y = room.label_point
    min_segment = 0.20 / scale_to_m
    max_segment = 12.0 / scale_to_m
    axis_deviation = 0.08 / scale_to_m
    cluster_tolerance = 0.10 / scale_to_m
    label_margin = 0.15 / scale_to_m
    merge_tolerance = 0.10 / scale_to_m
    min_span = 0.80 / scale_to_m

    horizontal = []
    vertical = []
    for entity in line_entities:
        geometry = entity.geometry or {}
        try:
            a = tuple(geometry["a"]); b = tuple(geometry["b"])
            length = ((b[0]-a[0])**2 + (b[1]-a[1])**2) ** 0.5
        except Exception:
            continue
        if not (min_segment <= length <= max_segment):
            continue
        dx, dy = abs(b[0]-a[0]), abs(b[1]-a[1])
        # Permit slightly skewed CAD wall faces, but not diagonal annotation.
        if dx >= min_segment and dy <= max(axis_deviation, 0.04 * dx):
            horizontal.append(((a[1]+b[1])/2.0, min(a[0],b[0]), max(a[0],b[0]), length))
        if dy >= min_segment and dx <= max(axis_deviation, 0.04 * dy):
            vertical.append(((a[0]+b[0])/2.0, min(a[1],b[1]), max(a[1],b[1]), length))

    h_rows = _cluster_axis_rows(horizontal, cluster_tolerance)
    v_rows = _cluster_axis_rows(vertical, cluster_tolerance)
    below = sorted((row for row in h_rows if row[0] < y-label_margin), key=lambda row: y-row[0])[:8]
    above = sorted((row for row in h_rows if row[0] > y+label_margin), key=lambda row: row[0]-y)[:8]
    left = sorted((row for row in v_rows if row[0] < x-label_margin), key=lambda row: x-row[0])[:8]
    right = sorted((row for row in v_rows if row[0] > x+label_margin), key=lambda row: row[0]-x)[:8]
    if not (below and above and left and right):
        return None

    frame_area_m2 = max(0.0, (frame_bounds[2]-frame_bounds[0]) * (frame_bounds[3]-frame_bounds[1])) * scale_to_m * scale_to_m
    max_area_m2 = max(20.0, min(500.0, frame_area_m2 * 0.45))
    candidates = []
    for bottom in below:
        for top in above:
            for west in left:
                for east in right:
                    btm, tp, wst, est = bottom[0], top[0], west[0], east[0]
                    width, height = est-wst, tp-btm
                    if width < min_span or height < min_span:
                        continue
                    if not (frame_bounds[0] <= wst < est <= frame_bounds[2] and frame_bounds[1] <= btm < tp <= frame_bounds[3]):
                        continue
                    area_m2 = width * height * scale_to_m * scale_to_m
                    if not (1.0 <= area_m2 <= max_area_m2):
                        continue
                    coverage = [
                        _interval_coverage(bottom[1], wst, est, merge_tolerance),
                        _interval_coverage(top[1], wst, est, merge_tolerance),
                        _interval_coverage(west[1], btm, tp, merge_tolerance),
                        _interval_coverage(east[1], btm, tp, merge_tolerance),
                    ]
                    # Every side needs material wall evidence.  This is what
                    # keeps open-plan/shared zones from becoming fake rooms.
                    if min(coverage) < 0.35 or sum(coverage)/4.0 < 0.55:
                        continue
                    polygon = [(wst, btm), (est, btm), (est, tp), (wst, tp)]
                    owned = [point for point in peer_points if _inside(point, polygon)]
                    if len(owned) != 1:
                        continue
                    score = (sum(coverage)/4.0) * 5.0 - 0.015 * area_m2
                    candidates.append((score, polygon))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def reconstruct_architecture_safe(path: str | Path) -> ArchitecturalModel:
    model = _base_reconstruct(path)
    units, scale_to_m, unit_issue = _effective_scale(model, path)
    model.units = units
    if unit_issue and unit_issue not in model.issues:
        model.issues.append(unit_issue)

    model.rooms = [room for room in model.rooms if not _measurement_note(room.label)]

    frames = {frame.id: frame for frame in model.frames}
    line_entities = [entity for entity in model.entities if entity.kind == "line_candidate"]
    by_frame = {}
    for room in model.rooms:
        by_frame.setdefault(room.frame_id, []).append(room)

    for room in model.rooms:
        peer_rooms = [peer for peer in by_frame.get(room.frame_id, []) if peer.label_point]
        peers = [peer.label_point for peer in peer_rooms]
        indoor_peers = [peer.label_point for peer in peer_rooms if str(peer.room_type.value or "") != "outdoor"]
        polygon = room.polygon
        if polygon and sum(1 for point in peers if _inside(point, polygon)) != 1:
            polygon = None
        frame = frames.get(room.frame_id)
        recovery_reference = "unique_room_enclosure"
        recovery_confidence = 0.90
        if polygon is None and frame is not None:
            polygon = _recover_orthogonal_room(room, frame.bounds, line_entities, peers, scale_to_m)
        if polygon is None and frame is not None and str(room.room_type.value or "") != "outdoor":
            # Outdoor labels are frequently placed just across/onto a facade
            # line for readability.  A fully wall-supported indoor enclosure
            # should therefore be unique among indoor functional labels; an
            # outdoor annotation alone must not veto it.
            polygon = _recover_wall_supported_room(room, frame.bounds, line_entities, indoor_peers, scale_to_m)
            if polygon is not None:
                recovery_reference = "wall_supported_unique_room_enclosure"
                recovery_confidence = 0.82
        room.polygon = polygon
        if polygon and scale_to_m:
            room.area_m2 = EvidenceValue.final(
                _area(polygon) * scale_to_m * scale_to_m,
                "architectural_evidence",
                recovery_confidence,
                reference=recovery_reference,
            )
        elif polygon:
            room.area_m2 = EvidenceValue.input_required("DXF unit required to convert room area")
        else:
            room.area_m2 = EvidenceValue.unknown("room polygon not detected")

    for level in model.levels:
        level.room_ids = [room.id for room in model.rooms if room.level_id == level.id]

    if unit_issue and model.building_footprint.status != EngineeringStatus.UNKNOWN:
        model.building_footprint = EvidenceValue.unknown("footprint requires reclassification after DXF unit-header conflict")

    if any(room.polygon is None for room in model.rooms) and "some_rooms_lack_boundaries" not in model.issues:
        model.issues.append("some_rooms_lack_boundaries")
    return model
