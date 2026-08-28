import unittest
from cad_engine.topology_v14 import build_system_topology

class TopologyV14Tests(unittest.TestCase):
 def test_endpoints_aggregate_to_branch_then_wet_core_then_shaft(self):
  arch={'bounds':[0,0,10000,10000],
        'shafts':[{'centroid':(8000,8000)}],
        'wet_cores':[{'room_id':'R1','centroid':(2000,2000),'nearest_shaft_centroid':(8000,8000)}]}
  rec={'detections':[
   {'id':'F1','type':'basin','category':'fixture','point':(1000,1000),'room_id':'R1','ports':['cold_water','sanitary','vent']},
   {'id':'F2','type':'wc','category':'fixture','point':(1500,1200),'room_id':'R1','ports':['cold_water','sanitary','vent']},
  ]}
  req={'project_systems':['cold_water','sanitary','vent']}; calc={'rooms':[{'room_id':'R1','water_fu':3.5,'sanitary_dfu':5.0}]}
  out=build_system_topology(arch,rec,req,calc)
  self.assertEqual(out['version'],'mechanical-topology-v14.5')
  self.assertEqual(out['quality']['direct_endpoint_to_shaft_edges'],0)
  self.assertGreaterEqual(out['quality']['branches'],3)
  cold=[e for e in out['edges'] if e['system']=='cold_water']
  self.assertTrue(any(e['role']=='fixture_branch' for e in cold))
  self.assertTrue(any(e['role']=='floor_main' for e in cold))
  self.assertTrue(any(e['role']=='riser_connection' for e in cold))
  self.assertEqual(out['systems']['cold_water']['endpoint_count'],2)

 def test_missing_real_shaft_is_explicitly_provisional(self):
  arch={'bounds':[0,0,1000,1000],'shafts':[],'wet_cores':[]}
  rec={'detections':[{'id':'F1','type':'basin','category':'fixture','point':(100,100),'room_id':'R1','ports':['cold_water']}]}
  out=build_system_topology(arch,rec,{'project_systems':['cold_water']},{'rooms':[]})
  self.assertTrue(out['quality']['provisional_shaft'])

if __name__=='__main__': unittest.main()
