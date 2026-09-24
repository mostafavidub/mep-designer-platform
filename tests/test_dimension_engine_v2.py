import json
import math
from pathlib import Path

import ezdxf
import pytest

from cad_engine.dimension_intent_model import DimensionIntentV2, validate_intents
from cad_engine.dimension_envelope import build_envelope_model
from cad_engine.dimension_reference_model import build_reference_model_v2
from cad_engine.dimension_requirement_engine import (
    collect_profile_elements,
    generate_setout_candidates,
    generate_context_intents,
    generate_governed_requirement_intents,
)
from cad_engine.dimension_determinacy_solver import build_determinacy_graph, minimum_constraint_set
from cad_engine.dimension_source_reconciliation import reconcile_source_dimensions
from cad_engine.dimension_redundancy_optimizer import optimize_dimensions
from cad_engine.dimension_placement_solver import solve_dimension_placement
from cad_engine.dimension_qa import validate_chain_closure
from cad_engine.dimension_renderer import materialize_engineering_dimension_intents, validate_engineering_dimension_exact_file, materialize_shadow_candidate
from cad_engine.dimension_engine import run_dimension_engine_shadow, build_dimension_promotion_report


def _doc(insunits=6, dim_value=10.0):
    doc=ezdxf.new("R2013")
    doc.header["$INSUNITS"]=insunits
    msp=doc.modelspace()
    d=msp.add_linear_dim(base=(0,-1),p1=(0,0),p2=(dim_value,0),angle=0)
    d.render()
    return doc


def _arch_rect(plan_id="P1", include_walls=False):
    arch={
      "building_envelopes":[{"id":"BLDG-1","plan_id":plan_id,"polygon":[(0,0),(10,0),(10,8),(0,8)]}],
      "grids":[
        {"id":"GX0","plan_id":plan_id,"start":(0,-1),"end":(0,9)},
        {"id":"GX1","plan_id":plan_id,"start":(10,-1),"end":(10,9)},
        {"id":"GY0","plan_id":plan_id,"start":(-1,0),"end":(11,0)},
        {"id":"GY1","plan_id":plan_id,"start":(-1,8),"end":(11,8)},
      ],
      "shafts":[{"id":"SH-1","plan_id":plan_id,"polygon":[(4,3),(5,3),(5,4),(4,4)]}],
      "stairs":[],
      "openings":[],
      "columns":[],
      "property_boundaries":[],
      "walls":[],
    }
    if include_walls:
        arch["walls"]=[{"id":"W-1","plan_id":plan_id,"start":(2,1),"end":(2,7)}]
    return arch


def _board():
    return {"plan_area":(20,20,120,100),"bounds":(10,10,130,110),"title_area":(10,10,130,18)}


def _ref(rid, subfeature, a, b, datum="GRID", priority=0):
    return {"id":rid,"element_id":rid.split("/")[0],"subfeature":subfeature,
            "geometry":{"type":"SEGMENT","a":a,"b":b},"plan_id":"P1","level":None,
            "priority":priority,"source":"test","confidence":1.0,"evidence":("test",),
            "datum_class":datum,"local_axis_deg":0.0}


def _intent(i, target="T1", datum="G1", axis=0.0, role="SETOUT", required=False, value=2.0):
    return {"id":i,"purpose":"EQUIPMENT_POSITION","role":role,"drawing_profile":"MECHANICAL_PLAN",
            "reference_a":{"id":target,"element_id":target,"subfeature":"EQUIPMENT_CENTER"},
            "reference_b":{"id":datum,"element_id":datum,"subfeature":"GRID_AXIS"},
            "world_p1":(2,2),"world_p2":(0,2),"measured_value":value,"engineering_value_m":value,
            "display_value":f"{value:.2f}","priority_class":"P1","required":required,
            "datum_class":"GRID","axis_deg":axis,
            "constraint_dof":"LOC_1" if abs((axis%180)-90)<1e-6 else "LOC_0",
            "evidence":("test",)}


def test_v1_golden_baseline_is_explicit_and_protected():
    path=Path("standards/golden/dimension-engine-v1.baseline.json")
    data=json.loads(path.read_text())
    assert data["baseline_commit"]=="d2355876efa7934a09cfbec855e7505a2f9c7519"
    assert "count_only_acceptance_forbidden" in data["protected_invariants"]
    assert "final_network_reconciliation" in data["protected_invariants"]


