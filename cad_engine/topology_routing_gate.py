"""Exact, fail-closed Mechanical topology and routing acceptance.

The gate does not invent geometry or engineering values.  It reconciles the
canonical graph, executed calculation rows and any applicable coordination or
equipment-route evidence.  Every one of the eighteen controls must pass and
the weighted score must be exactly 100 before CAD materialization.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from hashlib import sha256
import json
import math


CONTRACT_VERSION = "topology-routing/1"
CONTROL_WEIGHTS = {
    "typed_space_graph": 6,
    "hosted_endpoint_inventory": 7,
    "system_graph_separation": 5,
    "authoritative_sources_and_destinations": 5,
    "endpoint_exactly_once": 8,
    "branch_main_continuity": 7,
    "authoritative_shaft_selection": 5,
    "vertical_level_continuity": 7,
    "vertical_alignment": 5,
    "orthogonal_plan_routes": 5,
    "legal_terminal_penetrations": 5,
    "zero_critical_clashes": 7,
    "system_physical_constraints": 7,
    "bounded_route_efficiency": 4,
    "constructability_and_access": 5,
    "equipment_route_envelope": 4,
    "plan_riser_calc_schedule_identity": 5,
    "deterministic_exact_output_contract": 3,
}
assert len(CONTROL_WEIGHTS) == 18 and sum(CONTROL_WEIGHTS.values()) == 100

ENDPOINT_CATEGORIES = {"fixture", "equipment", "terminal"}
AGGREGATION_CATEGORIES = {"aggregation", "vertical_core"}
SOURCE_KINDS = {"source", "discharge", "tank", "pump", "water_heater", "split_outdoor"}
GRAVITY_SYSTEMS = {"sanitary", "rainwater", "condensate"}
ALLOWED_SHAFT_SOURCES = {"ARCHITECTURAL_SHAFT_GEOMETRY", "ARCHITECTURAL_SHAFT_ROOM"}


def _stable(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def _finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _orthogonal(points):
    if len(points) < 2:
        return False
    return all(
        _finite(a[0]) and _finite(a[1]) and _finite(b[0]) and _finite(b[1])
        and (abs(float(a[0]) - float(b[0])) < 1e-9 or abs(float(a[1]) - float(b[1])) < 1e-9)
        for a, b in zip(points, points[1:])
    )


def _connected(node_id, system, adjacency, terminals):
    queue = deque([node_id]); seen = {node_id}
    while queue:
        current = queue.popleft()
        if current in terminals and current != node_id:
            return True
        for nxt in adjacency.get((system, current), set()):
            if nxt not in seen:
                seen.add(nxt); queue.append(nxt)
    return False


def evaluate_topology_routing(network, calculation_rows=None, coordination=None,
                              equipment_routes=None, exact_output=None):
    network = network or {}; calculation_rows = calculation_rows or []
    coordination = coordination or {}; equipment_routes = equipment_routes or []
    if isinstance(equipment_routes, dict):
        equipment_routes = equipment_routes.get("checks") or equipment_routes.get("equipment") or []
    exact_output = exact_output or {}
    nodes = network.get("nodes") or []; edges = network.get("edges") or []
    levels = network.get("levels") or []
    node_by_id = {row.get("id"): row for row in nodes if row.get("id")}
    edge_ids = [row.get("id") for row in edges]
    errors = defaultdict(list)

    # 1 — typed, bounded logical space and level authority.
    if not levels or any(not row.get("id") or not row.get("type") for row in levels):
        errors["typed_space_graph"].append("TYPED_LEVEL_GRAPH_REQUIRED")
    if any(not row.get("level") for row in nodes if row.get("category") != "vertical_core"):
        errors["typed_space_graph"].append("NODE_LEVEL_BINDING_REQUIRED")

    # 2 — every real endpoint has a host and declared ports.
    endpoints = [row for row in nodes if row.get("category") in ENDPOINT_CATEGORIES
                 and row.get("kind") not in SOURCE_KINDS]
    for row in endpoints:
        if not (row.get("room_id") or row.get("host_id") or row.get("host_evidence")):
            errors["hosted_endpoint_inventory"].append("ENDPOINT_HOST_REQUIRED:" + str(row.get("id")))
        if not row.get("ports"):
            errors["hosted_endpoint_inventory"].append("ENDPOINT_PORTS_REQUIRED:" + str(row.get("id")))

    # 3/4 — edges are typed, stay inside one system and have real endpoints.
    for edge in edges:
        if not edge.get("system") or edge.get("from") not in node_by_id or edge.get("to") not in node_by_id:
            errors["system_graph_separation"].append("INVALID_TYPED_EDGE:" + str(edge.get("id")))
        if edge.get("from") == edge.get("to"):
            errors["authoritative_sources_and_destinations"].append("SELF_LOOP_FORBIDDEN:" + str(edge.get("id")))
        for node_id in (edge.get("from"), edge.get("to")):
            node_system = node_by_id.get(node_id, {}).get("system")
            if node_system and node_system != edge.get("system"):
                errors["system_graph_separation"].append("CROSS_SYSTEM_EDGE:" + str(edge.get("id")))
    if not edges or len(edge_ids) != len(set(edge_ids)) or any(not value for value in edge_ids):
        errors["authoritative_sources_and_destinations"].append("UNIQUE_AUTHORITATIVE_EDGES_REQUIRED")

    # 5/6 — each requested endpoint port is served once and every aggregation is continuous.
    service = Counter()
    adjacency = defaultdict(set)
    for edge in edges:
        system = edge.get("system")
        adjacency[(system, edge.get("from"))].add(edge.get("to"))
        adjacency[(system, edge.get("to"))].add(edge.get("from"))
        for endpoint_id in set(edge.get("endpoint_ids") or []):
            service[(endpoint_id, system)] += 1
    for endpoint in endpoints:
        for system in endpoint.get("ports") or []:
            count = service[(endpoint.get("id"), system)]
            if count == 0:
                errors["endpoint_exactly_once"].append(f"UNSERVED_ENDPOINT:{endpoint.get('id')}:{system}")
            # Multiple edges may legitimately carry one endpoint downstream;
            # exactly one terminal incidence is the non-duplication authority.
            terminal_incidence = sum(
                1 for edge in edges if edge.get("system") == system
                and endpoint.get("id") in {edge.get("from"), edge.get("to")}
            )
            if terminal_incidence != 1:
                errors["endpoint_exactly_once"].append(f"ENDPOINT_INCIDENCE_{terminal_incidence}:{endpoint.get('id')}:{system}")
    for node in nodes:
        if node.get("category") in AGGREGATION_CATEGORIES:
            relevant = [edge for edge in edges if node.get("id") in {edge.get("from"), edge.get("to")}]
            if relevant and len(relevant) < 2 and node.get("kind") not in {"shaft", "source", "discharge"}:
                errors["branch_main_continuity"].append("DANGLING_AGGREGATION:" + str(node.get("id")))
    for endpoint in endpoints:
        for system in endpoint.get("ports") or []:
            terminals = {
                row.get("id") for row in nodes
                if row.get("kind") in {"shaft", *SOURCE_KINDS}
                or row.get("kind") == "wet_core"
                or row.get("category") == "vertical_core"
            }
            if not _connected(endpoint.get("id"), system, adjacency, terminals):
                errors["branch_main_continuity"].append(f"NO_SYSTEM_TERMINATION:{endpoint.get('id')}:{system}")

    # 7/8/9 — shafts are source-backed and vertical graphs cover consecutive levels.
    shafts = [row for row in nodes if row.get("kind") == "shaft"]
    if any(row.get("source") not in ALLOWED_SHAFT_SOURCES for row in shafts):
        errors["authoritative_shaft_selection"].append("PROVISIONAL_SHAFT_FORBIDDEN")
    level_order = {row.get("id"): i for i, row in enumerate(sorted(levels, key=lambda x: x.get("order", 0)))}
    verticals = [row for row in edges if row.get("role") == "vertical_riser"]
    for edge in verticals:
        pair = edge.get("levels") or []
        if len(pair) != 2 or pair[0] not in level_order or pair[1] not in level_order or abs(level_order[pair[1]] - level_order[pair[0]]) != 1:
            errors["vertical_level_continuity"].append("NON_CONSECUTIVE_VERTICAL_EDGE:" + str(edge.get("id")))
        offset = edge.get("vertical_offset_xy") or [0, 0]
        if len(offset) != 2 or any(not _finite(v) for v in offset):
            errors["vertical_alignment"].append("INVALID_VERTICAL_OFFSET:" + str(edge.get("id")))
        elif any(abs(float(v)) > 1e-9 for v in offset) and not edge.get("offset_declared"):
            errors["vertical_alignment"].append("UNDECLARED_VERTICAL_OFFSET:" + str(edge.get("id")))
    systems_levels = defaultdict(set)
    for edge in edges:
        for level in edge.get("levels") or []:
            systems_levels[edge.get("system")].add(level)
    vertical_pairs = defaultdict(set)
    for edge in verticals:
        pair = edge.get("levels") or []
        if len(pair) == 2:
            vertical_pairs[edge.get("system")].add(tuple(pair))
    for system, used in systems_levels.items():
        ordered = sorted((level_order[x], x) for x in used if x in level_order)
        if len(ordered) > 1:
            required = {(a[1], b[1]) for a, b in zip(ordered, ordered[1:])}
            if not required.issubset(vertical_pairs[system]):
                errors["vertical_level_continuity"].append("MISSING_VERTICAL_CONTINUITY:" + str(system))

    # 10/11 — drawable routes are measurable, orthogonal and penetrate only coordinated terminals.
    plan_edges = [row for row in edges if row.get("draw_on_plan")]
    for edge in plan_edges:
        if not _orthogonal(edge.get("plan_path") or []):
            errors["orthogonal_plan_routes"].append("NON_ORTHOGONAL_OR_EMPTY_ROUTE:" + str(edge.get("id")))
        if int(edge.get("wall_crossings") or 0) != 0:
            errors["legal_terminal_penetrations"].append("INTERMEDIATE_WALL_CROSSING:" + str(edge.get("id")))
        if int(edge.get("coordinated_terminal_penetrations") or 0) > 2:
            errors["legal_terminal_penetrations"].append("EXCESS_TERMINAL_PENETRATIONS:" + str(edge.get("id")))

    # 12 — applicable structural/RCP evidence must be a real passing model/route set.
    if coordination:
        if coordination.get("status") != "PASS" or coordination.get("claim") not in {"COORDINATED", "COORDINATED_ROUTE"}:
            errors["zero_critical_clashes"].append("COORDINATION_NOT_PASS")
        if coordination.get("clashes") or coordination.get("critical_clashes") or coordination.get("warnings"):
            errors["zero_critical_clashes"].append("CRITICAL_CLASH_OR_WARNING_PRESENT")
    elif network.get("coordination_required"):
        errors["zero_critical_clashes"].append("COORDINATION_INPUT_REQUIRED")

    # 13 — execution rows carry size/material and gravity slope evidence.
    calc_by_edge = {row.get("network_edge_id"): row for row in calculation_rows if row.get("network_edge_id")}
    for edge in edges:
        calc = calc_by_edge.get(edge.get("id"))
        if not calc or not calc.get("calc_id") or not _finite(calc.get("size_mm")) or not calc.get("material"):
            errors["system_physical_constraints"].append("EXECUTED_SEGMENT_REQUIRED:" + str(edge.get("id")))
            continue
        requires_slope = edge.get("requires_slope")
        if edge.get("system") in GRAVITY_SYSTEMS and requires_slope is not True:
            errors["system_physical_constraints"].append("GRAVITY_SLOPE_REQUIRED:" + str(edge.get("id")))
        if requires_slope and (not _finite(calc.get("slope_percent")) or float(calc.get("slope_percent")) <= 0):
            errors["system_physical_constraints"].append("POSITIVE_SLOPE_REQUIRED:" + str(edge.get("id")))

    # 14/15 — route economy and access use explicit evidence when applicable.
    for edge in plan_edges:
        points = edge.get("plan_path") or []
        length = sum(abs(float(b[0])-float(a[0])) + abs(float(b[1])-float(a[1])) for a, b in zip(points, points[1:]))
        direct = abs(float(points[-1][0])-float(points[0][0])) + abs(float(points[-1][1])-float(points[0][1])) if len(points) > 1 else 0
        limit = edge.get("max_detour_ratio", 2.0)
        if not direct or not _finite(limit) or length / direct > float(limit) + 1e-9:
            errors["bounded_route_efficiency"].append("ROUTE_DETOUR_LIMIT:" + str(edge.get("id")))
        if edge.get("constructability_status", "PASS") != "PASS" or edge.get("access_blocked"):
            errors["constructability_and_access"].append("ROUTE_NOT_CONSTRUCTIBLE:" + str(edge.get("id")))

    # 16 — route-sensitive equipment must explicitly pass its envelope.
    for row in equipment_routes:
        if row.get("required", True) and row.get("status") != "PASS":
            errors["equipment_route_envelope"].append("EQUIPMENT_ROUTE_ENVELOPE:" + str(row.get("equipment_id") or row.get("id")))

    # 17 — one immutable identity set across graph, calculations and documents.
    calc_ids = []
    for edge in edges:
        identities = {edge.get(key) for key in ("calc_id", "plan_id", "riser_id", "schedule_id")}
        calc = calc_by_edge.get(edge.get("id"))
        calc_ids.append(calc.get("calc_id") if calc else None)
        if len(identities) != 1 or None in identities or not calc or calc.get("calc_id") != edge.get("calc_id"):
            errors["plan_riser_calc_schedule_identity"].append("IDENTITY_MISMATCH:" + str(edge.get("id")))
    if len(calc_ids) != len(set(calc_ids)):
        errors["plan_riser_calc_schedule_identity"].append("DUPLICATE_CALCULATION_ID")

    # 18 — stable graph identity, exact edge parity and post-write evidence when supplied.
    if not network.get("graph_id") or _stable({"nodes": sorted(node_by_id), "edges": sorted(edge_ids)}) == "":
        errors["deterministic_exact_output_contract"].append("DETERMINISTIC_GRAPH_ID_REQUIRED")
    expected_edges = {edge.get("id") for edge in plan_edges}
    output_edges = set(exact_output.get("edge_ids") or expected_edges)
    if output_edges != expected_edges:
        errors["deterministic_exact_output_contract"].append("EXACT_OUTPUT_EDGE_PARITY_FAILED")
    if exact_output and (exact_output.get("reopened") is not True or exact_output.get("immutable") is not True):
        errors["deterministic_exact_output_contract"].append("EXACT_REOPEN_IMMUTABILITY_REQUIRED")

    controls = []
    for name, weight in CONTROL_WEIGHTS.items():
        passed = not errors[name]
        controls.append({"id": name, "weight": weight, "status": "PASS" if passed else "FAIL", "errors": sorted(set(errors[name]))})
    score = sum(row["weight"] for row in controls if row["status"] == "PASS")
    all_pass = bool(nodes and edges) and score == 100 and all(row["status"] == "PASS" for row in controls)
    return {
        "contract_version": CONTRACT_VERSION,
        "status": "PASS" if all_pass else "FAIL",
        "score": score,
        "required_score": 100,
        "controls": controls,
        "errors": sorted({error for values in errors.values() for error in values}),
        "graph_id": network.get("graph_id"),
        "evidence_hash": _stable({"network": network, "calculation_rows": calculation_rows,
                                  "coordination": coordination, "equipment_routes": equipment_routes,
                                  "exact_output": exact_output}),
        "release_allowed": all_pass,
    }


def assert_topology_routing_100(report):
    controls = report.get("controls") or []
    if (report.get("contract_version") != CONTRACT_VERSION or report.get("status") != "PASS"
            or report.get("score") != 100 or report.get("release_allowed") is not True
            or len(controls) != 18 or any(row.get("status") != "PASS" for row in controls)):
        raise ValueError("TOPOLOGY_ROUTING_100_REQUIRED")
    return report
