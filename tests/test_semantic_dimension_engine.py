import math
import shutil
from pathlib import Path

import ezdxf

from cad_engine.mechanical_design_core import _entity_should_copy

from cad_engine.semantic_dimension_engine import (
    APPID,
    _override_status,
    apply_semantic_dimension_engine,
    build_and_materialize_plan_dimensions,
    build_reference_catalog,
    context_dimension_intents,
    determinacy_intents,
    entity_obstacle_boxes,
    extract_source_dimension_registry,
    governed_requirement_intents,
    infer_dimension_unit_evidence,
    select_minimal_dimension_set,
    source_dimension_intents,
    source_preservation_complete,
    validate_exact_file_dimensions,
)


def _source_doc():
    doc=ezdxf.new("R2013")
    doc.header["$INSUNITS"]=4  # deliberately misleading, matching reviewed source behavior.
    return doc


def _add_dim(doc,p1,p2,base,text=None,layer="RANDOM-DIM"):
    if layer not in doc.layers:
        doc.layers.add(layer)
    dim=doc.modelspace().add_linear_dim(
        base=base,p1=p1,p2=p2,angle=0,text=text,dxfattribs={"layer":layer}
    )
    dim.render()
    return dim.dimension


def _architectural_source(path: Path):
    doc=_source_doc();msp=doc.modelspace()
    msp.add_line((0,0),(10,0),dxfattribs={"layer":"WALL"})
    msp.add_line((10,0),(10,10),dxfattribs={"layer":"WALL"})
    _add_dim(doc,(0,0),(10,0),(5,.5),"10.00",layer="GRID")
    doc.saveas(path)


def test_override_status_uses_literal_precision_not_percentage_heuristic():
    assert _override_status(3.0,"3.00")=="FORMAT_EQUIVALENT"
    assert _override_status(2.97657,"3.00")=="NUMERIC_OVERRIDE"
    assert _override_status(3.23749,"3.25")=="NUMERIC_OVERRIDE"
    assert _override_status(0.9791463441,"1.00")=="NUMERIC_OVERRIDE"
    assert _override_status(0.6936889303,".70")=="NUMERIC_OVERRIDE"
    assert _override_status(5.95,"7.00")=="NUMERIC_OVERRIDE"
    assert _override_status(2.0,"20-30")=="NON_NUMERIC_OVERRIDE"


def test_source_registry_uses_geometry_not_insunits_layer_or_dimstyle_as_numeric_truth():
    doc=_source_doc()
    _add_dim(doc,(0,0),(13,0),(6.5,.5),"13.00",layer="UNRELATED-LAYER")
    registry=extract_source_dimension_registry(doc,(0,0,13,10),architecture={},plan_id="P1")
    assert registry["status"]=="PASS"
    assert registry["dimension_count"]==1
    row=registry["records"][0]
    assert row["raw_measurement"]==13.0
    assert row["measured_value"]==13.0
    assert registry["unit_evidence"]["header_insunits"]==4
    assert registry["unit_evidence"]["effective_scale_to_m"]==1.0
    assert registry["unit_evidence"]["source"]=="dimension-measurement-override-mm-header-to-m"
    assert row["measured_value_m"]==13.0
    assert row["semantic_type"]=="BUILDING_OVERALL"
    assert row["critical"] is True
    assert row["preservation_policy"]=="REGENERATE"
    assert row["conflict"] is None


def test_source_registry_preserves_linear_and_aligned_dimension_type_orientation():
    doc=_source_doc()
    _add_dim(doc,(0,0),(10,0),(5,.5),"10.00")
    # add_aligned_dim() normalizes to rotated-linear DIMTYPE in ezdxf.
    # Build a raw source DIMENSION with base type 1 to represent consultant
    # files that carry true ALIGNED entities, as observed in the reference corpus.
    doc.modelspace().new_entity("DIMENSION",dxfattribs={
        "dimtype":1,
        "defpoint":(1,1,0),
        "defpoint2":(0,0,0),
        "defpoint3":(3,4,0),
        "dimstyle":"Standard",
    })
    registry=extract_source_dimension_registry(doc,(0,0,10,8),architecture={},plan_id="P1")
    kinds={row["source_dimension_kind"] for row in registry["records"]}
    assert "LINEAR_ROTATED" in kinds
    assert "ALIGNED" in kinds
    aligned_row=next(row for row in registry["records"] if row["source_dimension_kind"]=="ALIGNED")
    assert aligned_row["source_dimtype_base"]==1
    assert aligned_row["source_orientation"]=="ALIGNED"
    assert abs(aligned_row["source_angle_deg"]-53.1301023542)<1e-6


