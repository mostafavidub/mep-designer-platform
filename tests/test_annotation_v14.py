import unittest
from cad_engine.annotation_v14 import build_annotations

class AnnotationV14Tests(unittest.TestCase):
 def test_annotations_include_size_slope_object_tags_and_riser_notes(self):
  routing={'routes':[{'id':'R1','edge_id':'E1','system':'sanitary','role':'floor_main','points':[(0,0),(1000,0)],'endpoint_ids':['F1']},
                     {'id':'R2','edge_id':'E2','system':'vent','role':'riser_connection','points':[(0,500),(0,1500)],'endpoint_ids':['F1']}]}
  sizing={'segments':[{'route_id':'R1','size_mm':75,'slope_percent':2.0},{'route_id':'R2','size_mm':63,'slope_percent':None}],
          'system_mains':[{'system':'sanitary','size_mm':75,'route_id':'R1','downstream_load':5}]}
  rec={'detections':[{'id':'F1','category':'fixture','type':'floor_drain','point':(100,100),'room_id':'ROOM-1'},
                     {'id':'E3','category':'equipment','type':'exhaust_fan','point':(500,500),'room_id':'ROOM-1'}]}
  calc={'rooms':[{'room_id':'ROOM-1','exhaust_cfm':100}]}; topo={'edges':[{'id':'E1'},{'id':'E2'}]}
  out=build_annotations(routing,sizing,rec,calc,topo)
  self.assertEqual(out['version'],'annotation-engine-v14.8')
  texts=[x['text'] for x in out['annotations']]
  self.assertTrue(any('SAN | DN75 | SLOPE 2%' in t for t in texts))
  self.assertTrue(any('V | DN63 | UP TO ROOF' in t for t in texts))
  self.assertIn('FD',texts)
  self.assertTrue(any('EF 100 CFM'==t for t in texts))
  self.assertTrue(any('SAN RISER DN75'==t for t in texts))
  self.assertTrue(out['quality']['traceable'])
  self.assertGreaterEqual(out['quality']['leaders'],4)

if __name__=='__main__': unittest.main()
