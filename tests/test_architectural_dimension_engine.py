import math

from cad_engine.dimensioning.architecture import build_architectural_dimension_network
from cad_engine.dimensioning.chains import build_dimension_chain, closure_check
from cad_engine.dimensioning.coordinate_frames import detect_local_coordinate_frames
from cad_engine.dimensioning.determinacy import analyze_overdimensioning
from cad_engine.dimensioning.references import build_semantic_references
from cad_engine.dimensioning.specialists.site import site_intents


def _wall(wid, a, b, *, exterior=False, basis="FINISH", zone_id=None):
    return {
        "id": wid, "start": a, "end": b, "face_basis": basis,
        "exterior": exterior, "zone_id": zone_id,
    }


def _simple_plan():
    return {
        "walls": [
            _wall("W-L",(0,0),(0,8),exterior=True),
            _wall("W-R",(12,0),(12,8),exterior=True),
            _wall("W-B",(0,0),(12,0),exterior=True),
            _wall("W-T",(0,8),(12,8),exterior=True),
            _wall("W-I",(5,0),(5,8)),
        ],
        "grids": [
            {"id":"G-A","start":(0,-1),"end":(0,9)},
            {"id":"G-B","start":(12,-1),"end":(12,9)},
            {"id":"G-1","start":(-1,0),"end":(13,0)},
            {"id":"G-2","start":(-1,8),"end":(13,8)},
        ],
    }


def test_wall_face_basis_is_never_guessed():
    report=build_semantic_references({
        "walls":[{"id":"W1","start":(0,0),"end":(0,5),"thickness":.2}]
    })
    assert report["status"]=="HUMAN_REVIEW"
    assert not [r for r in report["references"] if r.get("element_id")=="W1"]
    assert report["human_checkpoints"][0]["reason"]=="WALL_FACE_BASIS_AMBIGUOUS"


def test_explicit_finish_wall_has_one_stable_reference_not_duplicate():
    report=build_semantic_references({"walls":[_wall("W1",(0,0),(0,5))]})
    rows=[r for r in report["references"] if r.get("element_id")=="W1"]
    assert report["errors"]==[]
    assert len(rows)==1
    assert rows[0]["subfeature"]=="FINISH_FACE"


def test_rotated_chain_measures_in_local_axis_and_closes():
    angle=math.radians(30)
    u=(math.cos(angle),math.sin(angle)); v=(-math.sin(angle),math.cos(angle))
    def line(offset):
        a=(v[0]*offset,v[1]*offset)
        b=(a[0]+u[0]*10,a[1]+u[1]*10)
        return a,b
    refs=[]
    for idx,offset in enumerate((0,3,7)):
        a,b=line(offset)
        refs.append({"id":f"W{idx}","kind":"WALL","subfeature":"FINISH_FACE",
                     "reference_class":"FINISH","a":a,"b":b})
    frames=detect_local_coordinate_frames(refs)
    assert len(frames)==1
    result=build_dimension_chain(
        refs,frames[0],purpose="WALL_SETOUT",axis="SECONDARY",
        chain_id="ROT",add_check=True,
    )
    seg=[r for r in result["intents"] if r["purpose"]=="WALL_SETOUT"]
    assert [round(r["measured_value"],6) for r in seg]==[3.0,4.0]
    assert closure_check(result["intents"])["status"]=="PASS"


def test_architectural_floor_plan_builds_partition_chain_and_overall():
    network=build_architectural_dimension_network(
        _simple_plan(),"ARCHITECTURAL_FLOOR_PLAN",
        unit_evidence={"effective_scale_to_m":1.0,"source":"dimension_plausibility"},
        source_preservation={"pass":True,"critical_source_conflicts":[]},
        stage="PRE_RENDER",
    )
    assert network["errors"]==[]
    assert not network["human_checkpoints"]
    purposes={r["purpose"] for r in network["intents"]}
    assert "BUILDING_OVERALL" in purposes
    assert "GRID" in purposes
    assert "WALL_SETOUT" in purposes
    assert "CHECK" in purposes
    assert network["determinacy"]["status"]=="PASS"
    # Rendering/visual evidence is intentionally not fabricated at PRE_RENDER.
    assert network["status"]=="INPUT_REQUIRED"


