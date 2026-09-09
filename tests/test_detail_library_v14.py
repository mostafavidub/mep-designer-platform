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

 def test_final_water_service_calculation_drives_pump_and_tank_schedules(self):
  req={'project_systems':[]}
  rec={'detections':[{'id':'P1','type':'pump','room_id':'R1'},{'id':'T1','type':'tank','room_id':'R1'}]}
  calc={'rooms':[{'room_id':'R1'}],'totals':{'preliminary_water_lps':0.2},
        'water_service':{'status':'PASS','pump':{'calc_id':'CALC-WS','q_design_lps':1.1,'h_design_m':25},
                         'tank':{'calc_id':'CALC-WS','selected_volume_l':500}}}
  out=build_details_schedules(req,rec,calc,{'segments':[],'system_mains':[]},{})
  by={row['kind']:row for row in out['schedules']}
  self.assertEqual(by['pump_schedule']['parameters']['flow_lps'],1.1)
  self.assertEqual(by['pump_schedule']['parameters']['head_m'],25)
  self.assertEqual(by['tank_schedule']['parameters']['capacity_l'],500)
  self.assertEqual(by['pump_schedule']['parameters']['source_calc_id'],'CALC-WS')

 def test_final_heating_and_gas_records_drive_issue_details(self):
  req={'project_systems':[]}
  rec={'detections':[{'id':'RAD-1','type':'radiator','room_id':'R1'},
                     {'id':'WH-1','type':'water_heater','room_id':'R2'}]}
  calc={'rooms':[{'room_id':'R1','heating_w':1800},{'room_id':'R2','gas_kw':24}],
        'radiator_selection':{'status':'PASS','radiators':[{
          'radiator_id':'RAD-1','room_id':'R1','sections':12,'manufacturer':'Official','model':'R-600',
          'selected_output_w':1920,'dimensions_mm':{'width':960,'height':600,'depth':95}}]},
        'package_selection':{'status':'PASS','selection':{
          'manufacturer':'Official','model':'P-30','space_heating_capacity_kw':24,
          'dhw_capacity_kw':30,'gas_consumption_m3h':3.2}}}
  sizing={'segments':[{'system':'heating_supply','size_mm':20},{'system':'heating_return','size_mm':20}],
          'system_mains':[], 'gas_design':{'status':'PASS','appliances':[{
            'id':'WH-1','manufacturer':'Official','model':'P-24','thermal_input_kw':24,'gas_consumption_m3h':2.73}],
            'segments':[{'segment_id':'G-1','downstream_appliance_ids':['WH-1'],'equivalent_length_m':14,
                         'selected_dn_mm':20,'calc_id':'CALC-GAS-G1'}]}}
  out=build_details_schedules(req,rec,calc,sizing,{})
  radiator=next(x for x in out['details'] if x['kind']=='radiator_connection')
  gas=next(x for x in out['details'] if x['kind']=='gas_connection')
  package=next(x for x in out['schedules'] if x['kind']=='package_schedule')
  self.assertEqual(radiator['qa']['status'],'PASS')
  self.assertEqual(radiator['parameters']['dimensions_mm']['width'],960)
  self.assertEqual(gas['qa']['status'],'PASS')
  self.assertEqual((gas['parameters']['gas_flow_m3h'],gas['parameters']['equivalent_length_m'],
                    gas['parameters']['pipe_size'],gas['parameters']['calc_id']),(2.73,14,20,'CALC-GAS-G1'))
  self.assertEqual(package['qa']['status'],'PASS')

 def test_final_split_and_exhaust_selection_drive_details_and_schedule(self):
  req={'project_systems':[]}
  rec={'detections':[{'id':'IDU-1','type':'split_indoor','room_id':'R1','zone_id':'Z1'},
                     {'id':'EF-1','type':'exhaust_fan','room_id':'WC-1'}]}
  calc={'rooms':[{'room_id':'R1'},{'room_id':'WC-1'}],
        'split_selection':{'status':'PASS','idus':[{'zone_id':'Z1','calculated_load_btu_h':10500,
          'selected_capacity_btu_h':12000,'selection_margin_percent':14.29,'manufacturer':'Official',
          'model':'I12','route_length_m':18,'elevation_m':6,'liquid_size_mm':6.35,
          'gas_size_mm':12.7,'condensate_drain':True}]},
        'exhaust_selection':{'status':'PASS','fans':[{'room_id':'WC-1','required_cfm':100,
          'required_esp_pa':80,'selected_cfm':120,'selected_esp_pa':100,'manufacturer':'Official',
          'model':'F120','calc_id':'CALC-EXH-X'}]}}
  out=build_details_schedules(req,rec,calc,{'segments':[],'system_mains':[]},{})
  split=next(x for x in out['details'] if x['kind']=='split_connection')
  fan=next(x for x in out['schedules'] if x['kind']=='exhaust_schedule')
  self.assertEqual(split['qa']['status'],'PASS')
  self.assertEqual((split['parameters']['calculated_load_btu_h'],split['parameters']['selected_btu_h'],
                    split['parameters']['route_length_m']),(10500,12000,18))
  self.assertEqual(fan['qa']['status'],'PASS')
  self.assertEqual((fan['parameters']['required_cfm'],fan['parameters']['required_esp_pa'],
                    fan['parameters']['airflow_cfm'],fan['parameters']['esp_pa']),(100,80,120,100))

 def test_final_rainwater_calculation_drives_roof_detail(self):
  calc={'rooms':[],'rainwater_design':{'status':'PASS','catchments':[{'catchment_id':'C1','area_m2':100,
        'design_flow_lps':2.78,'drain_dn_mm':75,'slope_percent':2,'stack_id':'RW-1',
        'emergency_overflow':{'id':'OF-1'},'calc_id':'CALC-RW-X'}]}}
  out=build_details_schedules({'project_systems':['rainwater']},{'detections':[]},calc,
                              {'segments':[],'system_mains':[]},{})
  detail=next(x for x in out['details'] if x['kind']=='roof_drain')
  self.assertEqual(detail['qa']['status'],'PASS')
  self.assertEqual((detail['parameters']['catchment_area_m2'],detail['parameters']['design_flow_lps'],
                    detail['parameters']['calc_id']),(100,2.78,'CALC-RW-X'))

if __name__=='__main__': unittest.main()
