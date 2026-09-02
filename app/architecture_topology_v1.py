"""Architecture Topology v1.

Turns reconstructed per-level geometry into engineering relationships required
by MEP design: stable room IDs, door/window adjacency, nearest shafts, wet-core
clusters, service/equipment candidate zones and roof service zones.
"""
import math

TOPOLOGY_VERSION = "architecture-topology-v1"
WET_TYPES = {"kitchen", "bath", "toilet"}
SERVICE_TYPES = {"kitchen", "bath", "toilet", "parking"}


def _center(bounds, fallback=None):
    if bounds and len(bounds) == 4:
        return [(bounds[0]+bounds[2])/2.0, (bounds[1]+bounds[3])/2.0]
    return list(fallback or [0.0, 0.0])


def _diag(bounds):
    if not bounds or len(bounds) != 4:
        return 1.0
    return max(math.hypot(bounds[2]-bounds[0], bounds[3]-bounds[1]), 1.0)


def _distance(a, b):
    return math.dist(tuple(a), tuple(b))


def _cluster(items, threshold):
    """Simple connected-component clustering by centroid proximity."""
    pending = list(range(len(items))); groups = []
    while pending:
        seed = pending.pop(0); component = {seed}; changed = True
        while changed:
            changed = False
            for idx in list(pending):
                if any(_distance(items[idx]["center"], items[j]["center"]) <= threshold for j in component):
                    pending.remove(idx); component.add(idx); changed = True
        groups.append([items[i] for i in sorted(component)])
    return groups


def enrich_architecture_topology(auto):
    auto = dict(auto or {})
    model = dict(auto.get("architecture_model") or {})
    levels = []
    for level_index, raw_level in enumerate(model.get("levels") or [], 1):
        level = dict(raw_level)
        region_diag = _diag(level.get("region_bounds"))
        proximity = max(region_diag * 0.12, 1.0)

        rooms = []
        for room_index, raw_room in enumerate(level.get("rooms") or [], 1):
            room = dict(raw_room)
            room_id = f"L{level_index:02d}-R{room_index:03d}"
            room["id"] = room_id
            room["center"] = _center(room.get("bounds"), room.get("label_point"))
            room["wet"] = room.get("type") in WET_TYPES
            room["service_candidate"] = room.get("type") in SERVICE_TYPES
            room["door_ids"] = []
            room["window_ids"] = []
            rooms.append(room)

        def decorate(items, prefix):
            out = []
            for i, item in enumerate(items or [], 1):
                row = dict(item); row["id"] = f"L{level_index:02d}-{prefix}{i:03d}"
                row["center"] = _center(row.get("bounds"), row.get("centroid"))
                out.append(row)
            return out

        doors = decorate(level.get("doors"), "D")
        windows = decorate(level.get("windows"), "W")
        shafts = decorate(level.get("shafts"), "S")
        stairs = decorate(level.get("stairs"), "T")
        columns = decorate(level.get("columns"), "C")

        # Doors/windows are associated by nearest room only within a bounded
        # proximity, so annotations or symbols from another plan are not linked.
        for collection, field in ((doors, "door_ids"), (windows, "window_ids")):
            for item in collection:
                containing = [r for r in rooms if r.get("bounds") and _center(r.get("bounds")) and
                              r["bounds"][0] <= item["center"][0] <= r["bounds"][2] and
                              r["bounds"][1] <= item["center"][1] <= r["bounds"][3]]
                candidates = [(r, _distance(item["center"], r["center"])) for r in rooms]
                if containing or candidates:
                    room, dist = ((min(((r, _distance(item["center"], r["center"])) for r in containing), key=lambda x: x[1]))
                                  if containing else min(candidates, key=lambda x: x[1]))
                    if containing or dist <= proximity:
                        room[field].append(item["id"])
                        item["nearest_room_id"] = room["id"]
                        item["nearest_room_distance"] = round(dist, 4)

        for room in rooms:
            if shafts:
                shaft, dist = min(((s, _distance(room["center"], s["center"])) for s in shafts), key=lambda x: x[1])
                room["nearest_shaft_id"] = shaft["id"]
                room["nearest_shaft_distance"] = round(dist, 4)
            else:
                room["nearest_shaft_id"] = None
                room["nearest_shaft_distance"] = None

        wet_rooms = [r for r in rooms if r["wet"]]
        wet_groups = _cluster(wet_rooms, max(region_diag * 0.22, 1.0)) if wet_rooms else []
        wet_cores = []
        for i, group in enumerate(wet_groups, 1):
            centers = [r["center"] for r in group]
            cx = sum(p[0] for p in centers)/len(centers); cy = sum(p[1] for p in centers)/len(centers)
            nearest_shaft = None
            if shafts:
                nearest_shaft = min(shafts, key=lambda s: _distance([cx, cy], s["center"]))
            wet_cores.append({
                "id": f"L{level_index:02d}-WC{i:02d}",
                "room_ids": [r["id"] for r in group],
                "room_types": [r.get("type") for r in group],
                "center": [round(cx, 6), round(cy, 6)],
                "nearest_shaft_id": nearest_shaft.get("id") if nearest_shaft else None,
                "design_basis": "clustered wet rooms + nearest reconstructed shaft",
            })

        equipment_zones = []
        for room in rooms:
            if room["service_candidate"]:
                equipment_zones.append({
                    "id": f"{room['id']}-EZ", "kind": "room_service_zone",
                    "room_id": room["id"], "room_type": room.get("type"),
                    "bounds": room.get("bounds"), "center": room["center"],
                })
        if level.get("roof"):
            equipment_zones.append({
                "id": f"L{level_index:02d}-ROOF-EZ", "kind": "roof_service_zone",
                "room_id": None, "room_type": "roof", "bounds": level.get("region_bounds"),
                "center": _center(level.get("region_bounds"), level.get("title_point")),
            })

        level.update({
            "rooms": rooms, "doors": doors, "windows": windows, "shafts": shafts,
            "stairs": stairs, "columns": columns, "wet_cores": wet_cores,
            "equipment_candidate_zones": equipment_zones,
            "topology_counts": {
                "rooms": len(rooms), "doors": len(doors), "windows": len(windows),
                "shafts": len(shafts), "stairs": len(stairs), "columns": len(columns),
                "wet_cores": len(wet_cores), "equipment_zones": len(equipment_zones),
            },
        })
        levels.append(level)

    model["levels"] = levels
    model["topology_version"] = TOPOLOGY_VERSION
    model["wet_core_count"] = sum(len(x.get("wet_cores") or []) for x in levels)
    model["equipment_zone_count"] = sum(len(x.get("equipment_candidate_zones") or []) for x in levels)
    auto["architecture_model"] = model
    return auto


def install(main_auto_module):
    if getattr(main_auto_module, "_architecture_topology_v1_installed", False):
        return
    base_infer = main_auto_module.infer_architecture_facts

    def infer(analysis, discipline):
        return enrich_architecture_topology(base_infer(analysis, discipline))

    main_auto_module.infer_architecture_facts = infer
    main_auto_module._architecture_topology_v1_installed = True
