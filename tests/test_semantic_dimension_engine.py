import math
import shutil
from pathlib import Path

import ezdxf

from cad_engine.semantic_dimension_engine import (
    APPID,
    _override_status,
    apply_semantic_dimension_engine,
    build_and_materialize_plan_dimensions,
    build_reference_catalog,
    determinacy_intents,
    extract_source_dimension_registry,
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


def test_override_conflict_distinguishes_rounding_material_and_non_numeric_override():
    assert _override_status(2.97657,"3.00")=="MINOR_OVERRIDE"
    assert _override_status(3.23749,"3.25")=="MINOR_OVERRIDE"
    assert _override_status(5.95,"7.00")=="CONFLICT"
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
    assert row["semantic_type"]=="BUILDING_OVERALL"
    assert row["critical"] is True
    assert row["preservation_policy"]=="REGENERATE"
    assert row["conflict"] is None


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
    assert row["override_status"]=="CONFLICT"
    assert row["conflict"]=="DISPLAY_GEOMETRY_CONFLICT"
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
    target={"id":"R-01","point":(5.0,3.0),"kind":"VERTICAL_CONNECTION","priority":100}
    root=math.sqrt(2)/2
    refs=[
        {"id":"G-A","kind":"GRID_AXIS","a":(0,0),"b":(10*root,10*root),"priority":0},
        {"id":"G-1","kind":"GRID_AXIS","a":(0,8),"b":(8*root,-8*root+8),"priority":0},
    ]
    intents,missing=determinacy_intents([target],refs,math.radians(45))
    assert missing==[]
    assert len(intents)==2
    assert all(row["purpose"]=="SETOUT" and row["required"] for row in intents)


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