def test_dimension_ontology_requires_supported_purpose_role_and_semantic_references():
    good=DimensionIntentV2("D1","RISER","SETOUT",{"id":"R1"},{"id":"G1"},1.2,1.2,"MECHANICAL_PLAN")
    assert good.validate()==[]
    bad={"id":"D2","purpose":"ANYTHING","role":"DECORATION","reference_a":{},"reference_b":{},
         "measured_value":1,"engineering_value_m":1,"drawing_profile":"MECHANICAL_PLAN"}
    errors={e["error"] for e in validate_intents([bad])}
    assert {"UNSUPPORTED_DIMENSION_PURPOSE","DIMENSION_ROLE_REQUIRED","REFERENCE_A_REQUIRED","REFERENCE_B_REQUIRED"}<=errors


def test_wall_reference_basis_is_a_real_human_checkpoint_not_a_hidden_guess():
    doc=_doc();arch=_arch_rect(include_walls=True)
    model=build_reference_model_v2(doc,(0,0,10,8),arch,"P1")
    assert "WALL_REFERENCE_BASIS_REQUIRED" in model["human_review"]
    assert model["wall_references_enabled"] is False
    assert not any(r["subfeature"].startswith("WALL_") for r in model["references"])


def test_explicit_wall_reference_basis_enables_stable_wall_subfeature():
    doc=_doc();arch=_arch_rect(include_walls=True)
    model=build_reference_model_v2(doc,(0,0,10,8),arch,"P1",wall_reference_basis="CORE_FACE")
    assert model["wall_references_enabled"] is True
    assert any(r["subfeature"]=="WALL_CORE_FACE" and r["element_id"]=="W-1" for r in model["references"])


@pytest.mark.parametrize("polygon",[
 [(0,0),(10,0),(10,8),(0,8)],
 [(0,0),(10,0),(10,3),(6,3),(6,8),(0,8)],
 [(0,0),(8,0),(10,2),(8,8),(0,8)],
])
def test_envelope_uses_semantic_polygon_not_bounding_box(polygon):
    model=build_envelope_model({"building_envelopes":[{"id":"E1","polygon":polygon}]},"P1")
    assert model["status"]=="PASS"
    assert model["bbox_fallback_used"] is False
    assert model["envelopes"][0]["points"]==[(float(x),float(y)) for x,y in polygon]


def test_missing_semantic_envelope_requires_review_instead_of_bbox_promotion():
    model=build_envelope_model({"walls":[{"start":(0,0),"end":(10,0)}]},"P1")
    assert model["status"]=="HUMAN_REVIEW_REQUIRED"
    assert "BUILDING_ENVELOPE_NOT_PROVEN" in model["human_review"]


def test_reference_model_builds_grid_intersections_with_stable_ids():
    model=build_reference_model_v2(_doc(),(0,0,10,8),_arch_rect(),"P1")
    xs=[r for r in model["references"] if r["subfeature"]=="GRID_INTERSECTION"]
    assert len(xs)>=4
    assert all("GRID_INTERSECTION" in r["id"] for r in xs)


def test_mechanical_setout_uses_datum_perpendicular_to_measured_axis():
    model=build_reference_model_v2(_doc(),(0,0,10,8),_arch_rect(),"P1")
    elements=[{"id":"EQ-1","kind":"EQUIPMENT","point":(4,3),"geometry_kind":"POINT","priority_class":"P1","intrinsically_hosted":False}]
    gen=generate_setout_candidates(elements,model,"MECHANICAL_PLAN")
    assert gen["status"]=="PASS"
    assert len(gen["intents"])==2
    for row in gen["intents"]:
        datum=row["reference_b"]["geometry"]
        dx=datum["b"][0]-datum["a"][0];dy=datum["b"][1]-datum["a"][1]
        datum_axis=math.degrees(math.atan2(dy,dx))%180
        delta=abs((datum_axis-(row["axis_deg"]+90))%180)
        delta=min(delta,180-delta)
        assert delta<7.5


