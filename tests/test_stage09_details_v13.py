import unittest
from cad_engine.detail_library_v13 import build_details_schedules

class Stage09DetailTests(unittest.TestCase):
    def test_sanitary_and_water_details_are_dynamic_and_traceable(self):
        requirements={'project_systems':['sanitary','vent','cold_water','hot_water']}
        recognition={'detections':[]}
        calculations={'totals':{'preliminary_water_lps':0.5},'rooms':[]}
        sizing={'segments':[{'system':'sanitary','size_mm':75},{'system':'sanitary','size_mm':110}],
                'vertical_mains':[{'system':'sanitary','size_mm':110},{'system':'vent','size_mm':63},{'system':'cold_water','size_mm':32},{'system':'hot_water','size_mm':25}]}
        result=build_details_schedules(requirements,recognition,calculations,sizing,{},project_overrides={'levels':['Ground','First','Roof']})
        self.assertEqual(result['version'],'detail-schedule-library-v13.9')
        kinds={x['kind'] for x in result['details']}
        self.assertTrue({'sanitary_riser','cleanout','vent_termination','water_riser'} <= kinds)
        sanitary=next(x for x in result['details'] if x['kind']=='sanitary_riser')
        self.assertEqual(sanitary['parameters']['stack_size'],110)
        self.assertTrue(result['quality']['all_templates_traceable'])

if __name__=='__main__': unittest.main()
