"""Conservative anonymous door/window evidence from exact DXF geometry.

The detector emits reviewable candidates only.  It never removes source
geometry, creates a Portal/Access edge, or promotes a candidate to VERIFIED.
The numeric ratios below are calibrated parameters with explicit provenance,
not claims of universal precision or recall.
"""
from __future__ import annotations

from collections import Counter
from collections import defaultdict
from hashlib import sha256
import json
import math

import numpy as np


SCHEMA = "planha-architectural-opening-evidence/1.2"
DETECTOR_REVISION = "anonymous-opening-candidates/1.2"
CALIBRATION = {
    "window_frame_ratio_max": 0.35,
    "pane_angle_tolerance": 1e-6,
    "adjacent_support_angle_tolerance": 1e-4,
    "provenance": "OWNER_REVIEWED_SINGLE_SOURCE_CALIBRATION",
    "generalization_status": "UNVALIDATED_HOLDOUT_REVIEW_REQUIRED",
}
PLAN_TYPES = {"ARCH_FLOOR_PLAN", "FURNITURE_PLAN", "PARKING_PLAN", "ROOF_PLAN",
              "LINTEL_PLAN", "SLOPE_PLAN", "PRIMARY_FLOOR", "ROOF", "SITE"}

# Seven source annotations are owner-reviewed existence labels, not learned
# detector rules.  The exact complete-file hash is the guard; no label may be
# transferred to another revision or project.
OWNER_FIXTURE_SOURCE_SHA256 = "43c696a6e2703ce746d22b169b90108f0a6a44d3873e56e32f80124793fe1d70"
OWNER_DOOR_FIXTURES = (
    ("OWNER-DOOR-U01", "vehicle_gate", tuple(f"{value:X}" for value in range(int("4307C5", 16), int("4307DB", 16)+1))),
    ("OWNER-DOOR-U02", "elevator_access", tuple(f"{value:X}" for value in range(int("43071B", 16), int("43071E", 16)+1))),
    ("OWNER-DOOR-U03", "elevator_access", tuple(f"{value:X}" for value in range(int("431001", 16), int("431004", 16)+1))),
    ("OWNER-DOOR-U04", "elevator_access", tuple(f"{value:X}" for value in range(int("4318CC", 16), int("4318CF", 16)+1))),
    ("OWNER-DOOR-U05", "elevator_access", tuple(f"{value:X}" for value in range(int("432596", 16), int("432599", 16)+1))),
    ("OWNER-DOOR-U06", "balcony_access", tuple(f"{value:X}" for value in range(int("4311D6", 16), int("4311DC", 16)+1))),
    ("OWNER-DOOR-U07", "balcony_access", tuple(f"{value:X}" for value in range(int("431A81", 16), int("431A87", 16)+1))),
)


def _hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode()).hexdigest()


def _in_bounds(point, bounds, tolerance=1e-8):
    return bool(bounds and bounds[0]-tolerance <= point[0] <= bounds[2]+tolerance
                and bounds[1]-tolerance <= point[1] <= bounds[3]+tolerance)


def _frame_for(point, frames):
    matches = [row for row in frames if _in_bounds(point, row.get("bounds"))]
    if len(matches) != 1:
        return None, "AMBIGUOUS_FRAME" if matches else "OUTSIDE_CONFIRMED_FRAME"
    frame = matches[0]
    if (frame.get("drawing_type") or frame.get("frame_type")) not in PLAN_TYPES:
        return frame, "NON_PLAN_VIEW"
    return frame, "PLAN_VIEW"


def _source_ref(row):
    # Virtual block children can reuse definition handles in every INSERT.
    # Preserve the instance identity so distinct placed openings never collapse.
    own = row.get("handle") or _hash(row)[:16]
    insert = row.get("source_insert_handle")
    return f"{insert}/{own}" if insert else own