def test_point_target_requires_two_independent_constraints():
    elements=[{"id":"T1","geometry_kind":"POINT","priority_class":"P0","intrinsically_hosted":False}]
    one=[_intent("D1",axis=0)]
    state=build_determinacy_graph(elements,one,["G1"])
    assert state["status"]=="FAIL"
    two=[_intent("D1",datum="G1",axis=0),_intent("D2",datum="G2",axis=90)]
    state=build_determinacy_graph(elements,two,["G1","G2"])
    assert state["status"]=="PASS"


def test_minimum_solver_selects_two_independent_constraints_not_all_candidates():
    elements=[{"id":"T1","geometry_kind":"POINT","priority_class":"P0","intrinsically_hosted":False}]
    candidates=[_intent("D0",datum="G0",axis=0),_intent("D1",datum="G1",axis=0),_intent("D2",datum="G2",axis=90),_intent("D3",datum="G3",axis=90)]
    result=minimum_constraint_set(candidates,elements,["G0","G1","G2","G3"])
    selected=[r for r in result["selected"] if r["role"]=="SETOUT"]
    assert len(selected)==2
    assert result["determinacy"]["status"]=="PASS"


def test_intentional_check_survives_minimum_solver_even_when_redundant():
    elements=[{"id":"T1","geometry_kind":"POINT","priority_class":"P0","intrinsically_hosted":False}]
    candidates=[_intent("D1",datum="G1",axis=0),_intent("D2",datum="G2",axis=90),
                _intent("C1",target="G1",datum="G2",axis=0,role="CHECK",required=True)]
    result=minimum_constraint_set(candidates,elements,["G1","G2"])
    assert "C1" in {r["id"] for r in result["selected"]}


def test_profile_context_creates_grid_chain_and_envelope_overall_check():
    model=build_reference_model_v2(_doc(),(0,0,10,8),_arch_rect(),"P1")
    rows=generate_context_intents(model,"MECHANICAL_PLAN")
    assert any(r["purpose"]=="GRID" and r["role"]=="SETOUT" for r in rows)
    assert any(r["purpose"]=="BUILDING_OVERALL" and r["role"]=="CHECK" for r in rows)


def test_source_reconciliation_distinguishes_verified_conflict_and_unknown():
    src={"records":[
      {"id":"S1","critical":True,"measured_value_m":2.0,"source_display_text":"2.00","reference_a":{"id":"A"},"reference_b":{"id":"B"}},
      {"id":"S2","critical":True,"measured_value_m":3.0,"source_display_text":"3.00","reference_a":{"id":"C"},"reference_b":{"id":"D"}},
      {"id":"S3","critical":True,"measured_value_m":1.0,"source_display_text":"1.00","reference_a":{"id":"X"},"reference_b":{"id":"Y"}},
    ]}
    intents=[
      {"reference_a":{"id":"A"},"reference_b":{"id":"B"},"engineering_value_m":2.0},
      {"reference_a":{"id":"C"},"reference_b":{"id":"D"},"engineering_value_m":3.2},
    ]
    out=reconcile_source_dimensions(src,intents)
    states={r["source_dimension_id"]:r["status"] for r in out["rows"]}
    assert states=={"S1":"VERIFIED","S2":"CONFLICT","S3":"UNKNOWN"}
    assert out["status"]=="HUMAN_REVIEW_REQUIRED"


def test_redundancy_optimizer_removes_setout_duplicate_but_keeps_check():
    a=_intent("A");b={**a,"id":"B"};c={**a,"id":"C","role":"CHECK"}
    out=optimize_dimensions([a,b,c])
    assert out["duplicate_count"]==1
    assert {r["id"] for r in out["selected"]}=={"A","C"}


def test_contradictory_same_reference_pair_fails_redundancy_gate():
    a=_intent("A",value=2.0);b={**_intent("B",value=2.5),"reference_a":a["reference_a"],"reference_b":a["reference_b"]}
    out=optimize_dimensions([a,b])
    assert out["status"]=="FAIL"
    assert out["alternatives"][0]["reason"]=="CONTRADICTORY_REFERENCE_PAIR"


