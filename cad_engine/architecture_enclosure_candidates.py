"""Source-face enclosure candidates; no source admission or material fabrication.

Numerical endpoint coincidence is local, bounded by the caller's existing
precision, and anchored to independently supported accepted wall segments.
Original geometry remains the sole input to physical boundary verification.
"""
import hashlib
import json
import math

from shapely.geometry import LineString, MultiPoint, Point
from shapely.ops import polygonize, snap, unary_union
from shapely.strtree import STRtree

from .architecture_boundary_evidence import physical_boundary_evidence
from .pre_topology_object_classifier import excludes_from_wall_admission

_POSITIVE = {"SOURCE_CONTEXT", "RECURRING_PARALLEL_FACE_PAIR", "LOCAL_PARALLEL_FACE_PAIR"}


def _key(poly):
    # GEOS normalization makes orientation and starting vertex irrelevant.
    return poly.normalize().wkb_hex


def _identifier(frame_id, poly):
    return "ENC-" + hashlib.sha256((str(frame_id) + _key(poly)).encode()).hexdigest()[:16].upper()


def _supported(row):
    return bool(_POSITIVE & {e.get("class") for e in row.get("evidence") or []})


def _source_topology(classified, tolerance):
    records = sorted((r for r in classified if r.get("status") == "ACCEPTED"
                      and r.get("wall_evidence_state") != "HARD_EXCLUDED_NON_ENCLOSURE_OBJECT"
                      and not excludes_from_wall_admission(r.get("pre_topology_classification") or {})),
                     key=lambda r: str(r.get("segment_id")))
    lines = [LineString(r["geometry"]) for r in records]
    if not lines:
        return [], []
    tree = STRtree(lines)
    anchors = [[] for _ in lines]
    joins = []
    # Insert an existing supported endpoint into another supported segment when
    # their numerical separation is already below drawing precision. No distant
    # endpoints, inferred openings, transitive snap chains, or generated walls.
    for index, (record, line) in enumerate(zip(records, lines)):
        if not _supported(record):
            continue
        for coord in (line.coords[0], line.coords[-1]):
            point = Point(coord)
            nearby = []
            for raw in tree.query(point.buffer(tolerance)):
                other = int(raw)
                if other == index or not _supported(records[other]):
                    continue
                # Only a transverse endpoint-to-face T incidence is adjusted.
                # Parallel nearby independent walls and endpoint-to-endpoint
                # gaps are not evidence of intended connection.
                target = lines[other]
                along = target.project(point)
                if along <= tolerance or target.length - along <= tolerance:
                    continue
                ax, ay = line.coords[-1][0]-line.coords[0][0], line.coords[-1][1]-line.coords[0][1]
                bx, by = target.coords[-1][0]-target.coords[0][0], target.coords[-1][1]-target.coords[0][1]
                if abs(ax*bx+ay*by) >= math.cos(math.radians(3))*line.length*target.length:
                    continue
                distance = point.distance(target)
                if not 0 < distance <= tolerance:
                    continue
                projected = target.interpolate(along)
                nearby.append((other, distance, projected))
            # Multiple distinct nearby faces are ambiguous. Coincident duplicate
            # faces are equivalent; no nearest-wall guess is made.
            if not nearby or any(nearby[0][2].distance(item[2]) > tolerance * 1e-6 for item in nearby[1:]):
                continue
            for other, distance, projected in nearby:
                anchors[other].append(tuple(coord))
                joins.append({"source_segment_id": record.get("segment_id"),
                              "supporting_segment_id": records[other].get("segment_id"),
                              "source_handles": sorted({str(record.get("source_handle")), str(records[other].get("source_handle"))}),
                              "endpoint": list(coord), "distance": distance,
                              "tolerance": tolerance, "material": False,
                              "reason": "SUPPORTED_SOURCE_ENDPOINT_COINCIDENCE"})
    adjusted = [snap(line, MultiPoint(sorted(set(points))), tolerance) if points else line
                for line, points in zip(lines, anchors)]
    joins.sort(key=lambda r: json.dumps(r, sort_keys=True))
    return adjusted, joins


