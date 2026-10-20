import copy
import math

from cad_engine.architecture_opening_evidence import detect_opening_evidence


SOURCE = "a" * 64


def line(name, p, q):
    return {"entity_type": "LINE", "handle": name, "start": p, "end": q}


def insert_door_fixture(insert, dx=0):
    rows = [{**line("leaf", [dx, 0], [dx+1, 0]), "source_insert_handle": insert}]
    for index in range(1, 21):
        angle = index*.137
        rows.append({**line(f"l{index}", [dx+math.cos(angle), math.sin(angle)],
                            [dx+1.2*math.cos(angle+.03), 1.2*math.sin(angle+.03)]),
                     "source_insert_handle": insert})
    for index in range(7):
        rows.append({"entity_type": "ARC", "handle": f"a{index}",
                     "source_insert_handle": insert,
                     "center": [dx+index*.01, index*.02], "radius": 1-index*.05,
                     "start_angle": 0, "end_angle": 90,
                     "signed_sweep_degrees": 90,
                     "arc_endpoints": [[dx+1-index*.04, index*.02],
                                       [dx+index*.01, 1-index*.03]]})
    return rows


def window_fixture(*, support=True, remote_angle_line=False):
    rows = [line("p0", [0, 0], [1, 0]), line("p1", [0, .1], [1, .1]),
            line("p2", [0, .2], [1, .2]), line("c0", [0, 0], [0, .2]),
            line("c1", [1, 0], [1, .2])]
    if support:
        rows += [line("l0", [-1, 0], [0, 0]), line("r0", [1, 0], [2, 0]),
                 line("l1", [-1, .2], [0, .2]), line("r1", [1, .2], [2, .2])]
    if remote_angle_line:
        theta = 9e-5
        rows.append(line("remote", [100, 100], [102*math.cos(theta), 100+2*math.sin(theta)]))
    return rows


def test_window_requires_caps_and_two_interrupted_faces_and_retains_geometry():
    source = window_fixture()
    before = copy.deepcopy(source)
    result = detect_opening_evidence(source, source_sha256=SOURCE,
                                     frames=[{"plan_id": "P1", "drawing_type": "ARCH_FLOOR_PLAN", "bounds": [-2, -2, 3, 3]}])
    windows = [row for row in result["items"] if row["kind"] == "window"]
    assert len(windows) == 1
    assert windows[0]["view_scope"] == "PLAN_VIEW"
    assert windows[0]["status"] == "CANDIDATE"
    assert windows[0]["authority"] == {"material_geometry": False, "portal": False, "access_edge": False}
    assert source == before
    assert not [row for row in detect_opening_evidence(window_fixture(support=False), source_sha256=SOURCE)["items"]
                if row["kind"] == "window"]


def test_window_orientation_is_not_changed_by_remote_near_angle_chain():
    base = detect_opening_evidence(window_fixture(), source_sha256=SOURCE)
    changed = detect_opening_evidence(window_fixture(remote_angle_line=True), source_sha256=SOURCE)
    assert base["metrics"]["window_candidates"] == changed["metrics"]["window_candidates"] == 1
    assert next(x for x in base["items"] if x["kind"] == "window")["source_refs"] == \
           next(x for x in changed["items"] if x["kind"] == "window")["source_refs"]


def test_four_pane_window_with_single_boundary_face_is_review_candidate():
    rows = [line(f"p{i}", [0, i*.06], [1, i*.06]) for i in range(4)]
    rows += [line("c0", [0, 0], [0, .18]), line("c1", [1, 0], [1, .18]),
             line("left", [-1, 0], [0, 0]), line("right", [1, 0], [2, 0])]
    result = detect_opening_evidence(
        rows, source_sha256=SOURCE,
        frames=[{"plan_id": "P", "drawing_type": "ARCH_FLOOR_PLAN", "bounds": [-2, -2, 3, 3]}])
    windows = [row for row in result["items"] if row["kind"] == "window"]
    assert len(windows) == 1
    assert windows[0]["status"] == "CANDIDATE_CONTEXT_UNCONFIRMED"
    assert windows[0]["evidence"]["detection_path"] == "FOUR_PANE_SINGLE_BOUNDARY_FACE"


