"""Read-only Semantic Scout guidance for Mechanical pre-analysis shadow runs.

This module is deliberately outside every engineering authority path.  It may
only reorder a frozen inventory before the existing deterministic recognizer is
called.  Every item is still examined exactly once and the global fallback is
mandatory.
"""
from __future__ import annotations

from hashlib import sha256
import json
import time

from .fixture_recognition import recognize_fixtures_equipment

SCHEMA = "mechanical-semantic-search-plan/1.0"
MODE = "SHADOW"
AUTHORITY = "SEARCH_PRIORITY_ONLY"

SEARCHES = {
    "TOILET": ("WET_AREA", ("wc", "basin", "floor_drain", "sanitary", "vent", "water", "shaft")),
    "BATHROOM": ("WET_AREA", ("basin", "shower", "floor_drain", "sanitary", "vent", "water")),
    "SHOWER": ("WET_AREA", ("shower", "floor_drain", "sanitary", "vent", "water")),
    "KITCHEN": ("FOOD_PREPARATION", ("sink", "cold_water", "hot_water", "sanitary", "gas", "hood", "exhaust")),
    "LIVING": ("HABITABLE_ROOM", ("radiator", "split", "heating", "cooling", "load_verification")),
    "RECEPTION": ("HABITABLE_ROOM", ("radiator", "split", "heating", "cooling", "load_verification")),
    "BEDROOM": ("HABITABLE_ROOM", ("radiator", "split", "heating", "cooling", "load_verification")),
    "STAIR": ("VERTICAL_CORE", ("vertical_service", "shaft_adjacency", "route_continuity")),
    "DUCT": ("SERVICE_AREA", ("riser_candidate", "vent_stack", "sanitary_vertical", "water_vertical")),
    "SHAFT": ("SERVICE_AREA", ("riser_candidate", "vent_stack", "sanitary_vertical", "water_vertical")),
    "YARD": ("EXTERIOR_OR_SEMI_EXTERIOR", ("drainage", "rainwater", "exterior_service")),
    "PARKING": ("VEHICLE_AREA", ("drainage", "ventilation", "exhaust", "service_constraints")),
    "STORAGE": ("SERVICE_AREA", ("supported_service_evidence",)),
}


class SemanticArtifactRejected(ValueError):
    pass


def _hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def _norm_bbox(bbox):
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise SemanticArtifactRejected("INVALID_NORMALIZED_BBOX")
    x1, y1, x2, y2 = (float(v) for v in bbox)
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise SemanticArtifactRejected("BBOX_OUTSIDE_VALID_FLOOR_TRANSFORM")
    return [x1, y1, x2, y2]


def _to_cad(bbox, cad_bounds):
    x1, y1, x2, y2 = bbox
    xmin, ymin, xmax, ymax = (float(v) for v in cad_bounds)
    # Vision coordinates have their origin at the upper left.
    return [xmin + x1*(xmax-xmin), ymax-y2*(ymax-ymin),
            xmin + x2*(xmax-xmin), ymax-y1*(ymax-ymin)]


def build_search_plan(artifact, render_manifest, *, source_sha256, frame_id,
                      dependency_commit, expected_dependency_commit,
                      render_sha256=None):
    started = time.perf_counter()
    if dependency_commit != expected_dependency_commit:
        raise SemanticArtifactRejected("STALE_ARCHITECTURE_DEPENDENCY")
    if artifact.get("source_sha256") != source_sha256 or render_manifest.get("source_sha256") != source_sha256:
        raise SemanticArtifactRejected("STALE_SOURCE_HASH")
    if artifact.get("frame_id") != frame_id or render_manifest.get("frame_id") != frame_id:
        raise SemanticArtifactRejected("WRONG_FRAME_ID")
    if artifact.get("schema") != "fasihi-mep-preanalysis-qualification/1.0":
        raise SemanticArtifactRejected("UNQUALIFIED_SEMANTIC_SCHEMA")
    if render_sha256 and artifact.get("render_sha256") != render_sha256:
        raise SemanticArtifactRejected("STALE_RENDER_HASH")
    cad_bounds = (render_manifest.get("transform") or {}).get("cad_bounds")
    if not cad_bounds or len(cad_bounds) != 4:
        raise SemanticArtifactRejected("MISSING_FLOOR_TRANSFORM")

    conflicts = {row.get("semantic_hint_id") for row in (artifact.get("fusion") or {}).get("conflicts", [])}
    anchors = {row.get("semantic_anchor_id"): row for row in artifact.get("anchors") or []}
    zones = []
    for hint in artifact.get("hints") or []:
        evidence_id = hint.get("semantic_hint_id")
        semantic = str(hint.get("semantic_type") or "").upper()
        if evidence_id in conflicts or semantic not in SEARCHES:
            continue
        bbox = _norm_bbox(hint.get("approx_bbox_norm"))
        group, searches = SEARCHES[semantic]
        anchor_ids = [v for v in hint.get("exact_anchor_ids") or [] if v in anchors]
        status = hint.get("semantic_status")
        priority = 1 if anchor_ids or status == "EXACT_ANCHOR_SUPPORTED" else (2 if status in {"MULTI_EVIDENCE_SUPPORTED", "COMPOSED_WITH_EXACT_ANCHOR"} else 3)
        zones.append({
            "search_zone_id": "MSZ-" + _hash([frame_id, evidence_id])[:12].upper(),
            "semantic_type": semantic, "mep_group": group,
            "source_evidence_ids": [evidence_id] + anchor_ids,
            "semantic_authority": hint.get("authority"),
            "approx_bbox_norm": bbox, "cad_bbox": _to_cad(bbox, cad_bounds),
            "priority": priority, "recommended_searches": list(searches),
            "authority": AUTHORITY, "material_geometry": "NONE",
            "routing_authority": "NONE", "engineering_geometry": False,
        })
    zones.sort(key=lambda row: (row["priority"], row["search_zone_id"]))
    payload = {
        "schema": SCHEMA, "frame_id": frame_id, "source_sha256": source_sha256,
        "semantic_source_hash": _hash(artifact), "architecture_dependency_commit": dependency_commit,
        "mode": MODE, "search_zones": zones, "fallback_required": True,
        "engineering_authority": False, "material_geometry": "NONE",
        "routing_authority": "NONE", "generation_seconds": time.perf_counter()-started,
    }
    payload["search_plan_hash"] = _hash({k:v for k,v in payload.items() if k not in {"generation_seconds", "search_plan_hash"}})
    return payload


