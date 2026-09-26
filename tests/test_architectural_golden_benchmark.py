from tools.architectural_golden_benchmark import score
from tools.architectural_golden_annotation_package import build

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
    assert score(_golden("PENDING"),{"physical_spaces":[]})["status"]=="INCOMPLETE_GOLDEN"


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
    svg,golden=build(source,"case","GROUND",[0,0,4,2],"FRAME-G")
    assert "<polyline" in svg
    assert golden["review_status"]=="PENDING"
    assert golden["spaces"]==[] and golden["portals"]==[]
    assert golden["review"]["runtime_output_visible_during_annotation"] is False
