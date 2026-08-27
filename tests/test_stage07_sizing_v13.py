import unittest
from cad_engine.sizing_v13 import size_networks

class Stage07SizingTests(unittest.TestCase):
    def test_sanitary_segments_receive_size_and_slope(self):
        topology={'edges':[{'id':'SAN-E001','system':'sanitary','from':'MEP-001','to':'SHAFT-01'}]}
        routing={'routes':[{'id':'ROUTE-001','edge_id':'SAN-E001','system':'sanitary'}]}
        recognition={'detections':[{'id':'MEP-001','category':'fixture','type':'wc','room_id':'ROOM-001'}]}
        calculations={'rooms':[{'room_id':'ROOM-001','sanitary_dfu':4,'heating_w':0,'cooling_w':0,'gas_kw':0}]}
        result=size_networks(topology,routing,recognition,calculations)
        self.assertEqual(result['version'],'network-sizing-v13.7')
        seg=result['segments'][0]
        self.assertGreaterEqual(seg['size_mm'],75)
        self.assertEqual(seg['slope_percent'],2.0)
        self.assertTrue(result['quality']['sanitary_slopes_assigned'])

if __name__=='__main__': unittest.main()
