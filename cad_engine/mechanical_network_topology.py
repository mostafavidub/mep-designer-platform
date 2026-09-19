"""Fail-closed route-grade mechanical topology authority for v19.

This module extracts logical network topology from actual architectural/fixture
geometry and PMM v3 levels. It deliberately does not provide numeric sizing,
materials, slopes, provisional shafts, hidden offsets, or benchmark-derived
routing defaults. Missing route-grade evidence remains INPUT_REQUIRED.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
import re

from .architecture_reconstruction import reconstruct_architecture
from .fixture_recognition import recognize_fixtures_equipment
from .routing import _open_space_route


GRAPH_SCHEMA = "mechanical-network-graph/1"
PLUMBING_SYSTEMS = {"cold_water", "hot_water", "sanitary", "vent"}
SOURCE_TYPES = {
    "cold_water": {"tank", "pump"},
    "hot_water": {"water_heater"},
    "refrigerant_liquid": {"split_outdoor"},
    "refrigerant_gas": {"split_outdoor"},
    "exhaust": {"exhaust_fan"},
}
EVIDENCE_TYPE_MAP = {"toilet": "wc", "bath": "shower", "gas": "stove", "faucet": "basin"}
EVIDENCE_PORTS = {
    "wc": ["cold_water", "sanitary", "vent"],
    "basin": ["cold_water", "hot_water", "sanitary", "vent"],
    "sink": ["cold_water", "hot_water", "sanitary", "vent"],
    "shower": ["cold_water", "hot_water", "sanitary", "vent"],
    "stove": ["gas"],
}
LEVEL_TYPES = {"GROUND", "FIRST", "SECOND", "ROOF", "BASEMENT", "MEZZANINE"}
PERSIAN_ORDINALS = {
    "اول": 1, "یکم": 1, "دوم": 2, "سوم": 3, "چهارم": 4, "پنجم": 5,
    "ششم": 6, "هفتم": 7, "هشتم": 8, "نهم": 9, "دهم": 10,
}


def _norm(value):
    value = str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").lower()
    value = re.sub(r"[_./\\:;,-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _stable(prefix, payload):
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return prefix + "-" + sha256(raw.encode("utf-8")).hexdigest()[:14].upper()


def _ordinal(value):
    text = _norm(value)
    if text in PERSIAN_ORDINALS:
        return PERSIAN_ORDINALS[text]
    match = re.fullmatch(r"(?:floor|level)?\s*(\d+)(?:st|nd|rd|th)?", text)
    return int(match.group(1)) if match else None


def _typical_level(text):
    patterns = (
        r"طبقات?\s+(\S+)\s+تا\s+(\S+)",
        r"(?:typical\s+)?floors?\s+(\d+(?:st|nd|rd|th)?)\s+(?:to|through)\s+(\d+(?:st|nd|rd|th)?)",
        r"(?:typical\s+)?floors?\s+(\d+)\s+(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        start, end = _ordinal(match.group(1)), _ordinal(match.group(2))
        if start and end and start <= end:
            return f"TYPICAL_{start}_{end}"
    return None


def valid_level_type(value):
    text = str(value or "").upper()
    return text in LEVEL_TYPES or bool(re.fullmatch(r"TYPICAL_[1-9]\d*_[1-9]\d*", text))


def _typed_level(name, roof=False):
    text = _norm(name)
    if text.startswith("detail") or "دیتیل" in text:
        return None
    if roof or any(token in text for token in ("roof", "بام")):
        return "ROOF"
    if any(token in text for token in ("basement", "زیرزمین", "زيرزمين")):
        return "BASEMENT"
    if any(token in text for token in ("mezzanine", "نیم طبقه", "نيم طبقه")):
        return "MEZZANINE"
    if any(token in text for token in ("ground", "همکف")):
        return "GROUND"
    typical = _typical_level(text)
    if typical:
        return typical
    if any(token in text for token in ("first", "طبقه اول", "طبقه 1", "level 1", "floor 1")):
        return "FIRST"
    if any(token in text for token in ("second", "طبقه دوم", "طبقه 2", "level 2", "floor 2")):
        return "SECOND"
    return None


def _bounds(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = map(float, value)
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _inside(point, bounds):
    return bool(bounds and bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3])


def _room_host(point, level_name, rooms):
    """Return a unique source-backed room host using its polygon envelope."""
    matches = []
    for room in rooms or []:
        if room.get("level") and str(room.get("level")) != str(level_name):
            continue
        bounds = _bbox(room.get("polygon"))
        if _inside(point, bounds):
            matches.append(room)
    return matches[0] if len(matches) == 1 else None


def _level_registry(pmm):
    registry = []
    errors = []
    seen_types = set()
    for order, row in enumerate(pmm.get("levels") or []):
        name = str(row.get("name") or "").strip()
        level_type = _typed_level(name, bool(row.get("roof")))
        if not name:
            errors.append("LEVEL_NAME_REQUIRED")
            continue
        if not valid_level_type(level_type):
            errors.append("LEVEL_TYPE_REQUIRED:" + name)
            continue
        if level_type in seen_types:
            # Multiple titled viewports may describe one physical level (most
            # commonly roof/roof-access plans). Keep the richer bounded view as
            # the route authority and record the other as a duplicate view.
            prior = next(row for row in registry if row["type"] == level_type)
            prior_bounds = prior.get("region_bounds")
            candidate_bounds = _bounds(row.get("region_bounds"))
            if candidate_bounds and not prior_bounds:
                prior.update({"name": name, "id": _stable("LVL", {"name": name, "type": level_type}),
                              "region_bounds": candidate_bounds, "duplicate_view_names": [prior["name"]]})
            else:
                prior.setdefault("duplicate_view_names", []).append(name)
            continue
        seen_types.add(level_type)
        elevation = row.get("elevation_m")
        try:
            elevation = float(elevation) if elevation is not None else None
        except (TypeError, ValueError):
            errors.append("INVALID_LEVEL_ELEVATION:" + name)
            elevation = None
        registry.append({
            "id": _stable("LVL", {"name": name, "type": level_type}),
            "name": name,
            "type": level_type,
            "order": order,
            "region_bounds": _bounds(row.get("region_bounds")),
            "elevation_m": elevation,
        })
    return registry, sorted(set(errors))


def _resolve_explicit_level(value, levels):
    text = str(value or "").strip()
    if not text:
        return None
    matches = [row for row in levels if text in {row["id"], row["name"], row["type"], *(row.get("duplicate_view_names") or [])}]
    return matches[0] if len(matches) == 1 else None


def _assign_level(source_id, point, levels, assignments):
    explicit = (assignments or {}).get(source_id)
    if explicit is not None:
        return _resolve_explicit_level(explicit, levels), None if _resolve_explicit_level(explicit, levels) else "UNKNOWN_EXPLICIT_LEVEL:" + str(explicit)
    bounded = [row for row in levels if _inside(point, row.get("region_bounds"))]
    if len(bounded) == 1:
        return bounded[0], None
    if len(bounded) > 1:
        ranked = sorted((
            ((float(row["region_bounds"][2]) - float(row["region_bounds"][0]))
             * (float(row["region_bounds"][3]) - float(row["region_bounds"][1])), row)
            for row in bounded
        ), key=lambda item: item[0])
        if ranked[0][0] < ranked[1][0]:
            return ranked[0][1], None
        return None, "AMBIGUOUS_LEVEL_ASSIGNMENT:" + source_id
    if len(levels) == 1:
        return levels[0], None
    return None, "LEVEL_ASSIGNMENT_REQUIRED:" + source_id


def _resolve_level_for_point(source_id, explicit, point, levels, assignments):
    """Resolve a level only when its semantic label agrees with geometry.

    Upstream architecture evidence can carry a plausible level name while its
    coordinates still belong to a different viewport.  Trusting that label
    creates cross-sheet routes which only fail much later during CAD
    materialization.  A contradictory label is therefore treated as a hint:
    accept a unique spatial owner, otherwise fail closed with bounded evidence.
    """
    if explicit:
        labelled = _resolve_explicit_level(explicit, levels)
        if labelled and _inside(point, labelled.get("region_bounds")):
            return labelled, None
        spatial, spatial_error = _assign_level(source_id, point, levels, assignments)
        if (spatial and spatial_error is None
                and _inside(point, spatial.get("region_bounds"))):
            return spatial, None
        if not labelled:
            return None, "UNKNOWN_EXPLICIT_LEVEL:" + str(explicit)
        return None, "EXPLICIT_LEVEL_GEOMETRY_MISMATCH:%s:%s" % (source_id, explicit)
    return _assign_level(source_id, point, levels, assignments)


def _pmm_entity_id(pmm, detection):
    registry = (pmm.get("identity_registry") or {}).get("entities") or []
    dtype = detection.get("type")
    category = detection.get("category")
    if category == "fixture":
        matches = [row for row in registry if row.get("kind") == "fixture-group" and (row.get("fingerprint") or {}).get("type") == dtype]
        return matches[0].get("entity_id") if len(matches) == 1 else None
    aliases = (pmm.get("identity_registry") or {}).get("alias_to_entity_id") or {}
    return aliases.get(str(detection.get("id")))


def _centroid(poly):
    if not poly:
        return None
    return (sum(float(p[0]) for p in poly) / len(poly), sum(float(p[1]) for p in poly) / len(poly))


def _bbox(poly):
    if not poly:
        return None
    xs = [float(p[0]) for p in poly]
    ys = [float(p[1]) for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def _seg_hits_rect(a, b, rect):
    if not rect:
        return False
    x1, y1, x2, y2 = rect
    if a[0] == b[0]:
        x = a[0]
        return x1 <= x <= x2 and max(min(a[1], b[1]), y1) <= min(max(a[1], b[1]), y2)
    if a[1] == b[1]:
        y = a[1]
        return y1 <= y <= y2 and max(min(a[0], b[0]), x1) <= min(max(a[0], b[0]), x2)
    return True


def _ccw(a, b, c):
    return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])


def _intersects(a, b, c, d):
    if a == b or c == d:
        return False
    return _ccw(a, c, d) != _ccw(b, c, d) and _ccw(a, b, c) != _ccw(a, b, d)


def _clean(points):
    out = []
    for point in points:
        p = (float(point[0]), float(point[1]))
        if not out or p != out[-1]:
            out.append(p)
    if len(out) == 3:
        a, b, c = out
        if (a[0] == b[0] == c[0]) or (a[1] == b[1] == c[1]):
            return [a, c]
    return out


def _bounds_overlap(left, right):
    return bool(left and right and not (
        left[2] < right[0] or left[0] > right[2]
        or left[3] < right[1] or left[1] > right[3]
    ))


def _wall_bounds(wall):
    points = [tuple(point) for point in (wall.get("start"), wall.get("end"))
              if isinstance(point, (tuple, list)) and len(point) == 2]
    return _bbox(points)


def _orthogonal_path(start, end, walls, obstacles, route_bounds=None):
    if start == end:
        return None, None
    if route_bounds and (not _inside(start, route_bounds) or not _inside(end, route_bounds)):
        return None, "ROUTE_ENDPOINT_OUTSIDE_LEVEL_BOUNDS"
    # Architecture extraction contains walls and obstacles for every detected
    # viewport.  Routing one floor against another floor's geometry can send an
    # A* detour into a neighbouring plan board.  Keep the solver strictly local
    # to the owning level; this preserves plan/route coordinate identity.
    if route_bounds:
        walls = [wall for wall in walls or []
                 if _bounds_overlap(_wall_bounds(wall), route_bounds)]
        obstacles = [item for item in obstacles or []
                     if _bounds_overlap(_bbox(item.get("points") or item.get("polygon")), route_bounds)]
    # Score and search only geometry that can affect a bounded detour between
    # these terminals. Large multi-plan DXFs can contain tens of thousands of
    # otherwise valid wall segments in the same broad level envelope; scanning
    # every one for every network edge stalls before the first progress event.
    span=max(abs(float(end[0])-float(start[0])),abs(float(end[1])-float(start[1])),1.0)
    margin=max(1.0,min(25.0,span*.5))
    local_bounds=(min(start[0],end[0])-margin,min(start[1],end[1])-margin,
                  max(start[0],end[0])+margin,max(start[1],end[1])+margin)
    if route_bounds:
        local_bounds=(max(local_bounds[0],route_bounds[0]),max(local_bounds[1],route_bounds[1]),
                      min(local_bounds[2],route_bounds[2]),min(local_bounds[3],route_bounds[3]))
    walls=[wall for wall in walls or [] if _bounds_overlap(_wall_bounds(wall),local_bounds)]
    obstacles=[item for item in obstacles or []
               if _bounds_overlap(_bbox(item.get("points") or item.get("polygon")),local_bounds)]
    if start[0] == end[0] or start[1] == end[1]:
        candidates = [[start, end]]
    else:
        candidates = [[start, (end[0], start[1]), end], [start, (start[0], end[1]), end]]
    rects = [_bbox(item.get("points") or item.get("polygon")) for item in obstacles or []]
    def terminal_penetrations(points):
        counts = [
            sum(1 for wall in walls or [] if _intersects(a, b, tuple(wall.get("start") or ()), tuple(wall.get("end") or ())))
            for a, b in zip(points, points[1:])
        ]
        middle = counts[1:-1] if len(counts) > 2 else []
        # One sleeve at either endpoint is a constructible terminal penetration;
        # multiple or intermediate crossings remain hard routing clashes.
        if not any(middle) and counts and counts[0] <= 1 and counts[-1] <= 1:
            return counts[0] + (counts[-1] if len(counts) > 1 else 0)
        return None
    ranked = []
    for raw in candidates:
        points = _clean(raw)
        obstacle_hits = 0
        wall_crossings = 0
        for a, b in zip(points, points[1:]):
            obstacle_hits += sum(1 for rect in rects if _seg_hits_rect(a, b, rect))
            wall_crossings += sum(1 for wall in walls or [] if _intersects(a, b, tuple(wall.get("start") or ()), tuple(wall.get("end") or ())))
        ranked.append((obstacle_hits, wall_crossings, tuple(points), points))
    best = min(ranked, key=lambda row: (row[0], row[1], row[2]))
    if best[1] > 0:
        wall_points = [tuple(point) for wall in walls or [] for point in (wall.get("start") or (), wall.get("end") or ()) if isinstance(point, (tuple, list)) and len(point) == 2]
        xs = [start[0], end[0], *(point[0] for point in wall_points)]
        ys = [start[1], end[1], *(point[1] for point in wall_points)]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        margin = max(1.0, span * .02)
        bounds = tuple(route_bounds) if route_bounds else (
            min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin
        )
        open_route = _open_space_route(start, end, bounds, walls or [])
        # The graph and its eventual CAD board share the authoritative level
        # envelope.  A sparse-search result outside that envelope is not a
        # valid detour and must never reach materialization.  Reject the A*
        # candidate here and retain the already-ranked bounded orthogonal path;
        # do not clip or move any route point after engineering selection.
        if open_route and all(_inside(point, route_bounds or bounds) for point in open_route):
            obstacle_hits = sum(
                1 for a, b in zip(open_route, open_route[1:]) for rect in rects
                if _seg_hits_rect(a, b, rect)
            )
            wall_crossings = sum(
                1 for a, b in zip(open_route, open_route[1:]) for wall in walls or []
                if _intersects(a, b, tuple(wall.get("start") or ()), tuple(wall.get("end") or ()))
            )
            penetrations = terminal_penetrations(open_route)
            if obstacle_hits == 0 and penetrations is not None:
                metadata = {
                    "wall_crossings": 0,
                    "routing": "ORTHOGONAL_OPEN_SPACE_ASTAR" if not penetrations else "ORTHOGONAL_OPEN_SPACE_ASTAR_WITH_TERMINAL_SLEEVES",
                }
                if penetrations:
                    metadata["coordinated_terminal_penetrations"] = penetrations
                return open_route, metadata
    if best[0] == 0:
        penetrations = terminal_penetrations(best[3])
        if penetrations is not None:
            return best[3], {
                "wall_crossings": 0,
                "coordinated_terminal_penetrations": penetrations,
                "routing": "ORTHOGONAL_WITH_TERMINAL_SLEEVES",
            }
    if best[0]:
        return None, "ROUTE_INTERSECTS_STRUCTURAL_OBSTACLE"
    return best[3], {"wall_crossings": best[1], "routing": "ORTHOGONAL_PRE_COORDINATION"}


def _nearest(point, rows):
    return min(rows, key=lambda row: math.dist(point, row["point"])) if rows else None


def _architecture_from_evidence(model, fallback):
    if not isinstance(model, dict) or not model.get("levels"):
        return fallback
    rooms, shafts, wet_cores, walls, obstacles = [], [], [], [], []
    for level in model.get("levels") or []:
        if level.get("roof") and model.get("roof_scope_reliable") is False:
            # A title-like or reused occupied-floor view must not host owner-
            # declared fixtures as a roof. The upstream architecture analysis
            # already proved that this project has no reliable roof scope.
            continue
        level_name = level.get("name")
        for room in level.get("rooms") or []:
            normalized = dict(room)
            normalized["level"] = level_name
            normalized["centroid"] = tuple(room.get("center") or room.get("centroid") or room.get("label_point") or ())
            rooms.append(normalized)
            if room.get("type") == "shaft" and len(normalized["centroid"]) == 2:
                shafts.append({"centroid": normalized["centroid"], "polygon": room.get("polygon") or [],
                               "level": level_name, "source": "ARCHITECTURAL_SHAFT_ROOM"})
        for wet in level.get("wet_cores") or []:
            point = wet.get("center") or wet.get("centroid")
            if point:
                wet_cores.append({"centroid": tuple(point), "room_id": wet.get("id"), "level": level_name})
        walls.extend(level.get("walls") or [])
        obstacles.extend(level.get("columns") or [])
        for shaft in level.get("shafts") or []:
            point = shaft.get("center") or shaft.get("centroid")
            if point:
                shafts.append({"centroid": tuple(point), "polygon": shaft.get("polygon") or [],
                               "level": level_name, "source": "ARCHITECTURAL_SHAFT_GEOMETRY"})
    merged = dict(fallback)
    merged.update({"rooms": rooms, "shafts": shafts, "wet_cores": wet_cores,
                   "walls": walls or fallback.get("walls") or [],
                   "obstacles": obstacles or fallback.get("obstacles") or []})
    return merged


def _recognition_from_evidence(rows, fallback, architecture, declared_schedule=None):
    detections = []
    seen = set()
    for index, row in enumerate(rows or [], 1):
        if row.get("status") != "detected" or row.get("x") is None or row.get("y") is None:
            continue
        kind = EVIDENCE_TYPE_MAP.get(str(row.get("type")), str(row.get("type") or ""))
        if kind not in EVIDENCE_PORTS:
            continue
        signature = (kind, round(float(row["x"]), 5), round(float(row["y"]), 5))
        if signature in seen:
            continue
        seen.add(signature)
        detections.append({
            "id": "ARCH-EVIDENCE-%04d" % index, "category": "equipment" if kind == "stove" else "fixture",
            "type": kind, "point": (float(row["x"]), float(row["y"])), "ports": EVIDENCE_PORTS[kind],
            "room_id": row.get("room_id"), "level": row.get("level"), "installed": True,
            "evidence": ["ARCHITECTURE_FIXTURE_DETECTION", "USER_UPLOAD_ANALYSIS"],
        })
    if detections:
        return {"version": "canonical-architecture-evidence/1", "detections": detections, "candidates": []}

    # The questionnaire asks for the *actual* fixture counts when CAD symbols
    # are absent. Place those declared endpoints at architecture wet-core
    # service points and mark them declared/designed, never CAD-detected.
    counts = {}
    for key, value in re.findall(r"([A-Za-z_]+)\s+(\d+)", str(declared_schedule or "")):
        kind = EVIDENCE_TYPE_MAP.get(key.lower(), key.lower())
        if kind in EVIDENCE_PORTS:
            counts[kind] = counts.get(kind, 0) + int(value)
    wet = [row for row in architecture.get("wet_cores") or [] if len(tuple(row.get("centroid") or ())) == 2]
    if counts and wet:
        index = 0
        for kind, count in sorted(counts.items()):
            for occurrence in range(count):
                target = wet[index % len(wet)]; index += 1
                point = _distributed_declared_fixture_point(target, index, architecture)
                detections.append({
                    "id": "OWNER-DECLARED-%s-%03d" % (kind.upper(), occurrence + 1),
                    "category": "fixture", "type": kind, "point": point, "ports": EVIDENCE_PORTS[kind],
                    "room_id": target.get("room_id"), "level": target.get("level"), "installed": False,
                    "design_status": "DESIGNED_FROM_OWNER_DECLARED_COUNT",
                    "evidence": ["OWNER_QUESTIONNAIRE_ACTUAL_FIXTURE_COUNT", "ARCHITECTURE_WET_CORE_SERVICE_POINT"],
                })
        return {"version": "owner-declared-designed-endpoints/1", "detections": detections, "candidates": []}
    return fallback


def _distributed_declared_fixture_point(target, ordinal, architecture):
    """Place count-only fixtures near, but never exactly on, their wet-core node.

    Questionnaire counts identify real design endpoints but do not provide CAD
    insertion points. Collocating every endpoint with the wet-core aggregation
    node creates zero-length branches. This deterministic layout uses the
    matching room envelope when available and a drawing-scale-relative offset
    otherwise; it does not invent pipe sizes or engineering loads.
    """
    cx, cy = map(float, target["centroid"][:2])
    room_id = target.get("room_id")
    room = next((row for row in architecture.get("rooms") or []
                 if room_id and str(row.get("id")) == str(room_id)), None)
    polygon = (room or {}).get("polygon") or []
    xs = [float(point[0]) for point in polygon if len(point) >= 2]
    ys = [float(point[1]) for point in polygon if len(point) >= 2]
    directions = ((1, 0), (0, 1), (-1, 0), (0, -1),
                  (1, 1), (-1, 1), (-1, -1), (1, -1))
    direction = directions[(max(int(ordinal), 1) - 1) % len(directions)]
    if xs and ys and max(xs) > min(xs) and max(ys) > min(ys):
        width, height = max(xs) - min(xs), max(ys) - min(ys)
        step = max(min(width, height) * .08, 1e-6)
        margin_x, margin_y = width * .08, height * .08
        x = min(max(cx + direction[0] * step, min(xs) + margin_x), max(xs) - margin_x)
        y = min(max(cy + direction[1] * step, min(ys) + margin_y), max(ys) - margin_y)
    else:
        drawing_scale = max(abs(cx), abs(cy), 1.0)
        step = max(drawing_scale * .005, .05)
        x, y = cx + direction[0] * step, cy + direction[1] * step
    if math.dist((cx, cy), (x, y)) <= 1e-9:
        x = cx + max(abs(cx), abs(cy), 1.0) * .005
    return (round(x, 6), round(y, 6))


def _edge(system, from_node, to_node, role, endpoint_ids, levels, points=None, route_meta=None):
    edge_id = _stable("EDGE", {"system": system, "from": from_node, "to": to_node, "role": role, "levels": levels})
    calc_id = _stable("CALC", {"network_edge_id": edge_id})
    return {
        "id": edge_id,
        "system": system,
        "from": from_node,
        "to": to_node,
        "role": role,
        "endpoint_ids": sorted(set(endpoint_ids or [])),
        "levels": list(levels),
        "calc_id": calc_id,
        "plan_id": calc_id,
        "riser_id": calc_id,
        "schedule_id": calc_id,
        "plan_path": points or [],
        "draw_on_plan": bool(points),
        "route_status": (route_meta or {}).get("routing") if points else "LOGICAL_ONLY",
        "wall_crossings": (route_meta or {}).get("wall_crossings", 0),
        "coordinated_terminal_penetrations": (route_meta or {}).get("coordinated_terminal_penetrations", 0),
    }


def build_authoritative_topology_from_evidence(
    pmm, architecture, recognition, level_assignments=None, shaft_strategy=None,
):
    """Build one deterministic graph from PMM levels and installed DXF evidence."""
    if (pmm or {}).get("schema") != "project-mechanical-model/v3":
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["PROJECT_MECHANICAL_MODEL_V3"], "network": None}
    levels, level_errors = _level_registry(pmm or {})
    if level_errors or not levels:
        return {"status": "INPUT_REQUIRED", "missing_inputs": level_errors or ["TYPED_ARCHITECTURAL_LEVELS"], "network": None}
    assignments = level_assignments or {}
    if isinstance(assignments, dict) and "detections" in assignments:
        detection_assignments = assignments.get("detections") or {}
        shaft_assignments = assignments.get("shafts") or {}
        wetcore_assignments = assignments.get("wet_cores") or {}
    else:
        detection_assignments = assignments if isinstance(assignments, dict) else {}
        shaft_assignments = {}
        wetcore_assignments = {}

    missing = []
    excluded_unhosted_detections = []
    nodes = []
    node_by_id = {}
    endpoints_by_system_level = {}
    source_by_system_level = {}

    for detection in recognition.get("detections") or []:
        point = tuple(detection.get("point") or ())
        if len(point) != 2:
            missing.append("DETECTION_POINT_REQUIRED:" + str(detection.get("id") or "UNKNOWN"))
            continue
        explicit_level = detection.get("level")
        level, error = _resolve_level_for_point(
            str(detection.get("id") or "UNKNOWN"), explicit_level, point,
            levels, detection_assignments,
        )
        if (error and error.startswith("EXPLICIT_LEVEL_GEOMETRY_MISMATCH:")
                and not detection.get("room_id")):
            # Blocks outside every authoritative plan region are commonly
            # fixture symbols parked in a CAD library/legend.  They have no
            # architectural host and must not become installed consumers or
            # invalidate an otherwise bounded project model.
            excluded_unhosted_detections.append(str(detection.get("id") or "UNKNOWN"))
            continue
        if error:
            missing.append(error)
            continue
        node_id = _stable("NODE", {
            "level": level["id"], "category": detection.get("category"), "type": detection.get("type"),
            "point": [round(float(point[0]), 6), round(float(point[1]), 6)],
            "block": detection.get("block"), "layer": detection.get("layer"),
        })
        room_id = detection.get("room_id")
        inferred_host = None if room_id else _room_host(point, level["name"], architecture.get("rooms") or [])
        source_pmm_id = _pmm_entity_id(pmm, detection)
        installed_entity_host = bool(
            not room_id and not inferred_host and detection.get("installed") is True
            and detection.get("id") and detection.get("evidence")
        )
        node = {
            "id": node_id, "kind": detection.get("type"), "category": detection.get("category"),
            "point": (float(point[0]), float(point[1])), "level": level["id"], "level_type": level["type"],
            "level_name": level["name"], "room_id": room_id,
            "host_id": (inferred_host.get("id") if inferred_host else
                        (source_pmm_id or detection.get("id")) if installed_entity_host else None),
            "host_evidence": ("UNIQUE_ARCHITECTURAL_ROOM_ENVELOPE" if inferred_host else
                              "INSTALLED_ARCHITECTURAL_ENTITY" if installed_entity_host else None),
            "ports": list(detection.get("ports") or []), "source_detection_id": detection.get("id"),
            "source_pmm_id": source_pmm_id, "evidence": list(detection.get("evidence") or []),
        }
        nodes.append(node); node_by_id[node_id] = node
        for system in node["ports"]:
            key = (system, level["id"])
            if node.get("kind") in SOURCE_TYPES.get(system, set()):
                source_by_system_level.setdefault(key, []).append(node)
            else:
                endpoints_by_system_level.setdefault(key, []).append(node)

    shaft_nodes_by_level = {}
    for index, shaft in enumerate(architecture.get("shafts") or [], 1):
        point = tuple(shaft.get("centroid") or _centroid(shaft.get("polygon")) or ())
        if len(point) != 2:
            continue
        sid = "SHAFT-%02d" % index
        explicit_level = shaft.get("level")
        level, error = _resolve_level_for_point(
            sid, explicit_level, point, levels, shaft_assignments,
        )
        if error:
            missing.append(error)
            continue
        node_id = _stable("SHAFT", {"level": level["id"], "point": [round(point[0], 6), round(point[1], 6)]})
        shaft_key = shaft.get("vertical_alignment_key") or shaft.get("shaft_id")
        node = {"id": node_id, "kind": "shaft", "category": "vertical_core", "point": point,
                "level": level["id"], "level_type": level["type"], "level_name": level["name"],
                "elevation_m": level.get("elevation_m"), "shaft_key": shaft_key,
                "footprint_bounds": _bbox(shaft.get("polygon")),
                "source": shaft.get("source") or "ARCHITECTURAL_SHAFT_GEOMETRY"}
        nodes.append(node); node_by_id[node_id] = node; shaft_nodes_by_level.setdefault(level["id"], []).append(node)

    wet_nodes_by_level = {}
    for index, wet in enumerate(architecture.get("wet_cores") or [], 1):
        point = tuple(wet.get("centroid") or ())
        if len(point) != 2:
            continue
        wid = "WETCORE-%02d" % index
        explicit_level = wet.get("level")
        level, error = _resolve_level_for_point(
            wid, explicit_level, point, levels, wetcore_assignments,
        )
        if error:
            missing.append(error)
            continue
        node_id = _stable("WET", {"level": level["id"], "room_id": wet.get("room_id"), "point": [round(point[0], 6), round(point[1], 6)]})
        node = {"id": node_id, "kind": "wet_core", "category": "aggregation", "point": point,
                "level": level["id"], "level_type": level["type"], "level_name": level["name"],
                "room_id": wet.get("room_id"), "source": "ARCHITECTURAL_WET_CORE"}
        nodes.append(node); node_by_id[node_id] = node; wet_nodes_by_level.setdefault(level["id"], []).append(node)

    # An explicit owner authorization is itself authoritative project evidence,
    # but it must materialize as deterministic, level-owned shaft geometry
    # before routing.  Never create a shaft for an unknown/free-text strategy,
    # and never replace or disambiguate architectural shafts.
    proposal_strategies = {
        "propose_near_wet_core", "propose_adjacent_to_stair", "proposal_authorized",
    }
    if shaft_strategy in proposal_strategies:
        for level in levels:
            level_id = level["id"]
            # Preserve every architectural shaft, while materializing one separate
            # owner-authorized design core on every level.  A partial mixture of
            # architectural and proposed cores cannot guarantee one cross-level
            # alignment identity when the source file omits alignment keys.
            candidates = wet_nodes_by_level.get(level_id, [])
            if candidates:
                point = (
                    sum(float(row["point"][0]) for row in candidates) / len(candidates),
                    sum(float(row["point"][1]) for row in candidates) / len(candidates),
                )
            else:
                bounds = level.get("region_bounds") or ()
                if len(bounds) != 4:
                    continue
                point = ((float(bounds[0]) + float(bounds[2])) / 2,
                         (float(bounds[1]) + float(bounds[3])) / 2)
            node_id = _stable("SHAFT", {
                "level": level_id, "strategy": shaft_strategy,
                "point": [round(point[0], 6), round(point[1], 6)],
            })
            node = {
                "id": node_id, "kind": "shaft", "category": "vertical_core",
                "point": point, "level": level_id, "level_type": level["type"],
                "level_name": level["name"], "elevation_m": level.get("elevation_m"),
                "shaft_key": "USER-AUTHORIZED-PROPOSED-CORE",
                "footprint_bounds": None,
                "source": "USER_AUTHORIZED_PROPOSED_SHAFT",
                "proposal_strategy": shaft_strategy,
            }
            nodes.append(node); node_by_id[node_id] = node
            shaft_nodes_by_level.setdefault(level_id, []).append(node)

    def selected_vertical_shaft(level_id):
        shafts = shaft_nodes_by_level.get(level_id, [])
        proposed = [row for row in shafts
                    if row.get("source") == "USER_AUTHORIZED_PROPOSED_SHAFT"]
        if len(proposed) == 1:
            return proposed[0]
        if len(shafts) == 1:
            return shafts[0]
        return None

    if missing:
        return {"status": "INPUT_REQUIRED", "missing_inputs": sorted(set(missing)), "network": None,
                "evidence": {"installed_detections": len(recognition.get("detections") or []), "real_shafts": sum(len(v) for v in shaft_nodes_by_level.values())}}

    walls = architecture.get("walls") or []
    obstacles = architecture.get("obstacles") or []
    edges = []
    used_keys = set()
    missing_route = []
    systems_by_level = {}

    def add_edge(system, from_node, to_node, role, endpoint_ids, level_ids, vertical=False):
        key = (system, from_node["id"], to_node["id"], role, tuple(level_ids))
        if key in used_keys:
            return
        used_keys.add(key)
        if vertical:
            points = None; meta = None
        else:
            route_level = next((row for row in levels if row["id"] in level_ids), None)
            route_bounds = (route_level or {}).get("region_bounds")
            points, meta = _orthogonal_path(
                tuple(from_node["point"]), tuple(to_node["point"]),
                walls, obstacles, route_bounds=route_bounds,
            )
            if meta == "ROUTE_ENDPOINT_OUTSIDE_LEVEL_BOUNDS":
                missing_route.append(
                    "ROUTE_ENDPOINT_OUTSIDE_LEVEL_BOUNDS:%s:%s:%s"
                    % (system, from_node["id"], to_node["id"])
                )
                return
            if meta == "ROUTE_INTERSECTS_STRUCTURAL_OBSTACLE":
                missing_route.append("ROUTE_CLEARANCE_REQUIRED:" + system + ":" + from_node["id"] + ":" + to_node["id"])
                return
        edges.append(_edge(system, from_node["id"], to_node["id"], role, endpoint_ids, level_ids, points, meta if isinstance(meta, dict) else None))

    for (system, level_id), consumers in sorted(endpoints_by_system_level.items()):
        if not consumers:
            continue
        systems_by_level.setdefault(system, set()).add(level_id)
        level = next(row for row in levels if row["id"] == level_id)
        sources = source_by_system_level.get((system, level_id), [])
        shafts = shaft_nodes_by_level.get(level_id, [])
        wets = wet_nodes_by_level.get(level_id, []) if system in PLUMBING_SYSTEMS else []
        by_room = {}
        for node in consumers:
            by_room.setdefault(node.get("room_id") or "UNASSIGNED", []).append(node)
        level_endpoint_ids = []
        targets_used = []
        for room_id, room_nodes in sorted(by_room.items()):
            endpoint_ids = [node["id"] for node in room_nodes]
            level_endpoint_ids.extend(endpoint_ids)
            if len(room_nodes) == 1:
                branch_node = room_nodes[0]
            else:
                point = (sum(node["point"][0] for node in room_nodes) / len(room_nodes),
                         sum(node["point"][1] for node in room_nodes) / len(room_nodes))
                bid = _stable("BR", {"system": system, "level": level_id, "room": room_id, "endpoint_ids": sorted(endpoint_ids)})
                branch_node = {"id": bid, "kind": "branch_header", "category": "aggregation", "system": system,
                               "point": point, "level": level_id, "level_type": level["type"], "level_name": level["name"],
                               "room_id": None if room_id == "UNASSIGNED" else room_id}
                nodes.append(branch_node); node_by_id[bid] = branch_node
                for endpoint in room_nodes:
                    add_edge(system, endpoint, branch_node, "fixture_branch", [endpoint["id"]], [level_id])
            target = _nearest(branch_node["point"], sources) or _nearest(branch_node["point"], wets) or _nearest(branch_node["point"], shafts)
            if target is None or target["id"] == branch_node["id"]:
                missing_route.append("SYSTEM_TERMINATION_REQUIRED:%s:%s" % (level["name"], system))
                continue
            add_edge(system, branch_node, target, "floor_main", endpoint_ids, [level_id])
            targets_used.append(target)

        # A real wet core that is used by a multi-level plumbing system must connect
        # onward to a real architectural shaft; no floor-center/provisional shaft is allowed.
        system_level_count = len({lvl for (sys_name, lvl) in endpoints_by_system_level if sys_name == system})
        if system in PLUMBING_SYSTEMS and system_level_count > 1:
            for wet in {row["id"]: row for row in targets_used if row.get("kind") == "wet_core"}.values():
                shaft = selected_vertical_shaft(level_id)
                if shaft is None:
                    missing_route.append("AUTHORITATIVE_VERTICAL_CORE_REQUIRED:%s:%s" % (level["name"], system))
                else:
                    add_edge(system, wet, shaft, "riser_connection", level_endpoint_ids, [level_id])

    # The PMM flag is advisory scope metadata.  The installed endpoint graph is
    # the execution authority: whenever one system is present on more than one
    # detected level it necessarily requires continuous riser edges.  Relying
    # only on the advisory flag produced disconnected multi-level networks for
    # projects whose architectural inference discovered additional floors.
    vertical_enabled = bool(
        (pmm.get("systems") or {}).get("vertical_systems")
        or any(len(level_ids) > 1 for level_ids in systems_by_level.values())
    )
    if vertical_enabled:
        order = {row["id"]: row["order"] for row in levels}
        for system, level_ids in sorted(systems_by_level.items()):
            terminal_orders = [order[value] for value in level_ids]
            involved = [row["id"] for row in sorted(levels, key=lambda value: value["order"])
                        if min(terminal_orders) <= row["order"] <= max(terminal_orders)]
            if len(involved) < 2:
                continue
            selected = []
            for level_id in involved:
                level = next(row for row in levels if row["id"] == level_id)
                shaft = selected_vertical_shaft(level_id)
                if shaft is None:
                    missing_route.append("VERTICAL_SHAFT_CORRESPONDENCE_REQUIRED:%s:%s" % (level["name"], system))
                    selected = []
                    break
                selected.append(shaft)
            supplied_keys = [row.get("shaft_key") for row in selected]
            if selected and any(supplied_keys) and (not all(supplied_keys) or len(set(supplied_keys)) != 1):
                missing_route.append("VERTICAL_SHAFT_ALIGNMENT_KEY_MISMATCH:%s" % system)
                selected = []
            for lower, upper in zip(selected, selected[1:]):
                endpoint_ids = [node_id for (sys_name, lvl), values in endpoints_by_system_level.items()
                                if sys_name == system and order[lvl] >= order[upper["level"]]
                                for node_id in [node["id"] for node in values]]
                add_edge(system, lower, upper, "vertical_riser", endpoint_ids, [lower["level"], upper["level"]], vertical=True)
                edge = edges[-1]
                edge["shaft_key"] = lower.get("shaft_key") or upper.get("shaft_key")
                edge["from_elevation_m"] = lower.get("elevation_m")
                edge["to_elevation_m"] = upper.get("elevation_m")
                dx = round(float(upper["point"][0]) - float(lower["point"][0]), 6)
                dy = round(float(upper["point"][1]) - float(lower["point"][1]), 6)
                edge["vertical_offset_xy"] = [dx, dy]
                edge["offset_declared"] = bool(dx or dy) and bool(edge.get("shaft_key"))

    if missing_route:
        return {"status": "INPUT_REQUIRED", "missing_inputs": sorted(set(missing_route)), "network": None,
                "evidence": {"installed_detections": len(recognition.get("detections") or []), "real_shafts": sum(len(v) for v in shaft_nodes_by_level.values())}}
    if not edges:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["INSTALLED_SYSTEM_ENDPOINTS"], "network": None}

    logical_keys = [(row["system"], row["from"], row["to"], row["role"], tuple(row.get("levels") or [])) for row in edges]
    if len(logical_keys) != len(set(logical_keys)):
        return {"status": "FAIL", "errors": ["DUPLICATE_LOGICAL_NETWORK_EDGE"], "network": None}
    allowed_shaft_sources = {
        "ARCHITECTURAL_SHAFT_GEOMETRY", "ARCHITECTURAL_SHAFT_ROOM",
        "USER_AUTHORIZED_PROPOSED_SHAFT",
    }
    if any(node.get("kind") == "shaft" and node.get("source") not in allowed_shaft_sources for node in nodes):
        return {"status": "FAIL", "errors": ["PROVISIONAL_SHAFT_FORBIDDEN"], "network": None}

    network = {
        "schema": GRAPH_SCHEMA,
        "graph_id": _stable("GRAPH", {"levels": levels, "nodes": [row["id"] for row in nodes], "edges": [row["id"] for row in edges]}),
        "levels": levels,
        "nodes": nodes,
        "edges": edges,
        "authority": "PMM_V3_PLUS_INSTALLED_DXF_EVIDENCE",
        "coordination_state": "PRE_COORDINATION",
        "quality": {
            "node_count": len(nodes), "edge_count": len(edges), "provisional_shaft_count": 0,
            "duplicate_logical_edges": 0, "draw_on_plan_edges": sum(bool(row.get("draw_on_plan")) for row in edges),
        },
    }
    return {"status": "PASS", "network": network, "evidence": {
        "installed_detections": len(recognition.get("detections") or []) - len(excluded_unhosted_detections),
        "excluded_unhosted_out_of_plan_detections": sorted(excluded_unhosted_detections),
        "real_shafts": sum(len(v) for v in shaft_nodes_by_level.values()),
        "level_assignment_policy": "EXPLICIT_OR_UNAMBIGUOUS_REGION_BOUNDS_ONLY",
    }}


def build_authoritative_topology(src, pmm, level_assignments=None, architecture_evidence=None,
                                 fixture_evidence=None, declared_fixture_schedule=None,
                                 shaft_strategy=None):
    architecture = _architecture_from_evidence(architecture_evidence, reconstruct_architecture(src))
    recognition = _recognition_from_evidence(
        fixture_evidence, recognize_fixtures_equipment(architecture), architecture,
        declared_schedule=declared_fixture_schedule,
    )
    result = build_authoritative_topology_from_evidence(
        pmm, architecture, recognition, level_assignments=level_assignments,
        shaft_strategy=shaft_strategy,
    )
    result["architecture_version"] = architecture.get("version")
    result["recognition_version"] = recognition.get("version")
    return result
