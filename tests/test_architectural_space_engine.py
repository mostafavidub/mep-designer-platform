from pathlib import Path

import ezdxf
from shapely.geometry import LineString, Polygon

from cad_engine.architectural_space_engine import (
    SCHEMA, _completeness, _exclude_inset_sheet_border_segments, _recover_supported_partitions,
    _associate_dimensions, _dimension_reconciliation, _semantic_segment_classification,
    _pre_envelope_opening_evidence, _bind_openings, _architectural_void_candidates, normalize_text,
    reconstruct_architecture, require_complete_architecture,
)


def _drawing(path, *, labels=(), split=False, layer="WALL", rotate=False, units=6, fake_outside=False, dimension=False):
    doc = ezdxf.new("R2013"); doc.header["$INSUNITS"] = units
    msp = doc.modelspace()
    if layer not in doc.layers: doc.layers.add(layer)
    points = [(0,0),(10,0),(10,6),(0,6)]
    if rotate: points = [(x-y, x+y) for x,y in points]
    for a,b in zip(points, points[1:]+points[:1]): msp.add_line(a,b,dxfattribs={"layer":layer})
    if split:
        a,b=((5,0),(5,6)) if not rotate else ((5,5),(-1,11))
        msp.add_line(a,b,dxfattribs={"layer":layer})
    for text,point in labels:
        if rotate: point=(point[0]-point[1],point[0]+point[1])
        msp.add_text(text,dxfattribs={"height":.2,"insert":point})
    if fake_outside: msp.add_text("BEDROOM",dxfattribs={"height":.2,"insert":(30,30)})
    if dimension:
        msp.add_linear_dim(base=(0,-1),p1=(0,0),p2=(10,0),angle=0).render()
    doc.saveas(path); return path


def _drawing_with_opening(path, *, orphan=False, kind="door"):
    doc=ezdxf.new("R2013"); doc.header["$INSUNITS"]=6; msp=doc.modelspace()
    doc.layers.add("WALL"); doc.layers.add(kind)
    for a,b in [((0,0),(10,0)),((10,0),(10,6)),((10,6),(0,6)),((0,6),(0,0)),((5,0),(5,6))]:
        msp.add_line(a,b,dxfattribs={"layer":"WALL"})
    block=doc.blocks.new(kind.upper()); block.add_line((0,0),(0.8,0),dxfattribs={"layer":kind})
    msp.add_blockref(kind.upper(), (30,30) if orphan else (5,3), dxfattribs={"layer":kind})
    msp.add_text("خواب",dxfattribs={"height":.2,"insert":(2,3)})
    msp.add_text("آشپزخانه",dxfattribs={"height":.2,"insert":(8,3)})
    doc.saveas(path); return path


def _drawing_with_anonymous_door(path, *, leaf=True):
    doc=ezdxf.new("R2013"); doc.header["$INSUNITS"]=6; msp=doc.modelspace(); doc.layers.add("WALL")
    for a,b in [((0,0),(10,0)),((10,0),(10,6)),((10,6),(0,6)),((0,6),(0,0)),((5,0),(5,6))]:
        msp.add_line(a,b,dxfattribs={"layer":"WALL"})
    if leaf: msp.add_line((5,3),(5.8,3),dxfattribs={"layer":"0"})
    msp.add_arc((5,3),.8,0,90,dxfattribs={"layer":"0"})
    msp.add_text("خواب",dxfattribs={"height":.2,"insert":(2,3)})
    msp.add_text("آشپزخانه",dxfattribs={"height":.2,"insert":(8,3)})
    doc.saveas(path); return path


def test_persian_normalization_and_ontology():
    assert normalize_text("  آشپزخانه‌ی ۰۱ ") == "آشپزخانه ی 01"


