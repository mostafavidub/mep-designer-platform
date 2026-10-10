import json

import ezdxf
import pytest
from shapely.geometry import LineString

from cad_engine.architectural_space_engine import (
    _filter_wall_solid_cells,
    _recover_supported_partitions,
    _semantic_segment_classification,
    reconstruct_architecture,
)
from cad_engine.pre_topology_object_classifier import (
    OBJECT_CLASSES,
    classify_source_record,
    excludes_from_wall_admission,
    standardize_source_records,
    repeated_compact_column_handles,
)
from cad_engine.architecture_structural_obstacles import project_structural_obstacles
from cad_engine.architectural_space_engine import recognition_svg


@pytest.mark.parametrize(
    "record,expected,role",
    [
        ({"entity_type":"LWPOLYLINE","layer":"A-SHEET-BORDER"}, "SHEET_FRAME", "REFERENCE_ONLY"),
        ({"entity_type":"DIMENSION","layer":"0"}, "DIMENSION_CHAIN", "NON_TOPOLOGICAL"),
        ({"entity_type":"LINE","layer":"A-GRID-1a"}, "GRID_AXIS", "REFERENCE_ONLY"),
        ({"entity_type":"LWPOLYLINE","layer":"S-COLUMN"}, "COLUMN", "OBSTACLE_EVIDENCE_ONLY"),
        ({"entity_type":"LINE","layer":"A-STAIR-TREAD"}, "STAIR_ASSEMBLY", "OBSTACLE_EVIDENCE_ONLY"),
        ({"entity_type":"LINE","source_block":"WINDOW-120"}, "WINDOW_ASSEMBLY", "OPENING_EVIDENCE_ONLY"),
        ({"entity_type":"ARC","source_block":"DOUBLE-DOOR"}, "DOUBLE_DOOR_ASSEMBLY", "OPENING_EVIDENCE_ONLY"),
        ({"entity_type":"LINE","layer":"A-OPEN-PASSAGE"}, "OPEN_PASSAGE", "OPENING_EVIDENCE_ONLY"),
        ({"entity_type":"CIRCLE","source_block":"DINING-TABLE-8"}, "DINING_TABLE_ASSEMBLY", "NON_TOPOLOGICAL"),
        ({"entity_type":"SPLINE","source_block":"VEHICLE-SEDAN"}, "VEHICLE", "NON_TOPOLOGICAL"),
        ({"entity_type":"LWPOLYLINE","layer":"PARKING-BAY"}, "PARKING_BAY", "NON_TOPOLOGICAL"),
        ({"entity_type":"LINE","source_block":"SECTION-CUT-A-A"}, "SECTION_CUT", "REFERENCE_ONLY"),
        ({"entity_type":"HATCH","layer":"0"}, "GENERIC_NON_ENCLOSURE_OBJECT", "NON_TOPOLOGICAL"),
        ({"entity_type":"LINE","layer":"A-WALL"}, "ENCLOSURE_CANDIDATE", "ENCLOSURE_CANDIDATE_ONLY"),
        ({"entity_type":"LINE","layer":"0"}, "UNKNOWN", "UNRESOLVED"),
    ],
)
def test_canonical_classes_domains_and_roles(record, expected, role):
    result = classify_source_record(record)
    assert result["object_class"] == expected
    assert result["object_class"] in OBJECT_CLASSES
    assert result["topology_role"] == role
    assert result["enclosure_authority"] == "NONE"
    assert result["positive_evidence"] or result["negative_evidence"]


def test_ids_and_output_are_deterministic_and_source_order_independent():
    records = [
        {"handle":"B", "entity_type":"LINE", "layer":"GRID-1b"},
        {"handle":"A", "entity_type":"LINE", "layer":"GRID-1a"},
    ]
    left = standardize_source_records(records)
    right = standardize_source_records(list(reversed(records)))
    assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)
    assert len({row["classification_id"] for row in left}) == 2


def test_non_enclosure_semantics_override_wall_like_geometry():
    lines = [LineString([(0,0),(0,5)]), LineString([(0.2,0),(0.2,5)]),
             LineString([(1,0),(1,5)]), LineString([(1.2,0),(1.2,5)]),
             LineString([(2,0),(2,5)]), LineString([(2.2,0),(2.2,5)])]
    metas = [{"handle":str(i), "layer":"S-COLUMN", "entity_type":"LINE", "closed":False}
             for i in range(len(lines))]
    records, accepted = _semantic_segment_classification(lines, metas, 1.0, .001)
    assert accepted == []
    assert {row["semantic_class"] for row in records} == {"COLUMN"}
    assert all(row["status"] == "REJECTED" for row in records)