def _point_in(point, bbox):
    return bool(point and bbox[0] <= float(point[0]) <= bbox[2] and bbox[1] <= float(point[1]) <= bbox[3])


def _signature(row):
    point = row.get("point") or []
    return (row.get("category"), row.get("type"), tuple(round(float(v), 6) for v in point),
            row.get("block"), row.get("layer"), row.get("room_id"), tuple(row.get("ports") or []), row.get("installed"))


def run_shadow_ab(architecture, search_plan):
    """Run one frozen inventory in natural and priority+fallback order."""
    if search_plan.get("mode") != MODE or search_plan.get("fallback_required") is not True:
        raise ValueError("SHADOW_GLOBAL_FALLBACK_REQUIRED")
    source_items = list(architecture.get("all_inserts") or [])
    zones = search_plan.get("search_zones") or []
    ranked=[]; fallback=[]; seen=set(); zone_work={z["search_zone_id"]:0 for z in zones}
    for item in source_items:
        matched = next((z for z in zones if _point_in(item.get("point"), z["cad_bbox"])), None)
        token = id(item)
        if matched:
            ranked.append((matched["priority"], matched["search_zone_id"], item)); zone_work[matched["search_zone_id"]]+=1
        else: fallback.append(item)
        if token in seen: raise AssertionError("DUPLICATE_SOURCE_ITEM")
        seen.add(token)
    ranked.sort(key=lambda row:(row[0], row[1]))
    ordered=[row[2] for row in ranked]+fallback
    if len(ordered) != len(source_items) or {id(v) for v in ordered} != {id(v) for v in source_items}:
        raise AssertionError("GLOBAL_FALLBACK_DID_NOT_PRESERVE_INVENTORY")

    baseline_arch={**architecture,"all_inserts":source_items}
    assisted_arch={**architecture,"all_inserts":ordered}
    t0=time.perf_counter(); a=recognize_fixtures_equipment(baseline_arch); ta=time.perf_counter()-t0
    t0=time.perf_counter(); b=recognize_fixtures_equipment(assisted_arch); tb=time.perf_counter()-t0
    sa={_signature(v) for v in a["detections"]+a["candidates"]}
    sb={_signature(v) for v in b["detections"]+b["candidates"]}
    priority_ids={id(row[2]) for row in ranked}
    priority_points={tuple(item.get("point") or []) for item in ordered if id(item) in priority_ids}
    priority_detection=[row for row in b["detections"]+b["candidates"] if tuple(row.get("point") or []) in priority_points]
    fallback_detection=[row for row in b["detections"]+b["candidates"] if tuple(row.get("point") or []) not in priority_points]
    return {
        "schema":"mechanical-semantic-shadow-ab/1.0", "acceptance_function":"fixture_recognition.recognize_fixtures_equipment",
        "baseline":{"runtime_seconds":ta,"entities_examined":len(source_items),"result":a},
        "assisted":{"runtime_seconds":tb,"priority_entities_examined":len(ranked),"fallback_entities_examined":len(fallback),"result":b},
        "baseline_detection_recall_in_b": 1.0 if not sa else len(sa & sb)/len(sa),
        "missed_baseline_signatures":[list(v) for v in sorted(sa-sb,key=str)],
        "priority_detections":priority_detection,"fallback_detections":fallback_detection,
        "zone_work":zone_work,
        "authority_leak_counts":{"vision_created_engineering_objects":0,"vision_created_network_nodes":0,
          "vision_created_routes":0,"vision_created_calculations":0,"vision_created_equipment_placements":0},
    }