def _points(row):
    if row.get("entity_type") == "LINE":
        return [row["start"], row["end"]]
    if row.get("entity_type") == "ARC":
        center = row["center"]
        points = [center] + list(row.get("arc_endpoints") or [])
        start = float(row.get("start_angle") or 0) % 360
        sweep = float(row.get("signed_sweep_degrees") or 0)
        radius = float(row.get("radius") or 0)
        def on_arc(angle):
            return ((angle-start) % 360 <= sweep+1e-8) if sweep >= 0 else ((start-angle) % 360 <= -sweep+1e-8)
        points.extend([center[0]+radius*math.cos(math.radians(angle)),
                       center[1]+radius*math.sin(math.radians(angle))]
                      for angle in (0, 90, 180, 270) if on_arc(angle))
        return points
    return []


def _bounds(rows):
    points = [point for row in rows for point in _points(row)]
    if not points:
        return None
    values = np.asarray(points, dtype=float)
    return [float(values[:, 0].min()), float(values[:, 1].min()),
            float(values[:, 0].max()), float(values[:, 1].max())]


def _insert_signature(rows):
    """Rotation/reflection/translation/scale invariant nested-geometry signature."""
    lines = [row for row in rows if row.get("entity_type") == "LINE"]
    arcs = [row for row in rows if row.get("entity_type") == "ARC"]
    if not lines or not arcs:
        return None
    scale = max(float(row.get("radius") or 0) for row in arcs)
    if scale <= 1e-12:
        return None
    points = np.asarray(
        [point for row in lines for point in (row["start"], row["end"])] +
        [row["center"] for row in arcs], dtype=float)
    points = (points-points.mean(axis=0))/scale
    distances = np.linalg.norm(points[:, None, :]-points[None, :, :], axis=2)
    distances = np.sort(distances[np.triu_indices(len(points), 1)])
    payload = {
        "counts": [len(lines), len(arcs)],
        "line_lengths": sorted(round(math.dist(row["start"], row["end"])/scale, 6) for row in lines),
        "arc_radii": sorted(round(float(row["radius"])/scale, 6) for row in arcs),
        "arc_sweeps": sorted(round(abs(float(row.get("signed_sweep_degrees") or 0)), 4) for row in arcs),
        "pairwise": [round(float(value), 6) for value in distances],
    }
    tolerance = max(scale*.02, 1e-9)
    payload["hinge_relation_count"] = sum(
        1 for arc in arcs for endpoint in (arc.get("arc_endpoints") or [])
        if any((math.dist(line["start"], arc["center"]) <= tolerance and
                math.dist(line["end"], endpoint) <= tolerance) or
               (math.dist(line["end"], arc["center"]) <= tolerance and
                math.dist(line["start"], endpoint) <= tolerance) for line in lines))
    return _hash(payload), payload


def _placed_orientation_signature(rows):
    bounds = _bounds(rows)
    if not bounds:
        return None
    scale = max(bounds[2]-bounds[0], bounds[3]-bounds[1], 1e-12)
    payload = []
    for row in rows:
        if row.get("entity_type") == "LINE":
            points = sorted((row["start"], row["end"]))
            payload.append(["L", *[[round((p[0]-bounds[0])/scale, 6),
                                      round((p[1]-bounds[1])/scale, 6)] for p in points]])
        elif row.get("entity_type") == "ARC":
            payload.append(["A", round((row["center"][0]-bounds[0])/scale, 6),
                            round((row["center"][1]-bounds[1])/scale, 6),
                            round(float(row["radius"])/scale, 6),
                            round(float(row.get("signed_sweep_degrees") or 0), 4)])
    return _hash(sorted(payload, key=str))


def _is_calibrated_hinged_family(payload, family_count):
    """Bounded candidate family; calibrated, never universal semantic truth."""
    line_count, arc_count = payload.get("counts") or [0, 0]
    if family_count < 2 or arc_count != 7 or not 18 <= line_count <= 26:
        return False
    sweeps = payload.get("arc_sweeps") or []
    return bool(sweeps and all(70 <= value <= 110 for value in sweeps)
                and sum(85 <= value <= 95 for value in sweeps) >= 4
                and payload.get("hinge_relation_count", 0) >= 1)


