from cad_engine.architecture_stair_evidence import detect_stair_evidence, _corner_landing_evidence
import pytest


SOURCE = "a"*64
FRAME = [{"id": "P1", "drawing_type": "ARCH_FLOOR_PLAN", "bounds": [-5, -5, 10, 10]}]


def line(handle, start, end, layer="A-FLOOR"):
    return {"entity_type": "LINE", "handle": handle, "layer": layer,
            "start": list(start), "end": list(end)}


def test_regular_tread_array_is_one_drawn_flight_without_safety_authority():
    rows = [line(f"t{i}", [0, i*.3], [1.2, i*.3]) for i in range(8)]
    result = detect_stair_evidence(rows, source_sha256=SOURCE, frames=FRAME)
    assert result["metrics"]["drawn_flight_sample_count"] == 1
    assert result["metrics"]["physical_stair_count"] is None
    assert result["flight_samples"][0]["evidence"]["detected_row_fragment_count"] == 8
    assert result["flight_samples"][0]["authority"]["safety"] is False


def test_narrow_window_panes_are_not_stair_treads():
    rows = [line(f"p{i}", [0, i*.07], [1.5, i*.07]) for i in range(4)]
    result = detect_stair_evidence(rows, source_sha256=SOURCE, frames=FRAME)
    assert result["metrics"]["drawn_flight_sample_count"] == 0


def test_hatch_and_dimension_parallel_lines_are_excluded():
    rows = [line(f"h{i}", [0, i*.25], [1, i*.25], "A-HATCH") for i in range(9)]
    rows += [line(f"d{i}", [3, i*.25], [4, i*.25], "DIMENSION") for i in range(9)]
    result = detect_stair_evidence(rows, source_sha256=SOURCE, frames=FRAME)
    assert result["metrics"]["drawn_flight_sample_count"] == 0


def test_compact_roof_vent_arrow_array_is_not_stair():
    rows = [line(f"v{i}", [0, i*.177], [.3, i*.177], "ROOF") for i in range(9)]
    result = detect_stair_evidence(rows, source_sha256=SOURCE, frames=FRAME)
    assert result["metrics"]["drawn_flight_sample_count"] == 0


def test_short_four_line_threshold_or_window_motif_is_not_stair():
    rows = [line(f"s{i}", [0, i*.07], [.6, i*.07], "A-FLOOR") for i in range(4)]
    result = detect_stair_evidence(rows, source_sha256=SOURCE, frames=FRAME)
    assert result["metrics"]["drawn_flight_sample_count"] == 0


def test_shorter_first_last_and_landing_side_rows_are_recovered_but_unresolved():
    rows = [line(f"core{i}", [0, i*.3], [1.4, i*.3]) for i in range(4)]
    rows += [line("first", [.2, -.3], [1.2, -.3]),
             line("before_landing_a", [0, 1.2], [.6, 1.2]),
             line("before_landing_b", [.8, 1.2], [1.4, 1.2])]
    result = detect_stair_evidence(rows, source_sha256=SOURCE, frames=FRAME)
    assert result["metrics"]["drawn_flight_sample_count"] == 1
    evidence = result["flight_samples"][0]["evidence"]
    assert {"first", "before_landing_a", "before_landing_b"}.issubset(
        result["flight_samples"][0]["source_refs"])
    assert {"before_landing_a", "before_landing_b"}.issubset(evidence["recovered_source_refs"])
    assert any(row["role"] == "TREAD_OR_BOUNDARY_UNRESOLVED" for row in evidence["row_stations"])


def test_adjacent_fragmented_seed_rows_collapse_to_one_flight_sample():
    rows=[]
    for i in range(6):
        rows += [line(f"left{i}", [0, i*.3], [.9, i*.3]),
                 line(f"right{i}", [.91, i*.3], [1.81, i*.3])]
    result = detect_stair_evidence(rows, source_sha256=SOURCE, frames=FRAME)
    assert result["metrics"]["drawn_flight_sample_count"] == 1


def test_parallel_wall_beyond_spacing_chain_is_not_absorbed():
    rows = [line(f"core{i}", [0, i*.3], [1.4, i*.3]) for i in range(6)]
    rows.append(line("wall", [-2, 2.4], [4, 2.4], "A-WALL"))
    result = detect_stair_evidence(rows, source_sha256=SOURCE, frames=FRAME)
    assert "wall" not in result["flight_samples"][0]["source_refs"]


