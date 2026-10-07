"""Explicit spatial-authority declarations for synthetic canonical test models."""


FACTS = (
    "ROOM_POLYGON", "METRIC_AREA", "SITE_RELATION", "ENCLOSURE_TOPOLOGY",
    "ACCESS_TOPOLOGY", "VERTICAL_CIRCULATION",
)

CONSUMERS = {
    "MECHANICAL_ROOM_LOAD": ["ROOM_POLYGON", "METRIC_AREA"],
    "EXTERIOR_WALL_LOAD": ["ROOM_POLYGON", "METRIC_AREA", "SITE_RELATION", "ENCLOSURE_TOPOLOGY"],
    "MECHANICAL_ROUTING": ["ROOM_POLYGON", "ENCLOSURE_TOPOLOGY", "ACCESS_TOPOLOGY"],
    "VERTICAL_ROUTING": ["ROOM_POLYGON", "ACCESS_TOPOLOGY", "VERTICAL_CIRCULATION"],
}


def declare_verified_spatial_authority(model):
    """Make synthetic evidence explicit instead of relying on legacy release booleans."""
    for space in model.get("physical_spaces") or []:
        points = space.get("polygon") or []
        if len(points) >= 3:
            ring = points + ([] if points[0] == points[-1] else [points[0]])
            handle = str((space.get("source_handles") or [space["physical_space_id"]])[0])
            space["boundary_segments"] = [
                {"boundary_segment_id": f"{space['physical_space_id']}-B{index + 1}",
                 "geometry": [start, end], "source_handles": [handle], "status": "VERIFIED",
                 "opposite_relation": "SYNTHETIC_TEST_EXTERIOR"}
                for index, (start, end) in enumerate(zip(ring, ring[1:]))
            ]
        space["authority_level"] = "ENGINEERING_READY"
        space["area_authority"] = "METRIC"
        space.setdefault("space_geometry_type", "ENCLOSED_INTERIOR")
    facts = {name: {"granted": True, "status": "VERIFIED"} for name in FACTS}
    matrix = {"facts": facts, "consumers": {
        name: {"required_authorities": required, "missing_authorities": [], "allowed": True}
        for name, required in CONSUMERS.items()
    }}
    model["spatial_authority"] = {
        "schema": "planha-architecture-spatial-authority/1.0", "status": "VERIFIED",
        "text_creates_geometry": False, "vision_geometry_authority": False,
        "site_boundaries": [], "site_spaces": [],
        "vertical_circulation": {"stair_assemblies": [], "elevators": [], "shafts": []},
        "graph_qualification": {"enclosure_graph": {"status": "VERIFIED"},
                                "access_graph": {"status": "VERIFIED"}},
        "engineering_authority_matrix": matrix,
        "counters": {"unsupported_verified_geometry": 0,
                     "text_created_verified_geometry": 0,
                     "unsupported_verified_stairs": 0},
    }
    model["engineering_authority_matrix"] = matrix
    return model