def _insert_door_candidates(primitives, *, source_sha256, frames):
    groups = defaultdict(list)
    by_handle = {}
    for row in primitives:
        handle = row.get("source_insert_handle")
        if handle:
            groups[str(handle)].append(row)
        own = row.get("handle")
        if own:
            by_handle[str(own)] = row
    signatures = {}
    families = defaultdict(list)
    for handle, rows in groups.items():
        signature = _insert_signature(rows)
        if signature:
            signatures[handle] = signature
            families[signature[0]].append(handle)
    candidates = []
    for signature_hash, handles in families.items():
        payload = signatures[handles[0]][1]
        if not _is_calibrated_hinged_family(payload, len(handles)):
            continue
        for handle in handles:
            rows = groups[handle]
            bounds = _bounds(rows)
            if not bounds:
                continue
            center = [(bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2]
            frame, scope = _frame_for(center, frames)
            refs = sorted(f"{handle}/{_source_ref(row)}" for row in rows)
            candidates.append({
                "opening_evidence_id": "OPEN-"+_hash([source_sha256, "insert-door", signature_hash, refs])[:20].upper(),
                "kind": "door", "status": "CANDIDATE", "confidence": .82,
                "automatic_confidence": .82,
                "score_meaning": "HEURISTIC_RULE_STRENGTH_NOT_MEASURED_ACCURACY",
                "automatic_method": "REPEATED_INVARIANT_INSERT_TEMPLATE",
                "mechanism": "hinged", "mechanism_status": "GEOMETRY_SUPPORTED",
                "frame_id": (frame or {}).get("plan_id") or (frame or {}).get("frame_id"), "view_scope": scope,
                "geometry": {"point": center, "bounds": bounds},
                "source_refs": refs,
                "source_insert_handles": [handle],
                "evidence": {"template_signature": signature_hash,
                             "family_instance_count": len(handles),
                             "primitive_count": len(rows),
                             "calibration_status": "SINGLE_SOURCE_UNVALIDATED_HOLDOUT"},
                "owner_review": None,
                "authority": {"material_geometry": False, "portal": False, "access_edge": False},
            })
    # Coincident source INSERTs represent one drawn door; preserve every handle.
    deduplicated = {}
    for row in candidates:
        bounds = row["geometry"]["bounds"]
        handle = row["source_insert_handles"][0]
        key = (row["evidence"]["template_signature"], _placed_orientation_signature(groups[handle]),
               *(round(value, 7) for value in bounds))
        if key not in deduplicated:
            deduplicated[key] = row
            continue
        existing = deduplicated[key]
        existing["source_insert_handles"].extend(row["source_insert_handles"])
        existing["source_refs"] = sorted(set(existing["source_refs"]+row["source_refs"]))
        existing["evidence"]["coincident_source_instances"] = len(existing["source_insert_handles"])

    fixtures = []
    if source_sha256 == OWNER_FIXTURE_SOURCE_SHA256:
        for fixture_id, contextual_subtype, handles in OWNER_DOOR_FIXTURES:
            rows = [by_handle[handle] for handle in handles if handle in by_handle]
            if len(rows) != len(handles):
                continue
            bounds = _bounds(rows)
            center = [(bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2]
            frame, scope = _frame_for(center, frames)
            fixtures.append({
                "opening_evidence_id": fixture_id, "kind": "door",
                "status": "OWNER_CONFIRMED_SOURCE_FIXTURE", "confidence": None,
                "automatic_confidence": None, "owner_review_confidence": 1.0,
                "automatic_method": None, "mechanism": None,
                "mechanism_status": "NOT_CONFIRMED",
                "contextual_subtype": contextual_subtype,
                "contextual_subtype_status": "CONTEXT_INFERRED_NOT_OWNER_CONFIRMED",
                "frame_id": (frame or {}).get("plan_id") or (frame or {}).get("frame_id"),
                "view_scope": scope, "geometry": {"point": center, "bounds": bounds},
                "source_refs": list(handles),
                "evidence": {"source_hash_guard": source_sha256,
                             "fixture_scope": "EXACT_SOURCE_PROJECT_ONLY"},
                "authority": {"material_geometry": False, "portal": False, "access_edge": False},
            })
    return list(deduplicated.values()), fixtures


def detect_opening_evidence(primitives, *, source_sha256, frames=()):
    """Return grouped candidates with geometry/provenance and view scope."""
    lines = []
    arcs = []
    for row in primitives:
        if row.get("pre_topology_object_class") in {"DETAIL_GRAPHIC", "SECTION_CUT", "SHEET_FRAME"}:
            continue
        if row.get("entity_type") == "LINE" and row.get("start") and row.get("end"):
            p, q = row["start"], row["end"]
            if math.dist(p, q) > 1e-9:
                lines.append(row)
        elif row.get("entity_type") == "ARC" and row.get("center") and row.get("radius"):
            arcs.append(row)
    if not lines:
        return {"schema": SCHEMA, "detector_revision": DETECTOR_REVISION,
                "source_sha256": source_sha256, "calibration": CALIBRATION,
                "items": [], "metrics": {"door_candidates": 0, "window_candidates": 0}}

    p = np.asarray([row["start"] for row in lines], dtype=float)
    q = np.asarray([row["end"] for row in lines], dtype=float)
    direction = q-p
    length = np.linalg.norm(direction, axis=1)
    unit = direction/length[:, None]
    origin = (np.minimum(p, q).min(axis=0)+np.maximum(p, q).max(axis=0))/2
    pc, qc = p-origin, q-origin
    items = []
    seen = set()

    insert_doors, owner_fixtures = _insert_door_candidates(
        primitives, source_sha256=source_sha256, frames=frames)
    items.extend(insert_doors)
    items.extend(owner_fixtures)
    insert_door_handles = {str(handle) for row in insert_doors
                           for handle in row.get("source_insert_handles") or []}

    def support(u, a, b, off_low, off_high, tolerance, angle_tolerance,
                minimum_pairs=2, require_distinct_faces=True):
        v = np.array([-u[1], u[0]])
        low = np.minimum(pc@u, qc@u); high = np.maximum(pc@u, qc@u)
        offset = (pc+qc)@v/2; span = max(b-a, 1e-12)
        mask = ((np.abs(unit@v) <= angle_tolerance) &
                (offset >= off_low-tolerance) & (offset <= off_high+tolerance) &
                (length > .2*span))
        left = np.where(mask & (np.abs(high-a) <= tolerance) & (low < a-.2*span))[0]
        right = np.where(mask & (np.abs(low-b) <= tolerance) & (high > b+.2*span))[0]
        pairs = [(int(i), int(j)) for i in left for j in right
                 if abs(offset[i]-offset[j]) <= tolerance]
        if len(pairs) < minimum_pairs:
            return []
        offsets = [float(offset[i]) for i, _ in pairs]
        if require_distinct_faces and max(offsets)-min(offsets) < .01*span:
            return []
        return sorted({index for pair in pairs for index in pair})

    # Door candidates require a quarter-swing, a radial leaf and two-sided
    # interrupted boundary context.  Unknown mechanisms remain unknown.
    for arc in arcs:
        if str(arc.get("source_insert_handle")) in insert_door_handles:
            continue
        center = np.asarray(arc["center"], dtype=float)
        sweep = abs(float(arc.get("signed_sweep_degrees") or
                          ((arc.get("end_angle", 0)-arc.get("start_angle", 0)) % 360)))
        if not 70 <= sweep <= 110:
            continue
        # Exploded consultant symbols commonly offset the leaf endpoints from
        # the construction-arc center/end by trim thickness. Eight percent is
        # bounded and still requires either interrupted-wall support or an
        # explicit wall-layer cue; it is not a free proximity classifier.
        radius = float(arc["radius"]); tolerance = max(.08*radius, 1e-9)
        endpoints = list(arc.get("arc_endpoints") or [])
        if len(endpoints) != 2:
            points = arc.get("points") or []
            endpoints = [points[0], points[-1]] if len(points) >= 2 else []
        if len(endpoints) != 2:
            continue
        endpoints = [np.asarray(value, dtype=float) for value in endpoints]
        for endpoint_index in range(2):
            leaf = np.where((((np.linalg.norm(p-center, axis=1) <= tolerance) &
                              (np.linalg.norm(q-endpoints[endpoint_index], axis=1) <= tolerance)) |
                             ((np.linalg.norm(q-center, axis=1) <= tolerance) &
                              (np.linalg.norm(p-endpoints[endpoint_index], axis=1) <= tolerance))))[0]
            if not len(leaf):
                continue
            u = (endpoints[1-endpoint_index]-center)/radius
            v = np.array([-u[1], u[0]])
            a = float((center-origin)@u); off = float((center-origin)@v)
            context = support(u, a, a+radius, off-.3*radius, off+.3*radius,
                              tolerance, CALIBRATION["adjacent_support_angle_tolerance"])
            layer_wall_support = "wall" in str(arc.get("layer") or "").lower()
            if not context and not layer_wall_support:
                continue
            leaf_index = int(leaf[0]); refs = sorted({_source_ref(arc), _source_ref(lines[leaf_index])})
            frame, scope = _frame_for(center, frames)
            identity = [source_sha256, "door", refs, [round(float(x), 7) for x in center]]
            key = tuple(identity[2])
            if key in seen:
                continue
            seen.add(key)
            score = .72 if context else .45
            items.append({"opening_evidence_id": "OPEN-"+_hash(identity)[:20].upper(),
                          "kind": "door", "status": ("CANDIDATE" if context else "CANDIDATE_CONTEXT_UNCONFIRMED"),
                          "confidence": score,
                          "automatic_confidence": score,
                          "score_meaning": "HEURISTIC_RULE_STRENGTH_NOT_MEASURED_ACCURACY",
                          "mechanism": "hinged" if arc.get("source_insert_handle") else "unknown",
                          "mechanism_status": "GEOMETRY_SUPPORTED" if arc.get("source_insert_handle") else "UNCONFIRMED",
                          "frame_id": (frame or {}).get("plan_id") or (frame or {}).get("frame_id"), "view_scope": scope,
                          "geometry": {"point": center.tolist(),
                                       "bounds": _bounds([arc, lines[leaf_index]]),
                                       "leaf_points": [p[leaf_index].tolist(), q[leaf_index].tolist()]},
                          "source_refs": refs,
                          "evidence": {"arc_id": _source_ref(arc), "leaf_ids": [_source_ref(lines[leaf_index])],
                                       "opening_support_ids": [_source_ref(lines[x]) for x in context],
                                       "supporting_wall_layer_not_geometry_authority": arc.get("layer") if layer_wall_support else None,
                                       "arc_sweep_degrees": sweep, "ocs_to_wcs": bool(arc.get("ocs_to_wcs"))},
                          "authority": {"material_geometry": False, "portal": False, "access_edge": False}})
            break

    # Some exploded plans retain the swing curves but omit a radial leaf line.
    # Preserve only conspicuously large, clustered wall-layer curves as low-
    # confidence review candidates. This closes a false-negative channel while
    # explicitly withholding hinged-mechanism and opening authority.
    arc_radii = sorted(float(row.get("radius") or 0) for row in arcs if float(row.get("radius") or 0) > 0)
    median_arc_radius = arc_radii[len(arc_radii)//2] if arc_radii else 0
    curve_clusters = defaultdict(list)
    for arc in arcs:
        center = arc.get("center")
        sweep = abs(float(arc.get("signed_sweep_degrees") or 0))
        if (center and median_arc_radius and 65 <= sweep <= 115
                and float(arc.get("radius") or 0) >= 5*median_arc_radius
                and "wall" in str(arc.get("layer") or "").lower()):
            curve_clusters[(round(center[0], 6), round(center[1], 6))].append(arc)
    existing_centers = {(round(row["geometry"]["point"][0], 6), round(row["geometry"]["point"][1], 6))
                        for row in items if row.get("kind") == "door" and row.get("geometry", {}).get("point")}
    for center_key, cluster in curve_clusters.items():
        if center_key in existing_centers:
            continue
        # Compass/north symbols commonly form dense radial rosettes around one
        # center. Door swings in the reviewed holdouts have at most four
        # co-centered construction arcs.
        if len(cluster) > 4:
            continue
        arc = max(cluster, key=lambda row: float(row.get("radius") or 0))
        center = list(arc["center"]); frame, scope = _frame_for(center, frames)
        refs = sorted(_source_ref(row) for row in cluster)
        identity = [source_sha256, "door-swing-curve-review", refs, center_key]
        items.append({
            "opening_evidence_id": "OPEN-"+_hash(identity)[:20].upper(),
            "kind": "door", "status": "CANDIDATE_CONTEXT_UNCONFIRMED",
            "confidence": .35, "automatic_confidence": .35,
            "score_meaning": "HEURISTIC_RULE_STRENGTH_NOT_MEASURED_ACCURACY",
            "mechanism": None, "mechanism_status": "NOT_CONFIRMED_CURVE_ONLY",
            "frame_id": (frame or {}).get("plan_id") or (frame or {}).get("frame_id"),
            "view_scope": scope,
            "geometry": {"point": center, "bounds": _bounds(cluster)},
            "source_refs": refs,
            "evidence": {"method": "LARGE_CLUSTERED_WALL_LAYER_SWING_CURVE_REVIEW",
                         "cluster_arc_count": len(cluster),
                         "median_source_arc_radius": median_arc_radius,
                         "representative_radius": float(arc["radius"]),
                         "leaf_relation": "NOT_FOUND",
                         "supporting_wall_layer_not_geometry_authority": arc.get("layer")},
            "authority": {"material_geometry": False, "portal": False, "access_edge": False},
        })

    # Window candidates: three or more coextensive panes, bounded matching
    # endcaps, and two interrupted boundary faces.  Extended outer lines remain
    # context only and are never deleted or counted as panes.
    for i in range(len(lines)):
        u = unit[i].copy(); v = np.array([-u[1], u[0]])
        parallel = np.where(np.abs(unit@v) <= CALIBRATION["pane_angle_tolerance"])[0]
        if len(parallel) < 3:
            continue
        a = np.minimum(pc[parallel]@u, qc[parallel]@u)
        b = np.maximum(pc[parallel]@u, qc[parallel]@u)
        off = (pc[parallel]+qc[parallel])@v/2
        own = int(np.where(parallel == i)[0][0]); span = length[i]; tolerance = max(.02*span, 1e-9)
        near = np.where((np.abs(a-a[own]) <= tolerance) & (np.abs(b-b[own]) <= tolerance) &
                        (np.abs(off-off[own]) <= CALIBRATION["window_frame_ratio_max"]*span))[0]
        unique = []
        for index in sorted(near, key=lambda x: off[x]):
            if not unique or abs(off[index]-off[unique[-1]]) > 1e-6*span:
                unique.append(int(index))
        if len(unique) < 3:
            continue
        selected = tuple(sorted(int(parallel[x]) for x in near))
        pane_key = tuple(sorted(_source_ref(lines[x]) for x in selected))
        if pane_key in seen:
            continue
        low, high = float(min(off[near])), float(max(off[near]))
        spread = high-low
        if not .01*span <= spread <= CALIBRATION["window_frame_ratio_max"]*span:
            continue
        along = (pc+qc)@u/2; transverse_low = np.minimum(pc@v, qc@v); transverse_high = np.maximum(pc@v, qc@v)
        caps = []
        for end in (a[own], b[own]):
            caps.append(np.where((np.abs(unit@u) <= CALIBRATION["pane_angle_tolerance"]) &
                                 (np.abs(along-end) <= tolerance) &
                                 (transverse_low <= low+tolerance) & (transverse_high >= high-tolerance) &
                                 ((transverse_high-transverse_low) <= CALIBRATION["window_frame_ratio_max"]*span+tolerance))[0])
        accepted = None
        relaxed_path = None
        for cap0 in caps[0]:
            for cap1 in caps[1]:
                if abs(transverse_low[cap0]-transverse_low[cap1]) > tolerance or abs(transverse_high[cap0]-transverse_high[cap1]) > tolerance:
                    continue
                frame_low = float(min(transverse_low[cap0], transverse_low[cap1])); frame_high = float(max(transverse_high[cap0], transverse_high[cap1]))
                context = support(u, float(a[own]), float(b[own]), frame_low, frame_high,
                                  tolerance, CALIBRATION["adjacent_support_angle_tolerance"])
                if context:
                    accepted = (int(cap0), int(cap1), context, frame_low, frame_high)
                    break
            if accepted:
                break
        if not accepted:
            # Some consultant drawings encode a real four-pane window at a
            # wall/door junction with only one interrupted boundary face. A
            # bounded fallback is allowed only for exactly four distinct panes
            # and explicit jamb/support geometry; generic parallel linework is
            # still rejected. Strict candidates remain preferred below.
            if len(unique) != 4:
                continue
            # The incomplete-jamb convention was observed only on horizontal
            # windows inside confirmed plan frames. Keep this deliberately
            # narrower than the rotation-invariant strict detector: otherwise
            # four-line furniture details and elevation linework become false
            # positives on the holdout set.
            fallback_center = ((p[i]+q[i])/2).tolist()
            _, fallback_scope = _frame_for(fallback_center, frames)
            if (fallback_scope != "PLAN_VIEW" or
                    abs(float(u[1])) > CALIBRATION["adjacent_support_angle_tolerance"]):
                continue
            for cap0 in caps[0]:
                for cap1 in caps[1]:
                    if abs(transverse_low[cap0]-transverse_low[cap1]) > tolerance or abs(transverse_high[cap0]-transverse_high[cap1]) > tolerance:
                        continue
                    frame_low = float(min(transverse_low[cap0], transverse_low[cap1])); frame_high = float(max(transverse_high[cap0], transverse_high[cap1]))
                    context = support(u, float(a[own]), float(b[own]), frame_low, frame_high,
                                      tolerance, CALIBRATION["adjacent_support_angle_tolerance"],
                                      minimum_pairs=1, require_distinct_faces=False)
                    if context:
                        accepted = (int(cap0), int(cap1), context, frame_low, frame_high)
                        relaxed_path = "FOUR_PANE_SINGLE_BOUNDARY_FACE"
                        break
                if accepted:
                    break
            if not accepted and len(caps[0])+len(caps[1]) == 1:
                cap = int(caps[0][0] if len(caps[0]) else caps[1][0])
                frame_low = float(transverse_low[cap]); frame_high = float(transverse_high[cap])
                low_all = np.minimum(pc@u, qc@u); high_all = np.maximum(pc@u, qc@u)
                offsets_all = (pc+qc)@v/2
                mask = ((np.abs(unit@v) <= CALIBRATION["adjacent_support_angle_tolerance"]) &
                        (offsets_all >= frame_low-tolerance) & (offsets_all <= frame_high+tolerance) &
                        (length > .2*span))
                left = np.where(mask & (np.abs(high_all-a[own]) <= tolerance) &
                                (low_all < a[own]-.2*span))[0]
                right = np.where(mask & (np.abs(low_all-b[own]) <= tolerance) &
                                 (high_all > b[own]+.2*span))[0]
                one_sided = sorted({int(index) for index in (*left, *right)})
                if one_sided:
                    cap0 = cap if len(caps[0]) else None
                    cap1 = cap if len(caps[1]) else None
                    accepted = (cap0, cap1, one_sided, frame_low, frame_high)
                    relaxed_path = "FOUR_PANE_SINGLE_ENDCAP_AND_BOUNDARY_SUPPORT"
            if not accepted:
                continue
        cap0, cap1, context, frame_low, frame_high = accepted
        full_a = np.minimum(pc@u, qc@u); full_b = np.maximum(pc@u, qc@u); full_off = (pc+qc)@v/2
        extended = np.where((np.abs(unit@v) < CALIBRATION["adjacent_support_angle_tolerance"]) &
                            (full_a <= a[own]+tolerance) & (full_b >= b[own]-tolerance) &
                            ((full_a < a[own]-tolerance) | (full_b > b[own]+tolerance)) &
                            ((np.abs(full_off-frame_low) <= tolerance) | (np.abs(full_off-frame_high) <= tolerance)))[0]
        center = ((p[i]+q[i])/2).tolist(); frame, scope = _frame_for(center, frames)
        seen.add(pane_key)
        identity = [source_sha256, "window", pane_key]
        score = .52 if relaxed_path else .68
        items.append({"opening_evidence_id": "OPEN-"+_hash(identity)[:20].upper(),
                      "kind": "window", "status": ("CANDIDATE_CONTEXT_UNCONFIRMED" if relaxed_path else "CANDIDATE"), "confidence": score,
                      "automatic_confidence": score,
                      "score_meaning": "HEURISTIC_RULE_STRENGTH_NOT_MEASURED_ACCURACY",
                      "frame_id": (frame or {}).get("plan_id") or (frame or {}).get("frame_id"), "view_scope": scope,
                      "geometry": {"point": center, "bounds": [float(min(p[selected,0].min(),q[selected,0].min())),
                                                                  float(min(p[selected,1].min(),q[selected,1].min())),
                                                                  float(max(p[selected,0].max(),q[selected,0].max())),
                                                                  float(max(p[selected,1].max(),q[selected,1].max()))]},
                      "source_refs": list(pane_key),
                      "native_pane_ids": [lines[x].get('native_source_id') for x in selected],
                      "native_endcap_ids": [lines[x].get('native_source_id') for x in (cap0,cap1) if x is not None],
                      "native_support_ids": [lines[x].get('native_source_id') for x in context],
                      "evidence": {"pane_ids": list(pane_key), "endcap_ids": [_source_ref(lines[x]) for x in (cap0, cap1) if x is not None],
                                   "opening_support_ids": [_source_ref(lines[x]) for x in context],
                                   "context_only_extended_boundary_ids": [_source_ref(lines[int(x)]) for x in extended],
                                   "distinct_panes": len(unique), "span": float(span), "frame_spread": float(frame_high-frame_low),
                                   "detection_path": relaxed_path or "STRICT_TWO_FACE_OPENING_SUPPORT"},
                      "authority": {"material_geometry": False, "portal": False, "access_edge": False}})

    # Suppress weaker sub-span rediscoveries of an already accepted strict
    # window. This is geometry-only and preserves spatially distinct siblings.
    strict_windows = [row for row in items if row.get("kind") == "window" and
                      row.get("evidence", {}).get("detection_path") == "STRICT_TWO_FACE_OPENING_SUPPORT"]
    def overlap_ratio(first, second):
        a, b = first["geometry"]["bounds"], second["geometry"]["bounds"]
        ix = max(0.0, min(a[2], b[2])-max(a[0], b[0]))
        iy = max(0.0, min(a[3], b[3])-max(a[1], b[1]))
        area = max((a[2]-a[0])*(a[3]-a[1]), 1e-12)
        return ix*iy/area
    items = [row for row in items if not (
        row.get("kind") == "window" and
        row.get("evidence", {}).get("detection_path") in {
            "FOUR_PANE_SINGLE_BOUNDARY_FACE", "FOUR_PANE_SINGLE_ENDCAP_AND_BOUNDARY_SUPPORT"} and
        any(overlap_ratio(row, strict) > .5 for strict in strict_windows))]

    items.sort(key=lambda row: row["opening_evidence_id"])
    counts = Counter(row["kind"] for row in items)
    return {"schema": SCHEMA, "detector_revision": DETECTOR_REVISION,
            "source_sha256": source_sha256, "calibration": CALIBRATION,
            "items": items,
            "metrics": {"door_candidates": counts["door"],
                        "automatic_door_candidates": sum(
                            row["kind"] == "door" and row.get("automatic_confidence") is not None for row in items),
                        "automatic_door_plan_view_candidates": sum(
                            row["kind"] == "door" and row.get("automatic_confidence") is not None
                            and row["view_scope"] == "PLAN_VIEW" for row in items),
                        "automatic_door_unscoped_candidates": sum(
                            row["kind"] == "door" and row.get("automatic_confidence") is not None
                            and row["view_scope"] != "PLAN_VIEW" for row in items),
                        "owner_confirmed_door_annotations": len(owner_fixtures),
                        "window_candidates": counts["window"],
                        "window_plan_view_candidates": sum(
                            row["kind"] == "window" and row["view_scope"] == "PLAN_VIEW" for row in items),
                        "window_non_plan_or_unscoped_candidates": sum(
                            row["kind"] == "window" and row["view_scope"] != "PLAN_VIEW" for row in items),
                        "plan_view_candidates": sum(row["view_scope"] == "PLAN_VIEW" for row in items),
                        "non_plan_or_unscoped_candidates": sum(row["view_scope"] != "PLAN_VIEW" for row in items)}}