def test_four_pane_window_with_one_endcap_and_one_support_is_review_candidate():
    rows = [line(f"p{i}", [0, i*.06], [1, i*.06]) for i in range(4)]
    rows += [line("c0", [0, 0], [0, .18]), line("left", [-1, 0], [0, 0])]
    result = detect_opening_evidence(
        rows, source_sha256=SOURCE,
        frames=[{"plan_id": "P", "drawing_type": "ARCH_FLOOR_PLAN", "bounds": [-2, -2, 3, 3]}])
    windows = [row for row in result["items"] if row["kind"] == "window"]
    assert len(windows) == 1
    assert windows[0]["evidence"]["detection_path"] == "FOUR_PANE_SINGLE_ENDCAP_AND_BOUNDARY_SUPPORT"


def test_four_parallel_door_detail_lines_without_window_jamb_are_not_window():
    rows = [line(f"detail{i}", [0, i*.06], [1, i*.06]) for i in range(4)]
    rows += [{"entity_type": "ARC", "handle": "swing", "center": [0, 0], "radius": 1,
              "start_angle": 0, "end_angle": 90, "signed_sweep_degrees": 90,
              "arc_endpoints": [[1, 0], [0, 1]]}, line("leaf", [0, 0], [1, 0])]
    result = detect_opening_evidence(rows, source_sha256=SOURCE)
    assert not [row for row in result["items"] if row["kind"] == "window"]


def test_relaxed_four_pane_rule_does_not_classify_vertical_furniture_detail():
    rows = [line(f"p{i}", [i*.06, 0], [i*.06, 1]) for i in range(4)]
    rows += [line("c0", [0, 0], [.18, 0]), line("c1", [0, 1], [.18, 1]),
             line("lower", [0, -1], [0, 0]), line("upper", [0, 1], [0, 2])]
    result = detect_opening_evidence(
        rows, source_sha256=SOURCE,
        frames=[{"plan_id": "P", "drawing_type": "FURNITURE_PLAN", "bounds": [-2, -2, 3, 3]}])
    assert not [row for row in result["items"] if row["kind"] == "window"]


def test_relaxed_four_pane_rule_does_not_run_in_non_plan_view():
    rows = [line(f"p{i}", [0, i*.06], [1, i*.06]) for i in range(4)]
    rows += [line("c0", [0, 0], [0, .18]), line("c1", [1, 0], [1, .18]),
             line("left", [-1, 0], [0, 0]), line("right", [1, 0], [2, 0])]
    result = detect_opening_evidence(
        rows, source_sha256=SOURCE,
        frames=[{"plan_id": "E", "drawing_type": "ELEVATION", "bounds": [-2, -2, 3, 3]}])
    assert not [row for row in result["items"] if row["kind"] == "window"]


def test_distinct_inserted_windows_with_reused_definition_handles_do_not_collapse():
    rows = []
    for insert, dx in (("I1", 0), ("I2", 10)):
        for row in window_fixture():
            placed = copy.deepcopy(row)
            placed["source_insert_handle"] = insert
            placed["start"] = [placed["start"][0]+dx, placed["start"][1]]
            placed["end"] = [placed["end"][0]+dx, placed["end"][1]]
            rows.append(placed)
    result = detect_opening_evidence(rows, source_sha256=SOURCE,
                                     frames=[{"plan_id": "P", "drawing_type": "ARCH_FLOOR_PLAN", "bounds": [-3, -3, 15, 3]}])
    windows = [row for row in result["items"] if row["kind"] == "window"]
    assert len(windows) == 2
    assert {tuple(ref.split("/")[:1]) for row in windows for ref in row["source_refs"]} == {("I1",), ("I2",)}


def test_window_is_separated_from_section_view():
    result = detect_opening_evidence(window_fixture(), source_sha256=SOURCE,
                                     frames=[{"plan_id": "S1", "drawing_type": "SECTION", "bounds": [-2, -2, 3, 3]}])
    item = next(row for row in result["items"] if row["kind"] == "window")
    assert item["view_scope"] == "NON_PLAN_VIEW"
    assert result["metrics"]["plan_view_candidates"] == 0