def test_partition_recovery_cannot_readmit_hard_excluded_columns():
    shell=[LineString([(0,0),(6,0)]),LineString([(6,0),(6,6)]),
           LineString([(6,6),(0,6)]),LineString([(0,6),(0,0)])]
    columns=[]
    for x in (1,2,3):
        points=[(x,2),(x+.4,2),(x+.4,2.4),(x,2.4),(x,2)]
        columns.extend(LineString([a,b]) for a,b in zip(points,points[1:]))
    lines=shell+columns
    metas=[{"handle":f"W{i}","layer":"A-WALL","entity_type":"LINE","closed":False} for i in range(4)]
    metas.extend({"handle":f"C{i//4}","layer":"0","entity_type":"LINE","closed":True} for i in range(12))
    records,seeds=_semantic_segment_classification(lines,metas,1.0,.001)
    accepted,_,_=_recover_supported_partitions(seeds,records,{"bounds":[0,0,6,6]},.001,{"texts":[]},1.0)
    assert len(accepted)==4
    rejected=[row for row in records if row["semantic_class"]=="COLUMN"]
    assert len(rejected)==12
    assert all(row["status"]=="REJECTED" and not row.get("admission_trace") for row in rejected)


def test_wall_material_overlap_rejects_solid_cell_but_keeps_adjacent_room():
    wall_cell=LineString([(0,0),(4,0)]).buffer(.1,cap_style=2)
    room=LineString([(0,2),(4,2)]).buffer(1,cap_style=2)
    wall={"thickness":.2,"wall_solid":{"axis_origin":[0,0],"axis_direction":[1,0],
          "occupied_intervals":[[0,4]]}}
    accepted,rejected=_filter_wall_solid_cells([wall_cell,room],[],{"texts":[],"objects":[]},1.0,
                                               canonical_walls=[wall],tolerance=.001)
    assert accepted==[room]
    assert rejected[0]["reason"]=="WALL_MATERIAL_FOOTPRINT"


def test_opening_and_reference_roles_are_never_wall_admitted():
    for layer in ("A-WINDOW", "A-DOOR", "A-GRID-1", "A-STAIR", "A-SECTION-CUT"):
        assert excludes_from_wall_admission(classify_source_record({"entity_type":"LINE", "layer":layer}))


def test_repeated_compact_closed_footprints_are_columns_but_one_square_is_not():
    lines, metas = [], []
    for index, x in enumerate((0, 2, 4)):
        points=[(x,0),(x+.4,0),(x+.4,.4),(x,.4),(x,0)]
        for a,b in zip(points,points[1:]):
            lines.append(LineString([a,b])); metas.append({"handle":f"C{index}","closed":True})
    points=[(8,0),(8.6,0),(8.6,.3),(8,.3),(8,0)]
    for a,b in zip(points,points[1:]):
        lines.append(LineString([a,b])); metas.append({"handle":"RANDOM","closed":True})
    assert repeated_compact_column_handles(lines,metas,1.0) == {"C0","C1","C2"}


def test_column_footprint_does_not_create_a_physical_space(tmp_path):
    path = tmp_path / "column-inside-room.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    for layer in ("A-WALL", "S-COLUMN"):
        doc.layers.add(layer)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0,0),(10,0),(10,8),(0,8)], close=True, dxfattribs={"layer":"A-WALL"})
    msp.add_lwpolyline([(4,3),(5,3),(5,4),(4,4)], close=True, dxfattribs={"layer":"S-COLUMN"})
    doc.saveas(path)
    model = reconstruct_architecture(path)
    assert len(model["physical_spaces"]) == 1
    column_segments = [row for row in model["architectural_segments"] if row["semantic_class"] == "COLUMN"]
    assert len(column_segments) == 4
    assert all(row["status"] == "REJECTED" for row in column_segments)
    assert any(row["object_class"] == "COLUMN" for row in model["pre_topology_object_standardization"]["items"])
    assert model["structural_obstacles"]["items"] == []


def test_repeated_native_columns_are_persistent_but_not_legacy_routing_authority(tmp_path):
    path = tmp_path / "repeated-columns.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    msp.add_lwpolyline([(0,0),(8,0),(8,6),(0,6)], close=True, dxfattribs={"layer":"A-WALL"})
    for x in (1, 3, 5):
        msp.add_lwpolyline([(x,1),(x+.4,1),(x+.4,1.4),(x,1.4)], close=True)
    doc.saveas(path)
    model = reconstruct_architecture(path)
    rows = model["structural_obstacles"]["items"]
    assert len(rows) == 3
    assert len({row["structural_obstacle_id"] for row in rows}) == 3
    assert all(row["footprint"] == row["world_coordinates"] for row in rows)
    assert all(row["source_occurrence_id"] and row["source_geometry_fingerprint"] for row in rows)
    assert all(not any(row["authority"][key] for key in
                       ("material_geometry", "wall", "portal", "access", "routing", "release", "envelope"))
               for row in rows)
    assert model["columns"] == []
    assert model["recognition_preview_svg"].count('data-obstacle-type="COLUMN"') == 3
    assert all(segment["status"] == "REJECTED" for segment in model["architectural_segments"]
               if segment["semantic_class"] == "COLUMN")


