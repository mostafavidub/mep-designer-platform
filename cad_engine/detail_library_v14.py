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
 'radiator_connection':('RADIATOR CONNECTION DETAIL',['heating_w','sections','supply_size','return_size','tag']),
 'split_connection':('SPLIT UNIT CONNECTION',['selected_btu_h','liquid_size','gas_size','condensate_size','tag']),
 'exhaust_schedule':('EXHAUST FAN SCHEDULE',['airflow_cfm','location','tag']),
 'gas_connection':('GAS APPLIANCE CONNECTION',['load_kw','pipe_size','tag']),
 'roof_drain':('ROOF DRAIN / RAINWATER DETAIL',['drain_size','slope_percent','riser_id']),
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
 if ov.get('roof_drain_required'):
  detail('roof_drain',{'drain_size':ov.get('roof_drain_size_mm'),'slope_percent':ov.get('roof_slope_percent'),'riser_id':ov.get('rainwater_riser_id','RW1')})
 room_calc={x['room_id']:x for x in calculations.get('rooms') or []}
 # System-specific route sizes for equipment connection details.
 def route_size(system):
  vals=[x.get('size_mm') for x in sizing.get('segments') or [] if x.get('system')==system and x.get('size_mm')]
  return min(vals) if vals else None
 for item in recognition.get('detections') or []:
  rc=room_calc.get(item.get('room_id'),{}); typ=item.get('type'); tag=item.get('id')
  if typ=='pump': schedule('pump_schedule',{'flow_lps':ov.get('pump_flow_lps',calculations.get('totals',{}).get('preliminary_water_lps')),'head_m':ov.get('pump_head_m'),'location':item.get('room_id'),'tag':tag})
  elif typ=='tank': schedule('tank_schedule',{'capacity_l':ov.get('tank_capacity_l'),'location':item.get('room_id'),'tag':tag})
  elif typ=='radiator':
   cand=rc.get('radiator_candidate') or {}; detail('radiator_connection',{'heating_w':rc.get('heating_w'),'sections':cand.get('sections'),'supply_size':route_size('heating_supply'),'return_size':route_size('heating_return'),'tag':tag})
  elif typ=='split_indoor':
   cand=rc.get('split_candidate') or {}; detail('split_connection',{'selected_btu_h':cand.get('selected_btu_h'),'liquid_size':route_size('refrigerant_liquid'),'gas_size':route_size('refrigerant_gas'),'condensate_size':route_size('condensate'),'tag':tag})
  elif typ=='exhaust_fan': schedule('exhaust_schedule',{'airflow_cfm':rc.get('exhaust_cfm'),'location':item.get('room_id'),'tag':tag})
  elif typ in ('stove','water_heater'): detail('gas_connection',{'load_kw':rc.get('gas_kw'),'pipe_size':route_size('gas'),'tag':tag})
 all_rows=details+schedules; incomplete=[x['id'] for x in all_rows if x['qa']['status']!='PASS']
 return {'version':'detail-schedule-library-v14.9','details':details,'schedules':schedules,
         'quality':{'details':len(details),'schedules':len(schedules),'complete':len(all_rows)-len(incomplete),'incomplete':incomplete,
                    'all_templates_traceable':all(bool(x.get('required_fields')) for x in all_rows)}}
