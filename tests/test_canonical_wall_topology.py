from shapely.geometry import LineString

from cad_engine.architectural_topology_quality import (
    building_envelope_from_walls,
    canonical_space_subdivision,
    host_portal_on_walls,
    reconstruct_canonical_walls,
)


def _row(handle, a, b, *, status="ACCEPTED", frame="F1"):
    return {
        "segment_id": f"SEG-{handle}", "source_handle": handle,
        "geometry": [a, b], "frame_id": frame, "status": status,
    }


def test_fragmented_wall_has_stable_identity_and_preserves_door_gap():
    rows = []
    for y, prefix in ((0.0, "A"), (0.2, "B")):
        rows += [_row(prefix + "1", (0, y), (4, y)), _row(prefix + "2", (5, y), (10, y))]
    # A second repeated pair establishes the frame-local thickness cluster.
    rows += [_row("C", (0, 3), (10, 3)), _row("D", (0, 3.2), (10, 3.2))]
    first = reconstruct_canonical_walls(rows, frame_id="F1", tolerance=.001)
    repeat = reconstruct_canonical_walls(rows, frame_id="F1", tolerance=.001)
    assert first["thickness_clusters"]
    assert [w["wall_id"] for w in first["walls"]] == [w["wall_id"] for w in repeat["walls"]]
    host, reason, _ = host_portal_on_walls(LineString(((4, 0), (5, 0))), first["walls"],
                                            tolerance=.001, pixel_tolerance=.01)
    assert host is not None and reason == "WALL_OBJECT_GAP_SUPPORT"
    assert host["interruptions"]


def test_random_portal_and_portal_over_continuous_wall_are_rejected():
    rows = [_row("A", (0, 0), (10, 0)), _row("B", (0, .2), (10, .2)),
            _row("C", (0, 3), (10, 3)), _row("D", (0, 3.2), (10, 3.2))]
    result = reconstruct_canonical_walls(rows, frame_id="F1", tolerance=.001)
    assert host_portal_on_walls(LineString(((20, 0), (21, 0))), result["walls"],
                                tolerance=.001, pixel_tolerance=.01)[1] == "NO_NEARBY_WALL"
    assert host_portal_on_walls(LineString(((4, 0), (5, 0))), result["walls"],
                                tolerance=.001, pixel_tolerance=.01)[1] == "NO_WALL_GAP"


def test_rectangle_envelope_is_first_class_and_sheet_border_is_not_implicitly_used():
    rows = [_row(str(i), a, b) for i, (a, b) in enumerate([
        ((0, 0), (10, 0)), ((10, 0), (10, 6)), ((10, 6), (0, 6)), ((0, 6), (0, 0)),
    ])]
    result = reconstruct_canonical_walls(rows, frame_id="F1", tolerance=.001)
    envelope = building_envelope_from_walls(result["walls"], frame_id="F1", tolerance=.001)
    assert envelope["status"] == "HIGH_CONFIDENCE"
    assert envelope["area"] == 60
    assert envelope["evidence"][0]["class"] == "CANONICAL_WALL_CYCLE"


def test_rejected_annotation_never_enters_wall_objects():
    rows = [_row("W", (0, 0), (10, 0)), _row("NOTE", (0, 1), (10, 1), status="REJECTED")]
    result = reconstruct_canonical_walls(rows, frame_id="F1", tolerance=.001)
    assert all("SEG-NOTE" not in wall["source_fragments"] for wall in result["walls"])


def _wall(wall_id, a, b, occupied, interruptions=()):
    line=LineString((a,b)); length=line.length
    ux=(b[0]-a[0])/length; uy=(b[1]-a[1])/length
    return {"wall_id":wall_id,"frame_id":"F1","centerline":[a,b],"face_a":None,"face_b":None,
            "wall_solid":{"axis_origin":list(a),"axis_direction":[ux,uy],"occupied_intervals":occupied},
            "interruptions":[{"interval":list(row),"kind":"SUPPORTED_OPENING"} for row in interruptions],
            "source_fragments":[],"source_handles":[],"thickness":None}


def _envelope():
    return {"building_envelope_id":"ENV-1","frame_id":"F1","status":"HIGH_CONFIDENCE",
            "outer_ring":[[0,0],[10,0],[10,6],[0,6],[0,0]],"interior_voids":[]}


def test_canonical_subdivision_uses_envelope_wall_material_and_virtual_closure():
    walls=[_wall("PART",(5,0),(5,6),[[0,2.5],[3.5,6]],[(2.5,3.5)])]
    result=canonical_space_subdivision(walls,_envelope(),frame_id="F1",tolerance=.001)
    assert result["authority"]=="CANONICAL"
    assert len(result["cells"])==2
    assert any(row["kind"]=="VIRTUAL_CLOSURE" for row in result["barriers"])
    assert result["edges"][0]["closure_ids"]


def test_open_plan_without_wall_remains_one_physical_space():
    result=canonical_space_subdivision([],_envelope(),frame_id="F1",tolerance=.001)
    assert len(result["cells"])==1


def test_shaft_is_preserved_as_topological_hole():
    envelope=_envelope(); envelope["interior_voids"]=[[[4,2],[6,2],[6,4],[4,4],[4,2]]]
    result=canonical_space_subdivision([],envelope,frame_id="F1",tolerance=.001)
    assert len(result["cells"])==1
    assert result["cells"][0]["interior_rings"]


def test_unproven_envelope_cannot_become_canonical_authority():
    envelope=_envelope(); envelope["status"]="INPUT_REQUIRED"
    result=canonical_space_subdivision([],envelope,frame_id="F1",tolerance=.001)
    assert result["authority"]=="LEGACY_FALLBACK"
    assert result["cells"]==[]


def test_fragmentation_gap_cannot_host_a_portal():
    wall=_wall("W",(0,0),(10,0),[[0,4],[5,10]],[(4,5)])
    wall["interruptions"][0]["kind"]="UNKNOWN_FRAGMENTATION"
    assert host_portal_on_walls(LineString(((4,0),(5,0))),[wall],tolerance=.001,pixel_tolerance=.01)[1]=="NO_WALL_GAP"
