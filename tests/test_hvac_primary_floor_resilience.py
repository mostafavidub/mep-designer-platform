import unittest

from cad_engine.project_hvac_v13 import design_project_hvac


class HvacPrimaryFloorResilienceTests(unittest.TestCase):
    def test_noncanonical_primary_level_still_generates_hvac(self):
        architecture={
            'plans':[{'plan_id':'P-A','level':'طبقه اول مسکونی','mechanical_role':'PRIMARY_FLOOR','bounds':[0,0,20,15]}],
            'rooms':[
                {'id':'BED-1','plan_id':'P-A','type':'bedroom','label_point':(5,6)},
                {'id':'LIV-1','plan_id':'P-A','type':'living','label_point':(10,8)},
                {'id':'KIT-1','plan_id':'P-A','type':'kitchen','label_point':(15,5)},
                {'id':'BATH-1','plan_id':'P-A','type':'bathroom','label_point':(15,9)},
            ],
        }
        result=design_project_hvac(architecture,{'hvac':{'cooling':'split_ac','heating':'package_radiator','city':'Tehran'}})
        self.assertEqual(result['status'],'PASS')
        kinds={x['kind'] for x in result['equipment']}
        self.assertIn('package',kinds)
        self.assertIn('radiator',kinds)
        self.assertIn('split_indoor',kinds)
        systems={x['system'] for x in result['routes']}
        self.assertIn('heating_flow',systems)
        self.assertIn('heating_return',systems)
        self.assertIn('refrigerant',systems)
        self.assertIn('condensate',systems)
        self.assertGreater(result['quality']['equipment'],0)
        self.assertGreater(result['quality']['routes'],0)


if __name__=='__main__':
    unittest.main()