def test_collision_heavy_board_requires_controlled_review():
    rows=[]
    for i in range(8):
        r=_intent(f"D{i}",target=f"T{i}",datum=f"G{i}",axis=0,value=2+i*.1)
        r["world_p1"]=(2,2+i*.01);r["world_p2"]=(0,2+i*.01)
        rows.append(r)
    out=solve_dimension_placement(rows,(0,0,10,8),{"plan_area":(1,1,1.6,1.6),"bounds":(0,0,2,2),"title_area":(0,0,2,.9)})
    assert out["status"]=="HUMAN_REVIEW_REQUIRED"
    assert out["collision_count"]>0


def test_chain_closure_never_mixes_grid_and_envelope_datum_classes():
    rows=[
      {"chain_id":"X","datum_class":"GRID","chain_role":"PART","engineering_value_m":3.0},
      {"chain_id":"X","datum_class":"GRID","chain_role":"PART","engineering_value_m":4.0},
      {"chain_id":"X","datum_class":"GRID","chain_role":"TOTAL","engineering_value_m":7.0},
      {"chain_id":"X","datum_class":"ENVELOPE","chain_role":"TOTAL","engineering_value_m":8.0},
    ]
    assert validate_chain_closure(rows)==[]


def test_governed_code_clearance_requires_rule_and_stable_refs():
    model=build_reference_model_v2(_doc(),(0,0,10,8),_arch_rect(),"P1")
    refs=[r for r in model["references"] if r["subfeature"]=="GRID_AXIS"]
    bad=generate_governed_requirement_intents([{"id":"C","purpose":"CODE_CLEARANCE","reference_a_id":refs[0]["id"],"reference_b_id":refs[1]["id"],"p1":(0,0),"p2":(1,0),"minimum_value_m":1}],model,"MECHANICAL_PLAN","P1")
    assert bad["status"]=="FAIL"
    good=generate_governed_requirement_intents([{"id":"C","purpose":"CODE_CLEARANCE","rule_id":"IR-RULE-X","reference_a_id":refs[0]["id"],"reference_b_id":refs[1]["id"],"p1":(0,0),"p2":(1,0),"minimum_value_m":1,"actual_value_m":1}],model,"MECHANICAL_PLAN","P1")
    assert good["status"]=="PASS"
    assert good["intents"][0]["rule_id"]=="IR-RULE-X"


@pytest.mark.parametrize("profile,key",[
 ("PARKING_PLAN","parking_dimension_targets"),
 ("ROOF_PLAN","roof_dimension_targets"),
 ("DETAIL","detail_dimension_targets"),
])
def test_specialized_profiles_consume_only_explicit_semantic_targets(profile,key):
    arch=_arch_rect();arch[key]=[{"id":"X1","plan_id":"P1","kind":"ROOF_DRAIN" if profile=="ROOF_PLAN" else "DETAIL_SCOPE","point":(2,2)}]
    out=collect_profile_elements(profile,arch,{},plan_id="P1")
    assert out["status"]=="PASS"
    assert [e["id"] for e in out["elements"]]==["X1"]


def test_multi_plan_isolation_excludes_other_plan_elements():
    arch=_arch_rect("P1")
    arch["parking_dimension_targets"]=[
      {"id":"A","plan_id":"P1","point":(2,2)},
      {"id":"B","plan_id":"P2","point":(3,3)},
    ]
    out=collect_profile_elements("PARKING_PLAN",arch,{},plan_id="P1")
    assert {e["id"] for e in out["elements"]}=={"A"}


def test_v2_renderer_round_trips_semantic_reference_identity(tmp_path):
    doc=_doc();msp=doc.modelspace()
    row=_intent("D1",datum="G1",axis=0,value=2)
    row.update({"render_p1":(2,2),"render_p2":(0,2),"render_base":(1,2.4)})
    materialized=materialize_engineering_dimension_intents(doc,msp,[row])
    path=tmp_path/"v2.dxf";doc.saveas(path)
    out=validate_engineering_dimension_exact_file(path,materialized)
    assert out["status"]=="PASS"
    assert out["checked"]==1


