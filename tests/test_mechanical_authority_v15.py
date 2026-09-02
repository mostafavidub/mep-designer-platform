from pathlib import Path

import ezdxf

from cad_engine.mechanical_authority_v15 import (
    build_design_overrides,
    _sheet_code,
    compose_authority_dxf,
    qa_authority_dxf,
)
from cad_engine.authority_architecture_v14 import (
    build_project_model,
    resolve_design_basis,
    derive_system_requirements,
    build_reference_driven_manifest,
    build_network_contract,
    build_calculation_contract,
    validate_authority_contract,
)


def test_design_overrides_maps_site_answers():
    x=build_design_overrides({
        "location":"ایران، گنبد کاووس",
        "cooling":"کولر گازی / اسپلیت",
        "heating":"پکیج و رادیاتور",
        "gas":"دارد",
    })
    assert x["city"]=="گنبد کاووس"
    assert x["cooling_system"]=="wall_mounted_split_ac"
    assert x["heating_system"]=="package_radiator"
    assert x["gas_service"] is True


def test_project_contract_canonical_answers_are_consumed_without_rewording():
    x=build_design_overrides({
        'location':'Gonbad-e Kavus',
        'cooling':'wall_mounted_split_ac',
        'heating':'package_radiator',
        'gas_service':True,
        'gas_service_pressure_mbar':17.6,
        'water_inlet_pressure_bar':2.5,
        'rainfall_intensity_mm_h':110,
        'water_service_mode':'direct_city',
        'outdoor_unit_location':'ROOF',
        'mechanical_shaft_route':'propose_near_wet_core',
    })
    assert x['cooling_system']=='wall_mounted_split_ac'
    assert x['heating_system']=='package_radiator'
    assert x['gas_service'] is True
    assert x['gas_service_pressure']==17.6
    assert x['water_inlet_pressure']==2.5
    assert x['water_service_mode']=='direct_city'
    assert x['rainfall_intensity']==110
    assert x['mechanical_shaft_route']=='propose_near_wet_core'


def test_sheet_codes_are_systematic():
    assert _sheet_code("SANITARY_VENT","GROUND",1)=="M-101"
    assert _sheet_code("WATER","LEVEL-01",1)=="M-112"
    assert _sheet_code("HEATING","LEVEL-02",1)=="M-133"
    assert _sheet_code("SPLIT_AC","ROOF",1)=="M-164"
    assert _sheet_code("EXHAUST","GROUND",1)=="M-171"


def test_service_equipment_board_does_not_require_fabricated_north(tmp_path):
    path=tmp_path/'service.dxf'
    doc=ezdxf.new('R2010')
    doc.modelspace().add_line((1,1),(2,1),dxfattribs={'layer':'ENGITOOLS-M-WATER-SERVICE'})
    doc.saveas(path)
    composition={
        'copy_failures':[],
        'north':{},
        'boards':{'B1':{
            'sheet':'B1','code':'M-114','title':'Water service','family':'WATER','level':'SERVICE',
            'bounds':(0,0,10,10),'plan_area':(0,0,8,8),
            'subtitle_area':(0,8,8,9),'title_area':(0,9,10,10),
        }},
    }
    result=qa_authority_dxf(path,composition)
    assert not any(error.startswith('architectural_north_missing') for error in result['errors'])


def _synthetic_source(path: Path):
    doc=ezdxf.new("R2010")
    msp=doc.modelspace()
    if "suport" not in doc.layers:
        doc.layers.add("suport")
    if "WALL" not in doc.layers:
        doc.layers.add("WALL")
    msp.add_lwpolyline([(0,0),(21,0),(21,29.7),(0,29.7)],close=True,dxfattribs={"layer":"suport"})
    msp.add_lwpolyline([(30,0),(51,0),(51,29.7),(30,29.7)],close=True,dxfattribs={"layer":"suport"})
    for a,b in [((3,5),(18,5)),((18,5),(18,24)),((18,24),(3,24)),((3,24),(3,5)),((10,5),(10,24))]:
        msp.add_line(a,b,dxfattribs={"layer":"WALL"})
    msp.add_text("پلان معماری طبقه همکف",dxfattribs={"height":.25}).set_placement((6,2))
    msp.add_text("آشپزخانه",dxfattribs={"height":.25}).set_placement((6,18))
    msp.add_text("خواب",dxfattribs={"height":.25}).set_placement((13,18))
    msp.add_text("حمام",dxfattribs={"height":.25}).set_placement((6,10))
    msp.add_line((17.0,26.0),(17.0,27.0))
    msp.add_line((16.5,26.5),(17.5,26.5))
    msp.add_circle((17.0,26.5),.5)
    msp.add_text("N",dxfattribs={"height":.25}).set_placement((16.8,28.0))
    msp.add_text("پلان شیب بندی بام",dxfattribs={"height":.25}).set_placement((36,2))
    msp.add_lwpolyline([(33,5),(48,5),(48,24),(33,24)],close=True,dxfattribs={"layer":"WALL"})
    msp.add_line((47,26),(47,27))
    msp.add_circle((47,26.5),.5)
    msp.add_text("N",dxfattribs={"height":.25}).set_placement((46.8,28.0))
    doc.saveas(path)


