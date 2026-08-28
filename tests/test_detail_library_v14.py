import unittest
from cad_engine.detail_library_v14 import build_details_schedules

class DetailLibraryV14Tests(unittest.TestCase):
 def test_missing_project_values_remain_explicitly_incomplete(self):
  req={'project_systems':['sanitary','vent','cold_water','hot_water']}
  rec={'detections':[{'id':'P1','type':'pump','room_id':'R1'}]}
  calc={'rooms':[{'room_id':'R1'}],'totals':{'preliminary_water_lps':0.5}}
  sizing={'segments':[{'system':'sanitary','size_mm':75},{'system':'vent','size_mm':63},{'system':'cold_water','size_mm':25},{'system':'hot_water','size_mm':20}],
          'system_mains':[{'system':'sanitary','size_mm':90},{'system':'vent','size_mm':75},{'system':'cold_water','size_mm':32},{'system':'hot_water','size_mm':25}]}
  out=build_details_schedules(req,rec,calc,sizing,{},project_overrides={'levels':['G','1']})
  pump=next(x for x in out['schedules'] if x['kind']=='pump_schedule')
  self.assertEqual(pump['qa']['status'],'INCOMPLETE')
  self.assertIn('head_m',pump['qa']['missing'])
  riser=next(x for x in out['details'] if x['kind']=='sanitary_riser')
  self.assertEqual(riser['qa']['status'],'PASS')
  self.assertIn(pump['id'],out['quality']['incomplete'])

 def test_project_overrides_complete_pump_schedule(self):
  req={'project_systems':[]}; rec={'detections':[{'id':'P1','type':'pump','room_id':'R1'}]}; calc={'rooms':[{'room_id':'R1'}],'totals':{'preliminary_water_lps':0.6}}
  out=build_details_schedules(req,rec,calc,{'segments':[],'system_mains':[]},{},project_overrides={'pump_head_m':22})
  pump=out['schedules'][0]
  self.assertEqual(pump['qa']['status'],'PASS')
  self.assertEqual(pump['parameters']['flow_lps'],0.6)
  self.assertEqual(pump['parameters']['head_m'],22)

if __name__=='__main__': unittest.main()