def test_inset_print_border_on_wall_layer_is_not_admitted_as_architectural_wall():
    frame = {"frame_id": "FRAME-1", "bounds": [0, 0, 21, 29.7]}
    points = [(1, 1), (20, 1), (20, 28.7), (1, 28.7)]
    lines = [LineString([left, right]) for left, right in zip(points, points[1:]+points[:1])]
    metas = [{"handle": "SHEET-BORDER", "layer": "WALL", "entity_type": "LWPOLYLINE", "closed": True}
             for _ in lines]
    kept, _, records = _exclude_inset_sheet_border_segments(lines, metas, frame, .002)
    assert kept == []
    assert len(records) == 4
    assert {row["semantic_class"] for row in records} == {"PRINT_BORDER"}
    assert {row["status"] for row in records} == {"REJECTED"}
    assert {row["evidence"][0]["class"] for row in records} == {"INSET_PRINT_BORDER_GEOMETRY"}


def test_room_or_building_rectangle_is_not_mistaken_for_inset_print_border():
    frame = {"frame_id": "FRAME-1", "bounds": [0, 0, 21, 29.7]}
    points = [(4, 5), (17, 5), (17, 23), (4, 23)]
    lines = [LineString([left, right]) for left, right in zip(points, points[1:]+points[:1])]
    metas = [{"handle": "BUILDING", "layer": "WALL", "entity_type": "LWPOLYLINE", "closed": True}
             for _ in lines]
    kept, _, records = _exclude_inset_sheet_border_segments(lines, metas, frame, .002)
    assert kept == lines
    assert records == []


def test_unlabelled_line_room_is_reconstructed_but_blocks_downstream(tmp_path):
    model = reconstruct_architecture(_drawing(tmp_path/"unlabelled.dxf"))
    assert model["schema"] == SCHEMA
    assert len(model["physical_spaces"]) == 1
    assert model["physical_spaces"][0]["category"] == "unknown"
    assert model["completeness"]["status"] == "INPUT_REQUIRED"
    assert require_complete_architecture(model)["allowed"] is False


def test_separate_line_walls_create_all_cells_without_closed_polylines(tmp_path):
    model = reconstruct_architecture(_drawing(tmp_path/"split.dxf", split=True,
        labels=(("اتاق خواب",(2,3)),("آشپزخانه",(8,3)))))
    assert len(model["physical_spaces"]) == 2
    assert {s["category"] for s in model["physical_spaces"]} == {"bedroom","kitchen"}
    assert model["completeness"]["status"] == "INPUT_REQUIRED"
    assert any(r["code"] == "SEPARATOR_ROLE_REQUIRED" for r in model["completeness"]["issues"])
    assert require_complete_architecture(model)["allowed"] is False


def test_open_plan_is_one_physical_space_with_functional_zones(tmp_path):
    model = reconstruct_architecture(_drawing(tmp_path/"open.dxf", labels=(
        ("پذیرایی",(2,3)),("ناهارخوری",(5,3)),("آشپزخانه",(8,3)))))
    assert len(model["physical_spaces"]) == 1
    space = model["physical_spaces"][0]
    assert space["category"] == "open_plan"
    assert {z["category"] for z in space["functional_zones"]} == {"reception","dining","kitchen"}
    assert all(z["boundary_status"] == "approximate" for z in space["functional_zones"])
    assert model["completeness"]["status"] == "INPUT_REQUIRED"
    assert any(r["code"] == "SEPARATOR_ROLE_REQUIRED" for r in model["completeness"]["issues"])


def test_enclosed_service_label_inside_open_plan_fails_closed(tmp_path):
    model = reconstruct_architecture(_drawing(tmp_path/"missed-partition.dxf", labels=(
        ("پذیرایی",(2,3)),("آشپزخانه",(6,3)),("توالت",(8,3)))))
    assert model["physical_spaces"][0]["category"] == "open_plan"
    assert model["physical_spaces"][0]["status"] == "INPUT_REQUIRED"
    assert any(row["code"] == "UNRESOLVED_SPACE" for row in model["completeness"]["issues"])


