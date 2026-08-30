from pathlib import Path
import ezdxf

from cad_engine.authority_architecture_v14 import (
    build_project_model, resolve_design_basis, derive_system_requirements,
    build_reference_driven_manifest, build_network_contract, build_calculation_contract,
    validate_authority_contract,
)
from cad_engine.engineering_runner_v13 import validate_pipeline
from cad_engine.final_delivery_gate_v17 import sanitize_to_approved_boards, validate_final_delivery


def test_design_basis_is_fail_closed_when_user_inputs_missing():
    project=build_project_model({'GROUND':{'wet':True,'habitable':True,'exhaust':True,'gas_appliance':False}},False)
    basis=resolve_design_basis(project,{'city':'Tehran'})
    req=derive_system_requirements(project,basis)
    manifest=build_reference_driven_manifest(project,req)
    qa=validate_authority_contract(project,basis,req,manifest,build_network_contract(req),build_calculation_contract())
    assert basis['status']=='INPUT_REQUIRED'
    assert qa['status']=='FAIL'
    assert any(x.startswith('design_basis_input_required:') for x in qa['errors'])


def test_manifest_contains_only_project_justified_families():
    project=build_project_model({'GROUND':{'wet':True,'habitable':True,'exhaust':False,'gas_appliance':False}},False)
    basis=resolve_design_basis(project,{'city':'Tehran','cooling_system':'wall_mounted_split_ac','heating_system':'package_radiator','gas_service':False})
    req=derive_system_requirements(project,basis)
    manifest=build_reference_driven_manifest(project,req)
    families={x['family'] for x in manifest['sheets']}
    assert 'GAS' not in families
    assert 'ROOF' not in families
    assert 'EXHAUST' not in families
    assert {'COVER','GENERAL_NOTES','SANITARY_VENT','WATER','HEATING','SPLIT_AC','PLUMBING_RISER','WATER_SERVICE_CALC'} <= families


def test_pipeline_rejects_unrouted_or_unsized_topology_edges():
    result={
        'architecture':{'rooms':[{'id':'R1'}],'plans':[{'plan_id':'P1'}],'primary_floor_plan_ids':['P1']},
        'recognition':{'detections':[]},
        'requirements':{'project_systems':['sanitary']},
        'topology':{'edges':[{'id':'E1','system':'sanitary'}],'quality':{'cross_plan_edges':0},'unresolved':[]},
        'routing':{'routes':[],'rejected':[{'edge_id':'E1','reason':'ROUTE_OUTSIDE_PLAN'}],'quality':{'cross_plan_routes':0}},
        'sizing':{'segments':[]},
        'annotations':{'annotations':[]},
        'hvac':{'status':'PASS','equipment':[],'routes':[],'quality':{'cross_plan_routes':0,'out_of_bounds':0}},
    }
    qa=validate_pipeline(result)
    assert qa['status']=='FAIL'
    assert 'unrouted_topology_edges' in qa['errors']
    assert 'rejected_project_routes' in qa['errors']


def test_final_sanitizer_removes_offsheet_source_geometry_and_empty_layout(tmp_path:Path):
    path=tmp_path/'issued.dxf'
    doc=ezdxf.new('R2013'); msp=doc.modelspace()
    # Approved mechanical board: 0..21 x -29.7..0
    msp.add_line((1,-1),(20,-1),dxfattribs={'layer':'0'})
    msp.add_line((1,-5),(20,-5),dxfattribs={'layer':'ENGITOOLS-M-SANITARY'})
    # Typical leaked source architecture far away from generated sheets.
    msp.add_line((3500,-4500),(4100,-4500),dxfattribs={'layer':'SI'})
    msp.add_text('ARCHITECTURAL ELEVATION',dxfattribs={'insert':(3700,-4550),'height':10,'layer':'SI'})
    doc.layouts.new('M-101')  # intentionally empty legacy layout
    doc.saveas(path)
    report={'composition':{'boards':{'M-00':{'bounds':(0,-29.7,21,0)}}}}

    qa=sanitize_to_approved_boards(path,report)
    assert qa['status']=='PASS'
    assert qa['entities_removed']>=2
    assert 'M-101' in qa['empty_layouts_removed']

    exact=validate_final_delivery(path,report)
    assert exact['status']=='PASS'
    assert exact['outside_entity_count']==0
    assert exact['empty_layouts']==[]
    reopened=ezdxf.readfile(path)
    assert all(str(getattr(e.dxf,'layer',''))!='SI' for e in reopened.modelspace())


def test_final_validator_fails_without_approved_board_contract(tmp_path:Path):
    path=tmp_path/'issued.dxf'; doc=ezdxf.new('R2013'); doc.saveas(path)
    qa=validate_final_delivery(path,{'composition':{'boards':{}}})
    assert qa['status']=='FAIL'
    assert 'no_approved_board_bounds' in qa['errors']
