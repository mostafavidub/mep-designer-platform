from shapely.geometry import LineString

from cad_engine.architectural_topology_quality import (
    building_envelope_from_walls,
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