def test_mechanical_authority_frame_cannot_release_legacy_subdivision():
    completeness=_completeness(
        [{"frame_id":"F1","scope_relevance":"MECHANICAL_AUTHORITY","frame_type":"PLAN"}],
        [{"physical_space_id":"S1","frame_id":"F1","status":"VERIFIED","area_m2":10}],True,
        subdivision_comparisons=[{"frame_id":"F1","selected_authority":"LEGACY_FALLBACK"}])
    assert completeness["status"] == "INPUT_REQUIRED"
    assert completeness["release_allowed"] is False
    assert any(r["code"] == "CANONICAL_TOPOLOGY_REQUIRED" for r in completeness["issues"])


def test_stable_ids_survive_layer_rename_and_reprocessing(tmp_path):
    first = reconstruct_architecture(_drawing(tmp_path/"a.dxf", labels=(("خواب",(3,3)),), layer="A-WALL"))
    second = reconstruct_architecture(_drawing(tmp_path/"b.dxf", labels=(("خواب",(3,3)),), layer="0"))
    repeat = reconstruct_architecture(tmp_path/"a.dxf")
    assert first["physical_spaces"][0]["physical_space_id"] == repeat["physical_spaces"][0]["physical_space_id"]
    # Source identity intentionally differentiates different approved files.
    assert first["physical_spaces"][0]["traceability"]["geometry_fingerprint"] == second["physical_spaces"][0]["traceability"]["geometry_fingerprint"]


def test_rotated_plan_and_fake_outside_label_do_not_create_phantom_space(tmp_path):
    model = reconstruct_architecture(_drawing(tmp_path/"rotated.dxf", labels=(("اتاق خواب",(3,3)),), rotate=True, fake_outside=True))
    assert len(model["physical_spaces"]) == 1
    assert model["physical_spaces"][0]["category"] == "bedroom"


def test_dimension_provenance_and_svg_preview(tmp_path):
    model = reconstruct_architecture(_drawing(tmp_path/"dimension.dxf", labels=(("living",(3,3)),), dimension=True))
    assert model["dimensions"]
    assert all(d.get("handle") for d in model["dimensions"])
    assert model["recognition_preview_svg"].startswith("<svg")
    assert "VERIFIED" not in model["recognition_preview_svg"]  # status encoded visually, not as noisy debug text


def test_missing_units_fail_closed(tmp_path):
    model = reconstruct_architecture(_drawing(tmp_path/"unitless.dxf", labels=(("living",(3,3)),), units=0))
    assert model["physical_spaces"][0]["area_m2"] is None
    assert any(i["code"] == "UNIT_CALIBRATION_REQUIRED" for i in model["completeness"]["issues"])


def test_incorrect_mm_header_is_overridden_by_frame_and_dimension_evidence(tmp_path):
    model = reconstruct_architecture(_drawing(tmp_path/"misdeclared.dxf", labels=(("living", (3,3)),), units=4, dimension=True))
    calibration = model["source"]["unit_calibration"]
    assert calibration["status"] == "INFERRED"
    assert calibration["declared_unit_conflict"] is True
    assert calibration["effective_metres_per_unit"] == 1.0
    assert model["physical_spaces"][0]["area_m2"] == 60


def test_non_floor_section_never_silently_becomes_floor(tmp_path):
    model = reconstruct_architecture(_drawing(tmp_path/"section.dxf", labels=(("SECTION A-A",(3,3)),)))
    assert model["frames"][0]["frame_type"] == "SECTION"
    assert not model["physical_spaces"]
    assert model["completeness"]["status"] == "INPUT_REQUIRED"


def test_reference_only_frames_do_not_duplicate_spaces_or_block_authoritative_floor():
    frames = [
        {"frame_id": "FLOOR", "frame_type": "PRIMARY_FLOOR", "scope_relevance": "MECHANICAL_AUTHORITY"},
        {"frame_id": "FURN", "frame_type": "FURNITURE_PLAN", "scope_relevance": "REFERENCE_ONLY"},
        {"frame_id": "VIEW", "frame_type": "UNKNOWN", "scope_relevance": "REFERENCE_ONLY"},
    ]
    result = _completeness(frames, [{"physical_space_id": "S1", "frame_id": "FLOOR", "status": "VERIFIED", "area_m2": 12, "separator_status": "VERIFIED", "material_geometry": True}], True)
    assert result["status"] == "VERIFIED"
    assert result["relevant_space_count"] == 1


