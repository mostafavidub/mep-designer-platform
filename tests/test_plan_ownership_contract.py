import ezdxf

from cad_engine.plan_isolation_acceptance import evaluate_plan_isolation
from cad_engine.plan_segmentation import _drawable_content_envelope


def test_unresolved_architectural_ownership_blocks_engineering():
    result=evaluate_plan_isolation({
        "architecture":{"plans":[],"quality":{"ambiguous_plan_ownership_count":1},
                        "level_ownership_contract":{"status":"FAIL"}},
        "topology":{"nodes":[],"edges":[]},"routing":{"routes":[]}})
    assert result["status"]=="FAIL"
    assert "architectural_level_ownership_unresolved" in result["errors"]
    assert "ambiguous_plan_ownership" in result["errors"]


def test_duplicate_non_typical_level_fingerprints_block_engineering():
    result=evaluate_plan_isolation({
        "architecture":{"plans":[],"quality":{},"level_ownership_contract":{"status":"PASS","plans":[
            {"plan_id":"P1","level":"GROUND","source_geometry_fingerprint":"same"},
            {"plan_id":"P2","level":"LEVEL-01","source_geometry_fingerprint":"same"}]}},
        "topology":{"nodes":[],"edges":[]},"routing":{"routes":[]}})
    assert result["status"]=="FAIL"
    assert "duplicate_architecture_across_levels:P1:P2" in result["errors"]


def test_plan_content_envelope_ignores_frame_and_remote_annotation_geometry():
    doc=ezdxf.new("R2010");msp=doc.modelspace();doc.layers.add("SHEET-FRAME");doc.layers.add("WALL")
    msp.add_lwpolyline([(0,0),(100,0),(100,70),(0,70)],close=True,dxfattribs={"layer":"SHEET-FRAME"})
    for x in range(20,61,5):msp.add_line((x,20),(x,50),dxfattribs={"layer":"WALL"})
    for y in range(20,51,5):msp.add_line((20,y),(60,y),dxfattribs={"layer":"WALL"})
    msp.add_circle((95,65),.2,dxfattribs={"layer":"WALL"})
    msp.add_text("REMOTE NOTE",dxfattribs={"layer":"WALL","height":1}).set_placement((98,68))
    result=_drawable_content_envelope(list(msp),(0,0,100,70))
    assert result["status"]=="PASS",result
    assert result["bounds"][0]>=19 and result["bounds"][2]<=62
    assert result["bounds"][1]>=19 and result["bounds"][3]<=52


def test_missing_authoritative_content_envelope_blocks_isolation():
    result=evaluate_plan_isolation({
        "architecture":{"plans":[{"plan_id":"P1","bounds":[0,0,10,10]}],
                        "quality":{"invalid_plan_content_envelope_count":1},
                        "level_ownership_contract":{"status":"FAIL","plans":[]}},
        "topology":{"nodes":[],"edges":[]},"routing":{"routes":[]}})
    assert result["status"]=="FAIL"
    assert "invalid_plan_content_envelope" in result["errors"]
