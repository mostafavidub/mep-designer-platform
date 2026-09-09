import unittest
from cad_engine.sizing_v14 import (
 size_networks, design_water_network, design_heating_network, design_gas_network,
)

class SizingV14Tests(unittest.TestCase):
 def test_floor_main_accumulates_fixture_load_and_is_not_smaller_than_branch(self):
  rec={'detections':[{'id':'F1','category':'fixture','type':'basin','room_id':'R1'},{'id':'F2','category':'fixture','type':'wc','room_id':'R1'}]}
  calc={'rooms':[{'room_id':'R1','heating_w':0,'cooling_w':0,'gas_kw':0}]}
  topo={'edges':[{'id':'E1','system':'cold_water','from':'F1','to':'B','role':'fixture_branch','endpoint_ids':['F1']},
                 {'id':'E2','system':'cold_water','from':'B','to':'S','role':'floor_main','endpoint_ids':['F1','F2']},
                 {'id':'E3','system':'sanitary','from':'B','to':'S','role':'floor_main','endpoint_ids':['F1','F2']} ]}
  routing={'routes':[{'id':'R1','edge_id':'E1','system':'cold_water','role':'fixture_branch','endpoint_ids':['F1']},
                     {'id':'R2','edge_id':'E2','system':'cold_water','role':'floor_main','endpoint_ids':['F1','F2']},
                     {'id':'R3','edge_id':'E3','system':'sanitary','role':'floor_main','endpoint_ids':['F1','F2']} ]}
  out=size_networks(topo,routing,rec,calc)
  self.assertEqual(out['version'],'network-sizing-v14.7')
  by={x['route_id']:x for x in out['segments']}
  self.assertGreater(by['R2']['downstream_load'],by['R1']['downstream_load'])
  self.assertGreaterEqual(by['R2']['size_mm'],by['R1']['size_mm'])
  self.assertEqual(by['R3']['slope_percent'],2.0)
  self.assertTrue(out['quality']['downstream_accumulation'])
  self.assertEqual(out['quality']['unsized_routes'],[])

 def test_sanitary_slope_is_project_overrideable(self):
  rec={'detections':[{'id':'F1','category':'fixture','type':'basin','room_id':'R1'}]}; calc={'rooms':[{'room_id':'R1'}]}
  topo={'edges':[{'id':'E','system':'sanitary','from':'F1','to':'S','endpoint_ids':['F1']}]}; routing={'routes':[{'id':'R','edge_id':'E','system':'sanitary','endpoint_ids':['F1']} ]}
  out=size_networks(topo,routing,rec,calc,design_basis={'sanitary_slope_percent':1.5})
  self.assertEqual(out['segments'][0]['slope_percent'],1.5)

 def test_water_segments_are_hydraulically_sized_and_reducers_materialize(self):
  fixtures=[{'id':'F1','fixture_units':1.0},{'id':'F2','fixture_units':2.5},{'id':'F3','fixture_units':1.5}]
  segments=[
   {'id':'W-MAIN','system':'cold_water','downstream_fixture_ids':['F1','F2','F3'],'length_m':12,'fittings_equivalent_length_m':4},
   {'id':'W-SUB','parent_segment_id':'W-MAIN','system':'cold_water','downstream_fixture_ids':['F1','F3'],'length_m':5,'fittings_equivalent_length_m':2},
   {'id':'W-BR','parent_segment_id':'W-SUB','system':'cold_water','downstream_fixture_ids':['F1'],'length_m':2,'fittings_equivalent_length_m':1},
  ]
  basis={'probable_flow_curve':[{'max_fixture_units':1,'flow_lps':0.12},{'max_fixture_units':3,'flow_lps':0.25},{'max_fixture_units':6,'flow_lps':0.5}],
         'candidate_diameters_mm':[16,20,25,32],'max_velocity_m_s':1.5,'max_pressure_drop_pa_m':900,
         'hazen_williams_c':150}
  result=design_water_network(segments,fixtures,basis)
  self.assertEqual(result['status'],'PASS',result)
  by={row['segment_id']:row for row in result['segments']}
  self.assertGreaterEqual(by['W-MAIN']['selected_dn_mm'],by['W-SUB']['selected_dn_mm'])
  self.assertGreaterEqual(by['W-SUB']['selected_dn_mm'],by['W-BR']['selected_dn_mm'])
  self.assertTrue(all(row['size_source']==row['calc_id'] for row in result['segments']))
  self.assertTrue(all(row['drawing_dn_mm']==row['selected_dn_mm'] for row in result['segments']))
  self.assertTrue(all(reducer['entity_type']=='REDUCER' for reducer in result['reducers']))

 def test_water_sizing_never_invents_missing_basis_or_accepts_drawing_mismatch(self):
  self.assertEqual(design_water_network([],[],{})['status'],'INPUT_REQUIRED')
  fixtures=[{'id':'F1','fixture_units':1}]
  segment={'id':'W1','system':'hot_water','downstream_fixture_ids':['F1'],'length_m':2,'fittings_equivalent_length_m':0,'drawing_dn_mm':99}
  basis={'probable_flow_curve':[{'max_fixture_units':2,'flow_lps':0.1}],'candidate_diameters_mm':[16,20],
         'max_velocity_m_s':2,'max_pressure_drop_pa_m':5000,'hazen_williams_c':150}
  result=design_water_network([segment],fixtures,basis)
  self.assertEqual(result['status'],'FAIL')
  self.assertIn('W1:drawing_dn_mismatch',result['errors'])

 def test_heating_network_uses_cumulative_selected_radiator_output(self):
  radiators=[{'radiator_id':'RAD-1','selected_output_w':1300},{'radiator_id':'RAD-2','selected_output_w':2600}]
  segments=[{'id':'H-BR','system':'heating_supply','downstream_radiator_ids':['RAD-1']},
            {'id':'H-MAIN','system':'heating_supply','downstream_radiator_ids':['RAD-1','RAD-2']}]
  basis={'design_delta_t_k':20,'fluid_density_kg_m3':983,'fluid_specific_heat_j_kgk':4180,
         'candidate_diameters_mm':[10,16,20,25,32],'max_velocity_m_s':1.0}
  result=design_heating_network(segments,radiators,basis)
  self.assertEqual(result['status'],'PASS',result)
  by={row['segment_id']:row for row in result['segments']}
  self.assertGreater(by['H-MAIN']['cumulative_load_w'],by['H-BR']['cumulative_load_w'])
  self.assertGreaterEqual(by['H-MAIN']['selected_dn_mm'],by['H-BR']['selected_dn_mm'])
  self.assertTrue(all(row['size_source']==row['calc_id'] for row in result['segments']))

 def test_gas_segments_require_official_appliance_evidence_and_all_execution_fields(self):
  app={'id':'PKG-1','manufacturer':'Official','model':'P24','thermal_input_kw':24,
       'gas_consumption_m3h':2.73,'terminal_shutoff':{'id':'V-1'},'flue':{'diameter_mm':100},
       'combustion_air':{'area_cm2':150},
       'datasheet':{'official_url':'https://manufacturer.example/p.pdf','revision':'1','sha256':'f'*64}}
  segments=[{'id':'G-BR','downstream_appliance_ids':['PKG-1'],'equivalent_length_m':12}]
  basis={'service_pressure_mbar':21,'allowable_pressure_drop_mbar':2,
         'capacity_table':[{'max_equivalent_length_m':20,'dn_mm':15,'max_flow_m3h':2},
                           {'max_equivalent_length_m':20,'dn_mm':20,'max_flow_m3h':4}],
         'meter':{'id':'GM-1'},'regulator':{'id':'GR-1'}}
  result=design_gas_network(segments,[app],basis)
  self.assertEqual(result['status'],'PASS',result)
  row=result['segments'][0]
  self.assertEqual((row['flow_m3h'],row['equivalent_length_m'],row['selected_dn_mm']),(2.73,12.0,20.0))
  self.assertTrue(row['calc_id'].startswith('CALC-GAS-'))
  self.assertEqual({x['type'] for x in result['components']},{'METER','REGULATOR','APPLIANCE_SHUTOFF','FLUE','COMBUSTION_AIR'})

 def test_gas_design_fails_closed_for_missing_evidence_and_table_no_match(self):
  basis={'service_pressure_mbar':21,'allowable_pressure_drop_mbar':2,'capacity_table':[],
         'meter':{'id':'GM'},'regulator':{'id':'GR'}}
  self.assertEqual(design_gas_network([],[],basis)['status'],'INPUT_REQUIRED')
  app={'id':'A','manufacturer':'M','model':'X','thermal_input_kw':10,'gas_consumption_m3h':9,
       'terminal_shutoff':True,'flue':True,'combustion_air':True,
       'datasheet':{'official_url':'x','revision':'1','sha256':'a'*64}}
  result=design_gas_network([{'id':'G','downstream_appliance_ids':['A'],'equivalent_length_m':10}],[app],basis)
  self.assertEqual(result['status'],'FAIL')
  del app['datasheet']['sha256']
  missing=design_gas_network([{'id':'G','downstream_appliance_ids':['A'],'equivalent_length_m':10}], [app], basis)
  self.assertEqual(missing['status'],'INPUT_REQUIRED')
  self.assertIn('A:datasheet.sha256',missing['missing_inputs'])

if __name__=='__main__': unittest.main()
