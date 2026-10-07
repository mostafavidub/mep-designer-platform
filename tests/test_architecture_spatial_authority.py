from copy import deepcopy
import json
from pathlib import Path

from cad_engine.architecture_spatial_authority import (
    qualify_spatial_understanding,
    require_architecture_authorities,
)


def _primitive(handle, points, *, closed=False, layer="A-WALL"):
    return {"handle": handle, "points": points, "closed": closed,
            "layer": layer, "entity_type": "LWPOLYLINE" if closed else "LINE"}


def _model(*, scale=0.01, geometry_status="VERIFIED"):
    ring = [[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]]
    space = {
        "physical_space_id": "PS-1", "frame_id": "FRAME-1",
        "polygon": ring,
        "interior_rings": [], "geometry_status": geometry_status,
        "topology_status": "VERIFIED", "area_m2": 0.36 if scale else None,
        "geometry_evidence": {"status": geometry_status, "source_handles": ["ROOM-1"],
                              "segments": [{"geometry":[a,b],"source_handle":"ROOM-1",
                                            "opposite_space_id":"EXTERIOR"}
                                           for a,b in zip(ring,ring[1:])]},
        "source_handles": ["ROOM-1"], "text_evidence_ids": ["TEXT-1"],
        "functional_zones": [],
    }
    return {
        "source": {"metres_per_unit": scale},
        "frames": [{"frame_id": "FRAME-1", "bounds": [-5, -5, 20, 20]}],
        "building_envelopes": [{"frame_id": "FRAME-1", "status": "VERIFIED",
                                "outer_ring": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]}],
        "physical_spaces": [space],
        "openings": [{"opening_id": "OPEN-1", "portal_id": "PORTAL-1", "status": "VERIFIED",
                      "host_wall_id": "WALL-1", "kind": "door"}],
        "enclosure_graph": {"edges": [["PS-1", "EXTERIOR"]]},
        "access_graph": {"edges": [{"portal_id": "PORTAL-1", "space_a": "PS-1", "space_b": "EXTERIOR"}]},
    }


def _qualified_extraction():
    rows = [
        _primitive("SITE-1", [[-2, -2], [12, -2], [12, 12], [-2, 12], [-2, -2]], closed=True, layer="A-SITE"),
        _primitive("STAIR-CORE", [[2.5, 2.5], [7.5, 2.5], [7.5, 7.5], [2.5, 7.5], [2.5, 2.5]], closed=True),
        _primitive("RAIL-L", [[3, 3], [3, 7]]), _primitive("RAIL-R", [[7, 3], [7, 7]]),
    ]
    rows.extend(_primitive(f"TREAD-{i}", [[3, 3 + i * .75], [7, 3 + i * .75]]) for i in range(5))
    return {"primitives": rows}


def test_source_backed_space_site_stair_and_capability_matrix_are_granular():
    model = qualify_spatial_understanding(_model(), _qualified_extraction(), 0.01)
    authority = model["spatial_authority"]
    assert authority["text_creates_geometry"] is False
    assert authority["vision_geometry_authority"] is False
    assert authority["site_boundaries"][0]["status"] == "VERIFIED"
    assert authority["site_spaces"][0]["space_geometry_type"] == "EXTERIOR_SITE_SPACE"
    assert authority["vertical_circulation"]["stair_assemblies"][0]["status"] == "VERIFIED"
    assert model["physical_spaces"][0]["space_geometry_type"] == "VERTICAL_CIRCULATION"
    assert model["physical_spaces"][0]["authority_level"] == "ENGINEERING_READY"
    assert authority["counters"]["unsupported_verified_geometry"] == 0
    assert require_architecture_authorities(model, "MECHANICAL_ROUTING")["allowed"] is True


def test_text_and_unknown_site_never_create_verified_geometry():
    model = _model(geometry_status="INPUT_REQUIRED")
    model["physical_spaces"][0]["geometry_evidence"] = {"status": "INPUT_REQUIRED", "source_handles": []}
    model["physical_spaces"][0]["source_handles"] = []
    extracted = {"primitives": [_primitive("LABEL-BOX", [[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]], closed=True)]}
    result = qualify_spatial_understanding(model, extracted, 0.01)
    assert result["physical_spaces"][0]["authority_level"] == "GEOMETRY_CANDIDATE"
    assert result["spatial_authority"]["site_boundaries"][0]["status"] == "INPUT_REQUIRED"
    assert result["spatial_authority"]["site_spaces"] == []
    decision = require_architecture_authorities(result, "EXTERIOR_WALL_LOAD")
    assert decision["allowed"] is False
    assert "SITE_RELATION" in decision["missing_authorities"]


def test_repeated_parallel_lines_without_source_core_fail_closed_as_stair():
    model = _model()
    primitives = [_primitive(f"REPEAT-{i}", [[3, 3 + i * .75], [7, 3 + i * .75]]) for i in range(6)]
    result = qualify_spatial_understanding(model, {"primitives": primitives}, 0.01)
    stairs = result["spatial_authority"]["vertical_circulation"]["stair_assemblies"]
    assert stairs
    assert all(row["status"] == "INPUT_REQUIRED" for row in stairs)
    assert require_architecture_authorities(result, "VERTICAL_ROUTING")["allowed"] is False


def test_unknown_consumer_is_never_implicitly_authorized():
    assert require_architecture_authorities({}, "UNKNOWN_CONSUMER") == {
        "status": "INPUT_REQUIRED", "allowed": False,
        "missing_authorities": ["DECLARED_CONSUMER_PREREQUISITES"],
    }


def test_boundary_segments_bind_to_their_exact_source_witnesses():
    model=_model()
    ring=model["physical_spaces"][0]["polygon"]
    model["physical_spaces"][0]["source_handles"]=["A","B","C","D"]
    model["physical_spaces"][0]["geometry_evidence"]={
        "status":"VERIFIED","source_handles":["A","B","C","D"],
        "segments":[{"geometry":[a,b],"source_handle":handle,"opposite_space_id":"EXTERIOR"}
                    for (a,b),handle in zip(zip(ring,ring[1:]),["A","B","C","D"])]}
    result=qualify_spatial_understanding(model,_qualified_extraction(),.01)
    segments=result["physical_spaces"][0]["boundary_segments"]
    assert [row["source_handles"] for row in segments]==[["A"],["B"],["C"],["D"]]
    assert all(row["status"]=="VERIFIED" for row in segments)


def test_real_corpus_manifest_is_privacy_safe_and_fail_closed():
    path=Path(__file__).parents[1]/"standards"/"test-suites"/"architecture-spatial-real-corpus-v1.json"
    manifest=json.loads(path.read_text())
    assert manifest["privacy"]["source_drawings_committed"] is False
    assert manifest["vision_provider_calls"]==0
    assert len(manifest["cases"])==7 and manifest["review_case_count"]==8
    assert all(len(row["source_sha256"])==64 and row["status"]=="INPUT_REQUIRED" for row in manifest["cases"])
    assert manifest["qualification"]["fully_qualified_cases"]==0