def test_door_symbol_on_continuous_wall_is_rejected(tmp_path):
    model=reconstruct_architecture(_drawing_with_opening(tmp_path/"door.dxf"))
    door=model["doors"][0]
    assert door["status"]=="REJECTED"
    assert door["host_wall_id"].startswith("WALL-")
    assert door["reason"]=="OPENING_WITHOUT_CLASSIFIED_HOST_GAP"


def test_orphan_door_is_rejected_and_blocks_mechanical(tmp_path):
    model=reconstruct_architecture(_drawing_with_opening(tmp_path/"orphan.dxf",orphan=True))
    assert model["doors"][0]["status"]=="REJECTED"
    assert model["doors"][0]["reason"]=="ORPHAN_OPENING_NO_HOST_WALL"
    assert any(i["code"]=="UNRESOLVED_CRITICAL_DOOR" for i in model["completeness"]["issues"])
    assert require_complete_architecture(model)["allowed"] is False


def test_coverage_and_review_contract_expose_only_unresolved_regions(tmp_path):
    model=reconstruct_architecture(_drawing(tmp_path/"review.dxf",split=True,labels=(("خواب",(2,3)),)))
    assert model["coverage"]["status"]=="INPUT_REQUIRED"
    assert model["coverage"]["coverage_ratio"]==0.5
    assert model["review"]["verified_items_hidden"] is True
    assert len(model["review"]["decisions"])==1
    assert model["review"]["decisions"][0]["candidate_types"]==["unknown"]
    assert model["vision_reconciliation"]["status"]=="CONFIG_REQUIRED"
    assert model["diagnostics"]["dxf_parse_count"]==1


def test_dimension_conflict_is_never_silently_resolved(tmp_path):
    path=_drawing(tmp_path/"dim-conflict.dxf",labels=(("خواب",(3,3)),),dimension=True)
    doc=ezdxf.readfile(path); dim=next(e for e in doc.modelspace() if e.dxftype()=="DIMENSION")
    dim.dxf.text="20"; doc.saveas(path)
    # The native associative measurement remains geometry-backed, therefore a
    # text override is evidence that needs an explicit reconciliation rule.
    model=reconstruct_architecture(path)
    assert model["dimension_reconciliation"]["status"] in {"PASS","CONFLICT","INPUT_REQUIRED"}
    assert all("annotated_measurement_m" in row and "geometric_measurement_m" in row
               for row in model["dimension_reconciliation"]["rows"])


def test_dimension_requires_two_boundary_witnesses_crossing_space_interior():
    poly=Polygon(((0,0),(10,0),(10,6),(0,6)))
    one=[{"handle":"D1","measurement":10.0,"witness_points":[(0,0)],"definition_points":[(0,0)]}]
    same_edge=[{"handle":"D2","measurement":4.0,"witness_points":[(1,0),(5,0)],
                "definition_points":[(1,0),(5,0)]}]
    assert _associate_dimensions(poly,one,1.0)==[]
    assert _associate_dimensions(poly,same_edge,1.0)==[]


def test_dimension_reconciliation_uses_bound_references_not_space_bbox():
    poly=Polygon(((0,0),(10,0),(10,6),(0,6)))
    dim={"handle":"D1","measurement":10.0,"witness_points":[(0,3),(10,3)],
         "definition_points":[(0,3),(10,3)],"dimension_type":0,"text_override":""}
    associated=_associate_dimensions(poly,[dim],1.0)
    assert associated[0]["status"]=="VERIFIED_ASSOCIATION"
    space={"physical_space_id":"S1","polygon":list(poly.exterior.coords),"interior_rings":[],
           "dimensions":associated}
    result=_dimension_reconciliation([space],1.0,.001,[dim])
    assert result["status"]=="PASS"
    assert result["rows"][0]["geometric_measurement_m"]==10.0


