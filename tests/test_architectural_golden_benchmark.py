from tools.architectural_golden_benchmark import score
from tools.architectural_golden_annotation_package import build
from tools.architectural_golden_validate import validate

import ezdxf


def _space(identifier, polygon, category="bedroom", adjacent=()):
    return {"physical_space_id":identifier,"frame_id":"FRAME-G","polygon":polygon,"interior_rings":[],
            "category":category,"adjacent_space_ids":list(adjacent)}


def _golden(status="APPROVED"):
    return {"review_status":status,"frame":{"runtime_frame_id":"FRAME-G"},"space_match_iou":.5,
            "building_envelope":{"outer_ring":[[0,0],[4,0],[4,2],[0,2],[0,0]],"interior_voids":[]},
            "spaces":[
                {"golden_space_id":"G1","polygon":[[0,0],[2,0],[2,2],[0,2],[0,0]],"category":"bedroom"},
                {"golden_space_id":"G2","polygon":[[2,0],[4,0],[4,2],[2,2],[2,0]],"category":"kitchen"},
            ],"adjacency":[["G1","G2"]],"portals":[]}


def test_unreviewed_golden_refuses_to_score():
    assert score(_golden("REVIEWED"),{"physical_spaces":[]})["status"]=="INCOMPLETE_GOLDEN"


def test_exact_golden_match_scores_complete_topology():
    model={"physical_spaces":[
        _space("S1",[[0,0],[2,0],[2,2],[0,2],[0,0]],adjacent=("S2",)),
        _space("S2",[[2,0],[4,0],[4,2],[2,2],[2,0]],"kitchen",("S1",)),
    ],"openings":[]}
    report=score(_golden(),model)
    assert report["space_precision"]==report["space_recall"]==1
    assert report["mean_matched_iou"]==report["minimum_matched_iou"]==1
    assert report["semantic_accuracy"]==report["adjacency_accuracy"]==1
    assert report["phantom_space_count"]==report["missing_space_count"]==0


def test_phantom_and_missing_spaces_are_not_hidden_by_aggregate_area():
    model={"physical_spaces":[_space("S1",[[0,0],[2,0],[2,2],[0,2],[0,0]])],"openings":[]}
    report=score(_golden(),model)
    assert report["space_recall"]==.5
    assert report["missing_space_count"]==1
    assert report["unexplained_interior_area"]==4


def test_annotation_package_is_source_only_and_pending(tmp_path):
    source=tmp_path/"source.dxf"; doc=ezdxf.new("R2013"); doc.header["$INSUNITS"]=6
    doc.modelspace().add_lwpolyline([(0,0),(4,0),(4,2),(0,2)],close=True); doc.saveas(source)
    svg,golden,manifest,viewer,instructions=build(source,"case","GROUND",[0,0,4,2],"FRAME-G")
    assert "<polyline" in svg
    assert golden["review_status"]=="DRAFT"
    assert golden["spaces"]==[] and golden["portals"]==[]
    assert golden["review"]["runtime_output_visible_during_annotation"] is False
    assert "RAW DXF ONLY" in viewer and "current Planha" not in viewer
    assert manifest["excluded_runtime_material"] is True
    assert "UNKNOWN" in instructions
    report=validate(golden,source.read_bytes())
    assert report["status"]=="PASS" and report["official_scoring_enabled"] is False


def test_validator_rejects_self_intersection_and_unknown_references():
    golden=_golden(); golden.update({"schema":"architectural-topology-golden/1.0","case_id":"destructive","source_sha256":"0"*64,
        "functional_zones":[],"geometric_adjacency":[["G1","MISSING"]],"access_connectivity":[],
        "review":{"method":"INDEPENDENT_SOURCE_ARCHITECTURE_REVIEW","annotator":"A","annotation_date":"2026-09-26",
                  "reviewer":"B","reviewed_at":"2026-09-26","approved_at":"2026-09-26","runtime_output_visible_during_annotation":False}})
    golden["spaces"][0]["polygon"]=[[0,0],[2,2],[0,2],[2,0],[0,0]]
    report=validate(golden)
    assert report["status"]=="FAIL"
    assert any(error.startswith("space_polygon_invalid:G1") for error in report["errors"])
    assert any(error.startswith("invalid_geometric_adjacency") for error in report["errors"])
