"""Dynamic detail and schedule library v14.

Templates mirror the information density observed in approved mechanical sets,
but values are always generated from project calculations/sizing/overrides.  A
detail with missing required fields is explicitly INCOMPLETE and cannot silently
masquerade as an issue-ready engineering detail.
"""
from __future__ import annotations

TEMPLATES={
 'sanitary_riser':('SANITARY / VENT RISER',['stack_id','levels','branch_sizes','stack_size','cleanout','vent_termination']),
 'cleanout':('TYPICAL CLEANOUT DETAIL',['pipe_size','access_required']),
 'vent_termination':('VENT TERMINATION AT ROOF',['vent_size','roof_reference']),
 'water_riser':('COLD / HOT WATER RISER',['riser_id','cold_size','hot_size','levels']),
 'pump_schedule':('PUMP SCHEDULE',['flow_lps','head_m','location','tag']),
 'tank_schedule':('WATER TANK SCHEDULE',['capacity_l','location','tag']),
 'radiator_connection':('RADIATOR CONNECTION DETAIL',['heating_w','sections','manufacturer','model','dimensions_mm','supply_size','return_size','tag']),
 'package_schedule':('HEATING / DHW PACKAGE SCHEDULE',['manufacturer','model','space_heating_capacity_kw','dhw_capacity_kw','gas_consumption_m3h','tag']),
 'split_connection':('SPLIT UNIT CONNECTION',['calculated_load_btu_h','selected_btu_h','selection_margin_percent','manufacturer','model','route_length_m','elevation_m','liquid_size','gas_size','condensate_drain','tag']),
 'exhaust_schedule':('EXHAUST FAN SCHEDULE',['required_cfm','required_esp_pa','airflow_cfm','esp_pa','manufacturer','model','calc_id','location','tag']),
 'gas_connection':('GAS APPLIANCE CONNECTION',['load_kw','gas_flow_m3h','equivalent_length_m','pipe_size','calc_id','manufacturer','model','tag']),
 'roof_drain':('ROOF DRAIN / RAINWATER DETAIL',['catchment_id','catchment_area_m2','design_flow_lps','drain_size','slope_percent','riser_id','emergency_overflow','calc_id']),
}

def _main(sizing,system):
 rows=sizing.get('system_mains') or sizing.get('vertical_mains') or []
 row=next((x for x in rows if x.get('system')==system),None); return row.get('size_mm') if row else None

def _complete(kind,params):
 required=TEMPLATES[kind][1]; missing=[]
 for key in required:
  value=params.get(key)
  if value is None or value=='' or value==[]: missing.append(key)
 return {'status':'PASS' if not missing else 'INCOMPLETE','missing':missing}

def _row(kind,params,index,prefix):
 title,required=TEMPLATES[kind]; qa=_complete(kind,params)
 return {'id':f'{prefix}-{index:03d}','kind':kind,'title':title,'required_fields':required,'parameters':params,'qa':qa}

