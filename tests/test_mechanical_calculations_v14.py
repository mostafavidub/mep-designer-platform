import unittest
from cad_engine.mechanical_calculations_v14 import calculate_mechanical_loads

class MechanicalCalculationsV14Tests(unittest.TestCase):
 def test_room_loads_are_traceable_and_drive_selection_candidates(self):
  arch={'units':4,'rooms':[{'id':'R1','type':'kitchen','area':20_000_000},{'id':'R2','type':'bedroom','area':15_000_000}]}
  rec={'detections':[{'id':'F1','room_id':'R1','category':'fixture','type':'sink'},{'id':'E1','room_id':'R1','category':'equipment','type':'stove'}]}
  req={'rooms':[{'room_id':'R1','required':['cold_water','hot_water','sanitary','vent','exhaust','gas','cooling']},{'room_id':'R2','required':['heating','cooling']} ]}
  out=calculate_mechanical_loads(arch,rec,req)
  self.assertEqual(out['version'],'mechanical-calculations-v14.4')
  self.assertEqual(out['basis_status'],'PROJECT_OVERRIDE_REQUIRED_FOR_FINAL_DESIGN')
  kitchen=next(x for x in out['rooms'] if x['room_id']=='R1')
  bedroom=next(x for x in out['rooms'] if x['room_id']=='R2')
  self.assertGreater(kitchen['water_fu'],0); self.assertGreater(kitchen['sanitary_dfu'],0); self.assertGreater(kitchen['gas_kw'],0)
  self.assertIsNotNone(kitchen['split_candidate'])
  self.assertIsNotNone(bedroom['radiator_candidate'])
  self.assertIn('F1',kitchen['source_object_ids'])
  self.assertTrue(out['traceability']['all_assumptions_exposed'])
  self.assertGreater(out['totals']['preliminary_water_lps'],0)

 def test_design_basis_override_changes_result(self):
  arch={'units':4,'rooms':[{'id':'R1','type':'bedroom','area':10_000_000}]}; rec={'detections':[]}
  req={'rooms':[{'room_id':'R1','required':['cooling']}]}
  a=calculate_mechanical_loads(arch,rec,req)
  b=calculate_mechanical_loads(arch,rec,req,{'cooling_w_m2':{'bedroom':200}})
  self.assertGreater(b['rooms'][0]['cooling_w'],a['rooms'][0]['cooling_w'])

if __name__=='__main__': unittest.main()
