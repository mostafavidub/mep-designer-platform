import unittest
from cad_engine.topology_v13 import build_system_topology

class Stage05TopologyTests(unittest.TestCase):
    def test_fixture_connects_to_real_shaft_in_system_graph(self):
        architecture={'shafts':[{'polygon':[(4000,0),(5000,0),(5000,1000),(4000,1000)]}],'bounds':[0,0,5000,4000]}
        recognition={'detections':[{'id':'MEP-001','category':'fixture','type':'wc','point':(1000,1000),'room_id':'ROOM-001'}]}
        requirements={'project_systems':['cold_water','sanitary','vent']}
        result=build_system_topology(architecture,recognition,requirements,{})
        self.assertEqual(result['version'],'mechanical-topology-v13.13')
        self.assertFalse(result['quality']['provisional_shaft'])
        self.assertGreaterEqual(len(result['systems']['sanitary']['edges']),1)
        edge=next(e for e in result['edges'] if e['system']=='sanitary')
        self.assertEqual(edge['from'],'MEP-001')
        self.assertTrue(edge['to'].startswith('SHAFT-'))

    def test_real_shaft_without_plan_id_is_owned_by_containing_plan(self):
        architecture={'plans':[{'plan_id':'PLAN-01','bounds':[0,0,5000,4000]}],
                      'primary_floor_plan_ids':['PLAN-01'],
                      'shafts':[{'point':(4000,1000)}],'bounds':[0,0,5000,4000],
                      'rooms':[{'plan_id':'PLAN-01','type':'bathroom','label_point':(1000,1000)}]}
        recognition={'detections':[{'id':'MEP-001','category':'fixture','type':'wc','point':(1000,1000),'room_id':'ROOM-001','plan_id':'PLAN-01'}]}
        result=build_system_topology(architecture,recognition,{'project_systems':['sanitary']},{})
        self.assertFalse(result['quality']['provisional_shaft'])
        self.assertEqual(result['nodes'][1]['plan_id'],'PLAN-01')

    def test_user_approved_wet_core_proposal_is_not_provisional(self):
        architecture={'plans':[{'plan_id':'PLAN-01','bounds':[0,0,5000,4000]}],
                      'primary_floor_plan_ids':['PLAN-01'],'shafts':[],
                      'rooms':[{'plan_id':'PLAN-01','type':'bathroom','label_point':(1000,1000)}]}
        recognition={'detections':[{'id':'MEP-001','category':'fixture','type':'wc','point':(1000,1000),'room_id':'ROOM-001','plan_id':'PLAN-01'}]}
        result=build_system_topology(architecture,recognition,{'project_systems':['sanitary']},{},
                                     design_basis={'mechanical_shaft_route':'propose_near_wet_core'})
        self.assertFalse(result['quality']['provisional_shaft'])
        proposed=next(n for n in result['nodes'] if n['id'].startswith('SHAFT-PROPOSED'))
        self.assertTrue(proposed['proposal_approved'])

    def test_structured_persian_approval_is_bound_to_plan_and_point(self):
        architecture={'plans':[{'plan_id':'P1','bounds':[0,0,100,100]},{'plan_id':'P2','bounds':[200,0,300,100]}],
                      'primary_floor_plan_ids':['P1','P2'],'shafts':[],
                      'rooms':[{'plan_id':'P1','type':'bathroom','label_point':(20,20)},
                               {'plan_id':'P2','type':'kitchen','label_point':(220,20)}]}
        recognition={'detections':[]}
        basis={'mechanical_shaft_route':'propose_near_wet_core','mechanical_shaft_approval':{
            'status':'APPROVED','strategy':'propose_near_wet_core','source':'explicit_user_answer'}}
        result=build_system_topology(architecture,recognition,{'project_systems':[]},{},basis)
        proposed=[x for x in result['nodes'] if x.get('source')=='proposed_near_wet_core']
        self.assertEqual({x['approval']['plan_id'] for x in proposed},{'P1','P2'})
        self.assertTrue(all(x['approval']['approved_point']==x['point'] for x in proposed))
        self.assertFalse(result['quality']['provisional_shaft'])

    def test_existing_only_answer_does_not_authorize_invented_shaft(self):
        architecture={'plans':[{'plan_id':'P1','bounds':[0,0,100,100]}],
                      'primary_floor_plan_ids':['P1'],'shafts':[],'rooms':[]}
        basis={'mechanical_shaft_route':'use_existing_architectural_shafts','mechanical_shaft_approval':{
            'status':'APPROVED','strategy':'use_existing_architectural_shafts'}}
        result=build_system_topology(architecture,{'detections':[]},{'project_systems':[]},{},basis)
        self.assertTrue(result['quality']['provisional_shaft'])

if __name__=='__main__': unittest.main()
