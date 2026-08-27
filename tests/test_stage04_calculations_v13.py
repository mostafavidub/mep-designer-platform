import unittest

from cad_engine.mechanical_calculations_v13 import calculate_mechanical_loads


class Stage04CalculationTests(unittest.TestCase):
    def test_room_loads_are_traceable_and_nonzero(self):
        architecture = {'units':4,'rooms':[{'id':'ROOM-001','type':'bathroom','area':12_000_000.0}]}
        recognition = {'detections':[
            {'category':'fixture','type':'wc','room_id':'ROOM-001'},
            {'category':'fixture','type':'basin','room_id':'ROOM-001'},
        ]}
        requirements = {'rooms':[{'room_id':'ROOM-001','systems':['cold_water','hot_water','sanitary','vent','exhaust','heating']}]}
        result = calculate_mechanical_loads(architecture, recognition, requirements)
        self.assertEqual(result['version'], 'mechanical-calculations-v13.4')
        self.assertEqual(result['basis_status'], 'PRELIMINARY_OVERRIDEABLE')
        self.assertGreater(result['totals']['water_fu'], 0)
        self.assertGreater(result['totals']['sanitary_dfu'], 0)
        self.assertGreater(result['totals']['heating_w'], 0)
        self.assertGreater(result['totals']['exhaust_cfm'], 0)
        self.assertTrue(result['quality']['traceable_basis'])


if __name__ == '__main__': unittest.main()