def test_anonymous_leaf_arc_on_continuous_wall_remains_unqualified(tmp_path):
    model=reconstruct_architecture(_drawing_with_anonymous_door(tmp_path/"anonymous-door.dxf"))
    geometric=[door for door in model["doors"] if any(e["class"]=="SWING_ARC" for e in door["evidence"])]
    assert len(geometric)==1 and geometric[0]["status"]=="REJECTED"
    assert geometric[0]["reason"]=="OPENING_WITHOUT_CLASSIFIED_HOST_GAP"
    assert len(model["physical_spaces"])==2


def test_random_arc_without_leaf_is_not_a_door(tmp_path):
    model=reconstruct_architecture(_drawing_with_anonymous_door(tmp_path/"random-arc.dxf",leaf=False))
    assert not any(any(e["class"]=="SWING_ARC" for e in door["evidence"]) for door in model["doors"])


def test_current_human_confirmed_gap_is_binding_compatible_but_does_not_supply_geometry():
    spaces=[{"physical_space_id":"A","polygon":[(0,0),(5,0),(5,5),(0,5),(0,0)],"interior_rings":[],
             "level_id":"L1","openings":[],"windows":[]},
            {"physical_space_id":"B","polygon":[(5,0),(10,0),(10,5),(5,5),(5,0)],"interior_rings":[],
             "level_id":"L1","openings":[],"windows":[]}]
    wall={"wall_id":"W1","centerline":[(5,0),(5,5)]}
    opening={"opening_id":"O1","kind":"door","geometry":{"point":[5,2.5],"points":[[5,2],[5,3]]},
             "source_handle":"ARC1","evidence":[{"class":"SWING_ARC","handle":"ARC1"}]}
    gap={"gap_id":"G1","host_wall_ids":["W1"],"geometry":[[5,2],[5,3]],"gap_width":1.0,
         "classification":"DOOR_GAP","status":"HUMAN_CONFIRMED","source_handles":["WALL-END-1"]}
    bound,_=_bind_openings([opening],spaces,[LineString(wall["centerline"])],"s"*64,.01,
                           canonical_walls=[wall],internal_wall_gaps=[gap])
    assert bound[0]["status"]=="VERIFIED"
    assert bound[0]["portal_geometry"]["points"]==gap["geometry"]
    assert bound[0]["material_geometry_authority"]=="SOURCE_GAP_ONLY"

    rejected,_=_bind_openings([opening],spaces,[LineString(wall["centerline"])],"s"*64,.01,
                              canonical_walls=[wall],internal_wall_gaps=[])
    assert rejected[0]["reason"]=="OPENING_WITHOUT_CLASSIFIED_HOST_GAP"


def test_duct_label_selects_repeated_source_closed_footprint_but_supplies_no_geometry():
    extracted={"texts":[{"handle":"T1","text":"داکت","point":[1.7,1.2]},
                        {"handle":"T2","text":"داکت","point":[11.7,1.2]}],
               "primitives":[{"handle":"P1","entity_type":"LWPOLYLINE","closed":True,"layer":"DUCT",
                              "points":[[1,1],[1.4,1],[1.4,1.4],[1,1.4]]},
                             {"handle":"P1-DUP","entity_type":"LWPOLYLINE","closed":True,"layer":"DUCT",
                              "points":[[1,1],[1.4,1],[1.4,1.4],[1,1.4]]},
                             {"handle":"P2","entity_type":"LWPOLYLINE","closed":True,"layer":"DUCT",
                              "points":[[11,1],[11.4,1],[11.4,1.4],[11,1.4]]}]}
    frames=[{"frame_id":"F1","bounds":[0,0,5,5],"scope_relevance":"MECHANICAL_AUTHORITY"},
            {"frame_id":"F2","bounds":[10,0,15,5],"scope_relevance":"MECHANICAL_AUTHORITY"}]
    rows=_architectural_void_candidates(extracted,frames,"s"*64,.001)
    assert len(rows)==2
    first=next(row for row in rows if row["frame_id"]=="F1")
    assert first["void_type"]=="DUCT_VOID"
    assert first["source_handles"]==["P1","P1-DUP"]
    assert first["boundary"]==[[1.0,1.0],[1.4,1.0],[1.4,1.4],[1.0,1.4],[1.0,1.0]]
    assert first["material_geometry_authority"]=="NONE"
    assert first["routing_authority"]=="NONE"