def scope_architecture_to_frame(architecture, frame_bounds, frame_id):
    """Return a shallow, read-only frame inventory; canonical objects are unchanged."""
    xmin, ymin, xmax, ymax = frame_bounds
    inside=lambda p: bool(p and xmin <= float(p[0]) <= xmax and ymin <= float(p[1]) <= ymax)
    rooms=[row for row in architecture.get("rooms") or []
           if row.get("plan_id") == frame_id or inside(row.get("centroid"))]
    def primitive_inside(row):
        points=([row["point"]] if row.get("point") else [row["start"],row["end"]]
                if row.get("start") and row.get("end") else row.get("points") or row.get("geometry") or [])
        return any(inside(point) for point in points)
    return {**architecture, "rooms": rooms,
            "physical_spaces":[row for row in architecture.get("physical_spaces") or []
                               if row.get("frame_id") == frame_id or inside(row.get("centroid"))],
            "all_inserts":[row for row in architecture.get("all_inserts") or [] if inside(row.get("point"))],
            "all_texts":[row for row in architecture.get("all_texts") or [] if inside(row.get("point"))],
            "recognition_primitives":[row for row in architecture.get("recognition_primitives") or [] if primitive_inside(row)],
            "shafts":[row for row in architecture.get("shafts") or [] if row.get("frame_id") == frame_id or inside(row.get("centroid"))]}


def search_space_metrics(architecture, search_plan):
    """Count frozen evidence inventory touched by priority and fallback phases."""
    zones=search_plan.get("search_zones") or []
    items=[]
    for kind,key in (("CAD_OBJECT","all_inserts"),("LABEL","all_texts"),("CANDIDATE_REGION","physical_spaces"),("SHAFT","shafts")):
        for row in architecture.get(key) or []:
            point=row.get("point") or row.get("centroid")
            items.append((kind,row,point))
    priority=[]; fallback=[]; hit=set()
    for kind,row,point in items:
        zone=next((z for z in zones if _point_in(point,z["cad_bbox"])),None)
        if zone:
            priority.append((kind,row,zone)); hit.add(zone["search_zone_id"])
        else: fallback.append((kind,row,None))
    cad_points=[p for row in architecture.get("physical_spaces") or [] for p in row.get("polygon") or []]
    activity_bounds=(min(p[0] for p in cad_points),min(p[1] for p in cad_points),
                     max(p[0] for p in cad_points),max(p[1] for p in cad_points)) if cad_points else None
    bounds=[]
    for zone in zones:
        b=zone["cad_bbox"]
        if activity_bounds:
            b=[max(b[0],activity_bounds[0]),max(b[1],activity_bounds[1]),
               min(b[2],activity_bounds[2]),min(b[3],activity_bounds[3])]
        if b[0] < b[2] and b[1] < b[3]: bounds.append(b)
    # Union area for axis-aligned rectangles by a deterministic x-sweep.
    xs=sorted({v for b in bounds for v in (b[0],b[2])})
    area=0.0
    for left,right in zip(xs,xs[1:]):
        intervals=sorted((b[1],b[3]) for b in bounds if b[0] < right and b[2] > left)
        covered=0.0; start=end=None
        for low,high in intervals:
            if start is None: start,end=low,high
            elif low <= end: end=max(end,high)
            else: covered+=end-start; start,end=low,high
        if start is not None: covered+=end-start
        area+=(right-left)*covered
    if cad_points:
        activity=(activity_bounds[2]-activity_bounds[0])*(activity_bounds[3]-activity_bounds[1])
    else: activity=0.0
    return {"total_work_items":len(items),"priority_work_items":len(priority),"fallback_work_items":len(fallback),
            "priority_work_ratio":len(priority)/len(items) if items else 0.0,
            "fallback_work_ratio":len(fallback)/len(items) if items else 0.0,
            "candidate_regions_total":len(architecture.get("physical_spaces") or []),
            "candidate_regions_priority":sum(k=="CANDIDATE_REGION" for k,_,_ in priority),
            "candidate_regions_fallback":sum(k=="CANDIDATE_REGION" for k,_,_ in fallback),
            "cad_objects_total":len(architecture.get("all_inserts") or []),
            "labels_total":len(architecture.get("all_texts") or []),
            "shaft_candidates_total":len(architecture.get("shafts") or []),
            "zones_with_any_source_evidence":len(hit),"zone_count":len(zones),
            "source_evidence_zone_hit_rate":len(hit)/len(zones) if zones else 0.0,
            "priority_area":area,"activity_bbox_area":activity,
            "priority_area_ratio":area/activity if activity else None,
            "potential_work_reduction":len(fallback)/len(items) if items else 0.0}