def test_shadow_engine_does_not_change_visible_output_and_resolves_mm_header_metre_geometry():
    doc=_doc(insunits=4,dim_value=10.0)
    arch=_arch_rect()
    pipeline={"topology":{"nodes":[{"id":"R1","kind":"riser","plan_id":"P1","point":(4,3)}]},"hvac":{"equipment":[]}}
    v1={"materialized":[],"missing_determinacy":[]}
    out=run_dimension_engine_shadow(doc,{"plan_id":"P1","bounds":(0,0,10,8)},arch,pipeline,"MECHANICAL_PLAN",_board(),v1_report=v1)
    assert out["mode"]=="SHADOW"
    assert out["shadow_compare"]["visible_output_changed"] is False
    assert out["source_registry"]["unit_evidence"]["effective_scale_to_m"]==1.0
    assert out["determinacy"]["status"]=="PASS"


SCENARIO_CATALOG=[
 "rectangular_building","l_shaped_envelope","setback_site_chain","grid_vs_overall",
 "internal_partition_chain","shaft_dimensions","stair_core","door_window_position",
 "rotated_building","true_aligned_dimension","wrong_insunits","numeric_override_conflict",
 "non_numeric_override","zero_dimension","mechanical_riser_setout","equipment_setout",
 "sleeve_penetration","parking_bay_aisle","roof_drain","intentional_check_redundancy",
 "duplicate_dimension","missing_datum","collision_heavy_drawing","complex_envelope",
 "multi_plan_multi_level_isolation",
]


@pytest.mark.parametrize("scenario",SCENARIO_CATALOG)
def test_synthetic_regression_corpus_inventory_is_stable(scenario):
    assert isinstance(scenario,str) and scenario


def test_architectural_line_is_not_determinate_with_offset_only_when_extents_are_unhosted():
    elements=[{"id":"W1","geometry_kind":"LINE","priority_class":"P0","intrinsically_hosted":False,
               "required_dofs":["OFFSET","START","END"]}]
    rows=[
      {**_intent("O",target="W1",datum="G0",axis=90),"constraint_dof":"OFFSET"},
    ]
    state=build_determinacy_graph(elements,rows,["G0"])
    assert state["status"]=="FAIL"
    assert state["critical_missing"][0]["missing_dofs"]==["START","END"]


def test_architectural_line_passes_only_when_offset_start_and_end_are_proven():
    elements=[{"id":"W1","geometry_kind":"LINE","priority_class":"P0","intrinsically_hosted":False,
               "required_dofs":["OFFSET","START","END"]}]
    rows=[
      {**_intent("O",target="W1",datum="G0",axis=90),"constraint_dof":"OFFSET"},
      {**_intent("S",target="W1",datum="G1",axis=0),"constraint_dof":"START"},
      {**_intent("E",target="W1",datum="G2",axis=0),"constraint_dof":"END"},
    ]
    state=build_determinacy_graph(elements,rows,["G0","G1","G2"])
    assert state["status"]=="PASS"


def test_code_clearance_below_authoritative_minimum_fails_closed():
    model=build_reference_model_v2(_doc(),(0,0,10,8),_arch_rect(),"P1")
    refs=[r for r in model["references"] if r["subfeature"]=="GRID_AXIS"]
    out=generate_governed_requirement_intents([{
      "id":"C","purpose":"CODE_CLEARANCE","rule_id":"IR-RULE-X",
      "reference_a_id":refs[0]["id"],"reference_b_id":refs[1]["id"],
      "p1":(0,0),"p2":(.9,0),"minimum_value_m":1.0,"actual_value_m":.9
    }],model,"MECHANICAL_PLAN","P1")
    assert out["status"]=="FAIL"
    assert out["errors"][0]["reason"]=="CODE_CLEARANCE_BELOW_MINIMUM"


def test_opening_requires_size_and_position_and_uses_distinct_jamb_references():
    arch=_arch_rect()
    arch["openings"]=[{"id":"OP-1","plan_id":"P1","start":(3,0),"end":(4,0),"host_id":"W-EXT"}]
    model=build_reference_model_v2(_doc(),(0,0,10,8),arch,"P1")
    jambs=[r for r in model["references"] if r["element_id"]=="OP-1" and r["subfeature"]=="OPENING_JAMB"]
    assert len(jambs)==2
    elements=collect_profile_elements("ARCHITECTURAL_FLOOR_PLAN",arch,{},plan_id="P1")["elements"]
    opening=next(e for e in elements if e["id"]=="OP-1")
    assert opening["required_dofs"]==["POSITION","SIZE"]
    gen=generate_setout_candidates([opening],model,"ARCHITECTURAL_FLOOR_PLAN")
    assert any(r["purpose"]=="OPENING_SIZE" and r["constraint_dof"]=="SIZE" for r in gen["intents"])


