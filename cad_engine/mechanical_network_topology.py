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
        registry.append({
            "id": _stable("LVL", {"name": name, "type": level_type}),
            "name": name,
            "type": level_type,
            "order": order,
            "region_bounds": _bounds(row.get("region_bounds")),
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


def _orthogonal_path(start, end, walls, obstacles):
    if start == end:
        return None, None
    if start[0] == end[0] or start[1] == end[1]:
        candidates = [[start, end]]
    else:
        candidates = [[start, (end[0], start[1]), end], [start, (start[0], end[1]), end]]
    rects = [_bbox(item.get("points") or item.get("polygon")) for item in obstacles or []]
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
                point = tuple(target["centroid"])
                detections.append({
                    "id": "OWNER-DECLARED-%s-%03d" % (kind.upper(), occurrence + 1),
                    "category": "fixture", "type": kind, "point": point, "ports": EVIDENCE_PORTS[kind],
                    "room_id": target.get("room_id"), "level": target.get("level"), "installed": False,
                    "design_status": "DESIGNED_FROM_OWNER_DECLARED_COUNT",
                    "evidence": ["OWNER_QUESTIONNAIRE_ACTUAL_FIXTURE_COUNT", "ARCHITECTURE_WET_CORE_SERVICE_POINT"],
                })
        return {"version": "owner-declared-designed-endpoints/1", "detections": detections, "candidates": []}
    return fallback


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
    }


def build_authoritative_topology_from_evidence(pmm, architecture, recognition, level_assignments=None):
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
        if explicit_level:
            level = _resolve_explicit_level(explicit_level, levels)
            error = None if level else "UNKNOWN_EXPLICIT_LEVEL:" + str(explicit_level)
        else:
            level, error = _assign_level(str(detection.get("id") or "UNKNOWN"), point, levels, detection_assignments)
        if error:
            missing.append(error)
            continue
        node_id = _stable("NODE", {
            "level": level["id"], "category": detection.get("category"), "type": detection.get("type"),
            "point": [round(float(point[0]), 6), round(float(point[1]), 6)],
            "block": detection.get("block"), "layer": detection.get("layer"),
        })
        node = {
            "id": node_id, "kind": detection.get("type"), "category": detection.get("category"),
            "point": (float(point[0]), float(point[1])), "level": level["id"], "level_type": level["type"],
            "level_name": level["name"], "room_id": detection.get("room_id"),
            "ports": list(detection.get("ports") or []), "source_detection_id": detection.get("id"),
            "source_pmm_id": _pmm_entity_id(pmm, detection), "evidence": list(detection.get("evidence") or []),
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
        if explicit_level:
            level = _resolve_explicit_level(explicit_level, levels)
            error = None if level else "UNKNOWN_EXPLICIT_LEVEL:" + str(explicit_level)
        else:
            level, error = _assign_level(sid, point, levels, shaft_assignments)
        if error:
            missing.append(error)
            continue
        node_id = _stable("SHAFT", {"level": level["id"], "point": [round(point[0], 6), round(point[1], 6)]})
        node = {"id": node_id, "kind": "shaft", "category": "vertical_core", "point": point,
                "level": level["id"], "level_type": level["type"], "level_name": level["name"],
                "source": shaft.get("source") or "ARCHITECTURAL_SHAFT_GEOMETRY"}
        nodes.append(node); node_by_id[node_id] = node; shaft_nodes_by_level.setdefault(level["id"], []).append(node)

    wet_nodes_by_level = {}
    for index, wet in enumerate(architecture.get("wet_cores") or [], 1):
        point = tuple(wet.get("centroid") or ())
        if len(point) != 2:
            continue
        wid = "WETCORE-%02d" % index
        explicit_level = wet.get("level")
        if explicit_level:
            level = _resolve_explicit_level(explicit_level, levels)
            error = None if level else "UNKNOWN_EXPLICIT_LEVEL:" + str(explicit_level)
        else:
            level, error = _assign_level(wid, point, levels, wetcore_assignments)
        if error:
            missing.append(error)
            continue
        node_id = _stable("WET", {"level": level["id"], "room_id": wet.get("room_id"), "point": [round(point[0], 6), round(point[1], 6)]})
        node = {"id": node_id, "kind": "wet_core", "category": "aggregation", "point": point,
                "level": level["id"], "level_type": level["type"], "level_name": level["name"],
                "room_id": wet.get("room_id"), "source": "ARCHITECTURAL_WET_CORE"}
        nodes.append(node); node_by_id[node_id] = node; wet_nodes_by_level.setdefault(level["id"], []).append(node)

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
            points, meta = _orthogonal_path(tuple(from_node["point"]), tuple(to_node["point"]), walls, obstacles)
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
                shaft = _nearest(wet["point"], shafts)
                if shaft is None:
                    missing_route.append("AUTHORITATIVE_VERTICAL_CORE_REQUIRED:%s:%s" % (level["name"], system))
                else:
                    add_edge(system, wet, shaft, "riser_connection", level_endpoint_ids, [level_id])

    vertical_enabled = bool((pmm.get("systems") or {}).get("vertical_systems"))
    if vertical_enabled:
        order = {row["id"]: row["order"] for row in levels}
        for system, level_ids in sorted(systems_by_level.items()):
            involved = sorted(level_ids, key=lambda value: order[value])
            if len(involved) < 2:
                continue
            selected = []
            for level_id in involved:
                shafts = shaft_nodes_by_level.get(level_id, [])
                level = next(row for row in levels if row["id"] == level_id)
                if len(shafts) != 1:
                    missing_route.append("VERTICAL_SHAFT_CORRESPONDENCE_REQUIRED:%s:%s" % (level["name"], system))
                    selected = []
                    break
                selected.append(shafts[0])
            for lower, upper in zip(selected, selected[1:]):
                endpoint_ids = [node_id for (sys_name, lvl), values in endpoints_by_system_level.items()
                                if sys_name == system and lvl in {lower["level"], upper["level"]}
                                for node_id in [node["id"] for node in values]]
                add_edge(system, lower, upper, "vertical_riser", endpoint_ids, [lower["level"], upper["level"]], vertical=True)

    if missing_route:
        return {"status": "INPUT_REQUIRED", "missing_inputs": sorted(set(missing_route)), "network": None,
                "evidence": {"installed_detections": len(recognition.get("detections") or []), "real_shafts": sum(len(v) for v in shaft_nodes_by_level.values())}}
    if not edges:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["INSTALLED_SYSTEM_ENDPOINTS"], "network": None}

    logical_keys = [(row["system"], row["from"], row["to"], row["role"], tuple(row.get("levels") or [])) for row in edges]
    if len(logical_keys) != len(set(logical_keys)):
        return {"status": "FAIL", "errors": ["DUPLICATE_LOGICAL_NETWORK_EDGE"], "network": None}
    allowed_shaft_sources = {"ARCHITECTURAL_SHAFT_GEOMETRY", "ARCHITECTURAL_SHAFT_ROOM"}
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
        "installed_detections": len(recognition.get("detections") or []),
        "real_shafts": sum(len(v) for v in shaft_nodes_by_level.values()),
        "level_assignment_policy": "EXPLICIT_OR_UNAMBIGUOUS_REGION_BOUNDS_ONLY",
    }}


def build_authoritative_topology(src, pmm, level_assignments=None, architecture_evidence=None,
                                 fixture_evidence=None, declared_fixture_schedule=None):
    architecture = _architecture_from_evidence(architecture_evidence, reconstruct_architecture(src))
    recognition = _recognition_from_evidence(
        fixture_evidence, recognize_fixtures_equipment(architecture), architecture,
        declared_schedule=declared_fixture_schedule,
    )
    result = build_authoritative_topology_from_evidence(pmm, architecture, recognition, level_assignments=level_assignments)
    result["architecture_version"] = architecture.get("version")
    result["recognition_version"] = recognition.get("version")
    return result
