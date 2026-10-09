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
    material_continuity_graph,
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
                     "face_b":[[5.1,0],[5.1,6]],"source_handles":["PART-A","PART-B"]})
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
    assert first[0]["reason"] == "COLLINEAR_GAP_REQUIRES_OPENING_OR_LINEAGE"
    assert first[0]["roles"] == []
    assert first[0]["continuity_status"] == "INSUFFICIENT_CONTINUITY"
    assert first[0]["material"] is False
    assert {first[0][key] for key in ("wall_authority","routing_authority","portal_authority","access_authority")} == {"NONE"}


def test_source_supported_endpoint_closure_joins_small_orthogonal_corner():
    walls=[_proven_wall("A",(0,0),(4.8,0)),_proven_wall("B",(5,.2),(5,5))]
    rows=source_supported_endpoint_closures(walls,frame_id="F1",tolerance=.001)
    assert len(rows) == 1
    assert rows[0]["reason"] == "PROVEN_CORNER_CONTINUITY"


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
    assert gaps[0]["classification"]=="UNRESOLVED"
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
    assert gaps[0]["classification"]=="UNRESOLVED"
    assert gaps[0]["portal_evidence_ids"]==[]


def test_opening_evidence_locally_overlapping_gap_may_classify_that_gap_only():
    walls=[_proven_wall("A",(0,0),(4,0)),_proven_wall("B",(5,0),(10,0))]
    closures=source_supported_endpoint_closures(walls,frame_id="F1",tolerance=.001)
    host_ids=closures[0]["host_wall_ids"]
    evidence=[{"opening_evidence_id":"OPENEV-A","status":"OPENING_EVIDENCE_PRESENT",
               "candidate_type":"door","candidate_host_wall_ids":host_ids,
               "geometry":{"points":[[4.0,0.0],[5.0,0.0]]}}]
    gaps=classify_internal_wall_gaps(walls,closures,evidence,frame_id="F1",tolerance=.001)
    assert gaps[0]["classification"]=="PROVEN_DOOR_APERTURE"
    assert closures[0]["roles"]==["ENCLOSURE_BARRIER","ENVELOPE_SUPPORT"]
    assert closures[0]["portal_authority"]=="NONE"
    assert gaps[0]["portal_evidence_ids"]==["OPENEV-A"]


def test_reference_arc_cannot_promote_an_envelope_gap():
    walls=[_proven_wall("A",(0,0),(4,0)),_proven_wall("B",(5,0),(10,0))]
    closures=source_supported_endpoint_closures(walls,frame_id="F1",tolerance=.001)
    evidence=[{"opening_evidence_id":"OPENEV-REFERENCE","status":"OPENING_EVIDENCE_PRESENT",
               "candidate_type":"REFERENCE_ARC",
               "candidate_host_wall_ids":closures[0]["host_wall_ids"],
               "geometry":{"points":[[4.0,0.0],[5.0,0.0]]}}]
    gaps=classify_internal_wall_gaps(walls,closures,evidence,frame_id="F1",tolerance=.001)
    assert gaps[0]["classification"]=="UNRESOLVED"
    assert closures[0]["roles"]==[]
    assert closures[0]["portal_authority"]=="NONE"


def test_supported_single_line_endpoint_requires_source_role_classification():
    proven=_proven_wall("PROVEN",(0,0),(4.8,0))
    unrelated=_proven_wall("UNRELATED",(20,20),(25,20))
    supported=_topology_wall("SUPPORTED",(5,.2),(5,5),representation="SINGLE_LINE")
    supported.update({"status":"SUPPORTED_PARTITION","evidence":[
        {"class":"SOURCE_WALL_ADMISSION","iteratively_recovered":True}]})
    walls=[proven,unrelated,supported]
    closures=source_supported_endpoint_closures(walls,frame_id="F1",tolerance=.001)
    assert len(closures)==1
    gaps=classify_internal_wall_gaps(walls,closures,[],frame_id="F1",tolerance=.001)
    assert gaps[0]["classification"]=="SOURCE_ROLE_CLASSIFICATION_REQUIRED"
    assert gaps[0]["status"]=="INPUT_REQUIRED"
    assert closures[0]["roles"]==[]
    assert closures[0]["wall_authority"]=="NONE"


