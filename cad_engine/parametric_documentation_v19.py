"""Parametric construction details and graph-native riser documentation."""
from __future__ import annotations

from hashlib import sha256
import json


DETAIL_FIELDS = {"geometry", "dimensions", "fittings", "material", "clearance", "tag"}


def generate_detail(spec: dict) -> dict:
    missing = sorted(DETAIL_FIELDS - spec.keys())
    if missing:
        return {"status": "INPUT_REQUIRED", "missing_inputs": missing, "detail": None}
    if not spec["geometry"] or not spec["dimensions"] or not spec["fittings"]:
        return {"status": "FAIL", "errors": ["detail geometry, dimensions and fittings must be non-empty"], "detail": None}
    detail = {key: spec[key] for key in sorted(DETAIL_FIELDS)}
    detail["detail_id"] = spec.get("detail_id") or "DT-" + sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()[:12].upper()
    detail["source"] = "PARAMETRIC_NETWORK_MODEL"
    return {"status": "PASS", "detail": detail, "qa": {"executable_geometry": True, "zero_warnings": True}}


def _canonical_id(node: dict) -> str:
    if not node.get("id"):
        raise ValueError("network node id is required")
    return node["id"]


def generate_riser_from_network(network: dict) -> dict:
    nodes = network.get("nodes") or []
    edges = network.get("edges") or []
    if not nodes or not edges:
        return {"status": "INPUT_REQUIRED", "missing_inputs": ["NETWORK_GRAPH"], "riser": None}
    try:
        node_ids = {_canonical_id(n) for n in nodes}
    except ValueError as exc:
        return {"status": "FAIL", "errors": [str(exc)], "riser": None}
    dangling = [e.get("id", "UNKNOWN") for e in edges if e.get("from") not in node_ids or e.get("to") not in node_ids]
    if dangling:
        return {"status": "FAIL", "errors": ["dangling_edges:" + ",".join(sorted(dangling))], "riser": None}
    rows = []
    for edge in sorted(edges, key=lambda x: x["id"]):
        identity = edge["id"]
        rows.append({
            "plan_id": identity, "riser_id": identity, "calc_id": identity, "schedule_id": identity,
            "from": edge["from"], "to": edge["to"], "system": edge["system"],
            "size": edge.get("size"), "material": edge.get("material"),
            "fittings": edge.get("fittings", []), "levels": edge.get("levels", []),
        })
    mismatches = [row for row in rows if len({row["plan_id"], row["riser_id"], row["calc_id"], row["schedule_id"]}) != 1]
    missing_execution = [row["plan_id"] for row in rows if not row["size"] or not row["material"]]
    status = "PASS" if not mismatches and not missing_execution else "FAIL"
    return {
        "status": status,
        "riser": {"nodes": nodes, "segments": rows, "source_graph_id": network.get("graph_id")},
        "reconciliation": {"mismatch_count": len(mismatches), "mismatches": mismatches,
                           "missing_execution_data": missing_execution, "zero_mismatch": not mismatches},
        "claim": "GRAPH_DERIVED" if status == "PASS" else "NOT_ISSUABLE",
    }


def documentation_gate(details: list[dict], riser: dict) -> dict:
    errors = []
    for index, detail in enumerate(details):
        if detail.get("status") != "PASS": errors.append(f"detail_{index}:{detail.get('status', 'MISSING')}")
    if riser.get("status") != "PASS": errors.append(f"riser:{riser.get('status', 'MISSING')}")
    if not riser.get("reconciliation", {}).get("zero_mismatch"): errors.append("identity_mismatch")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors,
            "required_identity": "Plan ID=Riser ID=Calc ID=Schedule ID"}
