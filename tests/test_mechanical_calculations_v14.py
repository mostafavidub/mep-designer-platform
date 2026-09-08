import unittest
from cad_engine.mechanical_calculations_v14 import calculate_mechanical_loads

class MechanicalCalculationsV14Tests(unittest.TestCase):
 def test_room_loads_are_traceable_and_drive_selection_candidates(self):
  arch={'units':4,'rooms':[{'id':'R1','type':'kitchen','area':20_000_000},{'id':'R2','type':'bedroom','area':15_000_000}]}
  rec={'detections':[{'id':'F1','room_id':'R1','category':'fixture','type':'sink'},{'id':'E1','room_id':'R1','category':'equipment','type':'stove'}]}
  req={'rooms':[{'room_id':'R1','required':['cold_water','hot_water','sanitary','vent','exhaust','gas','cooling']},{'room_id':'R2','required':['heating','cooling']} ]}
  out=calculate_mechanical_loads(arch,rec,req)
  self.assertEqual(out['version'],'mechanical-calculations-v14.5')
  self.assertEqual(out['basis_status'],'PROJECT_OVERRIDE_REQUIRED_FOR_FINAL_DESIGN')
  kitchen=next(x for x in out['rooms'] if x['room_id']=='R1')
  bedroom=next(x for x in out['rooms'] if x['room_id']=='R2')
  self.assertGreater(kitchen['water_fu'],0); self.assertGreater(kitchen['sanitary_dfu'],0); self.assertGreater(kitchen['gas_kw'],0)
  self.assertIsNotNone(kitchen['split_candidate'])
  self.assertIsNotNone(bedroom['radiator_candidate'])
  self.assertIn('F1',kitchen['source_object_ids'])
  self.assertTrue(kitchen['calc_id'].startswith('CALC-'))
  self.assertTrue(out['traceability']['calculation_ids_unique'])
  self.assertTrue(out['traceability']['all_assumptions_exposed'])
  self.assertGreater(out['totals']['preliminary_water_lps'],0)

 def test_design_basis_override_changes_result_without_changing_calc_identity(self):
  arch={'units':4,'rooms':[{'id':'R1','type':'bedroom','area':10_000_000}]}; rec={'detections':[]}
  req={'rooms':[{'room_id':'R1','required':['cooling']}]}
  a=calculate_mechanical_loads(arch,rec,req)
  b=calculate_mechanical_loads(arch,rec,req,{'cooling_w_m2':{'bedroom':200}})
  self.assertGreater(b['rooms'][0]['cooling_w'],a['rooms'][0]['cooling_w'])
  self.assertEqual(a['rooms'][0]['calc_id'],b['rooms'][0]['calc_id'])

 def test_pmm_aliases_are_propagated_when_available(self):
  arch={'units':4,'rooms':[{'id':'R1','type':'kitchen','area':10_000_000}]}
  rec={'detections':[{'id':'F1','room_id':'R1','category':'fixture','type':'sink'}]}
  req={'rooms':[{'room_id':'R1','required':['cold_water']}]}
  pmm={'schema':'project-mechanical-model/v3','identity_registry':{'alias_to_entity_id':{'F1':'PMM-FIXTURE-ABC'}}}
  out=calculate_mechanical_loads(arch,rec,req,pmm=pmm)
  self.assertEqual(out['rooms'][0]['source_pmm_ids'],['PMM-FIXTURE-ABC'])
  self.assertEqual(out['traceability']['pmm_schema'],'project-mechanical-model/v3')

if __name__=='__main__': unittest.main()