def test_shared_terminal_row_and_native_rectangle_form_separate_landing_evidence():
    rows=[]
    for i in range(6):
        rows += [line(f"left{i}", [0, i*.3], [1.4, i*.3]),
                 line(f"right{i}", [1.7, i*.3], [3.1, i*.3])]
    rows += [line("shared_top", [0, 1.8], [3.1, 1.8]),
             line("landing_back", [0, 3.1], [3.1, 3.1]),
             line("landing_left", [0, 1.8], [0, 3.1]),
             line("landing_right", [3.1, 1.8], [3.1, 3.1])]
    result=detect_stair_evidence(rows,source_sha256=SOURCE,frames=FRAME)
    assert len(result["flight_samples"]) == 2
    assembly=result["items"][0]
    assert assembly["landing"]["status"] == "GEOMETRY_EVIDENCE_AVAILABLE"
    landing=next(row for row in assembly["landing"]["candidates"]
                 if row["status"] == "GEOMETRY_SUPPORTED_CLOSED")
    assert landing["geometry"]["ordered_polygon"]
    assert landing["geometry"]["closure_test"]["is_closed"] is True
    assert {edge["role"] for edge in landing["geometry"]["boundary_edges"]} == {
        "TERMINAL_BOUNDARY", "REMOTE_FLOOR_BOUNDARY",
        "SIDE_BOUNDARY_LEFT", "SIDE_BOUNDARY_RIGHT"}
    assert all(edge["source_refs"] for edge in landing["geometry"]["boundary_edges"])


def test_another_tread_row_cannot_be_used_as_landing_remote_boundary():
    rows=[]
    for i in range(7):
        rows += [line(f"left{i}", [0, i*.3], [1.4, i*.3]),
                 line(f"right{i}", [1.7, i*.3], [3.1, i*.3])]
    rows += [line("terminal", [0, 2.1], [3.1, 2.1]),
             line("landing_back", [0, 3.4], [3.1, 3.4]),
             line("landing_left", [0, 2.1], [0, 3.4]),
             line("landing_right", [3.1, 2.1], [3.1, 3.4])]
    result=detect_stair_evidence(rows,source_sha256=SOURCE,frames=FRAME)
    candidates=result["items"][0]["landing"]["candidates"]
    assert candidates
    assert all(abs(row["geometry"]["depth"]-1.3) < 1e-8 for row in candidates)
    assert all(not ({"left4", "right4"} & set(row["source_refs"])) for row in candidates)


def test_neighbouring_stairs_are_not_merged_across_material_separator_gap():
    rows=[]
    for i in range(7):
        rows += [line(f"a{i}", [0, i*.3], [1.2, i*.3]),
                 line(f"b{i}", [1.4, i*.3], [2.6, i*.3])]
    result=detect_stair_evidence(rows,source_sha256=SOURCE,frames=FRAME)
    assert result["metrics"]["drawn_flight_sample_count"] == 2
    assert result["metrics"]["drawn_assembly_candidate_count"] == 2


def test_landing_strip_cannot_overlap_perpendicular_flight_in_same_assembly():
    rows=[]
    for i in range(6):
        rows += [line(f"left{i}", [0, i*.3], [1.3, i*.3]),
                 line(f"right{i}", [1.35, i*.3], [2.65, i*.3])]
    rows += [line("terminal", [0, 1.8], [2.65, 1.8]),
             line("remote", [0, 3.1], [2.65, 3.1]),
             line("side_left", [0, 1.8], [0, 3.1]),
             line("side_right", [2.65, 1.8], [2.65, 3.1])]
    # A perpendicular third flight occupies the apparent landing strip.
    for i in range(6):
        rows.append(line(f"cross{i}", [1.45+i*.2, 1.8], [1.45+i*.2, 3.1]))
    result=detect_stair_evidence(rows,source_sha256=SOURCE,frames=FRAME)
    assembly=max(result["items"],key=lambda row:row["drawn_flight_count"])
    assert assembly["drawn_flight_count"] >= 3
    assert not any(abs(row["geometry"]["depth"]-1.3) < 1e-8
                   for row in assembly.get("landing",{}).get("candidates",[]))


