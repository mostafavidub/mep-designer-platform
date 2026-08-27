"""Stage 11 — authority-style acceptance gate for real mechanical output.

Unit tests prove code paths. This module proves that the generated engineering
content has the minimum connected information expected in an approval-oriented
mechanical drawing: architectural evidence, installed fixtures, independent
systems, real vertical cores, routed/sized networks, drawing annotations and
traceable dynamic details.
"""
from __future__ import annotations

PLUMBING_FIXTURES = {"wc", "basin", "sink", "shower", "floor_drain"}
REQUIRED_PLUMBING_SYSTEMS = {"sanitary", "vent"}
REQUIRED_PLUMBING_DETAILS = {"sanitary_riser", "cleanout", "vent_termination"}


def _gate(name, errors, metrics=None):
    return {
        "name": name,
        "status": "PASS" if not errors else "FAIL",
        "errors": list(errors),
        "metrics": metrics or {},
    }


def evaluate_engineering_acceptance(pipeline):
    """Return strict, stage-oriented acceptance results for one pipeline run."""
    gates = []
    arch = pipeline.get("architecture") or {}
    rooms = arch.get("rooms") or []
    room_polygons = [r for r in rooms if r.get("polygon")]
    arch_errors = []
    if not rooms:
        arch_errors.append("no_rooms")
    if rooms and len(room_polygons) / len(rooms) < 0.80:
        arch_errors.append("insufficient_room_geometry")
    if not arch.get("walls"):
        arch_errors.append("no_architectural_wall_evidence")
    if not arch.get("shafts"):
        arch_errors.append("no_real_shaft_evidence")
    gates.append(_gate("architecture", arch_errors, {
        "rooms": len(rooms), "rooms_with_polygon": len(room_polygons),
        "walls": len(arch.get("walls") or []), "shafts": len(arch.get("shafts") or []),
    }))

    rec = pipeline.get("recognition") or {}
    detections = rec.get("detections") or []
    plumbing = [x for x in detections if x.get("type") in PLUMBING_FIXTURES]
    assigned = [x for x in plumbing if x.get("room_id")]
    rec_errors = []
    if not plumbing:
        rec_errors.append("no_plumbing_fixture_evidence")
    if plumbing and len(assigned) / len(plumbing) < 0.80:
        rec_errors.append("fixtures_not_assigned_to_rooms")
    gates.append(_gate("fixture_recognition", rec_errors, {
        "plumbing_fixtures": len(plumbing), "room_assigned": len(assigned),
    }))

    req = pipeline.get("requirements") or {}
    systems = set(req.get("project_systems") or [])
    req_errors = []
    if plumbing and not REQUIRED_PLUMBING_SYSTEMS.issubset(systems):
        req_errors.append("sanitary_vent_not_both_required")
    gates.append(_gate("system_requirements", req_errors, {"systems": sorted(systems)}))

    topology = pipeline.get("topology") or {}
    edges = topology.get("edges") or []
    topo_errors = []
    if (topology.get("quality") or {}).get("provisional_shaft"):
        topo_errors.append("provisional_shaft_not_authority_acceptable")
    sanitary_edges = [e for e in edges if e.get("system") == "sanitary"]
    vent_edges = [e for e in edges if e.get("system") == "vent"]
    if plumbing and not sanitary_edges:
        topo_errors.append("no_sanitary_topology")
    if plumbing and not vent_edges:
        topo_errors.append("no_vent_topology")
    if {e.get("id") for e in sanitary_edges} & {e.get("id") for e in vent_edges}:
        topo_errors.append("sanitary_vent_topology_not_independent")
    gates.append(_gate("topology", topo_errors, {
        "sanitary_edges": len(sanitary_edges), "vent_edges": len(vent_edges),
    }))

    routing = pipeline.get("routing") or {}
    routes = routing.get("routes") or []
    route_errors = []
    if len(routes) != len(edges):
        route_errors.append("not_all_topology_edges_routed")
    if any((r.get("wall_crossings") or 0) > 0 for r in routes):
        route_errors.append("route_crosses_architectural_wall")
    if not (routing.get("quality") or {}).get("all_orthogonal", False):
        route_errors.append("non_orthogonal_route")
    if any((r.get("length") or 0) <= 0 for r in routes):
        route_errors.append("degenerate_route")
    gates.append(_gate("routing", route_errors, {
        "routes": len(routes), "wall_crossings": sum(r.get("wall_crossings") or 0 for r in routes),
    }))

    sizing = pipeline.get("sizing") or {}
    segments = sizing.get("segments") or []
    sized = {x.get("route_id"): x for x in segments if x.get("size_mm") is not None}
    size_errors = []
    route_ids = {r.get("id") for r in routes}
    if route_ids - set(sized):
        size_errors.append("unsized_routes")
    sanitary_segments = [x for x in segments if x.get("system") == "sanitary"]
    if sanitary_segments and any(x.get("slope_percent") is None or not (0.5 <= float(x["slope_percent"]) <= 5.0) for x in sanitary_segments):
        size_errors.append("invalid_or_missing_sanitary_slope")
    gates.append(_gate("sizing", size_errors, {
        "segments": len(segments), "sized": len(sized), "sanitary_sloped": len(sanitary_segments),
    }))

    annotations = (pipeline.get("annotations") or {}).get("annotations") or []
    route_annotations = {x.get("route_id") for x in annotations if x.get("route_id")}
    text_blob = "\n".join(str(x.get("text") or "").upper() for x in annotations)
    ann_errors = []
    if route_ids - route_annotations:
        ann_errors.append("routes_missing_annotations")
    if sanitary_segments and "SLOPE" not in text_blob:
        ann_errors.append("sanitary_slope_not_annotated")
    if vent_edges and ("VENT" not in text_blob or "ROOF" not in text_blob):
        ann_errors.append("vent_termination_not_annotated")
    if plumbing and "C.O" not in text_blob:
        ann_errors.append("cleanout_not_annotated")
    if sanitary_edges and "SANITARY RISER" not in text_blob:
        ann_errors.append("sanitary_riser_not_tagged")
    if vent_edges and "VENT RISER" not in text_blob:
        ann_errors.append("vent_riser_not_tagged")
    if any(x.get("type") == "floor_drain" for x in plumbing) and "FD" not in text_blob:
        ann_errors.append("floor_drain_not_annotated")
    gates.append(_gate("annotations", ann_errors, {"annotations": len(annotations)}))

    detail_rows = (pipeline.get("details") or {}).get("details") or []
    kinds = {x.get("kind") for x in detail_rows}
    detail_errors = []
    if plumbing and not REQUIRED_PLUMBING_DETAILS.issubset(kinds):
        detail_errors.append("missing_sanitary_vent_detail_family")
    for row in detail_rows:
        missing = [k for k in row.get("required_fields") or [] if (row.get("parameters") or {}).get(k) in (None, "", [])]
        if missing:
            detail_errors.append(f"incomplete_detail:{row.get('kind')}:{','.join(missing)}")
    gates.append(_gate("details", detail_errors, {"detail_kinds": sorted(k for k in kinds if k)}))

    errors = [f"{g['name']}:{e}" for g in gates for e in g["errors"]]
    return {
        "version": "engineering-acceptance-v13.11",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "gates": gates,
    }