def test_composer_creates_integrated_project_driven_package(tmp_path):
    src=tmp_path/"arch.dxf"
    dst=tmp_path/"out.dxf"
    _synthetic_source(src)

    pipeline={
        "architecture":{
            "plans":[
                {"plan_id":"PLAN-01","bounds":[0,0,21,29.7],"drawing_type":"ARCH_FLOOR_PLAN","level":"GROUND","mechanical_role":"PRIMARY_FLOOR"},
                {"plan_id":"PLAN-02","bounds":[30,0,51,29.7],"drawing_type":"ROOF_PLAN","level":"ROOF","mechanical_role":"ROOF_SUPPORT"},
            ],
            "primary_floor_plan_ids":["PLAN-01"],
            "rooms":[
                {"id":"ROOM-1","type":"kitchen","label_point":(6,18),"plan_id":"PLAN-01"},
                {"id":"ROOM-2","type":"bedroom","label_point":(13,18),"plan_id":"PLAN-01"},
                {"id":"ROOM-3","type":"bathroom","label_point":(6,10),"plan_id":"PLAN-01"},
            ],
            "walls":[
                {"start":(3,5),"end":(18,5)},{"start":(18,5),"end":(18,24)},
                {"start":(18,24),"end":(3,24)},{"start":(3,24),"end":(3,5)},
            ],
            "quality":{"excluded_frame_count":0},
        },
        "recognition":{"detections":[]},
        "routing":{"routes":[
            {"id":"R1","system":"sanitary","plan_id":"PLAN-01","points":[(6,10),(8,10),(8,12)]},
            {"id":"R2","system":"cold_water","plan_id":"PLAN-01","points":[(6,18),(8,18),(8,12)]},
        ]},
        "sizing":{"segments":[
            {"route_id":"R1","system":"sanitary","size_mm":63,"slope_percent":2.0},
            {"route_id":"R2","system":"cold_water","size_mm":20},
        ]},
        "hvac":{
            "equipment":[
                {"id":"AC-I-PLAN-01-01","kind":"split_indoor","plan_id":"PLAN-01","point":(13,18),"capacity_btu_h":12000},
                {"id":"RAD-PLAN-01-01","kind":"radiator","plan_id":"PLAN-01","point":(13,18),"capacity_kw":1.5},
            ],
            "routes":[
                {"id":"REF-1","system":"refrigerant","plan_id":"PLAN-01","points":[(13,18),(16,18),(16,22)]},
                {"id":"COND-1","system":"condensate","plan_id":"PLAN-01","points":[(13,18),(8,18),(8,12)]},
            ],
        },
    }

    project=build_project_model(
        levels={"GROUND":{"plan_id":"PLAN-01","bounds":[0,0,21,29.7],"wet":True,"habitable":True,"exhaust":True,"gas_appliance":True}},
        roof_present=True,
        occupancy="residential",
    )
    basis=resolve_design_basis(project,{
        "city":"Test City","cooling_system":"wall_mounted_split_ac",
        "heating_system":"package_radiator","gas_service":True,
    })
    req=derive_system_requirements(project,basis)
    manifest=build_reference_driven_manifest(project,req)
    network=build_network_contract(req)
    calc=build_calculation_contract()
    authority={
        "project":project,"design_basis":basis,"requirements":req,"manifest":manifest,
        "network":network,"calculation_contract":calc,
        "authority_qa":validate_authority_contract(project,basis,req,manifest,network,calc),
    }
    report=compose_authority_dxf(src,dst,pipeline,authority,{"project_name":"Synthetic Project"})
    assert dst.exists()
    assert not report["copy_failures"]
    qa=qa_authority_dxf(dst,report)
    assert qa["status"]=="PASS", qa
    assert qa["metrics"]["titleblock_overlap"]==0
    assert qa["metrics"]["north_from_architecture"]>=1