@pytest.mark.parametrize("side_skew", [0., .0004])
def test_three_sided_stair_recovers_two_native_corner_landings_not_full_strip(side_skew):
    rows=[]
    # Two split horizontal arms share a full terminal boundary.
    rows.append(line("terminal",[0,0],[3.5,0]))
    for i in range(1,7):
        rows += [line(f"left{i}",[0,-i*.3],[1.3,-i*.3]),
                 line(f"right{i}",[2.2,-i*.3],[3.5,-i*.3])]
    # Perpendicular middle arm ends at the shared terminal.
    for i in range(5):
        rows.append(line(f"stem{i}",[1.3+i*.225,0],[1.3+i*.225,1.3]))
    rows += [line("remote",[.2,1.1],[3.3+side_skew/2,1.1],"FON"),
             line("outer_left",[.2,0],[.2,1.1]),
             line("outer_right",[3.3,0],[3.3+side_skew,1.1])]
    result=detect_stair_evidence(rows,source_sha256=SOURCE,frames=FRAME)
    assembly=max(result["items"],key=lambda row:row["drawn_flight_count"])
    # Exercise provenance independently from containment pruning by the
    # ordinary detector; its geometry selection is outside this metadata test.
    members=[row for row in result["flight_samples"] if row["stair_flight_id"] in assembly["flight_ids"]]
    corners=_corner_landing_evidence(members,rows)
    assert len(corners)==2
    assert all(row["geometry"]["closure_test"]["is_closed"] for row in corners)
    for row in corners:
        scope=row["boundary_scope"]
        assert scope["full_landing_outline_status"]=="UNRESOLVED"
        assert scope["candidate_inner_face_depth_drawing_units"]==pytest.approx(1.1)
        assert scope["outer_architecture_reference_depth_drawing_units"]==pytest.approx(1.3)
        assert all(edge["native_source_segments"] for edge in row["geometry"]["boundary_edges"])
    if side_skew:
        snapped=[row for row in corners if row["status"]=="GEOMETRY_CLOSED_WITH_AXIS_SNAP"]
        assert len(snapped)==1
        closure=snapped[0]["geometry"]["closure_test"]
        assert closure["is_native_fully_covered"] is False
        assert closure["maximum_endpoint_displacement_drawing_units"]>0
    else:
        assert all(row["status"]=="GEOMETRY_SUPPORTED_CLOSED" for row in corners)
    assert all(not (row["geometry"]["bounds"][0] < 1.3 and
                    row["geometry"]["bounds"][2] > 2.2) for row in corners)


def test_three_short_rows_need_native_arrow_to_become_short_flight_evidence():
    rows=[line(f"step{i}",[0,i*.3],[1.4,i*.3]) for i in range(3)]
    rows += [line("shaft",[.7,0],[.7,.6]),
             line("head_left",[.7,0],[.58,.16]),
             line("head_right",[.7,0],[.82,.16])]
    result=detect_stair_evidence(rows,source_sha256=SOURCE,frames=FRAME)
    assert result["metrics"]["drawn_flight_sample_count"]==1
    flight=result["flight_samples"][0]
    assert flight["status"]=="SHORT_FLIGHT_EVIDENCE_REVIEW_REQUIRED"
    assert flight["evidence"]["method"]=="SHORT_REGULAR_ROWS_WITH_NATIVE_DIRECTION_MARKER"
    assert set(flight["evidence"]["native_direction_marker_refs"])=={
        "shaft","head_left","head_right"}
    assert flight["evidence"]["assembly_boundary_status"]=="UNRESOLVED_NO_INDEPENDENT_PERIMETER_PROOF"


def test_three_short_rows_without_arrow_are_not_promoted():
    rows=[line(f"step{i}",[0,i*.3],[1.4,i*.3]) for i in range(3)]
    result=detect_stair_evidence(rows,source_sha256=SOURCE,frames=FRAME)
    assert result["metrics"]["drawn_flight_sample_count"]==0


def spiral(insert, dx):
    rows = []
    for i in range(16):
        import math
        angle = i*2*math.pi/16
        rows.append({**line(f"r{i}", [dx, 0], [dx+math.cos(angle), math.sin(angle)]),
                     "source_insert_handle": insert})
    for index, radius in enumerate((.6, 1.0)):
        rows.append({"entity_type": "ARC", "handle": f"a{index}",
                     "source_insert_handle": insert, "center": [dx, 0],
                     "radius": radius, "signed_sweep_degrees": 360})
    return rows


def test_repeated_concentric_radial_family_is_spiral_candidate():
    result = detect_stair_evidence(spiral("I1", 0)+spiral("I2", 4),
                                   source_sha256=SOURCE, frames=FRAME)
    assert [row["kind"] for row in result["flight_samples"]].count("spiral_stair") == 2


def test_single_radial_symbol_is_not_assumed_to_be_spiral_stair():
    result = detect_stair_evidence(spiral("TREE", 0), source_sha256=SOURCE, frames=FRAME)
    assert not result["flight_samples"]