def build_details_schedules(requirements,recognition,calculations,sizing,topology,project_overrides=None):
 systems=set(requirements.get('project_systems') or []); ov=project_overrides or {}; levels=list(ov.get('levels') or [])
 details=[]; schedules=[]
 def detail(kind,params): details.append(_row(kind,params,len(details)+1,'DET'))
 def schedule(kind,params): schedules.append(_row(kind,params,len(schedules)+1,'SCH'))
 if 'sanitary' in systems:
  branch_sizes=sorted({x.get('size_mm') for x in sizing.get('segments') or [] if x.get('system')=='sanitary' and x.get('size_mm')})
  detail('sanitary_riser',{'stack_id':ov.get('sanitary_stack_id','S1'),'levels':levels,'branch_sizes':branch_sizes,'stack_size':_main(sizing,'sanitary'),'cleanout':True,'vent_termination':True})
  detail('cleanout',{'pipe_size':_main(sizing,'sanitary'),'access_required':True})
 if 'vent' in systems: detail('vent_termination',{'vent_size':_main(sizing,'vent'),'roof_reference':ov.get('roof_reference','ROOF PLAN')})
 if 'cold_water' in systems or 'hot_water' in systems:
  detail('water_riser',{'riser_id':ov.get('water_riser_id','W1'),'cold_size':_main(sizing,'cold_water'),'hot_size':_main(sizing,'hot_water'),'levels':levels})
 rainwater=calculations.get('rainwater_design') or {}
 if rainwater.get('catchments'):
  for catchment in rainwater['catchments']:
   detail('roof_drain',{'catchment_id':catchment.get('catchment_id'),'catchment_area_m2':catchment.get('area_m2'),
          'design_flow_lps':catchment.get('design_flow_lps'),'drain_size':catchment.get('drain_dn_mm'),
          'slope_percent':catchment.get('slope_percent'),'riser_id':catchment.get('stack_id'),
          'emergency_overflow':catchment.get('emergency_overflow'),'calc_id':catchment.get('calc_id')})
 elif ov.get('roof_drain_required'):
  detail('roof_drain',{'catchment_id':None,'catchment_area_m2':None,'design_flow_lps':None,
         'drain_size':ov.get('roof_drain_size_mm'),'slope_percent':ov.get('roof_slope_percent'),
         'riser_id':ov.get('rainwater_riser_id','RW1'),'emergency_overflow':None,'calc_id':None})
 room_calc={x['room_id']:x for x in calculations.get('rooms') or []}
 water_service=calculations.get('water_service') or {}
 pump_calc=water_service.get('pump') or {}
 tank_calc=water_service.get('tank') or {}
 radiator_selection={row['room_id']:row for row in (calculations.get('radiator_selection') or {}).get('radiators') or []}
 package_selection=(calculations.get('package_selection') or {}).get('selection') or {}
 gas_design=sizing.get('gas_design') or {}
 gas_appliances={row['id']:row for row in gas_design.get('appliances') or []}
 split_selection={row['zone_id']:row for row in (calculations.get('split_selection') or {}).get('idus') or []}
 exhaust_selection={row['room_id']:row for row in (calculations.get('exhaust_selection') or {}).get('fans') or []}
 # System-specific route sizes for equipment connection details.
 def route_size(system):
  vals=[x.get('size_mm') for x in sizing.get('segments') or [] if x.get('system')==system and x.get('size_mm')]
  return min(vals) if vals else None
 for item in recognition.get('detections') or []:
  rc=room_calc.get(item.get('room_id'),{}); typ=item.get('type'); tag=item.get('id')
  if typ=='pump':
   params={'flow_lps':ov.get('pump_flow_lps',pump_calc.get('q_design_lps',calculations.get('totals',{}).get('preliminary_water_lps'))),
           'head_m':ov.get('pump_head_m',pump_calc.get('h_design_m')),'location':item.get('room_id'),'tag':tag}
   if pump_calc.get('calc_id'): params['source_calc_id']=pump_calc['calc_id']
   schedule('pump_schedule',params)
  elif typ=='tank':
   params={'capacity_l':ov.get('tank_capacity_l',tank_calc.get('selected_volume_l')),'location':item.get('room_id'),'tag':tag}
   if tank_calc.get('calc_id'): params['source_calc_id']=tank_calc['calc_id']
   schedule('tank_schedule',params)
  elif typ=='radiator':
   cand=radiator_selection.get(item.get('room_id')) or rc.get('radiator_candidate') or {}
   detail('radiator_connection',{'heating_w':rc.get('heating_w'),'sections':cand.get('sections'),
          'manufacturer':cand.get('manufacturer'),'model':cand.get('model'),'dimensions_mm':cand.get('dimensions_mm'),
          'supply_size':route_size('heating_supply'),'return_size':route_size('heating_return'),'tag':tag})
  elif typ=='split_indoor':
   cand=split_selection.get(item.get('zone_id') or item.get('room_id')) or rc.get('split_candidate') or {}
   detail('split_connection',{'calculated_load_btu_h':cand.get('calculated_load_btu_h'),
          'selected_btu_h':cand.get('selected_capacity_btu_h',cand.get('selected_btu_h')),
          'selection_margin_percent':cand.get('selection_margin_percent'),'manufacturer':cand.get('manufacturer'),
          'model':cand.get('model'),'route_length_m':cand.get('route_length_m'),'elevation_m':cand.get('elevation_m'),
          'liquid_size':cand.get('liquid_size_mm',route_size('refrigerant_liquid')),
          'gas_size':cand.get('gas_size_mm',route_size('refrigerant_gas')),
          'condensate_drain':cand.get('condensate_drain'),'tag':tag})
  elif typ=='exhaust_fan':
   fan=exhaust_selection.get(item.get('room_id')) or {}
   schedule('exhaust_schedule',{'required_cfm':fan.get('required_cfm'),'required_esp_pa':fan.get('required_esp_pa'),
            'airflow_cfm':fan.get('selected_cfm'),'esp_pa':fan.get('selected_esp_pa'),
            'manufacturer':fan.get('manufacturer'),'model':fan.get('model'),'calc_id':fan.get('calc_id'),
            'location':item.get('room_id'),'tag':tag})
  elif typ in ('stove','water_heater'):
   app=gas_appliances.get(tag,{})
   segment=next((row for row in gas_design.get('segments') or [] if tag in row.get('downstream_appliance_ids',[])),{})
   detail('gas_connection',{'load_kw':app.get('thermal_input_kw',rc.get('gas_kw')),
          'gas_flow_m3h':app.get('gas_consumption_m3h'),'equivalent_length_m':segment.get('equivalent_length_m'),
          'pipe_size':segment.get('selected_dn_mm',route_size('gas')),'calc_id':segment.get('calc_id'),
          'manufacturer':app.get('manufacturer'),'model':app.get('model'),'tag':tag})
 if package_selection:
  schedule('package_schedule',{'manufacturer':package_selection.get('manufacturer'),'model':package_selection.get('model'),
           'space_heating_capacity_kw':package_selection.get('space_heating_capacity_kw'),
           'dhw_capacity_kw':package_selection.get('dhw_capacity_kw'),
           'gas_consumption_m3h':package_selection.get('gas_consumption_m3h'),'tag':ov.get('package_tag','PKG-01')})
 all_rows=details+schedules; incomplete=[x['id'] for x in all_rows if x['qa']['status']!='PASS']
 return {'version':'detail-schedule-library-v14.9','details':details,'schedules':schedules,
         'quality':{'details':len(details),'schedules':len(schedules),'complete':len(all_rows)-len(incomplete),'incomplete':incomplete,
                    'all_templates_traceable':all(bool(x.get('required_fields')) for x in all_rows)}}