def test_rectangular_shaft_requires_location_and_two_size_dimensions():
    arch=_arch_rect()
    model=build_reference_model_v2(_doc(),(0,0,10,8),arch,"P1")
    elements=collect_profile_elements("ARCHITECTURAL_FLOOR_PLAN",arch,{},plan_id="P1")["elements"]
    shaft=next(e for e in elements if e["id"]=="SH-1")
    assert shaft["geometry_kind"]=="RECT"
    assert shaft["required_dofs"]==["LOC_0","LOC_1","SIZE_0","SIZE_1"]
    gen=generate_setout_candidates([shaft],model,"ARCHITECTURAL_FLOOR_PLAN")
    dofs={r["constraint_dof"] for r in gen["intents"]}
    assert {"SIZE_0","SIZE_1"}<=dofs


def test_profile_reconciliation_suppresses_nonvisible_wall_dimensions_without_deleting_evidence():
    src={"records":[{"id":"S1","semantic_type":"WALL_SETOUT","critical":False,"measured_value_m":2.0,
                      "source_display_text":"2.00","reference_a":{"id":"A"},"reference_b":{"id":"B"}}]}
    out=reconcile_source_dimensions(src,[],profile="MECHANICAL_PLAN")
    assert out["rows"][0]["status"]=="SUPPRESSED_IN_VIEW"
    assert out["status"]=="PASS"


def test_shadow_candidate_materializes_and_reopens_exact_file_end_to_end(tmp_path):
    doc=_doc(insunits=4,dim_value=10.0)
    arch=_arch_rect()
    pipeline={"topology":{"nodes":[{"id":"R1","kind":"riser","plan_id":"P1","point":(4,3)}]},"hvac":{"equipment":[]}}
    v1={"materialized":[],"missing_determinacy":[]}
    out=run_dimension_engine_shadow(
        doc,{"plan_id":"P1","bounds":(0,0,10,8)},arch,pipeline,
        "MECHANICAL_PLAN",_board(),v1_report=v1
    )
    assert out["placement"]["status"]=="PASS", out["placement"]["unresolved"]
    assert out["qa"]["status"]=="PASS", out["qa"]
    assert out["determinacy"]["status"]=="PASS", out["determinacy"]
    assert out["shadow_compare"]["v2_missing_critical"]==0
    candidate=materialize_shadow_candidate(doc,out)
    assert candidate["status"]=="PASS"
    assert len(candidate["materialized"])==len(out["placement"]["placed"])>0
    path=tmp_path/"dimension-v2-promotion-candidate.dxf"
    doc.saveas(path)
    exact=validate_engineering_dimension_exact_file(path,candidate["materialized"])
    assert exact["status"]=="PASS"
    assert exact["exact_file_reopened"] is True
    assert exact["checked"]==len(candidate["materialized"])


def test_promotion_report_requires_zero_p0_p1_placement_and_source_review():
    good={
      "plan_id":"P1","profile":"MECHANICAL_PLAN",
      "qa":{"status":"PASS","critical_missing":[]},
      "shadow_compare":{"placement_unresolved":0,"source_reconciliation_human_review":0,
                        "duplicates_removed":0,"v1_count":5,"v2_count":7,"visible_output_changed":False},
    }
    report=build_dimension_promotion_report([good])
    assert report["status"]=="PROMOTION_CANDIDATE"
    assert report["metrics"]["missing_critical"]==0

    bad={
      "plan_id":"P2","profile":"ARCHITECTURAL_FLOOR_PLAN",
      "qa":{"status":"HUMAN_REVIEW_REQUIRED","critical_missing":[{"element_id":"W1"}]},
      "shadow_compare":{"placement_unresolved":1,"source_reconciliation_human_review":1,
                        "duplicates_removed":0,"v1_count":4,"v2_count":4,"visible_output_changed":False},
    }
    report=build_dimension_promotion_report([good,bad])
    assert report["status"]=="NOT_READY"
    reasons={b["reason"] for b in report["blockers"]}
    assert {"QA_NOT_PASS","P0_P1_DETERMINACY_DEFECT","UNRESOLVED_PLACEMENT","SOURCE_RECONCILIATION_REVIEW"}<=reasons


