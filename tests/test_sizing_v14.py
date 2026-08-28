import unittest
from cad_engine.sizing_v14 import size_networks

class SizingV14Tests(unittest.TestCase):
 def test_floor_main_accumulates_fixture_load_and_is_not_smaller_than_branch(self):
  rec={'detections':[{'id':'F1','category':'fixture','type':'basin','room_id':'R1'},{'id':'F2','category':'fixture','type':'wc','room_id':'R1'}]}
  calc={'rooms':[{'room_id':'R1','heating_w':0,'cooling_w':0,'gas_kw':0}]}
  topo={'edges':[{'id':'E1','system':'cold_water','from':'F1','to':'B','role':'fixture_branch','endpoint_ids':['F1']},
                 {'id':'E2','system':'cold_water','from':'B','to':'S','role':'floor_main','endpoint_ids':['F1','F2']},
                 {'id':'E3','system':'sanitary','from':'B','to':'S','role':'floor_main','endpoint_ids':['F1','F2']} ]}
  routing={'routes':[{'id':'R1','edge_id':'E1','system':'cold_water','role':'fixture_branch','endpoint_ids':['F1']},
                     {'id':'R2','edge_id':'E2','system':'cold_water','role':'floor_main','endpoint_ids':['F1','F2']},
                     {'id':'R3','edge_id':'E3','system':'sanitary','role':'floor_main','endpoint_ids':['F1','F2']} ]}
  out=size_networks(topo,routing,rec,calc)
  self.assertEqual(out['version'],'network-sizing-v14.7')
  by={x['route_id']:x for x in out['segments']}
  self.assertGreater(by['R2']['downstream_load'],by['R1']['downstream_load'])
  self.assertGreaterEqual(by['R2']['size_mm'],by['R1']['size_mm'])
  self.assertEqual(by['R3']['slope_percent'],2.0)
  self.assertTrue(out['quality']['downstream_accumulation'])
  self.assertEqual(out['quality']['unsized_routes'],[])

 def test_sanitary_slope_is_project_overrideable(self):
  rec={'detections':[{'id':'F1','category':'fixture','type':'basin','room_id':'R1'}]}; calc={'rooms':[{'room_id':'R1'}]}
  topo={'edges':[{'id':'E','system':'sanitary','from':'F1','to':'S','endpoint_ids':['F1']}]}; routing={'routes':[{'id':'R','edge_id':'E','system':'sanitary','endpoint_ids':['F1']} ]}
  out=size_networks(topo,routing,rec,calc,design_basis={'sanitary_slope_percent':1.5})
  self.assertEqual(out['segments'][0]['slope_percent'],1.5)

if __name__=='__main__': unittest.main()