def test_registry_can_derive_simple_plan_bounds_without_trusting_units():
    doc=_source_doc();msp=doc.modelspace()
    msp.add_line((0,0),(10,0),dxfattribs={"layer":"WALL"})
    msp.add_line((10,0),(10,10),dxfattribs={"layer":"WALL"})
    _add_dim(doc,(0,0),(10,0),(5,.5),"10.00")
    registry=extract_source_dimension_registry(doc)
    assert registry["status"]=="PASS"
    assert registry["dimension_count"]==1
    assert registry["records"][0]["measured_value"]==10.0


def test_numeric_source_override_conflict_is_preserved_and_blocks_critical_truth():
    doc=_source_doc()
    _add_dim(doc,(0,0),(5.95,0),(2.9,.5),"7.00")
    registry=extract_source_dimension_registry(doc,(0,0,6,4),architecture={},plan_id="P1")
    row=registry["records"][0]
    assert row["semantic_type"]=="BUILDING_OVERALL"
    assert row["measured_value"]==5.95
    assert row["source_display_text"]=="7.00"
    assert row["override_status"]=="NUMERIC_OVERRIDE"
    assert row["conflict"]=="DISPLAY_GEOMETRY_OVERRIDE"
    assert row["preservation_policy"]=="FLAG_CONFLICT"
    assert registry["override_conflict_count"]==1
    assert source_dimension_intents(registry,"MECHANICAL_PLAN")==[]


def test_non_numeric_override_is_preserved_as_evidence_not_fabricated_number():
    doc=_source_doc()
    _add_dim(doc,(2,2),(4,2),(3,2.5),"20-30")
    registry=extract_source_dimension_registry(doc,(0,0,10,8),architecture={},plan_id="P1")
    row=registry["records"][0]
    assert row["source_display_text"]=="20-30"
    assert row["simple_numeric_override"] is None
    assert row["override_status"]=="NON_NUMERIC_OVERRIDE"
    assert row["conflict"] is None
    assert row["measured_value"]==2.0


def test_wall_setout_can_be_suppressed_from_mechanical_view_without_data_loss():
    doc=_source_doc()
    _add_dim(doc,(2,2),(5,2),(3.5,2.5),"3.00")
    architecture={"walls":[
        {"plan_id":"P1","start":(2,0),"end":(2,8)},
        {"plan_id":"P1","start":(5,0),"end":(5,8)},
    ]}
    registry=extract_source_dimension_registry(doc,(0,0,10,8),architecture=architecture,plan_id="P1")
    assert registry["records"][0]["semantic_type"]=="WALL_SETOUT"
    assert registry["dimension_count"]==1
    assert source_dimension_intents(registry,"MECHANICAL_PLAN")==[]


def test_minimal_dimension_set_removes_exact_duplicate_reference_definition():
    row={
        "id":"D1","board_id":"B","orientation":"HORIZONTAL","purpose":"SETOUT",
        "reference_a":{"element_id":"A"},"reference_b":{"element_id":"B"},"mandatory":True,
    }
    duplicate={**row,"id":"D2"}
    assert [x["id"] for x in select_minimal_dimension_set([row,duplicate])]==["D1"]


def test_rotated_local_setout_gets_two_independent_datum_constraints():
    target={"id":"R-01","point":(5.0,4.0),"kind":"VERTICAL_CONNECTION","priority":100}
    root=math.sqrt(2)/2
    refs=[
        {"id":"G-A","kind":"GRID_AXIS","a":(0,0),"b":(10*root,10*root),"priority":0},
        {"id":"G-1","kind":"GRID_AXIS","a":(0,8),"b":(8*root,-8*root+8),"priority":0},
    ]
    intents,missing=determinacy_intents([target],refs,math.radians(45))
    assert missing==[]
    assert len(intents)==2
    assert all(row["purpose"]=="SETOUT" and row["required"] for row in intents)


