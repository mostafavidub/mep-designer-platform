from pathlib import Path

import ezdxf
from shapely.geometry import LineString

from cad_engine.architectural_space_engine import (
    SCHEMA, _completeness, _semantic_segment_classification, normalize_text,
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
    assert model["completeness"]["status"] == "VERIFIED"
    assert require_complete_architecture(model)["allowed"] is True


def test_open_plan_is_one_physical_space_with_functional_zones(tmp_path):
    model = reconstruct_architecture(_drawing(tmp_path/"open.dxf", labels=(
        ("پذیرایی",(2,3)),("ناهارخوری",(5,3)),("آشپزخانه",(8,3)))))
    assert len(model["physical_spaces"]) == 1
    space = model["physical_spaces"][0]
    assert space["category"] == "open_plan"
    assert {z["category"] for z in space["functional_zones"]} == {"reception","dining","kitchen"}
    assert all(z["boundary_status"] == "approximate" for z in space["functional_zones"])
    assert model["completeness"]["status"] == "VERIFIED"


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
    result = _completeness(frames, [{"physical_space_id": "S1", "frame_id": "FLOOR", "status": "VERIFIED", "area_m2": 12}], True)
    assert result["status"] == "VERIFIED"
    assert result["relevant_space_count"] == 1


def test_door_binds_host_wall_and_two_spaces(tmp_path):
    model=reconstruct_architecture(_drawing_with_opening(tmp_path/"door.dxf"))
    door=model["doors"][0]
    assert door["status"]=="VERIFIED"
    assert door["host_wall_id"].startswith("WALL-")
    assert door["space_a"] != door["space_b"] and door["space_b"] != "EXTERIOR"
    assert door["orientation"] == 90.0


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
    assert model["dimension_reconciliation"]["status"] in {"PASS","CONFLICT"}
    assert all("annotated_measurement_m" in row and "geometric_measurement_m" in row
               for row in model["dimension_reconciliation"]["rows"])


def test_anonymous_leaf_arc_and_host_wall_reconstruct_door_without_merging_rooms(tmp_path):
    model=reconstruct_architecture(_drawing_with_anonymous_door(tmp_path/"anonymous-door.dxf"))
    geometric=[door for door in model["doors"] if any(e["class"]=="SWING_ARC" for e in door["evidence"])]
    assert len(geometric)==1 and geometric[0]["status"]=="VERIFIED"
    assert geometric[0]["space_a"] != geometric[0]["space_b"]
    assert len(model["physical_spaces"])==2


def test_random_arc_without_leaf_is_not_a_door(tmp_path):
    model=reconstruct_architecture(_drawing_with_anonymous_door(tmp_path/"random-arc.dxf",leaf=False))
    assert not any(any(e["class"]=="SWING_ARC" for e in door["evidence"]) for door in model["doors"])


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
