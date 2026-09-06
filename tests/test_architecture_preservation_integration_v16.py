from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import ezdxf
from ezdxf.math import Matrix44

from cad_engine.mechanical_authority_site_v16 import (
    evaluate_architecture_preservation,
    _entities_in_output_board,
    design_mechanical_authority_site,
    _match_transformed_architecture,
    _snapshot_in_source_coordinates,
)
from cad_engine.architecture_preservation_gate_v16 import validate_topology
from cad_engine.mechanical_release_contract_v16 import release_contract_status
from cad_engine.main_v16 import app

SRC_BOUNDS=(0.0,0.0,10.0,10.0)
PLAN_AREA=(20.0,20.0,36.0,36.0)


def source_doc(path:Path):
    doc=ezdxf.new('R2010')
    for layer in ('WALL','DOOR','WINDOW','SHAFT'):
        if layer not in doc.layers: doc.layers.add(layer)
    m=doc.modelspace()
    # Deliberately put one wall and the door at the very bottom of the plan.
    # This is the regression that previously caused M-15 architectural loss.
    m.add_line((1,1),(9,1),dxfattribs={'layer':'WALL'})
    m.add_line((9,1),(9,9),dxfattribs={'layer':'WALL'})
    m.add_line((9,9),(1,9),dxfattribs={'layer':'WALL'})
    m.add_line((1,9),(1,1),dxfattribs={'layer':'WALL'})
    m.add_line((4.2,1),(5.2,1),dxfattribs={'layer':'DOOR'})
    m.add_line((9,4),(9,5),dxfattribs={'layer':'WINDOW'})
    m.add_lwpolyline([(7,6),(8,6),(8,7),(7,7)],close=True,dxfattribs={'layer':'SHAFT'})
    doc.saveas(path)


def pipeline():
    return {
        'architecture':{
            'plans':[{'plan_id':'PLAN-01','bounds':list(SRC_BOUNDS),'level':'GROUND','mechanical_role':'PRIMARY_FLOOR'}],
            'primary_floor_plan_ids':['PLAN-01'],'rooms':[],'walls':[],
        },
        'recognition':{'detections':[]},
        'routing':{'routes':[]},'sizing':{'segments':[]},
        'hvac':{'equipment':[],'routes':[]},
    }


def report():
    return {
        'status':'PASS','dxf_qa':{'status':'PASS'},
        'composition':{
            'manifest':[{'old_sheet':'M-05','code':'M-101','family':'SANITARY_VENT','level':'GROUND'}],
            'boards':{'M-05':{'plan_area':list(PLAN_AREA),'bounds':[19,17,37,40]}},
        },
    }


def transformed_output(src:Path,dst:Path,drop_layer=None):
    s=ezdxf.readfile(src); out=ezdxf.new('R2010')
    for layer in ('WALL','DOOR','WINDOW','SHAFT'):
        if layer not in out.layers: out.layers.add(layer)
    sm=s.modelspace(); om=out.modelspace()
    sx1,sy1,sx2,sy2=SRC_BOUNDS; tx1,ty1,tx2,ty2=PLAN_AREA
    scale=min((tx2-tx1)/(sx2-sx1),(ty2-ty1)/(sy2-sy1)); dx=tx1; dy=ty1
    M=Matrix44.chain(Matrix44.translate(-sx1,-sy1,0),Matrix44.scale(scale,scale,1),Matrix44.translate(dx,dy,0))
    for e in sm:
        if drop_layer and e.dxf.layer==drop_layer: continue
        c=e.copy(); c.transform(M); om.add_entity(c)
    out.saveas(dst)