def test_multi_axis_building_produces_multiple_coordinate_frames():
    a=math.radians(30)
    arch=_simple_plan()
    arch["walls"] += [
        _wall("W30-A",(20,0),(20+8*math.cos(a),8*math.sin(a)),exterior=True),
        _wall("W30-B",(18,3),(18+8*math.cos(a),3+8*math.sin(a)),exterior=True),
    ]
    refs=build_semantic_references(arch)["references"]
    frames=detect_local_coordinate_frames(refs)
    assert len(frames)>=2
    assert all(f["status"]=="PASS" for f in frames[:2])


def test_opening_without_host_forces_human_checkpoint():
    arch=_simple_plan()
    arch["doors"]=[{"id":"D1","jamb_left":(5,2),"jamb_right":(5,3)}]
    network=build_architectural_dimension_network(
        arch,"ARCHITECTURAL_FLOOR_PLAN",
        unit_evidence={"effective_scale_to_m":1.0},
        source_preservation={"pass":True,"critical_source_conflicts":[]},
        stage="PRE_RENDER",
    )
    assert any(x["reason"]=="OPENING_HOST_UNCERTAIN" for x in network["human_checkpoints"])
    assert network["status"] in {"INPUT_REQUIRED","FAIL"}


def test_site_setback_uses_shortest_segment_distance():
    property_refs=[
        {"id":"P","element_id":"P","kind":"PROPERTY","subfeature":"PROPERTY_EDGE",
         "reference_class":"PROPERTY","a":(0,0),"b":(0,20)}
    ]
    building_refs=[
        {"id":"B","element_id":"B","kind":"WALL","subfeature":"FINISH_FACE",
         "reference_class":"FINISH","a":(5,8),"b":(5,12),"metadata":{"exterior":True}}
    ]
    result=site_intents({},property_refs+building_refs,zone_id="Z")
    setback=next(r for r in result["intents"] if r["purpose"]=="SETBACK")
    assert round(setback["measured_value"],6)==5.0


def test_code_clearance_without_rule_never_becomes_final_dimension():
    refs=[
        {"id":"P","element_id":"P","kind":"PROPERTY","subfeature":"PROPERTY_EDGE",
         "reference_class":"PROPERTY","a":(0,0),"b":(0,20)},
        {"id":"B","element_id":"B","kind":"WALL","subfeature":"FINISH_FACE",
         "reference_class":"FINISH","a":(5,8),"b":(5,12),"metadata":{"exterior":True}},
    ]
    result=site_intents({},refs,zone_id="Z",code_requirements=[{
        "id":"C1","purpose":"CODE_CLEARANCE","reference_a_id":"P",
        "reference_b_id":"B","minimum_value_m":3.0,
    }])
    assert result["errors"][0]["reason"]=="GOVERNED_CODE_CLEARANCE_INCOMPLETE"
    assert not [r for r in result["intents"] if r["purpose"]=="CODE_CLEARANCE"]


def test_different_dimension_purposes_do_not_create_false_overconstraint():
    a={"id":"A"};b={"id":"B"}
    rows=[
        {"id":"G","purpose":"SETBACK","reference_a":a,"reference_b":b},
        {"id":"C","purpose":"CODE_CLEARANCE","reference_a":a,"reference_b":b},
    ]
    assert analyze_overdimensioning(rows)["status"]=="PASS"


def test_final_release_cannot_pass_without_exact_file_and_visual_evidence():
    network=build_architectural_dimension_network(
        _simple_plan(),"ARCHITECTURAL_FLOOR_PLAN",
        unit_evidence={"effective_scale_to_m":1.0},
        source_preservation={"pass":True,"critical_source_conflicts":[]},
        stage="FINAL",
    )
    assert network["qa"]["release_allowed"] is False
    statuses={row["id"]:row["status"] for row in network["qa"]["controls"]}
    assert statuses["exact_file_reopen_pass"]=="INPUT_REQUIRED"
    assert statuses["visual_qa_pass"]=="INPUT_REQUIRED"


def test_no_benchmark_numbers_are_needed_for_generation():
    network=build_architectural_dimension_network(
        _simple_plan(),"ARCHITECTURAL_FLOOR_PLAN",
        unit_evidence={"effective_scale_to_m":1.0},
        source_preservation={"pass":True,"critical_source_conflicts":[]},
    )
    raw=repr(network)
    for forbidden in ("835","810","187"):
        assert forbidden not in raw
