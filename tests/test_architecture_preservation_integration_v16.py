from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import ezdxf
from ezdxf.math import Matrix44

from cad_engine.mechanical_authority_site_v16 import (
    evaluate_architecture_preservation,
    design_mechanical_authority_site,
)
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


if __name__=='__main__': unittest.main()
