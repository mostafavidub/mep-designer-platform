import hashlib
from pathlib import Path

import pytest

from cad_engine.local_visual_context import (
    build_candidate_neighborhoods, build_context_pack, cad_to_view,
    candidate_adjacency, provider_target_graph, render_local_svg, view_to_cad,
)


def _graph():
    regions=[]
    for i,(x,label) in enumerate(((0,"ROOM"),(2,""),(8,"FAR"))):
        regions.append({"region_id":f"R{i}","polygon":[[x,0],[x+2,0],[x+2,2],[x,2],[x,0]],
            "centroid":[x+1,1],"exact_text_evidence":([{"source_handle":f"T{i}","text":label}] if label else []),
            "object_evidence":[]})
    return {"frame_id":"F","source_sha256":"a"*64,"frame_bounds":[0,0,10,2],"regions":regions,
        "boundaries":[{"boundary_id":"B01","adjacent_region_ids":["R0","R1"]}],"bridges":[],
        "preauthority":{"source_segments":[{"geometry":[[0,0],[4,0]],"authority_tier":"HARD_ACCEPTED_ARCHITECTURAL"}]}}


def test_local_pack_contains_target_neighbor_and_excludes_distant():
    graph=_graph(); pack=build_context_pack(graph,["R0"],graph_hash="g")
    assert pack["target_region_ids"]==["R0"] and pack["adjacent_ids"]==["R1"]
    assert "R2" not in pack["candidate_ids"] and pack["included_label_handles"]==["T0"]


def test_neighborhoods_are_stable_and_topological():
    graph=_graph(); first=build_candidate_neighborhoods(graph,["R2","R1","R0"])
    second=build_candidate_neighborhoods(graph,["R0","R1","R2"])
    assert first==second and len(first)==2


def test_crop_transform_is_reversible():
    bounds=[-1,-2,11,8]; point=[3.25,4.75]
    view=cad_to_view(point,bounds,1200,900); restored=view_to_cad(view,bounds,1200,900)
    assert restored==pytest.approx(point)


def test_local_render_is_stable_keeps_id_and_avoids_all_ids(tmp_path):
    graph=_graph(); pack=build_context_pack(graph,["R0"],graph_hash="g")
    one=render_local_svg(graph,pack,tmp_path/"one.svg"); two=render_local_svg(graph,pack,tmp_path/"two.svg")
    assert one["render_hash"]==two["render_hash"]
    text=(tmp_path/"one.svg").read_text(); assert "R2" not in text and "ROOM" in text


def test_provider_graph_contains_targets_only_and_preserves_ids():
    graph=_graph(); subset=provider_target_graph(graph,["R0"])
    assert [row["region_id"] for row in subset["regions"]]==["R0"]
    assert subset["boundaries"]==[] and subset["bridges"]==[]
    with pytest.raises(ValueError): provider_target_graph(graph,["INVENTED"])


def test_no_private_source_is_embedded_in_contract(tmp_path):
    graph=_graph(); pack=build_context_pack(graph,["R0"],graph_hash="g")
    assert set(pack) >= {"source_sha256","graph_hash","context_pack_id"}
    assert not any(key in pack for key in ("source_path","dxf_bytes","project_name"))
