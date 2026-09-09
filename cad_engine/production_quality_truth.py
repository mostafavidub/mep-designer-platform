"""Fail-closed production truth checks for the mechanical generation path.

This module does not change engineering formulas. It turns the already-computed
engineering pipeline into deterministic traceability evidence and blocks
production when PMM identity, route geometry, topology, sizing, or architectural
level semantics are internally inconsistent.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json


PMM_V3 = "project-mechanical-model/v3"
FORBIDDEN_LEVEL_PREFIXES = ("DETAIL", "CALC", "SCHEDULE", "SERVICE")
OVERLAY_SENSITIVE_SYSTEM_PAIRS = {
    frozenset(("sanitary", "vent")),
    frozenset(("cold_water", "hot_water")),
}


def _forbidden_level(value) -> bool:
    text = str(value or "").strip().upper()
    return bool(text) and any(text.startswith(prefix) for prefix in FORBIDDEN_LEVEL_PREFIXES)


def _geometry_key(route: dict):
    points = route.get("points") or []
    if len(points) < 2:
        return None
    try:
        normalized = tuple((round(float(p[0]), 6), round(float(p[1]), 6)) for p in points)
    except (TypeError, ValueError, IndexError):
        return None
    reverse = tuple(reversed(normalized))
    return min(normalized, reverse)


def _calc_id(edge: dict, route: dict, sizing: dict) -> str:
    payload = {
        "edge_id": edge.get("id"),
        "route_id": route.get("id"),
        "plan_id": route.get("plan_id") or edge.get("plan_id"),
        "system": route.get("system") or edge.get("system"),
        "downstream_load": sizing.get("downstream_load"),
        "size_mm": sizing.get("size_mm"),
        "slope_percent": sizing.get("slope_percent"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "CALC-NET-" + sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def build_pipeline_traceability(pipeline: dict) -> dict:
    """Reconcile actual topology -> route -> sizing into governed identities."""
    architecture = pipeline.get("architecture") or {}
    topology = pipeline.get("topology") or {}
    routing = pipeline.get("routing") or {}
    sizing = pipeline.get("sizing") or {}

    plan_level = {
        str(plan.get("plan_id")): str(plan.get("level") or plan.get("plan_id"))
        for plan in architecture.get("plans") or []
        if plan.get("plan_id")
    }
    forbidden_levels = sorted({value for value in plan_level.values() if _forbidden_level(value)})

    nodes = []
    node_ids = set()
    for row in topology.get("nodes") or []:
        node_id = row.get("id")
        if not node_id:
            continue
        plan_id = row.get("plan_id")
        nodes.append({
            "id": node_id,
            "plan_id": plan_id,
            "level": plan_level.get(str(plan_id)) if plan_id is not None else None,
            "kind": row.get("kind"),
        })
        node_ids.add(node_id)

    routes = list(routing.get("routes") or [])
    route_by_edge = {row.get("edge_id"): row for row in routes if row.get("edge_id")}
    sizing_by_route = {row.get("route_id"): row for row in sizing.get("segments") or [] if row.get("route_id")}

    topology_edges = list(topology.get("edges") or [])
    missing_routes = sorted(str(row.get("id")) for row in topology_edges if row.get("id") not in route_by_edge)
    missing_sizing = sorted(
        str(route.get("id")) for route in routes
        if route.get("id") and route.get("id") not in sizing_by_route
    )
    invalid_route_geometry = sorted(
        str(route.get("id") or "UNKNOWN") for route in routes if _geometry_key(route) is None
    )

    by_geometry = defaultdict(list)
    for route in routes:
        key = _geometry_key(route)
        if key is not None:
            by_geometry[(str(route.get("plan_id")), key)].append(route)
    exact_duplicate_routes = []
    exact_cross_system_overlays = []
    for grouped in by_geometry.values():
        if len(grouped) < 2:
            continue
        by_system = defaultdict(list)
        for route in grouped:
            by_system[str(route.get("system") or "")].append(str(route.get("id") or "UNKNOWN"))
        for system, ids in by_system.items():
            if system and len(ids) > 1:
                exact_duplicate_routes.append({"system": system, "route_ids": sorted(ids)})
        systems = sorted(system for system in by_system if system)
        for index, first in enumerate(systems):
            for second in systems[index + 1:]:
                if frozenset((first, second)) in OVERLAY_SENSITIVE_SYSTEM_PAIRS:
                    exact_cross_system_overlays.append({
                        "systems": [first, second],
                        "route_ids": sorted(by_system[first] + by_system[second]),
                    })

    calculation_rows = []
    network_edges = []
    for edge in topology_edges:
        route = route_by_edge.get(edge.get("id"))
        if not route:
            continue
        sized = sizing_by_route.get(route.get("id"))
        if not sized:
            continue
        calc_id = _calc_id(edge, route, sized)
        level = plan_level.get(str(route.get("plan_id") or edge.get("plan_id")))
        calculation_rows.append({
            "calc_id": calc_id,
            "calculation_type": "NETWORK_SEGMENT_SIZING",
            "source_edge_id": edge.get("id"),
            "source_route_id": route.get("id"),
            "system": route.get("system") or edge.get("system"),
            "downstream_load": sized.get("downstream_load"),
            "size_mm": sized.get("size_mm"),
            "slope_percent": sized.get("slope_percent"),
        })
        network_edges.append({
            "id": edge.get("id"),
            "from": edge.get("from"),
            "to": edge.get("to"),
            "system": route.get("system") or edge.get("system"),
            "plan_id": calc_id,
            "riser_id": calc_id,
            "schedule_id": calc_id,
            "calc_id": calc_id,
            "levels": [level] if level else [],
            "size": sized.get("size_mm"),
            "source_route_id": route.get("id"),
        })

    calc_ids = [row["calc_id"] for row in calculation_rows]
    errors = []
    if forbidden_levels:
        errors.append("FORBIDDEN_ARCHITECTURAL_LEVEL:" + ",".join(forbidden_levels))
    if missing_routes:
        errors.append("TOPOLOGY_WITHOUT_ROUTE:" + ",".join(missing_routes))
    if missing_sizing:
        errors.append("ROUTE_WITHOUT_SIZING:" + ",".join(missing_sizing))
    if invalid_route_geometry:
        errors.append("INVALID_ROUTE_GEOMETRY:" + ",".join(invalid_route_geometry))
    if exact_duplicate_routes:
        errors.append("EXACT_DUPLICATE_ROUTE_GEOMETRY")
    if exact_cross_system_overlays:
        errors.append("EXACT_CROSS_SYSTEM_ROUTE_OVERLAY")
    if len(calc_ids) != len(set(calc_ids)):
        errors.append("DUPLICATE_NETWORK_CALC_ID")
    if any(edge.get("from") not in node_ids or edge.get("to") not in node_ids for edge in network_edges):
        errors.append("NETWORK_EDGE_DANGLING_AFTER_TRACEABILITY_ADAPTER")

    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "calculation_rows": calculation_rows,
        "network_graph": {"nodes": nodes, "edges": network_edges},
        "route_count": len(routes),
        "topology_edge_count": len(topology_edges),
        "sized_segment_count": len(sizing.get("segments") or []),
        "exact_duplicate_routes": exact_duplicate_routes,
        "exact_cross_system_overlays": exact_cross_system_overlays,
        "identity_policy": "TOPOLOGY_EDGE -> ROUTE -> SIZING_CALC -> PLAN/RISER/SCHEDULE",
    }


def evaluate_production_truth(pmm: dict, pipeline: dict, pipeline_qa: dict) -> dict:
    """Production-only fail-closed truth gate independent of Structural/RCP status."""
    if not pmm:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["PROJECT_MECHANICAL_MODEL_V3"], "errors": []}
    if pmm.get("schema") != PMM_V3:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["PROJECT_MECHANICAL_MODEL_V3"], "errors": ["PMM_SCHEMA_MISMATCH"]}
    if pmm.get("valid") is not True:
        return {"status": "FAIL", "missing_inputs": [], "errors": ["PMM_NOT_VALID"] + list(pmm.get("diagnostics") or [])}
    if (pmm.get("traceability_contract") or {}).get("policy") != "NO_ORPHAN_ENGINEERING_OUTPUT":
        return {"status": "FAIL", "missing_inputs": [], "errors": ["PMM_TRACEABILITY_POLICY_MISSING"]}

    pmm_levels = [row.get("name") for row in pmm.get("levels") or []]
    bad_pmm_levels = sorted(str(value) for value in pmm_levels if _forbidden_level(value))
    if bad_pmm_levels:
        return {"status": "FAIL", "missing_inputs": [], "errors": ["PMM_FORBIDDEN_LEVEL:" + ",".join(bad_pmm_levels)]}

    if (pipeline_qa or {}).get("status") != "PASS":
        return {"status": "FAIL", "missing_inputs": [], "errors": ["LEGACY_ENGINEERING_PIPELINE_NOT_PASS"] + list((pipeline_qa or {}).get("errors") or [])}

    trace = build_pipeline_traceability(pipeline or {})
    if trace["status"] != "PASS":
        return {"status": "FAIL", "missing_inputs": [], "errors": trace["errors"], "traceability": trace}
    if trace["topology_edge_count"] and not trace["calculation_rows"]:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["NETWORK_CALCULATION_ROWS"], "errors": [], "traceability": trace}
    return {
        "status": "PASS",
        "missing_inputs": [],
        "errors": [],
        "traceability": trace,
        "coordination_independent": True,
        "pmm_schema": pmm.get("schema"),
    }
