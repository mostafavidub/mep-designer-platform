import unittest
import tempfile
from pathlib import Path
import ezdxf
from ezdxf.math import Matrix44
from cad_engine.mechanical_authority_v15 import (
    _new_composition_document, _clone_entities, _draw_plan_overlay, _boards,
)
from cad_engine.reference_parity_engine_v17 import ProjectContext, select_details


class CompositionEvidenceHandoffTests(unittest.TestCase):
    def test_source_is_immutable_and_destination_contains_only_composed_geometry(self):
        source=ezdxf.new('R2010')
        source.layers.new('WALL')
        source.blocks.new('WINDOW').add_line((0,0),(1,0),dxfattribs={'layer':'WALL'})
        source.modelspace().add_blockref('WINDOW',(3,3))
        source.modelspace().add_line((1,1),(2,1),dxfattribs={'layer':'WALL'})
        source.modelspace().add_line((100,100),(110,100),dxfattribs={'layer':'WALL'})
        source.layouts.new('SOURCE-SUPPORT')
        handles=[e.dxf.handle for e in source.modelspace()]
        doc,archive=_new_composition_document(source,[{'bounds':[0,0,10,10]}])
        self.assertEqual(len(doc.modelspace()),0)
        self.assertEqual(len(archive),2)
        copied,failed=_clone_entities(doc.modelspace(),list(archive),Matrix44.translate(20,20,0))
        self.assertFalse(failed)
        self.assertEqual(len(copied),2)
        self.assertEqual([e.dxf.handle for e in source.modelspace()],handles)
        self.assertIn('SOURCE-SUPPORT',source.layouts)
        self.assertNotIn('SOURCE-SUPPORT',doc.layouts)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'candidate.dxf';doc.saveas(path)
            reopened=ezdxf.readfile(path)
            self.assertEqual(len(reopened.modelspace()),2)
            self.assertFalse(reopened.audit().has_errors)
            insert=list(reopened.modelspace().query('INSERT'))[0]
            self.assertEqual(tuple(insert.dxf.insert)[:2],(23,23))
            self.assertEqual(len(reopened.blocks[insert.dxf.name]),1)

    def test_no_roof_draws_only_real_plan_local_outdoor_unit(self):
        board=_boards([{'old_sheet':'S1','code':'M-161','family':'SPLIT_AC','level':'L1','title_fa':'Cooling'}])['S1']
        plan={'plan_id':'P1','level':'L1','bounds':[0,0,10,10],'mechanical_role':'PRIMARY_FLOOR'}
        for equipment,expected in (([],0),([{'id':'AC-O-1','kind':'split_outdoor','plan_id':'P1','point':[2,2],'serves':'AC-I-1'}],1)):
            with self.subTest(expected=expected):
                doc=ezdxf.new('R2010')
                pipeline={'architecture':{'plans':[plan],'walls':[]},'routing':{'routes':[]},'sizing':{'segments':[]},'hvac':{'equipment':equipment}}
                _draw_plan_overlay(doc,doc.modelspace(),board,plan,pipeline)
                self.assertEqual(len(doc.modelspace().query('INSERT[name=="ENGI_AC_OUTDOOR"]')),expected)
                if expected:
                    self.assertIn('AC-O-1',' '.join(e.plain_text() for e in doc.modelspace().query('MTEXT')))

    def test_water_service_detail_is_materialized_only_for_water_scope(self):
        self.assertIn('D-WS-01 WATER SERVICE / PUMP',select_details(ProjectContext(active_systems=['WATER'])))
        self.assertNotIn('D-WS-01 WATER SERVICE / PUMP',select_details(ProjectContext(active_systems=['GAS'])))
