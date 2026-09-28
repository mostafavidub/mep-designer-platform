from copy import deepcopy

import pytest

from cad_engine.architectural_vision_recovery import RenderTransform, validate_global_payload
from cad_engine.hybrid_architectural_recovery import (
    AUTHORITY_CAD, AUTHORITY_HUMAN, AUTHORITY_INFERRED, AUTHORITY_UNRESOLVED,
    build_boundary_evidence_graph, construct_hybrid_topology,
    map_hypotheses_to_cad, validate_human_decision,
)


def _analysis(*, separator=True, site=True):
    boundaries=[{"boundary_id":"B-SHELL","geometry_px":[[0,100],[100,100],[100,0],[0,0],[0,100]],
                 "role":"EXTERIOR_SHELL","adjacent_regions":["R-IN","R-YARD"],
                 "evidence":["visible perimeter"],"confidence":.94,"uncertainties":[]}]
    if separator:
        boundaries.append({"boundary_id":"B-SEP","geometry_px":[[50,100],[50,0]],
                           "role":"INTERIOR_SEPARATOR","adjacent_regions":["R-A","R-B"],
                           "evidence":["visible separator"],"confidence":.91,"uncertainties":[]})
    roles=[{"region_id":"R-IN","polygon_px":[[0,100],[100,100],[100,0],[0,0]],
            "role":"BUILDING_INTERIOR","evidence":["plan context"],"confidence":.9,"uncertainties":[]}]
    if site:
        roles.append({"region_id":"R-YARD","polygon_px":[[100,100],[120,100],[120,0],[100,0]],
                      "role":"SITE_EXTERIOR","evidence":["yard label"],"confidence":.9,"uncertainties":[]})
    return {"frame_id":"F1","building_shells":[{"shell_id":"SH1","outer_ring_px":[[0,100],[100,100],[100,0],[0,0]],
             "inner_rings_px":[],"evidence":["visible shell"],"confidence":.95,"uncertainties":[]}],
            "boundary_hypotheses":boundaries,"region_roles":roles,
            "physical_spaces":[{"vision_space_id":"V1","polygon_px":[[0,100],[100,100],[100,0],[0,0]],
              "semantic_candidates":[{"type":"open_plan","confidence":.95}],"objects_seen":["kitchen"],
              "labels_seen":["living"],"boundary_evidence":["shell"],"uncertainties":[]}],
            "functional_zones":[{"zone_id":"Z1","geometry_px":[[0,100],[50,100],[50,0],[0,0]],
              "semantic_type":"living","evidence":["furniture"],"confidence":.9}],
            "doors":[],"windows":[],"open_passages":[],"stairs":[],"shafts":[],
            "suspected_false_boundaries":[],"suspected_missing_boundaries":[],"unresolved_regions":[]}


def _mapped(analysis=None):
    transform=RenderTransform(0,0,10,10,100,100,0)
    return map_hypotheses_to_cad(analysis or _analysis(),transform,source_sha256="a"*64,
        render_hash="render",provider="deepseek",model="vision",prompt_version="p1",schema_version="s2")


def _segment(a,b,identity="S1"):
    return {"segment_id":identity,"frame_id":"F1","geometry":[a,b],"status":"ACCEPTED","source_handle":identity}


def _fuse(mapped,segments=(),texts=(),dimensions=(),decisions=()):
    evidence=build_boundary_evidence_graph(mapped=mapped,segments=list(segments),texts=list(texts),
        dimensions=list(dimensions),source_sha256="a"*64,tolerance=.01)
    topology=construct_hybrid_topology(mapped=mapped,boundary_analysis=evidence,
        source_sha256="a"*64,tolerance=.01,human_decisions=list(decisions))
    return evidence,topology


def test_legacy_payload_is_readable_but_has_no_boundary_authority():
    payload=_analysis(); payload={key:value for key,value in payload.items()
                                 if key not in {"building_shells","boundary_hypotheses","region_roles"}}
    result=validate_global_payload(payload,frame_id="F1")
    assert result["building_shells"] == [] and result["boundary_hypotheses"] == []


def test_mapping_preserves_pixel_cad_and_provenance():
    mapped=_mapped()
    assert mapped["building_shells"][0]["outer_ring_cad"][2] == [10.0,10.0]
    assert mapped["provenance"]["render_hash"] == "render"
    assert mapped["boundaries" if "boundaries" in mapped else "boundary_hypotheses"][0]["provenance"]["status"] == "VISION_HYPOTHESIS"


def test_complete_cad_boundary_is_cad_confirmed_physical_wall():
    mapped=_mapped(_analysis(separator=False))
    shell=[_segment([0,0],[10,0],"A"),_segment([10,0],[10,10],"B"),
           _segment([10,10],[0,10],"C"),_segment([0,10],[0,0],"D")]
    evidence,_=_fuse(mapped,shell)
    assert all(row["authority"]==AUTHORITY_CAD for row in evidence["boundaries"])
    assert all(row["material_geometry"]=="PHYSICAL_WALL" for row in evidence["boundaries"])


def test_missing_cad_boundary_with_site_evidence_can_be_inferred():
    evidence,_=_fuse(_mapped(_analysis(separator=False)))
    assert all(row["authority"]==AUTHORITY_INFERRED for row in evidence["boundaries"])
    assert all(row["material_geometry"]=="NONE" for row in evidence["boundaries"])


def test_vision_only_material_boundary_requires_human():
    mapped=_mapped(_analysis(site=False))
    mapped["boundary_hypotheses"]=[row for row in mapped["boundary_hypotheses"] if row["boundary_id"]=="B-SEP"]
    evidence,_=_fuse(mapped)
    assert evidence["boundaries"][0]["authority"]==AUTHORITY_UNRESOLVED