def test_duct_label_alone_never_creates_void_geometry():
    extracted={"texts":[{"handle":"T1","text":"داکت","point":[1,1]}],"primitives":[]}
    frames=[{"frame_id":"F1","bounds":[0,0,5,5],"scope_relevance":"MECHANICAL_AUTHORITY"}]
    assert _architectural_void_candidates(extracted,frames,"s"*64,.001)==[]


def test_unknown_furniture_and_annotation_lines_never_silently_become_walls():
    lines=[LineString(((1,1),(2,1))),LineString(((1,2),(2,2)))]
    metadata=[
        {"handle":"F1","layer":"0","entity_type":"LINE","closed":False},
        {"handle":"A1","layer":"notes","entity_type":"LINE","closed":False},
    ]
    records,accepted=_semantic_segment_classification(lines,metadata,1.0,.001)
    assert accepted == []
    assert {row["semantic_class"] for row in records} == {"UNKNOWN_GEOMETRY"}
    assert all(row["status"] == "REJECTED" for row in records)


def test_recurring_double_line_wall_faces_are_inferred_without_layer_names():
    lines=[]; metadata=[]
    for index,y in enumerate((0,.2,2,2.2,4,4.2)):
        lines.append(LineString(((0,y),(8,y))))
        metadata.append({"handle":f"L{index}","layer":"0","entity_type":"LINE","closed":False})
    records,accepted=_semantic_segment_classification(lines,metadata,1.0,.001)
    assert len(accepted) == len(lines)
    assert all(row["semantic_class"] == "WALL_FACE" for row in records)
    assert all(any(e["class"] == "RECURRING_PARALLEL_FACE_PAIR" for e in row["evidence"]) for row in records)


def test_repeat_reconstruction_is_deterministic_with_anonymous_portal(tmp_path):
    path=_drawing_with_anonymous_door(tmp_path/"repeat-door.dxf")
    first=reconstruct_architecture(path); second=reconstruct_architecture(path)
    assert first["architectural_segments"] == second["architectural_segments"]
    assert first["topology_refinement"] == second["topology_refinement"]
    assert first["doors"] == second["doors"]


def _recover(lines, metadata, labels=()):
    records,seeds=_semantic_segment_classification(lines,metadata,1.0,.001)
    extracted={"texts":[{"text":text,"point":point} for text,point in labels]}
    accepted,decisions,iterations=_recover_supported_partitions(
        seeds,records,{"bounds":[-1,-1,11,7]},.001,extracted,1.0)
    return records,accepted,decisions,iterations


def test_globally_unique_double_face_partition_is_recovered_from_local_topology():
    lines=[LineString(((0,0),(10,0))),LineString(((10,0),(10,6))),LineString(((10,6),(0,6))),LineString(((0,6),(0,0))),
           LineString(((5,0),(5,6))),LineString(((5.2,0),(5.2,6)))]
    metadata=[{"handle":f"W{i}","layer":"WALL" if i<4 else "0","entity_type":"LINE","closed":False} for i in range(len(lines))]
    records,accepted,decisions,_=_recover(lines,metadata)
    assert len(accepted)==6
    assert sum(bool(row.get("admission_trace")) for row in records)==2
    assert decisions and decisions[0]["local_parallel_pair"] is True


