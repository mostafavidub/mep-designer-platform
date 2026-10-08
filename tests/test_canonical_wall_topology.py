from shapely.geometry import LineString, Polygon

from cad_engine.architectural_topology_quality import (
    _compose_shell_holes,
    building_envelope_from_walls,
    canonical_space_subdivision,
    canonical_enclosure_continuity,
    classify_internal_wall_gaps,
    evidence_based_building_envelope,
    enumerate_envelope_candidates,
    host_portal_on_walls,
    reconstruct_canonical_walls,
    source_supported_endpoint_closures,
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
    assert envelope["evidence"][0]["class"] == "SINGLE_UNAMBIGUOUS_CANONICAL_WALL_CYCLE"


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
    walls[0].update({"representation":"DOUBLE_FACE","face_a":[[4.9,0],[4.9,6]],
                     "face_b":[[5.1,0],[5.1,6]]})
    walls[0]["interruptions"][0].update({"face_a_gap":[2.5,3.5],"face_b_gap":[2.5,3.5]})
    result=canonical_space_subdivision(walls,_envelope(),frame_id="F1",tolerance=.001)
    assert result["authority"]=="CANONICAL"
    assert len(result["cells"])==2
    assert any(row["kind"]=="VIRTUAL_CLOSURE" for row in result["barriers"])
    assert result["edges"][0]["closure_ids"]


def test_double_face_door_gap_closes_enclosure_without_becoming_material():
    wall=_wall("W",(0,0),(10,0),[[0,4],[5,10]],[(4,5)])
    wall.update({"representation":"DOUBLE_FACE","face_a":[[0,-.1],[10,-.1]],
                 "face_b":[[0,.1],[10,.1]],"source_handles":["A","B"]})
    wall["interruptions"][0].update({"face_a_gap":[4,5],"face_b_gap":[4,5]})
    rows=canonical_enclosure_continuity([wall],frame_id="F1")
    assert rows[0]["continuity_status"]=="PROVEN_WALL_CONTINUITY"
    assert rows[0]["material"] is False
    assert rows[0]["possible_opening_type"]=="UNKNOWN"
    assert rows[0]["roles"]==["ENCLOSURE_BARRIER","ENVELOPE_SUPPORT"]


def test_single_line_gap_is_not_promoted_without_independent_support():
    wall=_wall("W",(0,0),(10,0),[[0,4],[7,10]],[(4,7)])
    wall.update({"representation":"SINGLE_LINE","source_handles":["A"]})
    rows=canonical_enclosure_continuity([wall],frame_id="F1")
    assert rows[0]["continuity_status"]=="SUPPORTED_WALL_CONTINUITY"
    assert rows[0]["roles"]==[]


def test_drafting_fragmentation_is_diagnostic_not_promoted():
    wall=_wall("W",(0,0),(10,0),[[0,4],[5,10]],[(4,5)])
    wall.update({"representation":"DOUBLE_FACE","source_handles":["A","B"]})
    wall["interruptions"][0].update({"kind":"UNKNOWN_FRAGMENTATION","face_a_gap":[4,5]})
    rows=canonical_enclosure_continuity([wall],frame_id="F1")
    assert rows[0]["continuity_status"]=="INSUFFICIENT_CONTINUITY"
    assert "ENCLOSURE_BARRIER" not in rows[0]["roles"]


def test_open_plan_without_wall_remains_one_physical_space():
    result=canonical_space_subdivision([],_envelope(),frame_id="F1",tolerance=.001)
    assert len(result["cells"])==1


def test_shaft_is_preserved_as_topological_hole():
    envelope=_envelope(); envelope["interior_voids"]=[[[4,2],[6,2],[6,4],[4,4],[4,2]]]
    result=canonical_space_subdivision([],envelope,frame_id="F1",tolerance=.001)
    assert len(result["cells"])==1
    assert result["cells"][0]["interior_rings"]


def test_verified_void_boundary_is_a_hole_not_an_occupied_space():
    boundary=[[4,2],[6,2],[6,4],[4,4],[4,2]]
    result=canonical_space_subdivision([],_envelope(),frame_id="F1",tolerance=.001,
                                       void_boundaries=[boundary])
    assert len(result["cells"])==1
    assert len(result["cells"][0]["interior_rings"])==1
    assert Polygon(result["cells"][0]["interior_rings"][0]).equals(Polygon(boundary))


def test_unproven_envelope_cannot_become_canonical_authority():
    envelope=_envelope(); envelope["status"]="INPUT_REQUIRED"
    result=canonical_space_subdivision([],envelope,frame_id="F1",tolerance=.001)
    assert result["authority"]=="LEGACY_FALLBACK"
    assert result["cells"]==[]


def test_fragmentation_gap_cannot_host_a_portal():
    wall=_wall("W",(0,0),(10,0),[[0,4],[5,10]],[(4,5)])
    wall["interruptions"][0]["kind"]="UNKNOWN_FRAGMENTATION"
    assert host_portal_on_walls(LineString(((4,0),(5,0))),[wall],tolerance=.001,pixel_tolerance=.01)[1]=="NO_WALL_GAP"


def _topology_wall(wall_id,a,b,representation="DOUBLE_FACE"):
    row=_wall(wall_id,a,b,[[0,LineString((a,b)).length]])
    row.update({"representation":representation,"source_handles":[wall_id],"thickness":.2 if representation=="DOUBLE_FACE" else None})
    return row


def _proven_wall(wall_id, a, b, *, thickness=.2, representation="DOUBLE_FACE"):
    row=_topology_wall(wall_id,a,b,representation=representation)
    row.update({"status":"HIGH_CONFIDENCE","thickness":thickness})
    return row


def test_source_supported_endpoint_closure_is_nonmaterial_and_deterministic():
    walls=[_proven_wall("A",(0,0),(4,0)),_proven_wall("B",(5,0),(10,0))]
    first=source_supported_endpoint_closures(walls,frame_id="F1",tolerance=.001)
    repeat=source_supported_endpoint_closures(list(reversed(walls)),frame_id="F1",tolerance=.001)
    assert first == repeat
    assert len(first) == 1
    assert first[0]["reason"] == "COLLINEAR_WALL_GAP"
    assert first[0]["roles"] == ["ENCLOSURE_BARRIER","ENVELOPE_SUPPORT"]
    assert first[0]["material"] is False
    assert {first[0][key] for key in ("wall_authority","routing_authority","portal_authority","access_authority")} == {"NONE"}


def test_source_supported_endpoint_closure_joins_small_orthogonal_corner():
    walls=[_proven_wall("A",(0,0),(4.8,0)),_proven_wall("B",(5,.2),(5,5))]
    rows=source_supported_endpoint_closures(walls,frame_id="F1",tolerance=.001)
    assert len(rows) == 1
    assert rows[0]["reason"] == "EXTERIOR_CORNER_JOIN"


def test_source_supported_endpoint_closure_rejects_unproven_or_oversized_gap():
    oversized=[_proven_wall("A",(0,0),(4,0)),_proven_wall("B",(7,0),(10,0))]
    single=[_proven_wall("A",(0,0),(4,0),representation="SINGLE_LINE"),
            _proven_wall("B",(5,0),(10,0))]
    low=[_proven_wall("A",(0,0),(4,0)),_proven_wall("B",(5,0),(10,0))]
    low[1]["status"]="LOW_CONFIDENCE"
    assert source_supported_endpoint_closures(oversized,frame_id="F1",tolerance=.001) == []
    assert source_supported_endpoint_closures(single,frame_id="F1",tolerance=.001) == []
    assert source_supported_endpoint_closures(low,frame_id="F1",tolerance=.001) == []


def test_gap_classification_precedes_closure_and_fails_closed_without_portal_evidence():
    walls=[_proven_wall("A",(0,0),(4,0)),_proven_wall("B",(5,0),(10,0))]
    closures=source_supported_endpoint_closures(walls,frame_id="F1",tolerance=.001)
    gaps=classify_internal_wall_gaps(walls,closures,[],frame_id="F1",tolerance=.001)
    assert gaps[0]["classification"]=="AMBIGUOUS_GAP"
    assert gaps[0]["status"]=="INPUT_REQUIRED"
    assert closures[0]["portal_authority"]=="NONE"


def test_opening_evidence_on_same_wall_cannot_classify_a_distant_gap():
    walls=[_proven_wall("A",(0,0),(4,0)),_proven_wall("B",(5,0),(10,0))]
    closures=source_supported_endpoint_closures(walls,frame_id="F1",tolerance=.001)
    host_ids=closures[0]["host_wall_ids"]
    evidence=[{"opening_evidence_id":"OPENEV-A","status":"OPENING_EVIDENCE_PRESENT",
               "candidate_type":"door","candidate_host_wall_ids":host_ids,
               "geometry":{"point":[9.0,0.0]}}]
    gaps=classify_internal_wall_gaps(walls,closures,evidence,frame_id="F1",tolerance=.001)
    assert gaps[0]["classification"]=="AMBIGUOUS_GAP"
    assert gaps[0]["portal_evidence_ids"]==[]


def test_opening_evidence_locally_overlapping_gap_may_classify_that_gap_only():
    walls=[_proven_wall("A",(0,0),(4,0)),_proven_wall("B",(5,0),(10,0))]
    closures=source_supported_endpoint_closures(walls,frame_id="F1",tolerance=.001)
    host_ids=closures[0]["host_wall_ids"]
    evidence=[{"opening_evidence_id":"OPENEV-A","status":"OPENING_EVIDENCE_PRESENT",
               "candidate_type":"door","candidate_host_wall_ids":host_ids,
               "geometry":{"points":[[4.0,0.0],[5.0,0.0]]}}]
    gaps=classify_internal_wall_gaps(walls,closures,evidence,frame_id="F1",tolerance=.001)
    assert gaps[0]["classification"]=="DOOR_GAP"
    assert gaps[0]["portal_evidence_ids"]==["OPENEV-A"]


def test_endpoint_closure_never_reuses_one_endpoint_for_multiple_synthetic_joins():
    walls=[_proven_wall("A",(0,0),(4,0)),_proven_wall("B",(4.2,0),(8,0)),
           _proven_wall("C",(4.3,0),(9,0))]
    rows=source_supported_endpoint_closures(walls,frame_id="F1",tolerance=.001)
    endpoints=[tuple(point) for row in rows for point in row["geometry"]]
    assert len(endpoints)==len(set(endpoints))




def _site_and_building_walls():
    return [_topology_wall("S",(0,0),(20,0)),_topology_wall("E",(20,0),(20,10)),
            _topology_wall("N",(20,10),(0,10)),_topology_wall("W",(0,10),(0,0)),
            _topology_wall("F",(10,0),(10,10)),_topology_wall("P",(5,0),(5,10))]


def test_largest_site_cycle_is_not_selected_as_building_envelope():
    labels=[{"point":[2,5],"semantic_candidate":"bedroom"},{"point":[7,5],"semantic_candidate":"kitchen"},
            {"point":[15,5],"semantic_candidate":"yard"}]
    envelope,diagnostic,regions=evidence_based_building_envelope(_site_and_building_walls(),frame_id="F1",tolerance=.001,semantic_labels=labels)
    assert max(row["area"] for row in diagnostic["candidates"]) == 100
    assert envelope["status"] == "HIGH_CONFIDENCE"
    assert envelope["area"] == 100
    assert Polygon(envelope["outer_ring"]).bounds == (0,0,10,10)
    assert {row["role"] for row in regions} >= {"BUILDING_INTERIOR","SITE_EXTERIOR"}


def test_conflicting_site_and_interior_labels_fail_closed():
    walls=[_topology_wall("A",(0,0),(10,0)),_topology_wall("B",(10,0),(10,10)),
           _topology_wall("C",(10,10),(0,10)),_topology_wall("D",(0,10),(0,0))]
    labels=[{"point":[2,2],"semantic_candidate":"bedroom"},{"point":[8,8],"semantic_candidate":"yard"}]
    envelope,_,regions=evidence_based_building_envelope(walls,frame_id="F1",tolerance=.001,semantic_labels=labels)
    assert envelope["status"] == "INPUT_REQUIRED"
    assert envelope["reason"] == "CONFLICTING_INTERIOR_EXTERIOR_EVIDENCE"
    assert regions[0]["status"] == "CONFLICT"


def test_source_supported_shell_survives_nested_interior_void_semantics():
    walls=[_topology_wall("A",(0,0),(10,0)),_topology_wall("B",(10,0),(10,10)),
           _topology_wall("C",(10,10),(0,10)),_topology_wall("D",(0,10),(0,0)),
           _topology_wall("P1",(2,3),(8,3)),_topology_wall("P2",(2,7),(8,7))]
    labels=[{"point":[2,2],"semantic_candidate":"elevator"},
            {"point":[5,5],"semantic_candidate":"lightwell"}]
    envelope,diagnostic,regions=evidence_based_building_envelope(
        walls,frame_id="F1",tolerance=.001,semantic_labels=labels)
    assert envelope["status"]=="HIGH_CONFIDENCE"
    assert envelope["reason"]=="SOURCE_SUPPORTED_DOMINANT_GEOMETRIC_SHELL"
    assert envelope["area"]==100
    assert envelope["evidence"][0]["semantic_authority"] is False
    assert diagnostic["candidates"][0]["internal_partition_count"]==2
    assert regions[0]["status"]=="CONFLICT"


def test_sparse_double_face_fragment_cannot_authorize_whole_shell():
    walls=[_topology_wall("A1",(0,0),(1,0)),
           _topology_wall("A2",(1,0),(10,0),representation="SINGLE_LINE"),
           _topology_wall("B",(10,0),(10,10),representation="SINGLE_LINE"),
           _topology_wall("C",(10,10),(0,10),representation="SINGLE_LINE"),
           _topology_wall("D",(0,10),(0,0),representation="SINGLE_LINE"),
           _topology_wall("P",(2,3),(8,3),representation="SINGLE_LINE")]
    envelope,diagnostic,_=evidence_based_building_envelope(walls,frame_id="F1",tolerance=.001)
    shell=max(diagnostic["candidates"],key=lambda row:row["area"])
    assert shell["source_boundary_proof"]["double_face_boundary_wall_count"]==1
    assert shell["source_boundary_proof"]["status"]=="INPUT_REQUIRED"
    assert "DOUBLE_FACE_SUPPORT_NOT_DISTRIBUTED" in shell["source_boundary_proof"]["reasons"]
    assert envelope["status"]=="INPUT_REQUIRED"


def test_distributed_material_boundary_proof_authorizes_shell_without_ratios():
    walls=[_topology_wall("A",(0,0),(10,0)),_topology_wall("B",(10,0),(10,10)),
           _topology_wall("C",(10,10),(0,10)),_topology_wall("D",(0,10),(0,0)),
           _topology_wall("P",(2,3),(8,3),representation="SINGLE_LINE")]
    envelope,diagnostic,_=evidence_based_building_envelope(walls,frame_id="F1",tolerance=.001)
    proof=max(diagnostic["candidates"],key=lambda row:row["area"])["source_boundary_proof"]
    assert proof["status"]=="SUPPORTED"
    assert proof["unsupported_interval_count"]==0
    assert proof["double_face_direction_classes"]==[0.0,90.0]
    assert envelope["status"]=="HIGH_CONFIDENCE"


def test_identical_classified_void_is_deduplicated_against_source_ring():
    shell=Polygon([(0,0),(10,0),(10,10),(0,10)],holes=[[(3,3),(7,3),(7,7),(3,7)]])
    result=_compose_shell_holes(shell,[{"candidate_id":"VOID-1","geometry":[[3,3],[7,3],[7,7],[3,7],[3,3]]}])
    assert result["status"]=="SUPPORTED"
    assert len(result["holes"])==1
    assert result["provenance"][0]["authority"]=="SOURCE_INTERIOR_RING"
    assert result["provenance"][0]["classified_void_ids"]==["VOID-1"]


def test_overlapping_classified_voids_fail_closed():
    shell=Polygon([(0,0),(10,0),(10,10),(0,10)])
    result=_compose_shell_holes(shell,[
        {"candidate_id":"VOID-A","geometry":[[2,2],[6,2],[6,6],[2,6],[2,2]]},
        {"candidate_id":"VOID-B","geometry":[[5,5],[8,5],[8,8],[5,8],[5,5]]},
    ])
    assert result["status"]=="CONFLICT"
    assert result["reason"]=="HOLES_OVERLAP_OR_TOUCH"


def test_classified_void_crossing_exterior_fails_closed():
    shell=Polygon([(0,0),(10,0),(10,10),(0,10)])
    result=_compose_shell_holes(shell,[
        {"candidate_id":"VOID-A","geometry":[[8,2],[12,2],[12,6],[8,6],[8,2]]},
    ])
    assert result["status"]=="CONFLICT"
    assert result["reason"]=="HOLE_NOT_STRICTLY_CONTAINED"


def test_valid_disjoint_source_backed_voids_compose_deterministically():
    shell=Polygon([(0,0),(10,0),(10,10),(0,10)])
    voids=[{"candidate_id":"VOID-B","geometry":[[6,6],[8,6],[8,8],[6,8],[6,6]]},
           {"candidate_id":"VOID-A","geometry":[[2,2],[4,2],[4,4],[2,4],[2,2]]}]
    first=_compose_shell_holes(shell,voids)
    second=_compose_shell_holes(shell,list(reversed(voids)))
    assert first==second
    assert first["status"]=="SUPPORTED"
    assert len(first["holes"])==2
    assert first["geometry"].area==92


def test_invalid_source_hole_never_repaired_into_authority():
    # A hole touching the outer shell makes the source polygon invalid.  The
    # composer must reject it, not snap, buffer, or make_valid it.
    shell=Polygon([(0,0),(10,0),(10,10),(0,10)],holes=[[(0,2),(3,2),(3,4),(0,4)]])
    result=_compose_shell_holes(shell,[])
    assert result["status"]=="CONFLICT"
    assert result["reason"] in {"INVALID_HOLE_GEOMETRY","HOLE_NOT_STRICTLY_CONTAINED"}


def test_geometric_shell_preserves_source_polygon_interior_rings():
    walls=[_topology_wall("A",(0,0),(10,0)),_topology_wall("B",(10,0),(10,10)),
           _topology_wall("C",(10,10),(0,10)),_topology_wall("D",(0,10),(0,0)),
           _topology_wall("IA",(3,3),(7,3)),_topology_wall("IB",(7,3),(7,7)),
           _topology_wall("IC",(7,7),(3,7)),_topology_wall("ID",(3,7),(3,3))]
    envelope,diagnostic,_=evidence_based_building_envelope(
        walls,frame_id="F1",tolerance=.001,
        semantic_labels=[{"point":[5,5],"semantic_candidate":"lightwell"}])
    shell=max(diagnostic["candidates"],key=lambda row:row["area"])
    assert len(shell["interior_rings"])==1
    assert shell["area"]==84
    assert envelope["status"]=="INPUT_REQUIRED"


def test_competing_comparable_geometric_shells_remain_fail_closed():
    walls=[]
    for prefix,x in (("L",0),("R",20)):
        walls.extend([_topology_wall(prefix+"A",(x,0),(x+10,0)),
                      _topology_wall(prefix+"B",(x+10,0),(x+10,10)),
                      _topology_wall(prefix+"C",(x+10,10),(x,10)),
                      _topology_wall(prefix+"D",(x,10),(x,0)),
                      _topology_wall(prefix+"P1",(x+2,3),(x+8,3)),
                      _topology_wall(prefix+"P2",(x+2,7),(x+8,7))])
    envelope,_,_=evidence_based_building_envelope(walls,frame_id="F1",tolerance=.001)
    assert envelope["status"]=="INPUT_REQUIRED"
    assert envelope["reason"]=="INSUFFICIENT_INDEPENDENT_INTERIOR_EVIDENCE"


def test_balcony_is_preserved_but_excluded_from_interior_area():
    labels=[{"point":[2,5],"semantic_candidate":"bedroom"},{"point":[7,5],"semantic_candidate":"kitchen"},
            {"point":[15,5],"semantic_candidate":"balcony"}]
    envelope,_,regions=evidence_based_building_envelope(_site_and_building_walls(),frame_id="F1",tolerance=.001,semantic_labels=labels)
    assert envelope["area"] == 100
    assert any(row["role"]=="SEMI_EXTERIOR" for row in regions)


def test_unlabelled_multiple_cycles_do_not_reintroduce_largest_wins():
    envelope,diagnostic,regions=evidence_based_building_envelope(_site_and_building_walls(),frame_id="F1",tolerance=.001)
    assert len(diagnostic["candidates"]) == 3
    assert envelope["status"] == "INPUT_REQUIRED"
    assert all(row["role"]=="UNKNOWN" for row in regions)


def test_envelope_candidate_diagnostic_exposes_boundary_quality_and_previous_selection():
    diagnostic=enumerate_envelope_candidates(_site_and_building_walls(),frame_id="F1",tolerance=.001,
                                             semantic_labels=[{"point":[15,5],"semantic_candidate":"parking"}])
    assert diagnostic["candidates"]
    assert all("boundary_double_face_ratio" in row and "source_handles" in row for row in diagnostic["candidates"])
    assert sum(row["previously_selected"] for row in diagnostic["candidates"]) == 1