def test_target_on_one_datum_uses_implicit_constraint_and_only_one_displayed_dimension():
    target={"id":"R-ON-GRID","point":(5.0,3.0),"kind":"VERTICAL_CONNECTION","priority":100}
    root=math.sqrt(2)/2
    refs=[
        {"id":"G-A","kind":"GRID_AXIS","a":(0,0),"b":(10*root,10*root),"priority":0},
        {"id":"G-1","kind":"GRID_AXIS","a":(0,8),"b":(8*root,-8*root+8),"priority":0},
    ]
    intents,missing=determinacy_intents([target],refs,math.radians(45))
    assert missing==[]
    assert len(intents)==1
    assert intents[0]["purpose"]=="SETOUT"


def test_reference_catalog_prefers_explicit_semantic_grid_stair_and_opening_geometry():
    doc=_source_doc()
    architecture={
        "grids":[{"plan_id":"P1","start":(2,0),"end":(2,8)}],
        "stairs":[{"plan_id":"P1","bounds":[4,2,6,5]}],
        "openings":[{"plan_id":"P1","start":(7,0),"end":(7,1)}],
    }
    refs=build_reference_catalog(doc,(0,0,10,8),architecture=architecture,plan_id="P1")
    kinds={row["kind"] for row in refs}
    assert "GRID_AXIS" in kinds
    assert "STAIR_CORE_FACE" in kinds
    assert "OPENING_JAMB" in kinds
    assert any(row.get("source")=="semantic_geometry" for row in refs if row["kind"]=="GRID_AXIS")


def test_reference_catalog_does_not_require_dimension_layer_names():
    doc=_source_doc();msp=doc.modelspace()
    msp.add_line((0,0),(10,0),dxfattribs={"layer":"0"})
    refs=build_reference_catalog(doc,(0,0,10,8),architecture={
        "walls":[{"plan_id":"P1","start":(0,0),"end":(10,0)}]
    },plan_id="P1")
    assert any(row["kind"]=="WALL_FACE" for row in refs)


def test_exact_file_semantic_dimension_materialization_and_source_preservation(tmp_path):
    doc=_source_doc()
    _add_dim(doc,(0,0),(13,0),(6.5,.5),"13.00")
    plan={"plan_id":"P1","bounds":(0,0,13,10)}
    architecture={"walls":[],"shafts":[],"columns":[]}
    pipeline={"topology":{"nodes":[]},"hvac":{"equipment":[]}}
    board={"bounds":(-2,-2,15,12),"plan_area":(0,0,13,10),"title_area":(-2,-2,15,-1)}
    report=build_and_materialize_plan_dimensions(
        doc,doc.modelspace(),board,plan,architecture,pipeline,"WATER","GROUND"
    )
    assert report["status"]=="PASS",report
    assert report["source_dimension_count"]==1
    assert report["source_visible_count"]==1
    assert source_preservation_complete(report)["pass"] is True

    path=Path(tmp_path)/"semantic-dim.dxf";doc.saveas(path)
    exact=validate_exact_file_dimensions(path,{"dimensioning":{"M-W-01":report}})
    assert exact["status"]=="PASS",exact
    reopened=ezdxf.readfile(path)
    generated=[]
    for entity in reopened.modelspace().query("DIMENSION"):
        try:data=entity.get_xdata(APPID)
        except Exception:continue
        markers=[value for code,value in data if code==1000]
        if "SOURCE_DIMENSION" in markers:generated.append(entity)
    assert len(generated)==1


def test_critical_source_dimension_may_be_suppressed_in_view_without_knowledge_loss():
    report={
        "source_registry":{"records":[{
            "id":"SRC-DIM-P1-0000","critical":True,"conflict":None,
        }]},
        "source_intent_ids":[],
        "materialized":[],
    }
    result=source_preservation_complete(report)
    assert result["pass"] is True
    assert result["suppressed_but_preserved_critical_dimensions"]==["SRC-DIM-P1-0000"]


def test_source_preservation_detects_missing_critical_regeneration():
    doc=_source_doc()
    _add_dim(doc,(0,0),(13,0),(6.5,.5),"13.00")
    registry=extract_source_dimension_registry(doc,(0,0,13,10),architecture={},plan_id="P1")
    result=source_preservation_complete({"source_registry":registry,"materialized":[]})
    assert result["pass"] is False
    assert result["missing_critical_source_dimensions"]==["SRC-DIM-P1-0000"]