def _ambiguous_cell_arrays(ordered, classified, tolerance):
    """Recognize repeated grid cells, not a semantic stair or room category.

    Recurrence itself is not independent material evidence. At least three
    congruent edge-adjacent cells and missing or competing face spacings are
    required. A wall layer alone cannot establish a material family.
    """
    eligible = []
    accepted = [r for r in classified if r.get("status") == "ACCEPTED"]
    source_lines = [LineString(r["geometry"]) for r in accepted]
    source_tree = STRtree(source_lines) if source_lines else None
    for poly, row in ordered:
        if row["origins"] != ["SOURCE_FACE"]:
            continue
        band = poly.boundary.buffer(tolerance)
        supporting = [accepted[int(raw)] for raw in (source_tree.query(band) if source_tree is not None else [])
                      if source_lines[int(raw)].intersection(band).length > tolerance]
        thicknesses = sorted({float(value) for r in supporting for e in r.get("evidence") or []
                              if e.get("class") in {"RECURRING_PARALLEL_FACE_PAIR", "LOCAL_PARALLEL_FACE_PAIR"}
                              for value in e.get("thicknesses") or []})
        distinct = []
        for value in thicknesses:
            if not distinct or value-distinct[-1] > tolerance:
                distinct.append(value)
        if len(distinct) == 1:
            continue
        rect = list(poly.minimum_rotated_rectangle.exterior.coords)
        dimensions = sorted(math.dist(a,b) for a,b in zip(rect,rect[1:]))
        eligible.append((poly,row,dimensions,distinct))
    parents = list(range(len(eligible)))
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]; i = parents[i]
        return i
    eligible_tree = STRtree([item[0] for item in eligible]) if eligible else None
    for i,(left,_,dims,_) in enumerate(eligible):
        for j in sorted(int(raw) for raw in eligible_tree.query(left.buffer(tolerance)) if int(raw) > i):
            right,_,other,_ = eligible[j]
            if all(abs(a-b) <= tolerance for a,b in zip(dims,other)) and left.distance(right) <= tolerance and left.boundary.intersection(right.boundary.buffer(tolerance)).length > tolerance * 4:
                parents[root(j)] = root(i)
    groups = {}
    for i,item in enumerate(eligible):
        groups.setdefault(root(i),[]).append(item)
    for group in groups.values():
        if len(group) < 3:
            continue
        ids = sorted(item[1]["candidate_id"] for item in group)
        for _,row,_,thicknesses in group:
            row["candidate_role"] = "REPEATED_CELL_ARRAY"
            row["selection_reason"] = "REPEATED_GRID_WITH_UNPROVEN_FACE_FAMILY"
            row["candidate_integrity"] = {"status":"INPUT_REQUIRED", "array_candidate_ids":ids,
                                          "competing_face_thicknesses":thicknesses,
                                          "source_context_does_not_resolve_family_conflict":True}


def _occupied_material(walls):
    solids = []
    for wall in walls:
        solid = wall.get("wall_solid") or {}
        origin, direction = solid.get("axis_origin"), solid.get("axis_direction")
        thickness = wall.get("thickness")
        if not origin or not direction or not thickness or thickness <= 0:
            continue
        for start, end in solid.get("occupied_intervals") or []:
            if end <= start:
                continue
            points = [[origin[0]+t*direction[0], origin[1]+t*direction[1]] for t in (start,end)]
            solids.append(LineString(points).buffer(thickness/2, cap_style=2, join_style=2))
    return unary_union(solids) if solids else None