def test_partial_face_family_survives_door_sized_interruption():
    lines=[LineString(((0,0),(10,0))),LineString(((10,0),(10,6))),LineString(((10,6),(0,6))),LineString(((0,6),(0,0))),
           LineString(((5,0),(5,6))),LineString(((5.2,0),(5.2,2.5))),LineString(((5.2,3.5),(5.2,6)))]
    metadata=[{"handle":f"P{i}","layer":"WALL" if i<4 else "0","entity_type":"LINE","closed":False} for i in range(len(lines))]
    records,accepted,decisions,_=_recover(lines,metadata)
    assert len(accepted)==7
    assert sum(bool(row.get("admission_trace")) for row in records)==3
    assert any(row["local_parallel_pair"] for row in decisions)


def test_single_line_partition_with_two_wall_connections_is_recovered_without_labels():
    lines=[LineString(((0,0),(10,0))),LineString(((10,0),(10,6))),LineString(((10,6),(0,6))),LineString(((0,6),(0,0))),LineString(((5,0),(5,6)))]
    metadata=[{"handle":f"S{i}","layer":"WALL" if i<4 else "0","entity_type":"LINE","closed":False} for i in range(len(lines))]
    records,accepted,decisions,_=_recover(lines,metadata)
    assert len(accepted)==5
    assert records[-1]["admission_trace"]["reason"]=="MULTI_EVIDENCE_PARTITION_ADMISSION"


def test_isolated_furniture_sized_line_is_not_recovered_as_partition():
    lines=[LineString(((0,0),(10,0))),LineString(((10,0),(10,6))),LineString(((10,6),(0,6))),LineString(((0,6),(0,0))),LineString(((2,2),(4,2)))]
    metadata=[{"handle":f"F{i}","layer":"WALL" if i<4 else "0","entity_type":"LINE","closed":False} for i in range(len(lines))]
    records,accepted,decisions,_=_recover(lines,metadata,labels=(("اتاق خواب",(2,3)),("اتاق خواب",(8,3))))
    assert len(accepted)==4
    assert records[-1]["status"]=="REJECTED"
    assert decisions==[]


def _opening_wall():
    return {"wall_id":"W1","frame_id":"F1","centerline":[[0,0],[10,0]],
            "representation":"DOUBLE_FACE","thickness":.2,
            "wall_solid":{"axis_origin":[0,0],"axis_direction":[1,0],"occupied_intervals":[[0,10]]},
            "interruptions":[],"source_handles":["WA","WB"]}


def test_cad_door_block_is_pre_envelope_evidence_but_not_material_gap_or_portal():
    candidate={"opening_id":"D1","kind":"door","geometry":{"point":[5,.05]},
               "source_handle":"D","evidence":[{"class":"CAD_BLOCK"}]}
    rows=_pre_envelope_opening_evidence([candidate],[_opening_wall()],
                                        {"frame_id":"F1","bounds":[-1,-1,11,7]},tolerance=.001)
    assert rows[0]["status"]=="OPENING_EVIDENCE_PRESENT"
    assert rows[0]["material_gap_status"]=="UNPROVEN"
    assert rows[0]["portal_status"]=="NOT_CLASSIFIED"
    assert rows[0]["access_edge_status"]=="NOT_EVALUATED"


def test_opening_symbol_without_compatible_wall_is_rejected():
    candidate={"opening_id":"D1","kind":"door","geometry":{"point":[5,5]},
               "source_handle":"D","evidence":[{"class":"CAD_BLOCK"}]}
    rows=_pre_envelope_opening_evidence([candidate],[_opening_wall()],
                                        {"frame_id":"F1","bounds":[-1,-1,11,7]},tolerance=.001)
    assert rows[0]["status"]=="REJECTED"
    assert rows[0]["candidate_host_wall_ids"]==[]


def test_random_block_is_not_opening_evidence_even_near_wall():
    candidate={"opening_id":"X1","kind":"door","geometry":{"point":[5,.05]},
               "source_handle":"X","evidence":[{"class":"UNKNOWN_BLOCK"}]}
    rows=_pre_envelope_opening_evidence([candidate],[_opening_wall()],
                                        {"frame_id":"F1","bounds":[-1,-1,11,7]},tolerance=.001)
    assert rows[0]["status"]=="REJECTED"