def test_standalone_adapter_generates_two_reference_bound_setout_dimensions(tmp_path):
    src=tmp_path/"source.dxf";out=tmp_path/"out.dxf"
    _architectural_source(src);shutil.copy2(src,out)
    network={
        "levels":[{"id":"L1","name":"Ground","type":"GROUND","region_bounds":[0,0,10,10]}],
        "nodes":[
            {"id":"S1","kind":"shaft","category":"vertical_core","point":(4,3),"level":"L1"},
            {"id":"F1","kind":"basin","category":"fixture","point":(8,7),"level":"L1"},
        ],
        "edges":[{"id":"E1","system":"cold_water","from":"S1","to":"F1","levels":["L1"],
                  "draw_on_plan":True,"plan_path":[(4,3),(8,3),(8,7)]}],
    }
    report={"composition":{
        "manifest":[{"family":"WATER","purpose":"PLAN","level":"GROUND","old_sheet":"B1","code":"M-W-01"}],
        "boards":{"B1":{"plan_area":[20,20,120,120]}},
    }}
    result=apply_semantic_dimension_engine(
        src,out,report,network,
        architecture_preservation={"status":"PASS","critical_missing_count":0,"important_missing_count":0},
    )
    assert result["status"]=="PASS",result
    assert result["generated_dimension_count"]==2
    assert result["source_preservation_proven"] is True
    reopened=ezdxf.readfile(out)
    generated=[]
    for entity in reopened.modelspace().query("DIMENSION"):
        try:data=entity.get_xdata(APPID)
        except Exception:continue
        values=[value for code,value in data if code==1000]
        if "SEMANTIC_DIMENSION" in values:generated.append(entity)
    assert len(generated)==2


def test_final_reconciliation_reuses_proven_semantic_reference_catalog(tmp_path):
    src=tmp_path/"source_refs.dxf";out=tmp_path/"out_refs.dxf"
    _architectural_source(src);shutil.copy2(src,out)
    proven_refs=[
        {"id":"G-A","kind":"GRID_AXIS","a":(2.0,0.0),"b":(2.0,10.0),"priority":0,"source":"semantic_geometry"},
        {"id":"G-1","kind":"GRID_AXIS","a":(0.0,1.0),"b":(10.0,1.0),"priority":0,"source":"semantic_geometry"},
        {"id":"PLAN-LEFT","kind":"PLAN_EDGE","a":(0.0,0.0),"b":(0.0,10.0),"priority":40},
        {"id":"PLAN-BOTTOM","kind":"PLAN_EDGE","a":(0.0,0.0),"b":(10.0,0.0),"priority":40},
    ]
    network={
        "levels":[{"id":"L1","name":"Ground","type":"GROUND","region_bounds":[0,0,10,10]}],
        "nodes":[{"id":"S1","kind":"shaft","category":"vertical_core","point":(4,3),"level":"L1"}],
        "edges":[],
    }
    report={"composition":{
        "manifest":[{"family":"WATER","purpose":"PLAN","level":"GROUND","old_sheet":"B1","code":"M-W-01"}],
        "boards":{"B1":{"plan_area":[20,20,120,120]}},
        "dimensioning":{"M-W-01":{"reference_catalog":proven_refs}},
    }}
    result=apply_semantic_dimension_engine(
        src,out,report,network,
        architecture_preservation={"status":"PASS","critical_missing_count":0,"important_missing_count":0},
    )
    assert result["status"]=="PASS",result
    rows=result["dimensioning"]["M-W-01"]["materialized"]
    generated=[row for row in rows if row["source_kind"]=="PLANHA_GENERATED"]
    assert len(generated)==2
    used={row["reference_b_id"] for row in generated}
    assert used=={"G-A","G-1"}


