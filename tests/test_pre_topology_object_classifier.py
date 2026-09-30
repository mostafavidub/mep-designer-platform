import json

import ezdxf
import pytest
from shapely.geometry import LineString

from cad_engine.architectural_space_engine import _semantic_segment_classification, reconstruct_architecture
from cad_engine.pre_topology_object_classifier import (
    OBJECT_CLASSES,
    classify_source_record,
    excludes_from_wall_admission,
    standardize_source_records,
    repeated_compact_column_handles,
)


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
