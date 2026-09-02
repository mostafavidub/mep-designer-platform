import tempfile
import unittest
from pathlib import Path
import ezdxf

from cad_engine.authority_architecture_v14 import (
    build_project_model, resolve_design_basis, derive_system_requirements,
    build_reference_driven_manifest, build_network_contract, build_calculation_contract,
    validate_authority_contract,
)
from cad_engine.system_requirements_v13 import derive_system_requirements as derive_pipeline_requirements
from cad_engine.engineering_runner_v13 import validate_pipeline
from cad_engine.final_delivery_gate_v17 import sanitize_to_approved_boards, validate_final_delivery
from cad_engine.mechanical_authority_site_v17 import validate_approved_manifest, _release_input_errors


class FinalMechanicalDeliveryGateV17Tests(unittest.TestCase):
    def test_release_input_gate_rejects_failed_engineering_acceptance(self):
        report={
            'pipeline_qa':{'status':'PASS','errors':[]},
            'engineering_acceptance':{'status':'FAIL','errors':['routing:non_orthogonal_route']},
            'authority':{'design_basis':{'status':'PASS'}},
            'enrichment':{},
        }
        self.assertIn(
            'engineering_acceptance:routing:non_orthogonal_route',
            _release_input_errors(report),
        )

    def test_design_basis_is_fail_closed_when_user_inputs_missing(self):
        project=build_project_model({'GROUND':{'wet':True,'habitable':True,'exhaust':True,'gas_appliance':False}},False)
        basis=resolve_design_basis(project,{'city':'Tehran'})
        req=derive_system_requirements(project,basis)
        manifest=build_reference_driven_manifest(project,req,basis)
        qa=validate_authority_contract(project,basis,req,manifest,build_network_contract(req),build_calculation_contract())
        self.assertEqual(basis['status'],'INPUT_REQUIRED')
        self.assertIn('cooling_system',basis['missing']);self.assertIn('heating_system',basis['missing']);self.assertIn('water_inlet_pressure',basis['missing'])
        self.assertEqual(qa['status'],'FAIL')

    def test_design_basis_requires_project_specific_pressures_and_rainfall(self):
        project=build_project_model({'GROUND':{'wet':True,'habitable':True,'exhaust':True,'gas_appliance':True}},True)
        basis=resolve_design_basis(project,{'city':'Tehran','cooling_system':'wall_mounted_split_ac','heating_system':'package_radiator','gas_service':True,'water_inlet_pressure':'2.5 bar','rainfall_intensity':'75 mm/h'})
        self.assertEqual(basis['status'],'INPUT_REQUIRED');self.assertIn('gas_service_pressure',basis['missing'])
        basis=resolve_design_basis(project,{'city':'Tehran','cooling_system':'wall_mounted_split_ac','heating_system':'package_radiator','gas_service':True,'gas_service_pressure':'22 mbar','water_inlet_pressure':'2.5 bar','rainfall_intensity':'75 mm/h'})
        self.assertEqual(basis['status'],'PASS')

    def test_pipeline_requirements_do_not_invent_optional_systems_from_room_type(self):
        architecture={'rooms':[{'id':'K1','type':'kitchen'},{'id':'L1','type':'living'}]};recognition={'detections':[]}
        req=derive_pipeline_requirements(architecture,recognition,design_basis={});systems=set(req['project_systems'])
        self.assertNotIn('gas',systems);self.assertNotIn('heating',systems);self.assertNotIn('cooling',systems)
        self.assertTrue({'cold_water','hot_water','sanitary','vent','exhaust'} <= systems)

    def test_pipeline_requirements_activate_only_locked_optional_systems(self):
        architecture={'rooms':[{'id':'K1','type':'kitchen'},{'id':'L1','type':'living'}]};recognition={'detections':[]}
        req=derive_pipeline_requirements(architecture,recognition,design_basis={'cooling_system':'wall_mounted_split_ac','heating_system':'package_radiator','gas_service':True})
        self.assertTrue({'gas','heating','cooling'} <= set(req['project_systems']))

    def test_manifest_contains_only_project_justified_families(self):
        project=build_project_model({'GROUND':{'wet':True,'habitable':True,'exhaust':False,'gas_appliance':False}},False)
        basis=resolve_design_basis(project,{'city':'Tehran','cooling_system':'wall_mounted_split_ac','heating_system':'package_radiator','gas_service':False,'water_inlet_pressure':'2.5 bar','water_service_mode':'direct_city'})
        req=derive_system_requirements(project,basis);manifest=build_reference_driven_manifest(project,req,basis);families={x['family'] for x in manifest['sheets']}
        self.assertNotIn('GAS',families);self.assertNotIn('ROOF',families);self.assertNotIn('EXHAUST',families);self.assertNotIn('WATER_SERVICE_CALC',families)
        self.assertTrue({'COVER','GENERAL_NOTES','SANITARY_VENT','WATER','HEATING','SPLIT_AC','PLUMBING_RISER'} <= families)

    def test_manifest_adds_water_service_only_when_project_requires_it(self):
        project=build_project_model({'GROUND':{'wet':True,'habitable':False,'exhaust':False,'gas_appliance':False}},False)
        basis={'basis':{'water_service_mode':'tank_pump'}};req={'project_systems':['cold_water','hot_water','sanitary','vent'],'by_level':{'GROUND':['cold_water','hot_water','sanitary','vent']}}
        manifest=build_reference_driven_manifest(project,req,basis);families=[x['family'] for x in manifest['sheets']]
        self.assertIn('WATER_SERVICE_CALC',families);self.assertTrue(any(x['family']=='WATER' and x['level']=='SERVICE' for x in manifest['sheets']))

    def test_pipeline_rejects_unrouted_or_unsized_topology_edges(self):
        result={'architecture':{'rooms':[{'id':'R1'}],'plans':[{'plan_id':'P1'}],'primary_floor_plan_ids':['P1']},'recognition':{'detections':[]},'requirements':{'project_systems':['sanitary']},'topology':{'edges':[{'id':'E1','system':'sanitary'}],'quality':{'cross_plan_edges':0},'unresolved':[]},'routing':{'routes':[],'rejected':[{'edge_id':'E1','reason':'ROUTE_OUTSIDE_PLAN'}],'quality':{'cross_plan_routes':0}},'sizing':{'segments':[]},'annotations':{'annotations':[]},'hvac':{'status':'PASS','equipment':[],'routes':[],'quality':{'cross_plan_routes':0,'out_of_bounds':0}},'design_basis':{}}
        qa=validate_pipeline(result);self.assertEqual(qa['status'],'FAIL');self.assertIn('unrouted_topology_edges',qa['errors']);self.assertIn('rejected_project_routes',qa['errors']);self.assertIn('missing_project_endpoint_evidence:sanitary',qa['errors'])

    def test_pipeline_rejects_route_sizing_without_real_load_and_slope(self):
        result={'architecture':{'rooms':[{'id':'R1'}],'plans':[{'plan_id':'P1'}],'primary_floor_plan_ids':['P1']},'recognition':{'detections':[{'id':'F1','type':'wc','category':'fixture','plan_id':'P1'}]},'requirements':{'project_systems':['sanitary']},'topology':{'edges':[{'id':'E1','system':'sanitary'}],'quality':{'cross_plan_edges':0},'unresolved':[]},'routing':{'routes':[{'id':'R1','edge_id':'E1','system':'sanitary','plan_id':'P1','points':[(0,0),(1,0)],'length':1.0}],'rejected':[],'quality':{'cross_plan_routes':0}},'sizing':{'segments':[{'route_id':'R1','system':'sanitary','size_mm':75,'downstream_load':0,'slope_percent':0}]},'annotations':{'annotations':[{'route_id':'R1'}]},'hvac':{'status':'PASS','equipment':[],'routes':[],'quality':{'cross_plan_routes':0,'out_of_bounds':0}},'design_basis':{}}
        qa=validate_pipeline(result);self.assertEqual(qa['status'],'FAIL');self.assertIn('sanitary_route_without_slope',qa['errors']);self.assertIn('route_sizing_without_project_load',qa['errors'])

    def test_approved_web_manifest_rejects_generated_unapproved_gas_family(self):
        report={'composition':{'manifest':[
            {'family':'SANITARY_VENT','level':'GROUND','purpose':'PLAN','sheet':'M-01'},
            {'family':'GAS','level':'GROUND','purpose':'PLAN','sheet':'M-02'},
        ]}}
        approved={'schema_version':'3.0','sheets':[
            {'family':'sanitary_vent','code':'M-S-01','pattern':'GROUND','levels':['GROUND'],'drawing_type':'floor_plan','special':False},
        ]}
        qa=validate_approved_manifest(report,{'_approved_drawing_manifest':approved})
        self.assertEqual(qa['status'],'FAIL')
        self.assertIn('generated_unapproved_system_families:GAS',qa['errors'])

    def test_approved_web_manifest_accepts_canonical_family_and_count_match(self):
        report={'composition':{'manifest':[
            {'family':'WATER','level':'GROUND','purpose':'PLAN','sheet':'M-01'},
            {'family':'SANITARY_VENT','level':'GROUND','purpose':'PLAN','sheet':'M-02'},
            {'family':'PLUMBING_RISER','level':'MULTI','purpose':'RISER','sheet':'M-03'},
            {'family':'GENERAL_NOTES','level':'MULTI','purpose':'NOTES','sheet':'M-04'},
        ]}}
        approved={'schema_version':'3.0','sheets':[
            {'family':'water_supply','code':'M-W-01','pattern':'GROUND','levels':['GROUND'],'drawing_type':'floor_plan','special':False},
            {'family':'sanitary_vent','code':'M-S-01','pattern':'GROUND','levels':['GROUND'],'drawing_type':'floor_plan','special':False},
        ]}
        qa=validate_approved_manifest(report,{'_approved_drawing_manifest':approved})
        self.assertEqual(qa['status'],'PASS',qa)
        self.assertEqual(qa['approved_primary_counts'],{'WATER':1,'SANITARY_VENT':1})
        self.assertEqual(qa['generated_primary_counts'],{'WATER':1,'SANITARY_VENT':1})

    def test_approved_web_manifest_rejects_primary_plan_count_mismatch(self):
        report={'composition':{'manifest':[
            {'family':'WATER','level':'GROUND','purpose':'PLAN','sheet':'M-01'},
            {'family':'WATER','level':'LEVEL-01','purpose':'PLAN','sheet':'M-02'},
        ]}}
        approved={'schema_version':'3.0','sheets':[
            {'family':'water_supply','code':'M-W-01','pattern':'GROUND','levels':['GROUND'],'drawing_type':'floor_plan','special':False},
        ]}
        qa=validate_approved_manifest(report,{'_approved_drawing_manifest':approved})
        self.assertEqual(qa['status'],'FAIL');self.assertTrue(any(x.startswith('primary_plan_count_mismatch:WATER:') for x in qa['errors']))

    def test_final_sanitizer_removes_offsheet_source_geometry_and_empty_layout(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'issued.dxf';doc=ezdxf.new('R2013');msp=doc.modelspace()
            msp.add_line((1,-1),(20,-1),dxfattribs={'layer':'0'});msp.add_line((1,-5),(20,-5),dxfattribs={'layer':'ENGITOOLS-M-SANITARY'})
            msp.add_line((3500,-4500),(4100,-4500),dxfattribs={'layer':'SI'});text=msp.add_text('ARCHITECTURAL ELEVATION',dxfattribs={'height':10,'layer':'SI'});text.dxf.insert=(3700,-4550)
            doc.layouts.new('M-101');doc.saveas(path);report={'composition':{'boards':{'M-00':{'bounds':(0,-29.7,21,0)}}}}
            qa=sanitize_to_approved_boards(path,report);self.assertEqual(qa['status'],'PASS');self.assertGreaterEqual(qa['entities_removed'],2);self.assertIn('M-101',qa['empty_layouts_removed'])
            exact=validate_final_delivery(path,report);self.assertEqual(exact['status'],'PASS');self.assertEqual(exact['outside_entity_count'],0);self.assertEqual(exact['empty_layouts'],[])
            reopened=ezdxf.readfile(path);self.assertTrue(all(str(getattr(e.dxf,'layer',''))!='SI' for e in reopened.modelspace()))

    def test_final_validator_fails_without_approved_board_contract(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'issued.dxf';doc=ezdxf.new('R2013');doc.saveas(path)
            qa=validate_final_delivery(path,{'composition':{'boards':{}}});self.assertEqual(qa['status'],'FAIL');self.assertIn('no_approved_board_bounds',qa['errors'])


if __name__=='__main__':unittest.main()
