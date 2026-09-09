import unittest
from cad_engine.mechanical_calculations_v14 import calculate_mechanical_loads, calculate_water_service

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

 def test_break_tank_pump_uses_critical_path_and_exposes_operating_point(self):
  segments=[{'segment_id':'W1','calc_id':'CALC-W1','friction_head_m':2.2},
            {'segment_id':'W2','calc_id':'CALC-W2','friction_head_m':1.8}]
  basis={'service_mode':'break_tank_pump','design_flow_lps':1.1,'static_head_m':9,
         'remote_residual_pressure_m':12,'meter_loss_m':1,'valve_loss_m':0.5,
         'available_suction_head_m':1.5,'critical_path_segment_ids':['W1','W2'],
         'occupants':5,'demand_l_per_person_day':80,'autonomy_days':1,'reserve_factor':1.25,
         'selected_tank_volume_l':500}
  result=calculate_water_service(basis,segments)
  self.assertEqual(result['status'],'PASS',result)
  self.assertEqual(result['tank']['required_volume_l'],500)
  self.assertEqual(result['pump']['h_design_m'],25.0)
  self.assertAlmostEqual(result['pump']['q_design_gpm'],17.435,places=3)
  self.assertEqual(result['pump']['source_segment_calc_ids'],['CALC-W1','CALC-W2'])

 def test_water_service_missing_external_basis_stays_input_required(self):
  result=calculate_water_service({'service_mode':'break_tank_pump'},[])
  self.assertEqual(result['status'],'INPUT_REQUIRED')
  self.assertIn('occupants',result['missing_inputs'])
  self.assertIn('critical_path_segment_ids',result['missing_inputs'])

 def test_utility_pressure_is_subtracted_only_for_inline_booster(self):
  segments=[{'segment_id':'W1','calc_id':'C1','friction_head_m':2}]
  common={'design_flow_lps':1,'static_head_m':10,'remote_residual_pressure_m':10,
          'meter_loss_m':1,'valve_loss_m':1,'critical_path_segment_ids':['W1']}
  inline=calculate_water_service({**common,'service_mode':'inline_booster','utility_pressure_m':15},segments)
  self.assertEqual(inline['pump']['h_design_m'],9)
  tank=calculate_water_service({**common,'service_mode':'break_tank_pump','available_suction_head_m':0,
       'occupants':2,'demand_l_per_person_day':100,'autonomy_days':1,'reserve_factor':1,
       'selected_tank_volume_l':200,'utility_pressure_m':99},segments)
  self.assertEqual(tank['pump']['h_design_m'],24)

 def test_undersized_selected_tank_is_rejected(self):
  segments=[{'segment_id':'W1','calc_id':'C1','friction_head_m':1}]
  basis={'service_mode':'break_tank_pump','design_flow_lps':0.5,'static_head_m':5,
         'remote_residual_pressure_m':10,'meter_loss_m':1,'valve_loss_m':1,
         'available_suction_head_m':0,'critical_path_segment_ids':['W1'],
         'occupants':5,'demand_l_per_person_day':100,'autonomy_days':1,'reserve_factor':1,
         'selected_tank_volume_l':400}
  result=calculate_water_service(basis,segments)
  self.assertEqual(result['status'],'FAIL')
  self.assertIn('SELECTED_TANK_BELOW_REQUIRED_VOLUME',result['errors'])

if __name__=='__main__': unittest.main()