def test_door_needs_arc_leaf_and_two_sided_interrupted_boundary():
    rows = [
        {"entity_type": "ARC", "handle": "a", "center": [0, 0], "radius": 1,
         "start_angle": 0, "end_angle": 90, "signed_sweep_degrees": 90,
         "arc_endpoints": [[1, 0], [0, 1]], "ocs_to_wcs": True},
        line("leaf", [0, 0], [1, 0]),
        line("l0", [-.1, -1], [-.1, 0]), line("r0", [-.1, 1], [-.1, 2]),
        line("l1", [.1, -1], [.1, 0]), line("r1", [.1, 1], [.1, 2]),
    ]
    result = detect_opening_evidence(rows, source_sha256=SOURCE,
                                     frames=[{"plan_id": "P1", "drawing_type": "ARCH_FLOOR_PLAN", "bounds": [-2, -2, 3, 3]}])
    doors = [row for row in result["items"] if row["kind"] == "door"]
    assert len(doors) == 1
    assert doors[0]["mechanism_status"] == "UNCONFIRMED"
    assert doors[0]["evidence"]["ocs_to_wcs"] is True
    assert not [row for row in detect_opening_evidence(rows[:-1], source_sha256=SOURCE)["items"] if row["kind"] == "door"]


def test_calibration_provenance_is_explicit_not_universal():
    result = detect_opening_evidence(window_fixture(), source_sha256=SOURCE)
    assert result["calibration"]["window_frame_ratio_max"] == .35
    assert result["calibration"]["adjacent_support_angle_tolerance"] == 1e-4
    assert result["calibration"]["generalization_status"] == "UNVALIDATED_HOLDOUT_REVIEW_REQUIRED"


def test_repeated_insert_template_is_automatic_and_coincident_instances_are_deduplicated():
    rows = (insert_door_fixture("I1", 0)+insert_door_fixture("I2", 0)+
            insert_door_fixture("I3", 5))
    result = detect_opening_evidence(
        rows, source_sha256=SOURCE,
        frames=[{"plan_id": "P1", "drawing_type": "FURNITURE_PLAN", "bounds": [-3, -3, 8, 3]}])
    doors = [row for row in result["items"] if row["kind"] == "door"]
    assert len(doors) == 2
    assert result["metrics"]["automatic_door_candidates"] == 2
    assert result["metrics"]["owner_confirmed_door_annotations"] == 0
    assert sorted(len(row["source_insert_handles"]) for row in doors) == [1, 2]
    assert all(row["automatic_confidence"] == .82 for row in doors)
    assert all(row["owner_review"] is None for row in doors)


def test_repeated_arc_rich_non_door_symbol_needs_hinge_leaf_relation():
    rows = insert_door_fixture("I1", 0) + insert_door_fixture("I2", 5)
    for row in rows:
        if row.get("handle") == "leaf":
            row["start"], row["end"] = [100, 100], [101, 100]
    result = detect_opening_evidence(rows, source_sha256=SOURCE,
                                     frames=[{"plan_id": "P1", "drawing_type": "ARCH_FLOOR_PLAN", "bounds": [-3, -3, 110, 110]}])
    assert result["metrics"]["automatic_door_candidates"] == 0


def test_arc_bounds_include_cardinal_extrema_not_only_endpoints():
    rows = insert_door_fixture("I1", 0) + insert_door_fixture("I2", 5)
    # The first arc goes from 45 to 135 degrees and must include its 90-degree apex.
    for row in rows:
        if row.get("entity_type") == "ARC" and row.get("handle") == "a0":
            row.update(start_angle=45, end_angle=135, signed_sweep_degrees=90,
                       arc_endpoints=[[row["center"][0]+2**-.5, row["center"][1]+2**-.5],
                                      [row["center"][0]-2**-.5, row["center"][1]+2**-.5]])
        elif row.get("handle") == "leaf":
            row["end"] = [row["start"][0]+2**-.5, row["start"][1]+2**-.5]
    result = detect_opening_evidence(rows, source_sha256=SOURCE,
                                     frames=[{"plan_id": "P1", "drawing_type": "ARCH_FLOOR_PLAN", "bounds": [-3, -3, 8, 3]}])
    assert result["items"]
    assert max(item["geometry"]["bounds"][3] for item in result["items"] if item["kind"] == "door") >= 1


