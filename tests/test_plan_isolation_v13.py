import os,tempfile,unittest
import ezdxf
from cad_engine.plan_segmentation_v13 import detect_print_plans
from cad_engine.topology_v13 import build_system_topology
from cad_engine.routing_v13 import route_topology
from cad_engine.plan_isolation_acceptance_v13 import evaluate_plan_isolation

class TestPlanIsolationV13(unittest.TestCase):
    def test_independent_frames_never_connect(self):
        with tempfile.TemporaryDirectory() as td:
            path=os.path.join(td,'two_plans.dxf');doc=ezdxf.new('R2013');doc.layers.add('suport');msp=doc.modelspace()
            msp.add_lwpolyline([(0,0),(21,0),(21,29.7),(0,29.7)],close=True,dxfattribs={'layer':'suport'})
            msp.add_lwpolyline([(30,0),(51,0),(51,29.7),(30,29.7)],close=True,dxfattribs={'layer':'suport'});doc.saveas(path)
            plans=detect_print_plans(path);self.assertEqual(2,len(plans))
            arch={'plans':plans,'walls':[],'shafts':[{'point':(10,10),'plan_id':'PLAN-01'}]}
            rec={'detections':[{'id':'MEP-001','type':'wc','category':'fixture','point':(5,5),'room_id':'R1','plan_id':'PLAN-01'},
                                 {'id':'MEP-002','type':'wc','category':'fixture','point':(35,5),'room_id':'R2','plan_id':'PLAN-02'}]}
            req={'project_systems':['sanitary','vent']};top=build_system_topology(arch,rec,req,{})
            self.assertTrue(all(e['plan_id']=='PLAN-01' for e in top['edges']))
            self.assertTrue(any(x['plan_id']=='PLAN-02' and x['reason']=='NO_LOCAL_SHAFT' for x in top['unresolved']))
            routed=route_topology(arch,top);self.assertEqual(0,routed['quality']['cross_plan_routes'])
            pipe={'architecture':arch,'topology':top,'routing':routed};gate=evaluate_plan_isolation(pipe)
            self.assertEqual('PASS',gate['status'],gate)
            for r in routed['routes']:
                self.assertEqual('PLAN-01',r['plan_id']);self.assertTrue(all(0<=x<=21 and 0<=y<=29.7 for x,y in r['points']))

if __name__=='__main__':unittest.main()
