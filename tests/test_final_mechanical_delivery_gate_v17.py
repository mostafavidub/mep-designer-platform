import tempfile
import unittest
from pathlib import Path
import ezdxf

from cad_engine.authority_architecture_v14 import (
    build_project_model, resolve_design_basis, derive_system_requirements,
    build_reference_driven_manifest, build_network_contract, build_calculation_contract,
    validate_authority_contract,
)
from cad_engine.engineering_runner_v13 import validate_pipeline
from cad_engine.final_delivery_gate_v17 import sanitize_to_approved_boards, validate_final_delivery


class FinalMechanicalDeliveryGateV17Tests(unittest.TestCase):
    def test_design_basis_is_fail_closed_when_user_inputs_missing(self):
        project=build_project_model({'GROUND':{'wet':True,'habitable':True,'exhaust':True,'gas_appliance':False}},False)
        basis=resolve_design_basis(project,{'city':'Tehran'})
        req=derive_system_requirements(project,basis)
        manifest=build_reference_driven_manifest(project,req)
        qa=validate_authority_contract(project,basis,req,manifest,build_network_contract(req),build_calculation_contract())
        self.assertEqual(basis['status'],'INPUT_REQUIRED')
        self.assertEqual(qa['status'],'FAIL')
        self.assertTrue(any(x.startswith('design_basis_input_required:') for x in qa['errors']))

    def test_manifest_contains_only_project_justified_families(self):
        project=build_project_model({'GROUND':{'wet':True,'habitable':True,'exhaust':False,'gas_appliance':False}},False)
        basis=resolve_design_basis(project,{'city':'Tehran','cooling_system':'wall_mounted_split_ac','heating_system':'package_radiator','gas_service':False})
        req=derive_system_requirements(project,basis)
        manifest=build_reference_driven_manifest(project,req)
        families={x['family'] for x in manifest['sheets']}
        self.assertNotIn('GAS',families); self.assertNotIn('ROOF',families); self.assertNotIn('EXHAUST',families)
        required={'COVER','GENERAL_NOTES','SANITARY_VENT','WATER','HEATING','SPLIT_AC','PLUMBING_RISER','WATER_SERVICE_CALC'}
        self.assertTrue(required <= families)

    def test_pipeline_rejects_unrouted_or_unsized_topology_edges(self):
        result={
            'architecture':{'rooms':[{'id':'R1'}],'plans':[{'plan_id':'P1'}],'primary_floor_plan_ids':['P1']},
            'recognition':{'detections':[]},
            'requirements':{'project_systems':['sanitary']},
            'topology':{'edges':[{'id':'E1','system':'sanitary'}],'quality':{'cross_plan_edges':0},'unresolved':[]},
            'routing':{'routes':[],'rejected':[{'edge_id':'E1','reason':'ROUTE_OUTSIDE_PLAN'}],'quality':{'cross_plan_routes':0}},
            'sizing':{'segments':[]}, 'annotations':{'annotations':[]},
            'hvac':{'status':'PASS','equipment':[],'routes':[],'quality':{'cross_plan_routes':0,'out_of_bounds':0}},
        }
        qa=validate_pipeline(result)
        self.assertEqual(qa['status'],'FAIL')
        self.assertIn('unrouted_topology_edges',qa['errors'])
        self.assertIn('rejected_project_routes',qa['errors'])

    def test_final_sanitizer_removes_offsheet_source_geometry_and_empty_layout(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'issued.dxf'
            doc=ezdxf.new('R2013'); msp=doc.modelspace()
            msp.add_line((1,-1),(20,-1),dxfattribs={'layer':'0'})
            msp.add_line((1,-5),(20,-5),dxfattribs={'layer':'ENGITOOLS-M-SANITARY'})
            msp.add_line((3500,-4500),(4100,-4500),dxfattribs={'layer':'SI'})
            text=msp.add_text('ARCHITECTURAL ELEVATION',dxfattribs={'height':10,'layer':'SI'}); text.dxf.insert=(3700,-4550)
            doc.layouts.new('M-101'); doc.saveas(path)
            report={'composition':{'boards':{'M-00':{'bounds':(0,-29.7,21,0)}}}}
            qa=sanitize_to_approved_boards(path,report)
            self.assertEqual(qa['status'],'PASS')
            self.assertGreaterEqual(qa['entities_removed'],2)
            self.assertIn('M-101',qa['empty_layouts_removed'])
            exact=validate_final_delivery(path,report)
            self.assertEqual(exact['status'],'PASS')
            self.assertEqual(exact['outside_entity_count'],0)
            self.assertEqual(exact['empty_layouts'],[])
            reopened=ezdxf.readfile(path)
            self.assertTrue(all(str(getattr(e.dxf,'layer',''))!='SI' for e in reopened.modelspace()))

    def test_final_validator_fails_without_approved_board_contract(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'issued.dxf'; doc=ezdxf.new('R2013'); doc.saveas(path)
            qa=validate_final_delivery(path,{'composition':{'boards':{}}})
            self.assertEqual(qa['status'],'FAIL')
            self.assertIn('no_approved_board_bounds',qa['errors'])


if __name__=='__main__':
    unittest.main()