def test_generic_arc_leaf_door_is_counted_as_automatic():
    rows = [
        {"entity_type": "ARC", "handle": "a", "center": [0, 0], "radius": 1,
         "start_angle": 0, "end_angle": 90, "signed_sweep_degrees": 90,
         "arc_endpoints": [[1, 0], [0, 1]]},
        line("leaf", [0, 0], [1, 0]),
        line("l0", [-.1, -1], [-.1, 0]), line("r0", [-.1, 1], [-.1, 2]),
        line("l1", [.1, -1], [.1, 0]), line("r1", [.1, 1], [.1, 2]),
    ]
    result = detect_opening_evidence(rows, source_sha256=SOURCE)
    assert result["metrics"]["door_candidates"] == 1
    assert result["metrics"]["automatic_door_candidates"] == 1


def test_23_line_hinged_family_variant_is_not_lost_to_exact_count_rule():
    rows = insert_door_fixture("I1", 0) + insert_door_fixture("I2", 5)
    for insert, dx in (("I1", 0), ("I2", 5)):
        rows.extend([{**line("trim1", [dx+.2, .2], [dx+.3, .2]), "source_insert_handle": insert},
                     {**line("trim2", [dx+.2, .3], [dx+.3, .3]), "source_insert_handle": insert}])
    result = detect_opening_evidence(rows, source_sha256=SOURCE,
                                     frames=[{"plan_id": "P", "drawing_type": "ARCH_FLOOR_PLAN", "bounds": [-2, -2, 8, 3]}])
    assert result["metrics"]["automatic_door_candidates"] == 2


def test_large_wall_layer_swing_curve_without_leaf_is_review_only():
    rows = [line("base", [-2, 0], [2, 0])]
    for index, radius in enumerate((.01, .011, .012, .8)):
        rows.append({"entity_type": "ARC", "handle": f"a{index}", "layer": "Wall_G",
                     "center": [0, 0], "radius": radius,
                     "start_angle": 0, "end_angle": 80, "signed_sweep_degrees": 80,
                     "arc_endpoints": [[radius, 0], [radius*.173648, radius*.984808]]})
    result = detect_opening_evidence(rows, source_sha256=SOURCE)
    review = [row for row in result["items"] if row["kind"] == "door"]
    assert len(review) == 1
    assert review[0]["status"] == "CANDIDATE_CONTEXT_UNCONFIRMED"
    assert review[0]["mechanism_status"] == "NOT_CONFIRMED_CURVE_ONLY"
    assert review[0]["automatic_confidence"] == .35


def test_dense_rotated_compass_rosette_is_not_a_door_candidate():
    rows = [line("base", [-2, 0], [2, 0])]
    for index in range(8):
        angle = index*45
        rows.append({"entity_type": "ARC", "handle": f"north-{index}", "layer": "Wall_G",
                     "center": [0, 0], "radius": 1-index*.03,
                     "start_angle": angle, "end_angle": angle+80,
                     "signed_sweep_degrees": 80,
                     "arc_endpoints": [[math.cos(math.radians(angle)), math.sin(math.radians(angle))],
                                       [math.cos(math.radians(angle+80)), math.sin(math.radians(angle+80))]]})
    result = detect_opening_evidence(rows, source_sha256=SOURCE)
    assert not [row for row in result["items"] if row["kind"] == "door"]


def test_owner_annotations_never_transfer_to_another_source_hash():
    result = detect_opening_evidence(window_fixture(), source_sha256=SOURCE)
    assert result["metrics"]["owner_confirmed_door_annotations"] == 0
    assert not [row for row in result["items"]
                if row.get("status") == "OWNER_CONFIRMED_SOURCE_FIXTURE"]

