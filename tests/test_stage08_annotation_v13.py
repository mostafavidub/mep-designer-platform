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
        self.assertEqual(result['version'],'annotation-engine-v13.8.2')
        label=result['annotations'][0]['text']
        self.assertIn('DN110',label)
        self.assertIn('SLOPE 2.0%',label)
        self.assertTrue(result['annotations'][0]['leader'])

    def test_floor_drain_is_tagged_independently_of_edge_direction(self):
        result=build_annotations(
            {'routes':[{'id':'ROUTE-001','edge_id':'SAN-E001','system':'sanitary','points':[(0,0),(1000,0)]}]},
            {'segments':[{'route_id':'ROUTE-001','system':'sanitary','size_mm':75,'slope_percent':2.0}],
             'vertical_mains':[{'system':'sanitary','size_mm':110}]},
            {'detections':[{'id':'FD-01','type':'floor_drain','point':(1000,0),'room_id':'ROOM-01'}]},
            {'rooms':[]},
            {'nodes':[{'kind':'shaft','point':(1100,100),'provisional':False}],
             'edges':[{'id':'SAN-E001','from':'SHAFT-01','to':'FD-01','system':'sanitary'}]},
        )
        tags=[x for x in result['annotations'] if x.get('source')=='detected_floor_drain']
        self.assertEqual(len(tags),1)
        self.assertEqual(tags[0]['text'],'FD')
        self.assertEqual(tags[0]['object_id'],'FD-01')

    def test_cleanout_uses_heaviest_sanitary_segment_when_main_summary_is_absent(self):
        result=build_annotations(
            {'routes':[{'id':'ROUTE-001','edge_id':'SAN-E001','system':'sanitary','points':[(0,0),(1000,0)]}]},
            {'segments':[{'route_id':'ROUTE-001','system':'sanitary','size_mm':90,'slope_percent':2.0}],
             'vertical_mains':[]},
            {'detections':[{'id':'WC-01','type':'wc','point':(0,0),'room_id':'ROOM-01'}]},
            {'rooms':[]},
            {'nodes':[{'kind':'shaft','point':(1100,100),'provisional':False}],
             'edges':[{'id':'SAN-E001','from':'WC-01','to':'SHAFT-01','system':'sanitary'}]},
        )
        cleanouts=[x for x in result['annotations'] if x.get('source')=='cleanout']
        self.assertEqual(len(cleanouts),1)
        self.assertIn('DN90',cleanouts[0]['text'])

if __name__=='__main__': unittest.main()