def test_endpoint_closure_never_reuses_one_endpoint_for_multiple_synthetic_joins():
    walls=[_proven_wall("A",(0,0),(4,0)),_proven_wall("B",(4.2,0),(8,0)),
           _proven_wall("C",(4.3,0),(9,0))]
    rows=source_supported_endpoint_closures(walls,frame_id="F1",tolerance=.001)
    endpoints=[tuple(point) for row in rows for point in row["geometry"]]
    assert len(endpoints)==len(set(endpoints))


def test_axis_endpoint_proximity_cannot_create_material_continuity():
    left=_proven_wall("LEFT",(0,0),(10,0)); left["wall_solid"]["occupied_intervals"]=[[0,2]]
    right=_proven_wall("RIGHT",(10.1,0),(20.1,0)); right["wall_solid"]["occupied_intervals"]=[[8,10]]
    assert source_supported_endpoint_closures([left,right],frame_id="F1",tolerance=.001)==[]


def test_endpoint_closure_binds_matint_lineage_and_keeps_all_authority_none():
    left=_proven_wall("LEFT",(0,0),(4,0)); right=_proven_wall("RIGHT",(4.5,0),(10,0))
    left["source_lineage"]=[{"segment_id":"SEG-L","source_insert_handle":"INSERT-L"}]
    right["source_lineage"]=[{"segment_id":"SEG-R","source_insert_handle":"INSERT-R"}]
    closure=source_supported_endpoint_closures([left,right],frame_id="F1",tolerance=.001)[0]
    assert len(closure["host_material_interval_ids"])==2
    assert all(value.startswith("MATINT-") for value in closure["host_material_interval_ids"])
    assert {row["source_insert_handle"] for row in closure["source_lineage"]}=={"INSERT-L","INSERT-R"}
    assert closure["material"] is False
    assert {closure[key] for key in ("wall_authority","portal_authority","routing_authority","access_authority")}=={"NONE"}


def test_material_continuity_graph_keeps_edge_types_distinct_and_reports_closed_cycle():
    walls=[_proven_wall("A1",(0,0),(4,0)),_proven_wall("A2",(4.5,0),(10,0)),
           _proven_wall("B",(10,0),(10,10)),_proven_wall("C",(10,10),(0,10)),
           _proven_wall("D",(0,10),(0,0))]
    walls[0]["source_fragments"]=["SHARED-BOTTOM"]
    walls[1]["source_fragments"]=["SHARED-BOTTOM"]
    closures=source_supported_endpoint_closures(walls,frame_id="F1",tolerance=.001)
    gap=next(row for row in closures if row["reason"]=="GOVERNED_DRAFTING_FRAGMENTATION")
    graph=material_continuity_graph(walls,[gap],frame_id="F1",tolerance=.001)
    assert graph==material_continuity_graph(list(reversed(walls)),[gap],frame_id="F1",tolerance=.001)
    assert len(graph["components"])==1
    component=graph["components"][0]
    assert component["matint_count"]==5
    assert component["closure_count"]==1
    assert component["closure_ids"]==[gap["closure_id"]]
    assert component["open_endpoint_count"]==0
    assert component["cycle_rank"]==1
    assert component["closed_cycle"] is True


def test_material_continuity_graph_does_not_join_nearest_disconnected_components():
    walls=[_topology_wall("A",(0,0),(1,0)),_topology_wall("B",(1.1,0),(2.1,0))]
    graph=material_continuity_graph(walls,[],frame_id="F1",tolerance=.001)
    assert len(graph["components"])==2
    assert all(component["open_endpoint_count"]==2 for component in graph["components"])
    assert all(endpoint["material_interval_id"].startswith("MATINT-") for endpoint in graph["open_endpoints"])
    assert all(endpoint["nearest_material_endpoints"] for endpoint in graph["open_endpoints"])
    assert all("distance" in endpoint["nearest_material_endpoints"][0]
               for endpoint in graph["open_endpoints"])




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


def test_nested_source_lineage_survives_into_canonical_wall_evidence():
    rows=[_row("A",(0,0),(10,0)),_row("B",(10,0),(10,6)),
          _row("C",(10,6),(0,6)),_row("D",(0,6),(0,0))]
    for row in rows:
        row.update({"source_insert_handle":"INSERT-1","source_block_path":["UNIT","WALLS"],
                    "source_transform":{"fingerprint":"TX-1"}})
    result=reconstruct_canonical_walls(rows,frame_id="F1",tolerance=.001)
    assert result["walls"]
    for wall in result["walls"]:
        assert wall["source_lineage"]
        assert all(item["source_insert_handle"]=="INSERT-1" for item in wall["source_lineage"])
        assert all(item["source_block_path"]==["UNIT","WALLS"] for item in wall["source_lineage"])
        assert all(item["source_transform"]=={"fingerprint":"TX-1"} for item in wall["source_lineage"])
        assert all(item["primitive_geometry_fingerprint"].startswith("PRIM-") for item in wall["source_lineage"])