def test_exact_file_xdata_binds_reference_ids_and_engineering_value(tmp_path):
    doc=_source_doc()
    _add_dim(doc,(0,0),(13,0),(6.5,.5),"13.00")
    plan={"plan_id":"P1","bounds":(0,0,13,10)}
    board={"bounds":(-2,-2,15,12),"plan_area":(0,0,13,10),"title_area":(-2,-2,15,-1)}
    report=build_and_materialize_plan_dimensions(
        doc,doc.modelspace(),board,plan,{"walls":[],"shafts":[],"columns":[]},
        {"topology":{"nodes":[]},"hvac":{"equipment":[]}},"WATER","GROUND"
    )
    path=tmp_path/"trace.dxf";doc.saveas(path)
    assert validate_exact_file_dimensions(path,{"dimensioning":{"M-W-01":report}})["status"]=="PASS"
    generated=next(item for item in report["materialized"] if item["source_kind"]=="SOURCE_REGENERATED")
    reopened=ezdxf.readfile(path)
    entity=next(e for e in reopened.modelspace().query("DIMENSION") if str(getattr(e.dxf,"handle",""))==generated["handle"])
    xdata=entity.get_xdata(APPID)
    strings=[value for code,value in xdata if code==1000]
    doubles=[float(value) for code,value in xdata if code==1040]
    assert strings[0]=="SOURCE_DIMENSION"
    assert strings[1]==generated["intent_id"]
    assert strings[4]==generated["reference_a_id"]
    assert strings[5]==generated["reference_b_id"]
    assert strings[6]==generated["unit_evidence_source"]
    assert doubles[0]==generated["measured_value"]
    assert doubles[1]==generated["engineering_value_m"]
    assert doubles[2]==generated["effective_scale_to_m"]


def test_critical_non_numeric_override_requires_review_instead_of_numeric_regeneration():
    doc=_source_doc()
    _add_dim(doc,(0,0),(13,0),(6.5,.5),"20-30")
    registry=extract_source_dimension_registry(doc,(0,0,13,10),architecture={},plan_id="P1")
    row=registry["records"][0]
    assert row["critical"] is True
    assert row["override_status"]=="NON_NUMERIC_OVERRIDE"
    assert row["conflict"]=="NON_NUMERIC_CRITICAL_OVERRIDE"
    assert row["preservation_policy"]=="FLAG_CONFLICT"
    assert source_dimension_intents(registry,"MECHANICAL_PLAN")==[]


def test_true_millimetre_dimension_keeps_header_scale_and_normalizes_to_metres():
    doc=ezdxf.new("R2013")
    doc.header["$INSUNITS"]=4
    _add_dim(doc,(0,0),(3000,0),(1500,400),"3000")
    registry=extract_source_dimension_registry(doc,(0,0,3000,2000),architecture={},plan_id="P1")
    assert registry["unit_evidence"]["effective_scale_to_m"]==0.001
    assert registry["unit_evidence"]["source"]=="header"
    assert registry["records"][0]["measured_value_m"]==3.0


def test_governed_code_clearance_requires_rule_stable_references_and_canonical_minimum():
    doc=_source_doc();msp=doc.modelspace()
    msp.add_line((0,0),(0,8),dxfattribs={"layer":"WALL"})
    msp.add_line((3,0),(3,8),dxfattribs={"layer":"WALL"})
    refs=build_reference_catalog(doc,(0,0,10,8),architecture={
        "walls":[
            {"plan_id":"P1","start":(0,0),"end":(0,8)},
            {"plan_id":"P1","start":(3,0),"end":(3,8)},
        ]
    },plan_id="P1")
    wall_ids=[r["id"] for r in refs if r["kind"]=="WALL_FACE"]
    assert len(wall_ids)>=2
    intents,errors=governed_requirement_intents([{
        "id":"CLR-1","plan_id":"P1","purpose":"CODE_CLEARANCE","rule_id":"TEST-RULE-001",
        "reference_a_id":wall_ids[0],"reference_b_id":wall_ids[1],
        "p1":(0,2),"p2":(3,2),"minimum_value_m":2.5,
    }],refs,"P1")
    assert errors==[]
    assert len(intents)==1
    assert intents[0]["governance_rule_id"]=="TEST-RULE-001"
    assert intents[0]["minimum_value_m"]==2.5

    _,missing_rule=governed_requirement_intents([{
        "id":"CLR-2","plan_id":"P1","purpose":"CODE_CLEARANCE",
        "reference_a_id":wall_ids[0],"reference_b_id":wall_ids[1],
        "p1":(0,2),"p2":(3,2),"minimum_value_m":2.5,
    }],refs,"P1")
    assert missing_rule[0]["reason"]=="CODE_CLEARANCE_RULE_ID_REQUIRED"