def test_strong_crossing_cad_wall_rejects_vision_boundary():
    mapped=_mapped(_analysis(site=False))
    mapped["boundary_hypotheses"]=[row for row in mapped["boundary_hypotheses"] if row["boundary_id"]=="B-SEP"]
    evidence,_=_fuse(mapped,[_segment([0,5],[10,5])])
    row=evidence["boundaries"][0]
    assert "STRONG_CAD_WALL_CONFLICT" in row["conflict_classes"]
    assert row["authority"]==AUTHORITY_UNRESOLVED


def test_no_cad_evidence_is_not_itself_a_conflict():
    evidence,_=_fuse(_mapped(_analysis(site=False)))
    assert all("NO_CAD_EVIDENCE" not in row["conflict_classes"] for row in evidence["boundaries"])


def test_open_plan_zone_does_not_create_physical_boundary():
    _,topology=_fuse(_mapped(_analysis(separator=False)))
    assert len(topology["physical_spaces"])==1
    assert topology["functional_zones"][0]["creates_boundary"] is False


def test_human_boundary_is_topology_only_never_material_wall():
    mapped=_mapped(_analysis(site=False))
    mapped["boundary_hypotheses"]=[row for row in mapped["boundary_hypotheses"] if row["boundary_id"]=="B-SEP"]
    evidence,_=_fuse(mapped)
    decision={"answer":"YES","affected_hypothesis_ids":["B-SEP"]}
    topology=construct_hybrid_topology(mapped=mapped,boundary_analysis=evidence,
        source_sha256="a"*64,tolerance=.01,human_decisions=[decision])
    row=topology["boundaries"][0]
    assert row["authority"]==AUTHORITY_HUMAN and row["material_geometry"]=="NONE"


def test_stale_human_confirmation_is_invalidated():
    decision={"invalidation_inputs":{"source_sha256":"old","frame_id":"F1",
              "hypothesis_geometry_hash":"g","question_version":"q1"}}
    result=validate_human_decision(decision,source_sha256="new",frame_id="F1",
        hypothesis_geometry_hash="g",question_version="q1")
    assert result=={"valid":False,"invalidated_by":["source_sha256"],"authority":AUTHORITY_UNRESOLVED}


def test_vision_only_edge_never_becomes_routing_obstacle():
    evidence,_=_fuse(_mapped(_analysis(site=False)))
    assert all(row["physical_barrier"]=="PHYSICAL_BARRIER_UNKNOWN"
               for row in evidence["boundaries"] if row["authority"]!=AUTHORITY_CAD)


def test_shell_reports_authority_composition_and_traceability():
    _,topology=_fuse(_mapped(_analysis(separator=False)))
    shell=topology["building_envelopes"][0]
    assert sum(shell["authority_composition"].values())==pytest.approx(1)
    assert shell["vision_hypothesis_ids"]==["SH1"]


def test_hybrid_space_can_exist_without_legacy_cad_space():
    _,topology=_fuse(_mapped(_analysis(separator=False)))
    assert topology["physical_spaces"]
    assert topology["trigger"]=="SOURCE_ARCHITECTURE_GEOMETRY_INSUFFICIENT"


def test_overlap_fails_closed():
    analysis=_analysis(separator=False)
    duplicate=deepcopy(analysis["physical_spaces"][0]); duplicate["vision_space_id"]="V2"
    analysis["physical_spaces"].append(duplicate)
    _,topology=_fuse(_mapped(analysis))
    assert topology["overlap_area"]>0 and topology["status"]=="CONFLICT"


def test_high_vision_confidence_alone_is_insufficient():
    analysis=_analysis(site=False); analysis["boundary_hypotheses"][1]["confidence"]=1.0
    mapped=_mapped(analysis); mapped["boundary_hypotheses"]=[mapped["boundary_hypotheses"][1]]
    evidence,_=_fuse(mapped)
    assert evidence["boundaries"][0]["authority"]==AUTHORITY_UNRESOLVED


def test_evidence_graph_keeps_support_and_conflict_edges():
    evidence,_=_fuse(_mapped(_analysis(separator=False)))
    graph=evidence["evidence_graph"]
    assert any(edge["relation"]=="SUPPORTS" for edge in graph["edges"])
    assert graph["source_sha256"]=="a"*64


def test_targeted_question_uses_small_yes_no_unknown_unit():
    mapped=_mapped(_analysis(site=False)); mapped["building_shells"]=[]
    mapped["boundary_hypotheses"]=[mapped["boundary_hypotheses"][1]]
    _,topology=_fuse(mapped)
    question=topology["human_questions"][0]
    assert question["options"]==["YES","NO","UNKNOWN"]
    assert question["geometry"]


def test_window_never_creates_access_edge():
    analysis=_analysis(separator=False)
    analysis["windows"]=[{"geometry_px":[[0,60],[0,40]],"connects":["V1","EXTERIOR"],
                          "evidence":["facade opening"],"confidence":.95}]
    _,topology=_fuse(_mapped(analysis),[_segment([0,0],[0,10])])
    assert topology["portals"][0]["kind"]=="WINDOW"
    assert topology["access_graph"]["edges"]==[]


def test_supported_door_creates_access_edge_after_topology():
    analysis=_analysis(separator=False)
    analysis["doors"]=[{"geometry_px":[[0,60],[0,40]],"connects":["V1","EXTERIOR"],
                        "evidence":["leaf and opening"],"confidence":.95}]
    _,topology=_fuse(_mapped(analysis),[_segment([0,0],[0,10])])
    assert topology["portals"][0]["authority"]=="CAD_SUPPORTED_PORTAL"
    assert len(topology["access_graph"]["edges"])==1