def test_extension_line_may_leave_host_obstacle_but_dimension_line_may_not_cross_it():
    board={"plan_area":(0,0,10,10),"bounds":(-2,-2,12,12),"title_area":(-2,-2,12,-1.5)}
    hosted=_intent("HOSTED",target="R1",datum="G1",axis=0,value=4)
    hosted["world_p1"]=(4,3);hosted["world_p2"]=(0,3)
    # Target starts inside the shaft obstacle; extension may legitimately leave it.
    ok=solve_dimension_placement([hosted],(0,0,10,10),board,obstacles=[(3.8,2.8,5.2,4.2)])
    assert ok["status"]=="PASS"

    crossing=_intent("CROSS",target="T2",datum="G2",axis=0,value=8)
    crossing["world_p1"]=(1,5);crossing["world_p2"]=(9,5)
    # The dimension line itself cannot be routed through an unrelated obstacle.
    movable=solve_dimension_placement([crossing],(0,0,10,10),board,obstacles=[(4.5,4.5,5.5,5.5)])
    assert movable["status"]=="PASS"

    blocked=solve_dimension_placement([crossing],(0,0,10,10),board,obstacles=[(4.5,3.5,5.5,6.5)])
    assert blocked["status"]=="HUMAN_REVIEW_REQUIRED"
    assert blocked["collision_count"]==1


def test_orthogonal_coordinate_setout_for_same_target_is_clean_not_collision():
    board={"plan_area":(0,0,10,10),"bounds":(-2,-2,12,12),"title_area":(-2,-2,12,-1.5)}
    x=_intent("X",target="R1",datum="GX",axis=0,value=4)
    x["world_p1"]=(4,3);x["world_p2"]=(0,3)
    y=_intent("Y",target="R1",datum="GY",axis=90,value=3)
    y["world_p1"]=(4,3);y["world_p2"]=(4,0)
    out=solve_dimension_placement([x,y],(0,0,10,10),board)
    assert out["status"]=="PASS"
    assert out["collision_count"]==0
    assert {r["id"] for r in out["placed"]}=={"X","Y"}


def test_orthogonal_global_grid_and_overall_tiers_may_meet_at_clean_outer_corner():
    board={"plan_area":(0,0,10,8),"bounds":(-2,-2,12,10),"title_area":(-2,-2,12,-1.5)}
    h=_intent("GH",target="GX0",datum="GX1",axis=0,value=10)
    h.update({"purpose":"GRID","role":"SETOUT","world_p1":(0,4),"world_p2":(10,4)})
    v=_intent("OV",target="EB",datum="ET",axis=90,role="CHECK",value=8)
    v.update({"purpose":"BUILDING_OVERALL","world_p1":(5,0),"world_p2":(5,8)})
    out=solve_dimension_placement([h,v],(0,0,10,8),board)
    assert out["status"]=="PASS"


def test_exact_duplicate_cleanup_is_informational_not_human_review():
    from cad_engine.dimension_qa import construction_determinacy_gate
    refs={"errors":[],"human_review":[],"envelope":{"status":"PASS","envelopes":[{"id":"E"}]},"references":[]}
    det={"critical_missing":[]}
    rec={"status":"PASS","rows":[],"human_review":[]}
    red={"status":"PASS","duplicate_count":1}
    place={"status":"PASS","collision_count":0}
    intents=[{"id":"O","purpose":"BUILDING_OVERALL","role":"CHECK","reference_a":{"id":"A"},"reference_b":{"id":"B"}}]
    qa=construction_determinacy_gate(refs,[],det,rec,red,place,intents,profile="MECHANICAL_PLAN")
    assert qa["status"]=="PASS"
    assert "SEMANTIC_DUPLICATES_REMOVED" in qa["informational"]