def test_governed_code_clearance_compares_actual_geometry_in_metres_not_raw_dxf_units():
    doc=ezdxf.new("R2013");doc.header["$INSUNITS"]=4;msp=doc.modelspace()
    msp.add_line((0,0),(0,5000),dxfattribs={"layer":"WALL"})
    msp.add_line((1000,0),(1000,5000),dxfattribs={"layer":"WALL"})
    _add_dim(doc,(0,0),(3000,0),(1500,400),"3000")
    plan={"plan_id":"P1","bounds":(0,0,3000,5000)}
    architecture={"walls":[
        {"plan_id":"P1","start":(0,0),"end":(0,5000)},
        {"plan_id":"P1","start":(1000,0),"end":(1000,5000)},
    ],"shafts":[],"columns":[]}
    refs=build_reference_catalog(doc,plan["bounds"],architecture=architecture,plan_id="P1")
    wall_ids=[r["id"] for r in refs if r["kind"]=="WALL_FACE"]
    board={"bounds":(-500,-500,3500,5500),"plan_area":(0,0,3000,5000),"title_area":(-500,-500,3500,-100)}
    pipeline={"topology":{"nodes":[]},"hvac":{"equipment":[]},"dimension_requirements":[{
        "id":"CLR-MM","plan_id":"P1","purpose":"CODE_CLEARANCE","rule_id":"TEST-RULE-001",
        "reference_a_id":wall_ids[0],"reference_b_id":wall_ids[1],
        "p1":(0,2000),"p2":(1000,2000),"minimum_value_m":0.9,
    }]}
    report=build_and_materialize_plan_dimensions(doc,msp,board,plan,architecture,pipeline,"WATER","GROUND")
    assert report["status"]=="PASS",report
    req=[x for x in report["materialized"] if x["source_kind"]=="GOVERNED_REQUIREMENT"]
    assert len(req)==1
    assert req[0]["measured_value"]==1000.0
    assert req[0]["engineering_value_m"]==1.0

    pipeline["dimension_requirements"][0]["minimum_value_m"]=1.1
    report_fail=build_and_materialize_plan_dimensions(doc,msp,board,plan,architecture,pipeline,"WATER","GROUND")
    assert report_fail["status"]=="FAIL"
    assert "GOVERNED_DIMENSION_REQUIREMENT_INVALID" in report_fail["errors"]
    assert report_fail["governed_requirement_errors"][0]["reason"]=="CODE_CLEARANCE_NOT_SATISFIED"


def test_opposite_envelope_wall_faces_define_overall_but_internal_pair_remains_setout():
    doc=_source_doc()
    _add_dim(doc,(0,4),(10,4),(5,4.5),"10.00")
    architecture={"walls":[
        {"id":"EXT-L","plan_id":"P1","start":(0,0),"end":(0,8),"is_exterior":True},
        {"id":"INT-L","plan_id":"P1","start":(3,0),"end":(3,8)},
        {"id":"INT-R","plan_id":"P1","start":(6,0),"end":(6,8)},
        {"id":"EXT-R","plan_id":"P1","start":(10,0),"end":(10,8),"is_exterior":True},
    ]}
    registry=extract_source_dimension_registry(doc,(0,0,10,8),architecture=architecture,plan_id="P1")
    assert registry["records"][0]["semantic_type"]=="BUILDING_OVERALL"

    doc2=_source_doc()
    _add_dim(doc2,(3,4),(6,4),(4.5,4.5),"3.00")
    registry2=extract_source_dimension_registry(doc2,(0,0,10,8),architecture=architecture,plan_id="P1")
    assert registry2["records"][0]["semantic_type"]=="WALL_SETOUT"


def test_raw_source_dimension_is_not_copied_into_mechanical_board():
    doc=_source_doc()
    source_dim=_add_dim(doc,(0,0),(10,0),(5,.5),"10.00")
    assert _entity_should_copy(source_dim,(0,0,10,8)) is False