def test_column_identity_uses_occurrence_and_orientation_normalized_geometry():
    base = {"object_class":"COLUMN", "topology_role":"OBSTACLE_EVIDENCE_ONLY",
            "evidence":["REPEATED_COMPACT_CLOSED_FOOTPRINT"], "closed":True,
            "source_handle":"10", "entity_type":"LWPOLYLINE", "source_layer":"0",
            "source_block_path":["C"], "source_insert_handle":"I", "source_transform":[1,0,0,1,0,0],
            "frame_ids":["F1"]}
    ring = [[0,0],[.4,0],[.4,.4],[0,.4]]
    diagnostics = {"items":[{**base,"source_occurrence_id":"SRC-1111111111111111","geometry":ring},
                              {**base,"source_occurrence_id":"SRC-2222222222222222",
                               "geometry":[[2,0],[2.4,0],[2.4,.4],[2,.4]]}]}
    frames = [{"frame_id":"F1","bounds":[-1,-1,4,2],"level_candidate":"L1"}]
    first = project_structural_obstacles(diagnostics, frames, "a"*64)
    reversed_diagnostics = {"items":list(reversed(diagnostics["items"]))}
    reversed_diagnostics["items"][1] = {**reversed_diagnostics["items"][1], "geometry":list(reversed(ring))}
    second = project_structural_obstacles(reversed_diagnostics, frames, "a"*64)
    assert first == second
    assert len({row["structural_obstacle_id"] for row in first["items"]}) == 2


def test_column_projection_excludes_reference_unassigned_and_multiply_assigned_frames():
    base = {"object_class":"COLUMN", "topology_role":"OBSTACLE_EVIDENCE_ONLY",
            "evidence":["REPEATED_COMPACT_CLOSED_FOOTPRINT"], "closed":True,
            "entity_type":"LWPOLYLINE", "source_layer":"S-COLUMN",
            "source_block_path":[], "source_transform":[1,0,0,1,0,0],
            "geometry":[[0,0],[.4,0],[.4,.4],[0,.4]]}
    diagnostics = {"items":[
        {**base,"source_handle":"A","source_occurrence_id":"SRC-A","frame_ids":["F-ARCH"]},
        {**base,"source_handle":"R","source_occurrence_id":"SRC-R","frame_ids":["F-REF"]},
        {**base,"source_handle":"U","source_occurrence_id":"SRC-U","frame_ids":[]},
        {**base,"source_handle":"M","source_occurrence_id":"SRC-M","frame_ids":["F-ARCH","F-REF"]},
    ]}
    frames = [
        {"frame_id":"F-ARCH","bounds":[-1,-1,1,1],"status":"VERIFIED",
         "scope_relevance":"MECHANICAL_AUTHORITY"},
        {"frame_id":"F-REF","bounds":[2,-1,4,1],"status":"REFERENCE_ONLY",
         "scope_relevance":"REFERENCE_ONLY"},
    ]
    result = project_structural_obstacles(diagnostics, frames, "a"*64)
    assert [row["source_handle"] for row in result["items"]] == ["A"]
    assert result["projection_diagnostics"]["excluded_counts"] == {
        "reference_only":1, "unassigned":1, "multiply_assigned":1, "invalid_geometry":0}


def test_recognition_svg_union_viewbox_keeps_columns_from_all_frames_visible():
    model = {"frames":[{"frame_id":"F1","bounds":[0,0,10,10]},
                       {"frame_id":"F2","bounds":[100,50,120,70]}],
             "physical_spaces":[],
             "structural_obstacles":{"items":[
                 {"frame_id":"F1","footprint":[[1,1],[2,1],[2,2],[1,2]]},
                 {"frame_id":"F2","footprint":[[101,51],[102,51],[102,52],[101,52]]},
             ]}}
    svg = recognition_svg(model)
    assert 'viewBox="0 -70 120 70"' in svg
    assert svg.count('data-obstacle-type="COLUMN"') == 2
    assert "101,-51 102,-51 102,-52 101,-52" in svg