def test_short_parallel_face_axis_extension_is_not_envelope_material():
    rows=[_row("LONG",(0,0),(10,0)),_row("SHORT",(0,.2),(2,.2)),
          _row("PAIR-A",(0,3),(10,3)),_row("PAIR-B",(0,3.2),(10,3.2))]
    result=reconstruct_canonical_walls(rows,frame_id="F1",tolerance=.001)
    mixed=next(wall for wall in result["walls"] if set(wall["source_handles"])=={"LONG","SHORT"})
    assert mixed["representation"]=="DOUBLE_FACE"
    assert LineString(mixed["centerline"]).length==10
    assert sum(end-start for start,end in mixed["wall_solid"]["occupied_intervals"])==2
    assert any(set(wall["source_handles"])=={"PAIR-A","PAIR-B"} and wall["representation"]=="DOUBLE_FACE"
               for wall in result["walls"])
    diagnostic=enumerate_envelope_candidates(result["walls"],frame_id="F1",tolerance=.001)
    assert not any(row["area"]>1 for row in diagnostic["candidates"])


def test_full_axis_inside_shell_cannot_prove_internal_partition_when_material_is_outside():
    walls=[_topology_wall("A",(0,0),(10,0)),_topology_wall("B",(10,0),(10,10)),
           _topology_wall("C",(10,10),(0,10)),_topology_wall("D",(0,10),(0,0))]
    partition=_topology_wall("P",(5,5),(25,5))
    partition["wall_solid"]["occupied_intervals"]=[[10,12]]
    partition["source_lineage"]=[{"segment_id":"SEG-P","source_handle":"P"}]
    walls.append(partition)
    envelope,diagnostic,_=evidence_based_building_envelope(walls,frame_id="F1",tolerance=.001)
    shell=max(diagnostic["candidates"],key=lambda row:row["area"])
    proof=shell["source_boundary_proof"]
    assert LineString(partition["centerline"]).representative_point().within(Polygon(shell["polygon"]))
    assert proof["internal_partition_evidence"]==[]
    assert "SOURCE_BACKED_INTERNAL_PARTITION_REQUIRED" in proof["reasons"]
    assert envelope["status"]=="INPUT_REQUIRED"


def test_short_material_interval_inside_shell_proves_partition_with_matint_lineage():
    walls=[_topology_wall("A",(0,0),(10,0)),_topology_wall("B",(10,0),(10,10)),
           _topology_wall("C",(10,10),(0,10)),_topology_wall("D",(0,10),(0,0))]
    partition=_topology_wall("P",(5,5),(25,5))
    partition["wall_solid"]["occupied_intervals"]=[[0,2]]
    partition["source_lineage"]=[{"segment_id":"SEG-P","source_handle":"P",
                                  "source_block_path":["UNIT"],"source_transform":{"id":"TX-P"}}]
    walls.append(partition)
    envelope,diagnostic,_=evidence_based_building_envelope(walls,frame_id="F1",tolerance=.001)
    shell=max(diagnostic["candidates"],key=lambda row:row["area"])
    proof=shell["source_boundary_proof"]
    evidence=proof["internal_partition_evidence"]
    assert envelope["status"]=="HIGH_CONFIDENCE"
    assert proof["source_backed_internal_wall_ids"]==["P"]
    assert len(evidence)==1
    assert evidence[0]["material_interval_id"].startswith("MATINT-")
    assert evidence[0]["source_handles"]==["P"]
    assert evidence[0]["source_lineage"]==partition["source_lineage"]
    assert evidence[0]["material_geometry"]==[[5.0,5.0],[7.0,5.0]]
    assert evidence[0]["applicable_material_length"]==2.0
    assert shell["internal_wall_length"]==2.0


