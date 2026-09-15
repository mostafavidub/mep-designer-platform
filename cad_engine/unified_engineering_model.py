"""One graph-native engineering source of truth for Mechanical outputs."""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json


SCHEMA = "unified-engineering-model/1"
PLAN_ROLES = {"fixture_branch", "floor_main", "riser_connection", "equipment_branch"}


def _hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def build_unified_engineering_model(pmm, network_graph, calculation_rows, design_basis=None):
    """Bind architecture, topology, sizing and every drawing representation."""
    pmm = pmm or {}; graph = network_graph or {}; rows = calculation_rows or []
    errors, missing = [], []
    rooms = list(pmm.get("rooms") or [])
    room_ids = [row.get("id") for row in rooms]
    if any(not value for value in room_ids): missing.append("INDIVIDUAL_ROOM_ID")
    if len(room_ids) != len(set(room_ids)): errors.append("DUPLICATE_ROOM_ID")

    nodes = list(graph.get("nodes") or []); edges = list(graph.get("edges") or [])
    node_ids = {row.get("id") for row in nodes if row.get("id")}
    if not nodes or not edges: missing.append("AUTHORITATIVE_NETWORK_GRAPH")
    by_calc = {row.get("calc_id"): row for row in rows if row.get("calc_id")}
    if len(by_calc) != len(rows): errors.append("DUPLICATE_OR_MISSING_CALCULATION_ID")

    records = []; branch_counts = Counter(); level_branch_counts = defaultdict(Counter)
    for edge in edges:
        edge_id = edge.get("id"); calc_id = edge.get("calc_id")
        if edge.get("from") not in node_ids or edge.get("to") not in node_ids:
            errors.append("DANGLING_NETWORK_EDGE:" + str(edge_id))
        calc = by_calc.get(calc_id)
        if not calc: missing.append("CALCULATION_FOR_EDGE:" + str(edge_id)); continue
        identities = [edge.get(key) for key in ("plan_id", "riser_id", "schedule_id")]
        if any(value != calc_id for value in identities):
            errors.append("OUTPUT_IDENTITY_DIVERGENCE:" + str(edge_id))
        if calc.get("network_edge_id") != edge_id:
            errors.append("CALCULATION_EDGE_DIVERGENCE:" + str(edge_id))
        if not calc.get("source") and not calc.get("provenance"):
            missing.append("CALCULATION_PROVENANCE:" + str(calc_id))
        role = str(edge.get("role") or "")
        endpoints = sorted(set(edge.get("endpoint_ids") or []))
        is_plan_branch = role in PLAN_ROLES and bool(endpoints)
        if is_plan_branch:
            branch_counts[str(edge.get("system"))] += 1
            for level in edge.get("levels") or []:
                level_branch_counts[str(level)][str(edge.get("system"))] += 1
        records.append({
            "network_edge_id": edge_id, "calc_id": calc_id,
            "plan_id": calc_id, "riser_id": calc_id, "schedule_id": calc_id,
            "plan_representation_id": edge.get("plan_representation_id"),
            "riser_representation_id": edge.get("riser_representation_id"),
            "schedule_row_id": edge.get("schedule_row_id"),
            "system": edge.get("system"), "role": role, "levels": list(edge.get("levels") or []),
            "endpoint_ids": endpoints, "branch_on_plan": is_plan_branch,
            "size_mm": calc.get("size_mm"), "material": calc.get("material"),
            "slope_percent": calc.get("slope_percent"), "downstream_load": calc.get("downstream_load"),
            "load_unit": calc.get("load_unit"), "source": calc.get("source") or calc.get("provenance"),
        })

    unknown_calcs = sorted(set(by_calc) - {edge.get("calc_id") for edge in edges})
    if unknown_calcs: errors.append("ORPHAN_CALCULATIONS:" + ",".join(unknown_calcs))
    connected = sum(len(edge.get("endpoint_ids") or []) for edge in edges)
    if connected and not sum(branch_counts.values()): errors.append("ZERO_PLAN_BRANCHES_WITH_CONNECTED_ENDPOINTS")

    status = "FAIL" if errors else ("INPUT_REQUIRED" if missing else "PASS")
    identity = {"pmm": _hash(pmm), "network": _hash(graph), "calculations": _hash(rows)}
    identity["unified"] = _hash(identity)
    return {
        "schema": SCHEMA, "status": status, "errors": sorted(set(errors)),
        "missing_inputs": sorted(set(missing)), "identity": identity,
        "rooms": rooms, "levels": list(graph.get("levels") or []), "nodes": nodes,
        "edges": edges, "calculation_records": records,
        "branch_counts": dict(sorted(branch_counts.items())),
        "level_branch_counts": {key: dict(sorted(value.items())) for key, value in sorted(level_branch_counts.items())},
        "totals": {"rooms": len(rooms), "nodes": len(nodes), "edges": len(edges),
                   "calculations": len(records), "branches": sum(branch_counts.values()),
                   "connected_endpoint_references": connected},
        "design_basis": design_basis or {},
        "output_policy": "PLAN_RISER_SCHEDULE_MUST_DERIVE_FROM_CALCULATION_RECORDS",
    }
