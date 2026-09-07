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

    def test_native_gas_equipment_gets_project_design_load(self):
        topology={'edges':[{'id':'GAS-E1','from':'G1'}]}
        routing={'routes':[{'id':'R1','edge_id':'GAS-E1','system':'gas'}]}
        recognition={'detections':[{'id':'G1','category':'equipment','type':'stove','room_id':'K1'}]}
        result=size_networks(topology,routing,recognition,{'rooms':[{'room_id':'K1','gas_kw':0}]})
        self.assertEqual(result['segments'][0]['downstream_load'],12.0)
        self.assertEqual(result['segments'][0]['size_mm'],20)

if __name__=='__main__': unittest.main()