def test_semantic_union_exterior_wall_ids_require_material_at_boundary():
    walls=[_topology_wall("A",(0,0),(10,0)),_topology_wall("B",(10,0),(10,10)),
           _topology_wall("C",(10,10),(0,10)),_topology_wall("D",(0,10),(0,0))]
    stray=_topology_wall("STRAY",(0,0),(0,30))
    stray["wall_solid"]["occupied_intervals"]=[[20,22]]
    walls.append(stray)
    labels=[{"point":[2,2],"semantic_candidate":"bedroom"},
            {"point":[8,8],"semantic_candidate":"kitchen"}]
    envelope,_,_=evidence_based_building_envelope(
        walls,frame_id="F1",tolerance=.001,semantic_labels=labels)
    assert envelope["status"]=="HIGH_CONFIDENCE"
    assert "STRAY" not in envelope["exterior_wall_ids"]
    assert set(envelope["exterior_wall_ids"])=={"A","B","C","D"}


def test_fragmented_shell_requires_material_or_governed_continuity_for_every_interval():
    walls=[_topology_wall("A",(0,0),(10,0)),_topology_wall("B",(10,0),(10,10)),
           _topology_wall("C",(10,10),(0,10)),_topology_wall("D",(0,10),(0,0)),
           _topology_wall("P",(2,3),(8,3))]
    walls[0]["wall_solid"]["occupied_intervals"]=[[0,4],[6,10]]
    envelope,diagnostic,_=evidence_based_building_envelope(walls,frame_id="F1",tolerance=.001)
    assert envelope["status"]=="INPUT_REQUIRED"
    assert not any(row.get("area")==100 for row in diagnostic["candidates"])


def test_governed_nonmaterial_closure_supports_enclosure_but_never_wall_material():
    walls=[_proven_wall("A1",(0,0),(4,0)),_proven_wall("A2",(4.5,0),(10,0)),
           _proven_wall("B",(10,0),(10,10)),_proven_wall("C",(10,10),(0,10)),
           _proven_wall("D",(0,10),(0,0)),_proven_wall("P",(2,3),(8,3))]
    walls[0]["source_fragments"]=["SHARED-BOTTOM"]
    walls[1]["source_fragments"]=["SHARED-BOTTOM"]
    closures=source_supported_endpoint_closures(walls,frame_id="F1",tolerance=.001)
    gap_closure=next(row for row in closures if row["reason"]=="GOVERNED_DRAFTING_FRAGMENTATION")
    envelope,diagnostic,_=evidence_based_building_envelope(
        walls,frame_id="F1",tolerance=.001,enclosure_closures=closures)
    shell=max(diagnostic["candidates"],key=lambda row:row["area"])
    assert envelope["status"]=="HIGH_CONFIDENCE"
    assert shell["source_boundary_proof"]["governed_nonmaterial_closure_count"]>=1
    assert gap_closure["material"] is False
    assert gap_closure["wall_authority"]=="NONE"


def test_nearby_wrong_source_line_cannot_fill_material_boundary_gap():
    walls=[_topology_wall("A",(0,0),(10,0)),_topology_wall("B",(10,0),(10,10)),
           _topology_wall("C",(10,10),(0,10)),_topology_wall("D",(0,10),(0,0)),
           _topology_wall("P",(2,3),(8,3)),_topology_wall("WRONG",(4,.02),(6,.02))]
    walls[0]["wall_solid"]["occupied_intervals"]=[[0,4],[6,10]]
    envelope,diagnostic,_=evidence_based_building_envelope(walls,frame_id="F1",tolerance=.001)
    assert envelope["status"]=="INPUT_REQUIRED"
    assert not any(row.get("area")==100 for row in diagnostic["candidates"])


def test_candidate_containment_graph_is_diagnostic_and_deterministic():
    walls=[_topology_wall("A",(0,0),(10,0)),_topology_wall("B",(10,0),(10,10)),
           _topology_wall("C",(10,10),(0,10)),_topology_wall("D",(0,10),(0,0)),
           _topology_wall("IA",(3,3),(7,3)),_topology_wall("IB",(7,3),(7,7)),
           _topology_wall("IC",(7,7),(3,7)),_topology_wall("ID",(3,7),(3,3))]
    first=enumerate_envelope_candidates(walls,frame_id="F1",tolerance=.001)
    second=enumerate_envelope_candidates(list(reversed(walls)),frame_id="F1",tolerance=.001)
    assert first["candidate_relationships"]==second["candidate_relationships"]
    assert {row["relation"] for row in first["candidate_relationships"]}<={"CONTAINS","WITHIN","OVERLAPS","TOUCHES","DISJOINT"}


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
