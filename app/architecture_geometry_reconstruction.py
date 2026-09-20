"""Evidence-backed room and shaft boundary reconstruction.

Architectural DXFs frequently contain no semantic WALL/ROOM layers and no
closed room polylines. This module reconstructs topological cells from the
actual linework inside a confirmed plan frame. Door-gap closures are used only
during segmentation and are never emitted as architectural walls.

The module is intentionally fail-closed: a cell is accepted only when it
contains exactly one semantic label and passes geometry/area checks. Every
accepted polygon records the DXF handles and layers that support it.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import math
import re

from shapely.geometry import LineString, Point, box
from shapely.ops import polygonize, unary_union


_EXCLUDED_LAYER_TOKENS = (
    "dim", "اندازه", "axis", "axband", "grid", "section", "نما", "elev",
    "text", "note", "title", "frame", "border", "hatch", "furn", "fur",
    "cabinet", "مبلمان", "symbol", "fixture", "sanitary", "mechanic",
)
_DOOR_TOKENS = ("door", "در وپنجره", "در وپنچره", " در ")
_WALL_TOKENS = ("wall", "walls", "دیوار", "تيغه", "تیغه", "construction")
_SHAFT_TOKENS = ("shaft", "شفت", "duct", "داکت")


def _norm(value):
    value = str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").lower()
    value = re.sub(r"[_./\\:-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _matches(layer, tokens):
    value = f" {_norm(layer)} "
    return any(token in value for token in tokens)


def _entity_handle(entity):
    return str(getattr(entity.dxf, "handle", "") or "")


def _inside(bounds, point, tolerance=1e-8):
    return (bounds[0] - tolerance <= point[0] <= bounds[2] + tolerance and
            bounds[1] - tolerance <= point[1] <= bounds[3] + tolerance)


def _linework(entity):
    """Return source polylines without inventing intermediate geometry."""
    typ = entity.dxftype()
    try:
        if typ == "LINE":
            a, b = entity.dxf.start, entity.dxf.end
            return [[(float(a.x), float(a.y)), (float(b.x), float(b.y))]]
        if typ == "LWPOLYLINE":
            points = [(float(x), float(y)) for x, y, *_ in entity.get_points("xy")]
            if entity.closed and points and points[0] != points[-1]:
                points.append(points[0])
            return [points] if len(points) >= 2 else []
        if typ == "POLYLINE":
            points = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
            if entity.is_closed and points and points[0] != points[-1]:
                points.append(points[0])
            return [points] if len(points) >= 2 else []
        if typ == "HATCH":
            paths = []
            for boundary in entity.paths:
                if hasattr(boundary, "vertices"):
                    points = [(float(v[0]), float(v[1])) for v in boundary.vertices]
                    if points and points[0] != points[-1]:
                        points.append(points[0])
                    if len(points) >= 3:
                        paths.append(points)
            return paths
    except Exception:
        return []
    return []


def _candidate_layer(layer):
    normalized = _norm(layer)
    if not normalized or normalized in {"0", "defpoints"}:
        return False
    return not _matches(layer, _EXCLUDED_LAYER_TOKENS)


def _source_lines(msp, frame_bounds):
    """Collect geometry and retain the provenance of every source segment."""
    rows = []
    for entity in msp:
        layer = str(getattr(entity.dxf, "layer", "") or "")
        typ = entity.dxftype()
        if typ not in {"LINE", "LWPOLYLINE", "POLYLINE", "HATCH"}:
            continue
        semantic = "door" if _matches(layer, _DOOR_TOKENS) else (
            "wall" if _matches(layer, _WALL_TOKENS) else (
                "shaft" if _matches(layer, _SHAFT_TOKENS) else "generic"
            )
        )
        if semantic == "generic" and not _candidate_layer(layer):
            continue
        for points in _linework(entity):
            for a, b in zip(points, points[1:]):
                if math.dist(a, b) <= 1e-7:
                    continue
                midpoint = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                if not _inside(frame_bounds, midpoint):
                    continue
                rows.append({
                    "line": LineString([a, b]), "layer": layer,
                    "handle": _entity_handle(entity), "semantic": semantic,
                    "entity_type": typ,
                })
    return rows


def _snap_tolerance(frame_bounds):
    width = max(frame_bounds[2] - frame_bounds[0], 1e-6)
    height = max(frame_bounds[3] - frame_bounds[1], 1e-6)
    return max(min(math.hypot(width, height) * 0.0003, min(width, height) * 0.01), 1e-5)


def _door_closures(rows, tolerance):
    """Close short, evidenced gaps for segmentation only."""
    doors = [row for row in rows if row["semantic"] == "door"]
    structure = [row for row in rows if row["semantic"] != "door"]
    structural_ends = [Point(coord) for row in structure for coord in row["line"].coords]
    closures = []
    seen = set()
    for row in doors:
        attached = []
        for endpoint in row["line"].coords:
            nearest = min(structural_ends, key=lambda p: p.distance(Point(endpoint)), default=None)
            if nearest is not None and nearest.distance(Point(endpoint)) <= tolerance * 8:
                attached.append((float(nearest.x), float(nearest.y)))
        if len(attached) != 2 or math.dist(attached[0], attached[1]) > tolerance * 80:
            continue
        key = tuple(round(v / tolerance) for point in attached for v in point)
        if key in seen or attached[0] == attached[1]:
            continue
        seen.add(key)
        closures.append({
            "line": LineString(attached), "layer": row["layer"],
            "handle": row["handle"], "semantic": "temporary_door_closure",
            "entity_type": row["entity_type"],
        })
    return closures


def _polygon_coords(poly):
    return [[round(float(x), 6), round(float(y), 6)] for x, y in list(poly.exterior.coords)[:-1]]


def _fingerprint(coords):
    normalized = ";".join(f"{x:.6f},{y:.6f}" for x, y in coords)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def _supporting_evidence(poly, rows, tolerance):
    boundary = poly.boundary.buffer(tolerance * 3)
    hits = [row for row in rows if boundary.intersects(row["line"])]
    return {
        "source_handles": sorted({row["handle"] for row in hits if row["handle"]}),
        "source_layers": sorted({row["layer"] for row in hits if row["layer"]}),
        "source_entity_count": len(hits),
        "temporary_closure_count": sum(row["semantic"] == "temporary_door_closure" for row in hits),
    }


def _review_geometry(noded, sources, frame_bounds, tolerance):
    """Serialize the *noded* wall graph used by the review UI.

    Edges are split at real CAD intersections.  Consequently a UI anchor is
    not merely close to a wall: it is a vertex in the exact graph along which
    the confirmed room boundary will later be resolved.
    """
    coordinates = []
    raw_segments = []
    geometries = list(noded.geoms) if hasattr(noded, "geoms") else [noded]
    for geometry in geometries:
        if hasattr(geometry, "coords"):
            coords = list(geometry.coords)
            coordinates.extend(coords)
            raw_segments.extend(zip(coords, coords[1:]))
    deduped = {}
    for x, y in coordinates:
        key = (round(float(x) / tolerance), round(float(y) / tolerance))
        deduped.setdefault(key, (float(x), float(y)))
    nodes = []
    key_to_id = {}
    for _index, (key, (x, y)) in enumerate(sorted(deduped.items(), key=lambda row: row[1])):
        if not _inside(frame_bounds, (x, y)):
            continue
        digest = hashlib.sha256(f"{x:.8f},{y:.8f}".encode()).hexdigest()[:16]
        node_id = f"NODE-{digest}"
        key_to_id[key] = node_id
        nodes.append({"id": node_id, "x": round(x, 6), "y": round(y, 6)})
        if len(nodes) >= 2500:
            break
    segments = []
    seen = set()
    for a, b in raw_segments:
        a_key = (round(float(a[0]) / tolerance), round(float(a[1]) / tolerance))
        b_key = (round(float(b[0]) / tolerance), round(float(b[1]) / tolerance))
        a_id, b_id = key_to_id.get(a_key), key_to_id.get(b_key)
        if not a_id or not b_id or a_id == b_id:
            continue
        edge = tuple(sorted((a_id, b_id)))
        if edge in seen:
            continue
        seen.add(edge)
        segments.append({
            "a_id": a_id, "b_id": b_id,
            "a": [round(float(a[0]), 6), round(float(a[1]), 6)],
            "b": [round(float(b[0]), 6), round(float(b[1]), 6)],
            "kind": "noded_architectural_linework",
        })
        if len(segments) >= 5000:
            break
    return {"snap_points": nodes, "wall_segments": segments}


def reconstruct_boundaries(msp, frame_bounds, semantic_labels):
    """Reconstruct validated room/shaft cells within one canonical frame."""
    if not frame_bounds or len(frame_bounds) != 4:
        return {"accepted": {}, "diagnostics": ["canonical_frame_missing"], "quality": {}}
    frame = box(*frame_bounds)
    tolerance = _snap_tolerance(frame_bounds)
    sources = _source_lines(msp, frame_bounds)
    closures = _door_closures(sources, tolerance)
    noded = unary_union([row["line"] for row in sources + closures] + [frame.boundary])
    cells = [p for p in polygonize(noded) if p.is_valid and p.area > tolerance * tolerance * 25]

    label_points = [(idx, kind, Point(point)) for idx, (_item, kind, point) in enumerate(semantic_labels)
                    if _inside(frame_bounds, point)]
    accepted = {}
    rejected = Counter()
    for cell in cells:
        contained = [(idx, kind, point) for idx, kind, point in label_points
                     if cell.buffer(tolerance).contains(point)]
        if not contained:
            continue
        if len(contained) != 1:
            rejected["multiple_semantic_labels"] += 1
            continue
        idx, _kind, _point = contained[0]
        if cell.area >= frame.area * 0.88:
            rejected["frame_sized_cell"] += 1
            continue
        minx, miny, maxx, maxy = cell.bounds
        if min(maxx - minx, maxy - miny) <= tolerance * 3:
            rejected["degenerate_cell"] += 1
            continue
        evidence = _supporting_evidence(cell, sources + closures, tolerance)
        if evidence["source_entity_count"] < 3:
            rejected["insufficient_source_edges"] += 1
            continue
        coords = _polygon_coords(cell)
        accepted[idx] = {
            "polygon": coords,
            "bounds": [round(float(v), 6) for v in cell.bounds],
            "area_drawing_units2": round(float(cell.area), 6),
            "polygon_confidence": "high" if evidence["temporary_closure_count"] == 0 else "medium",
            "geometry_method": "noded_architectural_linework_polygonization",
            "geometry_fingerprint": _fingerprint(coords),
            "geometry_evidence": evidence,
            "provenance": "INFERRED",
        }

    # Many consultant drawings leave door openings in otherwise valid wall
    # linework.  A single global closing distance either leaves the whole plan
    # connected or erases small wet rooms.  Resolve each label at the smallest
    # evidence-derived clearance that yields an exclusive free-space cell.
    # The returned polygon is explicitly an interior-clear boundary (not a
    # fabricated wall face), and the offset is retained for audit/replay.
    short_side = min(frame_bounds[2] - frame_bounds[0], frame_bounds[3] - frame_bounds[1])
    adaptive_offsets = sorted({
        max(tolerance * 2, short_side * ratio)
        for ratio in (0.0007, 0.001, 0.0015, 0.0025, 0.004, 0.0067,
                      0.01, 0.0135, 0.016, 0.019, 0.022)
    })
    adaptive_attempts = 0
    for offset in adaptive_offsets:
        unresolved = [row for row in label_points if row[0] not in accepted]
        if not unresolved:
            break
        obstacles = unary_union([
            row["line"].buffer(offset, cap_style=2, join_style=2) for row in sources
        ])
        free = frame.difference(obstacles)
        cells_at_offset = list(free.geoms) if hasattr(free, "geoms") else [free]
        adaptive_attempts += 1
        for idx, _kind, label_point in unresolved:
            candidates = [cell for cell in cells_at_offset
                          if not cell.is_empty and cell.buffer(tolerance).contains(label_point)]
            if len(candidates) != 1:
                continue
            cell = candidates[0]
            occupants = [other_idx for other_idx, _other_kind, point in label_points
                         if cell.buffer(tolerance).contains(point)]
            if occupants != [idx] or cell.area >= frame.area * 0.35:
                continue
            minx, miny, maxx, maxy = cell.bounds
            if (cell.area <= offset * offset * 4 or
                    min(maxx - minx, maxy - miny) <= offset * 2):
                continue
            evidence = _supporting_evidence(cell, sources, max(offset, tolerance))
            if evidence["source_entity_count"] < 3:
                continue
            coords = _polygon_coords(cell)
            accepted[idx] = {
                "polygon": coords,
                "bounds": [round(float(v), 6) for v in cell.bounds],
                "area_drawing_units2": round(float(cell.area), 6),
                "polygon_confidence": "medium",
                "geometry_method": "adaptive_clear_space_segmentation",
                "geometry_fingerprint": _fingerprint(coords),
                "geometry_evidence": {
                    **evidence,
                    "clearance_offset_drawing_units": round(float(offset), 8),
                    "selection_rule": "smallest_offset_with_one_semantic_label",
                },
                "provenance": "INFERRED",
            }

    review_geometry = _review_geometry(noded, sources, frame_bounds, tolerance)
    return {
        "accepted": accepted,
        "diagnostics": [f"rejected_{key}:{value}" for key, value in sorted(rejected.items())],
        "quality": {
            "source_segment_count": len(sources),
            "temporary_door_closure_count": len(closures),
            "polygonized_cell_count": len(cells),
            "accepted_cell_count": len(accepted),
            "adaptive_offset_attempt_count": adaptive_attempts,
            "snap_tolerance": tolerance,
            "source_layer_counts": dict(Counter(row["layer"] for row in sources)),
        },
        **review_geometry,
    }
