import unittest
from cad_engine.annotation_v13 import build_annotations

class Stage08AnnotationTests(unittest.TestCase):
    def test_sanitary_route_gets_size_slope_and_leader(self):
        routing={'routes':[{'id':'ROUTE-001','edge_id':'SAN-E001','system':'sanitary','points':[(0,0),(1000,0),(1000,1000)]}]}
        sizing={'segments':[{'route_id':'ROUTE-001','system':'sanitary','size_mm':110,'slope_percent':2.0}],
                'vertical_mains':[{'system':'sanitary','size_mm':110}]}
        recognition={'detections':[{'id':'MEP-001','type':'wc','room_id':'ROOM-001'}]}
        calculations={'rooms':[{'room_id':'ROOM-001','cooling_w':0,'exhaust_cfm':0}]}
        topology={'edges':[{'id':'SAN-E001','from':'MEP-001','to':'SHAFT-01','system':'sanitary'}]}
        result=build_annotations(routing,sizing,recognition,calculations,topology)
        self.assertEqual(result['version'],'annotation-engine-v13.8.1')
        label=result['annotations'][0]['text']
        self.assertIn('DN110',label)
        self.assertIn('SLOPE 2.0%',label)
        self.assertTrue(result['annotations'][0]['leader'])

if __name__=='__main__': unittest.main()