class ArchitecturePreservationIntegrationV16(unittest.TestCase):
    def test_dense_topology_is_compared_in_source_coordinates(self):
        before={'entities':[
            {'semantic_class':'WALL','bbox':(0.0,0.0,10.0,0.0)},
            {'semantic_class':'WALL','bbox':(10.001,0.0,20.0,0.0)},
        ]}
        target=(100.0,100.0,101.0,101.0)
        after={'entities':[
            {'semantic_class':'WALL','bbox':(100.0,100.0,100.5,100.0)},
            {'semantic_class':'WALL','bbox':(100.50005,100.0,101.0,100.0)},
        ]}
        self.assertFalse(validate_topology(before,after)['pass'])
        normalized=_snapshot_in_source_coordinates(after,(0.0,0.0,20.0,20.0),target)
        self.assertTrue(validate_topology(before,normalized)['pass'])

    def test_preserved_copy_order_avoids_dense_greedy_mismatch(self):
        def rec(key,bbox):
            return {'key':key,'criticality':'CRITICAL','entity_type':'LWPOLYLINE',
                    'semantic_class':'UNKNOWN_GEOMETRY','layer':'0','bbox':bbox}
        before={'entities':[rec('a',(0,0,1,1)),rec('b',(0.09,0,1.09,1))]}
        after={'entities':[rec('x',(20,20,21,21)),rec('y',(20.09,20,21.09,21))]}
        result=_match_transformed_architecture(before,after,(0,0,16,16),(20,20,36,36))
        self.assertTrue(result['pass'],result)
        self.assertEqual(result['strategy'],'exact_transformed_geometry')

    def test_release_contract_and_entrypoint_are_v16(self):
        status=release_contract_status()
        self.assertEqual(status['status'],'PASS',status)
        self.assertEqual(status['version'],'16.0.0')
        self.assertTrue(status['checks']['production_architecture_preservation_transaction'])
        paths={getattr(r,'path',None) for r in app.routes}
        self.assertIn('/architecture_preservation',paths)
        self.assertIn('/mechanical_release',paths)

    def test_bottom_wall_and_door_are_preserved(self):
        with TemporaryDirectory() as td:
            src=Path(td)/'src.dxf'; dst=Path(td)/'out.dxf'; source_doc(src); transformed_output(src,dst)
            with patch('cad_engine.mechanical_authority_site_v16.run_engineering_pipeline',return_value=pipeline()):
                qa=evaluate_architecture_preservation(src,dst,report(),answers={})
            self.assertEqual(qa['status'],'PASS',qa)
            self.assertEqual(qa['critical_missing_count'],0)
            sheet=qa['sheet_results'][0]
            self.assertEqual(sheet['preservation_match']['protected_source_count'],sheet['preservation_match']['matched_count'])

    def test_missing_bottom_door_blocks_delivery(self):
        with TemporaryDirectory() as td:
            src=Path(td)/'src.dxf'; dst=Path(td)/'out.dxf'; source_doc(src); transformed_output(src,dst,drop_layer='DOOR')
            with patch('cad_engine.mechanical_authority_site_v16.run_engineering_pipeline',return_value=pipeline()):
                qa=evaluate_architecture_preservation(src,dst,report(),answers={})
            self.assertEqual(qa['status'],'FAIL',qa)
            self.assertGreaterEqual(qa['critical_missing_count'],1)
            self.assertEqual(qa['action'],'ROLLBACK_AND_BLOCK_DELIVERY')

    def test_transaction_removes_failed_new_output(self):
        with TemporaryDirectory() as td:
            src=Path(td)/'src.dxf'; dst=Path(td)/'out.dxf'; source_doc(src)
            def fake_design(src_path,dst_path,answers=None,plan_analysis=None):
                transformed_output(Path(src_path),Path(dst_path),drop_layer='DOOR')
                return report()
            with patch('cad_engine.mechanical_authority_site_v16._design_v15',side_effect=fake_design), \
                 patch('cad_engine.mechanical_authority_site_v16.run_engineering_pipeline',return_value=pipeline()):
                result=design_mechanical_authority_site(src,dst,answers={})
            self.assertEqual(result['status'],'FAIL')
            self.assertEqual(result['stage'],'architecture_preservation_gate')
            self.assertFalse(dst.exists(), 'failed output must not be deliverable')

    def test_output_board_selects_large_block_by_insert_point(self):
        doc=ezdxf.new('R2010')
        block=doc.blocks.new('DISTANT_GEOMETRY')
        block.add_line((0,0),(1000,1000))
        inserted=doc.modelspace().add_blockref('DISTANT_GEOMETRY',(5,5),dxfattribs={'layer':'0'})
        selected=_entities_in_output_board(doc,(0,0,10,10),{'0'})
        self.assertIn(inserted,selected)


if __name__=='__main__': unittest.main()
