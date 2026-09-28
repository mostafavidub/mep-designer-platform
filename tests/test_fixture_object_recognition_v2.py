from copy import deepcopy

from cad_engine.fixture_recognition import recognize_fixtures_equipment


ROOM={"id":"R1","type":"toilet","status":"VERIFIED","polygon":[(0,0),(10,0),(10,10),(0,10)]}
FRAME={"frame_id":"F1","frame_type":"PRIMARY_FLOOR","bounds":[0,0,20,20]}


def architecture(inserts, *, rooms=None, frames=None, primitives=None, texts=None):
    return {"rooms": [ROOM] if rooms is None else rooms, "frames": [FRAME] if frames is None else frames,
            "all_inserts": inserts, "recognition_primitives": primitives or [], "all_texts": texts or []}


def insert(name="WC", point=(5,5), handle="10", **extra):
    return {"name":name,"point":point,"handle":handle,"root_insert_handle":handle,"layer":"0",
            "nested_path":[name],"nested_depth":0,"rotation":0,"scale":[1,1,1],"attributes":[],**extra}


def test_named_wc_is_confirmed_hosted_and_eligible():
    result=recognize_fixtures_equipment(architecture([insert()]))
    row=result["confirmed_objects"][0]
    assert row["type_candidate"]=="wc"
    assert row["hosting_status"]=="HOSTED_PHYSICAL_SPACE"
    assert row["authority"]=="ENGINEERING_ELIGIBLE"
    assert row["connection_points"]==[]
    assert len(result["detections"])==1


def test_unhosted_identity_is_preserved_but_not_engineering_eligible():
    result=recognize_fixtures_equipment(architecture([insert(point=(15,15))]))
    row=result["confirmed_objects"][0]
    assert row["hosting_status"]=="UNHOSTED"
    assert row["authority"]=="PREANALYSIS_EVIDENCE"
    assert not result["detections"]
    assert result["unhosted_confirmed"]==[row]


def test_room_labels_do_not_create_objects():
    texts=[{"text":"توالت","point":(5,5)},{"text":"حمام","point":(6,6)}]
    result=recognize_fixtures_equipment(architecture([insert("GENERIC")],texts=texts))
    assert not result["confirmed_objects"]
    assert result["object_candidates"][0]["type_candidate"] is None


def test_exact_attribute_can_identify_anonymous_block():
    item=insert("*U12",attributes=[{"tag":"TYPE","text":"SINK","handle":"A1"}])
    row=recognize_fixtures_equipment(architecture([item]))["confirmed_objects"][0]
    assert row["source_representation"]=="ANONYMOUS_BLOCK"
    assert row["type_candidate"]=="sink"
    assert "EXACT_OBJECT_ATTRIBUTE" in row["evidence_families"]


def test_nested_transform_and_provenance_are_preserved():
    item=insert("SINK",handle="11",root_insert_handle="ROOT",nested_depth=2,
                nested_path=["ROOT","KITCHEN","SINK"],rotation=90,scale=[-2,2,1])
    row=recognize_fixtures_equipment(architecture([item]))["confirmed_objects"][0]
    assert row["source_representation"]=="NESTED_BLOCK"
    assert row["root_insert_handle"]=="ROOT"
    assert row["nested_path"][-1]=="SINK"
    assert row["transform"]=={"rotation":90,"scale":[-2,2,1]}


def test_detail_or_legend_object_is_rejected():
    frame={"frame_id":"L","frame_type":"LEGEND","bounds":[0,0,20,20]}
    result=recognize_fixtures_equipment(architecture([insert()],frames=[frame]))
    assert result["rejected_objects"][0]["recognition_status"]=="REJECTED_NON_MEP"
    assert not result["detections"]


def test_exploded_object_specific_layer_plus_geometry_is_confirmed():
    primitives=[{"entity_type":"LINE","handle":"E1","layer":"FD","start":(4.9,5),"end":(5.1,5)},
                {"entity_type":"LINE","handle":"E2","layer":"FD","start":(5,4.9),"end":(5,5.1)}]
    result=recognize_fixtures_equipment(architecture([],primitives=primitives))
    row=result["confirmed_objects"][0]
    assert row["source_representation"]=="EXPLODED_GEOMETRY"
    assert row["type_candidate"]=="floor_drain"
    assert row["evidence_families"]==["OBJECT_SPECIFIC_LAYER","SOURCE_GEOMETRY"]


def test_same_file_signature_propagates_only_from_exact_sibling():
    named=insert("WC",point=(2,2),handle="A")
    anonymous=insert("*U7",point=(8,8),handle="B")
    primitives=[]
    for root,dx in (("A",0),("B",6)):
        primitives += [{"entity_type":"LINE","root_insert_handle":root,"start":(dx,0),"end":(dx+2,0)},
                       {"entity_type":"ARC","root_insert_handle":root,"points":[(dx,0),(dx+1,1),(dx+2,0)]}]
    result=recognize_fixtures_equipment(architecture([named,anonymous],primitives=primitives))
    propagated=next(r for r in result["confirmed_objects"] if r["block_definition"]=="*U7")
    assert propagated["type_candidate"]=="wc"
    assert propagated["evidence_families"]==["LABELED_OR_NAMED_SIBLING","REPEATED_GEOMETRY_SIGNATURE"]


def test_duplicate_nested_and_root_evidence_collapses_by_root_and_type():
    root=insert("WC",handle="A")
    nested=insert("WC",handle="B",root_insert_handle="A",nested_depth=1,nested_path=["WC","WC"])
    result=recognize_fixtures_equipment(architecture([root,nested]))
    assert len(result["confirmed_objects"])==1


def test_candidate_ids_and_results_are_deterministic():
    source=architecture([insert("WC"),insert("SINK",point=(7,7),handle="20")])
    first=recognize_fixtures_equipment(deepcopy(source)); second=recognize_fixtures_equipment(deepcopy(source))
    assert [r["candidate_id"] for r in first["object_candidates"]]==[r["candidate_id"] for r in second["object_candidates"]]
    for result in (first,second):
        for row in result["object_candidates"]: row.pop("classification_seconds",None)
        result["quality"].pop("runtime_seconds",None)
    assert first==second


def test_semantic_context_and_text_cannot_increase_authority():
    item=insert("GENERIC"); item["semantic_context"]=["TOILET"]
    result=recognize_fixtures_equipment(architecture([item],texts=[{"text":"WC","point":(5,5)}]))
    assert not result["confirmed_objects"]
    assert result["quality"]["vision_created_fixture_count"]==0
    assert result["quality"]["vision_created_network_node_count"]==0