def reconcile_enclosure_candidates(polygons, classified, walls, closures, tolerance, frame_id,
                                   candidate_filter=None):
    """Return nonoverlapping selected polygons plus deterministic diagnostics.

    Existing verified geometry is preserved. A source-face child may replace an
    unsupported containing candidate; the parent remains diagnostic, never a
    label host. Unsupported source candidates may fill otherwise empty regions
    but retain the independent proof's INPUT_REQUIRED status.
    """
    tol = max(float(tolerance or .001), 1e-9)
    lines, joins = _source_topology(classified, tol)
    source = list(polygonize(unary_union(lines))) if lines else []
    source = [p for p in source if p.is_valid and not p.is_empty and math.isfinite(p.area)
              and p.area > max(tol * tol * 4, 1e-9)]
    # Preserve the full local grid as negative context before wall-material
    # filtering removes alternating cells. Filtered cells never gain authority.
    raw_entries = [(p, {"candidate_id": _identifier(frame_id, p), "origins": ["SOURCE_FACE"],
                        "candidate_role": "SPACE_CANDIDATE"}) for p in source]
    _ambiguous_cell_arrays(raw_entries, classified, tol)
    array_context = {_key(p): row for p, row in raw_entries if row["candidate_role"] == "REPEATED_CELL_ARRAY"}
    if candidate_filter:
        source = candidate_filter(source)
    entries = {}
    invalid = []
    material = _occupied_material(walls)
    for origin, candidates in (("EXISTING_SUBDIVISION", polygons), ("SOURCE_FACE", source)):
        for poly in candidates:
            if not poly.is_valid or poly.is_empty or not math.isfinite(poly.area) or poly.area <= 0:
                invalid.append({"origin": origin, "reason": "INVALID_POLYGON", "wkt": poly.wkt})
                continue
            key = _key(poly)
            if key in entries:
                entries[key][1]["origins"].append(origin)
                continue
            proof = physical_boundary_evidence(poly, classified, walls, closures, tol)
            row = {"candidate_id": _identifier(frame_id, poly), "frame_id": frame_id,
                   "origins": [origin], "polygon": [list(x) for x in poly.exterior.coords],
                   "interior_rings": [[list(x) for x in ring.coords] for ring in poly.interiors],
                   "area": poly.area, "boundary_evidence": proof, "contains": [],
                   "contained_by": [], "overlaps": [], "candidate_role": "SPACE_CANDIDATE",
                   "selected": False}
            if origin == "SOURCE_FACE" and key in array_context:
                context = array_context[key]
                row.update(candidate_role=context["candidate_role"],
                           candidate_integrity=context["candidate_integrity"],
                           selection_reason=context["selection_reason"])
            if origin == "SOURCE_FACE" and material is not None:
                clearance = float(proof.get("tolerance", tol)) * 2
                interior = poly.buffer(-clearance)
                overlap = interior.intersection(material).area if not interior.is_empty else 0.0
                if overlap > tol * tol:
                    row["candidate_role"] = "WALL_MATERIAL_CONFLICT"
                    row["selection_reason"] = "SOURCE_FACE_INTERIOR_INTERSECTS_OCCUPIED_MATERIAL"
                    row["candidate_integrity"] = {"status": "INPUT_REQUIRED", "interior_material_overlap": overlap,
                                                  "erosion_tolerance": clearance, "numerical_area_residue": tol * tol}
            entries[key] = (poly, row)
    ordered = sorted(entries.values(), key=lambda item: item[1]["candidate_id"])
    epsilon = max(tol * tol, 1e-12)
    candidate_tree = STRtree([item[0] for item in ordered]) if ordered else None
    for i, (left, a) in enumerate(ordered):
        for j in sorted(int(raw) for raw in candidate_tree.query(left) if int(raw) > i):
            right, b = ordered[j]
            overlap = left.intersection(right).area
            if overlap <= epsilon:
                continue
            a["overlaps"].append({"candidate_id": b["candidate_id"], "ratio": overlap / left.area})
            b["overlaps"].append({"candidate_id": a["candidate_id"], "ratio": overlap / right.area})
            if left.covers(right) and left.area - right.area > epsilon:
                a["contains"].append(b["candidate_id"]); b["contained_by"].append(a["candidate_id"])
            elif right.covers(left) and right.area - left.area > epsilon:
                b["contains"].append(a["candidate_id"]); a["contained_by"].append(b["candidate_id"])
    by_id = {r["candidate_id"]: r for _, r in ordered}
    for _, row in ordered:
        if row["candidate_role"] == "SPACE_CANDIDATE" and row["boundary_evidence"]["status"] != "VERIFIED" and any(
                by_id[child]["boundary_evidence"]["status"] == "VERIFIED" and by_id[child]["candidate_role"] == "SPACE_CANDIDATE" for child in row["contains"]):
            row["candidate_role"] = "PARENT_CONTAINER"
            row["selection_reason"] = "SUPPORTED_CHILD_WITHIN_UNSUPPORTED_CONTAINER"
    # Evidence precedes size: never blindly choose the smallest/largest loop.
    ranked = sorted(ordered, key=lambda item: (
        item[1]["boundary_evidence"]["status"] != "VERIFIED",
        "EXISTING_SUBDIVISION" not in item[1]["origins"], item[1]["candidate_id"]))
    selected = []
    for poly, row in ranked:
        if row["candidate_role"] in {"PARENT_CONTAINER", "REPEATED_CELL_ARRAY", "WALL_MATERIAL_CONFLICT"}:
            continue
        if any(poly.intersection(other).area > epsilon for other in selected):
            row["selection_reason"] = "OVERLAP_WITH_PRESERVED_OR_BETTER_SUPPORTED_CANDIDATE"
            continue
        selected.append(poly); row["selected"] = True
        row["selection_reason"] = "SOURCE_SUPPORTED_ENCLOSURE" if row["boundary_evidence"]["status"] == "VERIFIED" else "UNRESOLVED_DIAGNOSTIC_ENCLOSURE"
    return selected, {"schema": "architecture-enclosure-candidates/1.0", "frame_id": frame_id,
                      "candidates": [r for _, r in ordered], "endpoint_coincidences": joins,
                      "invalid_candidates": invalid, "source_face_cell_count": len(source),
                      "selected_count": len(selected), "synthetic_wall_count": 0}
