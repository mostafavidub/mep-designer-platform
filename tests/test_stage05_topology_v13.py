import unittest
from cad_engine.topology_v13 import build_system_topology

class Stage05TopologyTests(unittest.TestCase):
    def test_fixture_connects_to_real_shaft_in_system_graph(self):
        architecture={'shafts':[{'polygon':[(4000,0),(5000,0),(5000,1000),(4000,1000)]}],'bounds':[0,0,5000,4000]}
        recognition={'detections':[{'id':'MEP-001','category':'fixture','type':'wc','point':(1000,1000),'room_id':'ROOM-001'}]}
        requirements={'project_systems':['cold_water','sanitary','vent']}
        result=build_system_topology(architecture,recognition,requirements,{})
        self.assertEqual(result['version'],'mechanical-topology-v13.5')
        self.assertFalse(result['quality']['provisional_shaft'])
        self.assertGreaterEqual(len(result['systems']['sanitary']['edges']),1)
        edge=next(e for e in result['edges'] if e['system']=='sanitary')
        self.assertEqual(edge['from'],'MEP-001')
        self.assertTrue(edge['to'].startswith('SHAFT-'))

if __name__=='__main__': unittest.main()