def test_context_engine_generates_overall_grid_and_shaft_when_source_dimensions_are_absent():
    doc=_source_doc()
    architecture={
        "walls":[
            {"id":"EXT-L","plan_id":"P1","start":(0,0),"end":(0,8),"is_exterior":True},
            {"id":"EXT-R","plan_id":"P1","start":(10,0),"end":(10,8),"is_exterior":True},
            {"id":"EXT-B","plan_id":"P1","start":(0,0),"end":(10,0),"is_exterior":True},
            {"id":"EXT-T","plan_id":"P1","start":(0,8),"end":(10,8),"is_exterior":True},
        ],
        "grids":[
            {"plan_id":"P1","start":(2,0),"end":(2,8)},
            {"plan_id":"P1","start":(5,0),"end":(5,8)},
            {"plan_id":"P1","start":(8,0),"end":(8,8)},
            {"plan_id":"P1","start":(0,2),"end":(10,2)},
            {"plan_id":"P1","start":(0,6),"end":(10,6)},
        ],
        "shafts":[{"plan_id":"P1","polygon":[(7,3),(8,3),(8,4.5),(7,4.5)]}],
        "columns":[],
    }
    refs=build_reference_catalog(doc,(0,0,10,8),architecture=architecture,plan_id="P1")
    registry=extract_source_dimension_registry(
        doc,(0,0,10,8),architecture=architecture,plan_id="P1",reference_catalog=refs
    )
    intents=context_dimension_intents(refs,registry,"MECHANICAL_PLAN",0.0)
    counts={}
    for row in intents:counts[row["purpose"]]=counts.get(row["purpose"],0)+1
    assert counts["BUILDING_OVERALL"]==2
    assert counts["GRID"]==3
    assert counts["SHAFT"]==2
    assert all(row["source_kind"]=="PLANHA_GENERATED_CONTEXT" for row in intents)


def test_partial_source_grid_chain_is_completed_without_duplicate_reference_pair():
    doc=_source_doc()
    architecture={
        "grids":[
            {"plan_id":"P1","start":(2,0),"end":(2,8)},
            {"plan_id":"P1","start":(5,0),"end":(5,8)},
            {"plan_id":"P1","start":(8,0),"end":(8,8)},
        ],
        "walls":[],
    }
    _add_dim(doc,(2,4),(5,4),(3.5,7.5),"3.00")
    refs=build_reference_catalog(doc,(0,0,10,8),architecture=architecture,plan_id="P1")
    registry=extract_source_dimension_registry(
        doc,(0,0,10,8),architecture=architecture,plan_id="P1",reference_catalog=refs
    )
    assert registry["records"][0]["semantic_type"]=="GRID"
    source=source_dimension_intents(registry,"MECHANICAL_PLAN")
    context=context_dimension_intents(refs,registry,"MECHANICAL_PLAN",0.0)
    selected=select_minimal_dimension_set(source+context)
    grid=[row for row in selected if row["purpose"]=="GRID"]
    assert len(grid)==2
    assert sum(row["source_kind"]=="SOURCE_REGENERATED" for row in grid)==1
    assert sum(row["source_kind"]=="PLANHA_GENERATED_CONTEXT" for row in grid)==1


def test_semantic_dedupe_uses_reference_pair_even_when_graphical_base_differs():
    base={
        "purpose":"GRID","angle_deg":0,
        "reference_a":{"id":"G-A"},"reference_b":{"id":"G-B"},
        "world_p1":(0,0),"world_p2":(3,0),
    }
    rows=[
        {"id":"SOURCE",**base,"world_base":(1.5,-1)},
        {"id":"GENERATED",**base,"world_base":(1.5,-2)},
    ]
    selected=select_minimal_dimension_set(rows)
    assert len(selected)==1
    assert selected[0]["id"]=="SOURCE"


def test_architecture_obstacle_boxes_force_dimension_text_to_alternate_candidate():
    doc=_source_doc();msp=doc.modelspace()
    text=msp.add_text("ROOM",dxfattribs={"height":.35})
    text.dxf.insert=(5.0,4.22)
    board={"bounds":(0,0,10,8),"plan_area":(0,0,10,8),"title_area":(0,0,10,.5)}
    obstacles=entity_obstacle_boxes([text],board)
    assert len(obstacles)==1
    intent={
        "id":"SET-X","purpose":"SETOUT","source_kind":"PLANHA_GENERATED",
        "reference_a":{"id":"M"},"reference_b":{"id":"W"},
        "world_p1":(4,4),"world_p2":(6,4),"world_base":None,
        "measured_value":2.0,"displayed_value":"2.00","required":True,
        "priority":100,"placement_zone":"LOCAL","angle_deg":0.0,
    }
    from cad_engine.semantic_dimension_engine import place_intents
    placed,collisions=place_intents([intent],(0,0,10,8),board,obstacles=obstacles)
    assert collisions==[]
    assert placed[0]["render_base"]!=(5.0,4.22)


