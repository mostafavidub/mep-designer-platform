import copy
import unittest
import ezdxf
from ezdxf.math import Matrix44

from cad_engine.architecture_preservation_gate_v16 import (
    snapshot_architecture, classify_entity, criticality_for, build_dependency_graph,
    authorize_mutation, atomic_transform, diff_snapshots, validate_topology,
    validate_visibility, validate_mechanical_impact, run_golden_regression, finalize_gate,
)


def make_doc():
    doc=ezdxf.new('R2010')
    for name in ('WALL','DOOR','WINDOW','SHAFT','GRID','A-NOTE'):
        if name not in doc.layers: doc.layers.add(name)
    m=doc.modelspace()
    # closed room walls
    m.add_line((1,1),(9,1),dxfattribs={'layer':'WALL'})
    m.add_line((9,1),(9,8),dxfattribs={'layer':'WALL'})
    m.add_line((9,8),(1,8),dxfattribs={'layer':'WALL'})
    m.add_line((1,8),(1,1),dxfattribs={'layer':'WALL'})
    # door/window/shaft/grid
    m.add_line((4,1),(5,1),dxfattribs={'layer':'DOOR'})
    m.add_line((9,4),(9,5),dxfattribs={'layer':'WINDOW'})
    m.add_lwpolyline([(7,6),(8,6),(8,7),(7,7)],close=True,dxfattribs={'layer':'SHAFT'})
    m.add_line((0,4.5),(10,4.5),dxfattribs={'layer':'GRID'})
    m.add_text('پلان معماری طبقه همکف',dxfattribs={'layer':'A-NOTE','height':.2}).set_placement((2,.3))
    return doc


class PreservationGateV16Tests(unittest.TestCase):
    def test_stage_01_snapshot_baseline(self):
        snap=snapshot_architecture(make_doc(),plan_id='P1',plan_bounds=(0,0,10,9))
        self.assertGreaterEqual(snap['entity_count'],9)
        self.assertEqual(len(snap['snapshot_hash']),64)
        self.assertTrue(all('geometry_hash' in r for r in snap['entities']))

    def test_stage_02_semantic_classifier(self):
        doc=make_doc(); classes=[classify_entity(e)[0] for e in doc.modelspace()]
        for cls in ('WALL','DOOR','WINDOW','SHAFT','GRID','LEGACY_TITLE'):
            self.assertIn(cls,classes)

    def test_stage_03_criticality_fail_closed(self):
        self.assertEqual(criticality_for('WALL',.99),'CRITICAL')
        self.assertEqual(criticality_for('UNKNOWN_GEOMETRY',.35),'CRITICAL')
        self.assertEqual(criticality_for('LEGACY_TITLE',.99),'REMOVABLE')

    def test_stage_04_dependency_graph(self):
        snap=snapshot_architecture(make_doc(),plan_id='P1')
        graph=build_dependency_graph(snap,{'equipment':[{'id':'AC-01','kind':'split_indoor'}],'routes':[{'id':'S-01'}]})
        self.assertFalse(graph['unhosted_hard'])
        self.assertTrue(any(d['mechanical_id']=='AC-01' and d['requires']=='WALL' for d in graph['dependencies']))

    def test_stage_05_mutation_policy(self):
        wall={'criticality':'CRITICAL'}; removable={'criticality':'REMOVABLE'}
        self.assertFalse(authorize_mutation(wall,'DELETE')['allowed'])
        self.assertTrue(authorize_mutation(removable,'DELETE',.99)['allowed'])
        self.assertTrue(authorize_mutation(wall,'TRANSFORM')['allowed'])

    def test_stage_06_atomic_transform(self):
        doc=make_doc(); snap=snapshot_architecture(doc,plan_id='P1'); handles=[r['handle'] for r in snap['entities'] if r['handle']]
        result=atomic_transform(doc,handles,Matrix44.translate(20,10,0))
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['transformed'],len(handles))

    def test_stage_07_diff_detects_critical_loss(self):
        before=snapshot_architecture(make_doc(),plan_id='P1')
        after=copy.deepcopy(before)
        victim=next(r for r in after['entities'] if r['semantic_class']=='WALL')
        after['entities'].remove(victim); after['entity_count']-=1
        diff=diff_snapshots(before,after)
        self.assertFalse(diff['pass'])
        self.assertEqual(len(diff['critical_deleted']),1)

    def test_stage_08_topology_preservation(self):
        before=snapshot_architecture(make_doc(),plan_id='P1')
        after=copy.deepcopy(before)
        self.assertTrue(validate_topology(before,after)['pass'])
        after['entities']=[r for r in after['entities'] if r['semantic_class']!='DOOR']
        self.assertFalse(validate_topology(before,after)['pass'])

    def test_stage_09_visibility_gate(self):
        snap=snapshot_architecture(make_doc(),plan_id='P1')
        good=validate_visibility(snap,(0,0,10,9))
        self.assertTrue(good['pass'])
        bad=validate_visibility(snap,(2,2,8,7))
        self.assertFalse(bad['pass'])
        self.assertTrue(bad['clipped'])

    def test_stage_10_mechanical_impact(self):
        snap=snapshot_architecture(make_doc(),plan_id='P1')
        graph=build_dependency_graph(snap,{'equipment':[{'id':'AC-01','kind':'split_indoor'}]})
        self.assertTrue(validate_mechanical_impact(snap,graph)['pass'])
        after=copy.deepcopy(snap); after['entities']=[r for r in after['entities'] if r['semantic_class']!='WALL']
        self.assertFalse(validate_mechanical_impact(after,graph)['pass'])

    def test_stage_11_golden_regression(self):
        a=snapshot_architecture(make_doc(),plan_id='P1')
        result=run_golden_regression([{'name':'simple-room','before':a,'after':copy.deepcopy(a)}])
        self.assertTrue(result['pass'])
        self.assertTrue(result['results'][0]['pass'])

    def test_stage_12_hard_fail_rollback(self):
        ok=finalize_gate(diff={'critical_deleted':[]},topology={'pass':True},visibility={'pass':True},mechanical={'pass':True},regression={'pass':True})
        self.assertEqual(ok['status'],'PASS'); self.assertEqual(ok['action'],'COMMIT_OUTPUT')
        bad=finalize_gate(diff={'critical_deleted':[{'key':'W1'}]},topology={'pass':True},visibility={'pass':True},mechanical={'pass':True},regression={'pass':True})
        self.assertEqual(bad['status'],'FAIL'); self.assertEqual(bad['action'],'ROLLBACK_AND_BLOCK_DELIVERY')


if __name__=='__main__': unittest.main()