def test_planha_owned_dimension_is_not_reingested_as_source_evidence():
    doc=_source_doc();msp=doc.modelspace()
    if APPID not in doc.appids:doc.appids.add(APPID)
    dim=msp.add_linear_dim(base=(5,.5),p1=(0,0),p2=(10,0),angle=0,text="10.00")
    dim.render();dim.dimension.set_xdata(APPID,[(1000,"SEMANTIC_DIMENSION")])
    registry=extract_source_dimension_registry(doc,(0,0,10,8),architecture={},plan_id="P1")
    assert registry["dimension_count"]==0


def test_context_unit_evidence_can_correct_misleading_mm_header_from_unique_metric_plan_bounds():
    doc=ezdxf.new("R2013")
    doc.header["$INSUNITS"]=4
    doc.header["$MEASUREMENT"]=1
    unit=infer_dimension_unit_evidence(doc,(0,0,10,8))
    assert unit["effective_scale_to_m"]==1.0
    assert unit["source"]=="plan-bounds-unique-plausibility"
    assert unit["plan_bounds_plausible"] is True


def test_context_unit_evidence_fails_closed_when_plan_bounds_allow_multiple_unit_interpretations():
    doc=ezdxf.new("R2013")
    doc.header["$INSUNITS"]=0
    doc.header["$MEASUREMENT"]=0
    unit=infer_dimension_unit_evidence(doc,(0,0,10,8))
    assert unit["effective_scale_to_m"] is None
    assert unit["source"]=="plan-bounds-unit-ambiguous"
    assert unit["confidence"]=="low"


def test_context_generation_with_ambiguous_units_cannot_pass_exact_dimension_gate():
    doc=ezdxf.new("R2013")
    doc.header["$INSUNITS"]=0
    doc.header["$MEASUREMENT"]=0
    msp=doc.modelspace()
    plan={"plan_id":"P1","bounds":(0,0,10,8)}
    architecture={"walls":[
        {"id":"EXT-L","plan_id":"P1","start":(0,0),"end":(0,8),"is_exterior":True},
        {"id":"EXT-R","plan_id":"P1","start":(10,0),"end":(10,8),"is_exterior":True},
        {"id":"EXT-B","plan_id":"P1","start":(0,0),"end":(10,0),"is_exterior":True},
        {"id":"EXT-T","plan_id":"P1","start":(0,8),"end":(10,8),"is_exterior":True},
    ],"shafts":[],"columns":[]}
    board={"bounds":(-2,-2,12,10),"plan_area":(0,0,10,8),"title_area":(-2,-2,12,-1)}
    report=build_and_materialize_plan_dimensions(
        doc,msp,board,plan,architecture,
        {"topology":{"nodes":[]},"hvac":{"equipment":[]}},
        "WATER","GROUND",
    )
    assert report["status"]=="FAIL"
    assert "DIMENSION_UNIT_BASIS_REQUIRED" in report["errors"]
    assert report["context_intent_count"]==2


def test_rotated_exterior_envelope_generates_two_local_axis_overall_dimensions():
    doc=_source_doc()
    root=math.sqrt(2)/2
    # 10 x 6 rectangle rotated 45 degrees.
    p0=(0.0,0.0)
    p1=(10*root,10*root)
    p3=(-6*root,6*root)
    p2=(p1[0]+p3[0],p1[1]+p3[1])
    architecture={"walls":[
        {"id":"E1","plan_id":"P1","start":p0,"end":p1,"is_exterior":True},
        {"id":"E2","plan_id":"P1","start":p1,"end":p2,"is_exterior":True},
        {"id":"E3","plan_id":"P1","start":p2,"end":p3,"is_exterior":True},
        {"id":"E4","plan_id":"P1","start":p3,"end":p0,"is_exterior":True},
    ],"grids":[],"shafts":[],"columns":[]}
    bounds=(-5, -1, 8, 12)
    refs=build_reference_catalog(doc,bounds,architecture=architecture,plan_id="P1")
    registry=extract_source_dimension_registry(doc,bounds,architecture=architecture,plan_id="P1",reference_catalog=refs)
    intents=context_dimension_intents(refs,registry,"MECHANICAL_PLAN",math.radians(45))
    overall=[row for row in intents if row["purpose"]=="BUILDING_OVERALL"]
    assert len(overall)==2
    values=sorted(round(row["measured_value"],6) for row in overall)
    assert values==[6.0,10.0]
