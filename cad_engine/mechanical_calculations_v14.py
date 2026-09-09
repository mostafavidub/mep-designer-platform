"""Traceable Mechanical Calculation Engine v14.

All numerical design assumptions are explicit and overrideable. Nothing in this
module is represented as a statutory/code constant unless supplied by the caller.
Calculation formulas are unchanged; deterministic calculation identities now
allow Plan/Riser/Schedule outputs to reconcile to the same engineering result.
"""
from __future__ import annotations
from hashlib import sha256
import json
import math

DEFAULT_BASIS={
 'water_fixture_units':{'wc':2.5,'basin':1.0,'sink':1.5,'shower':2.0,'floor_drain':0.0},
 'sanitary_dfu':{'wc':4.0,'basin':1.0,'sink':2.0,'shower':2.0,'floor_drain':2.0},
 'heating_w_m2':{'bathroom':90,'toilet':65,'kitchen':70,'living':80,'bedroom':75,'parking':0,'mechanical':45},
 'cooling_w_m2':{'bathroom':0,'toilet':0,'kitchen':110,'living':120,'bedroom':105,'parking':0,'mechanical':0},
 'exhaust_cfm':{'bathroom':80,'toilet':70,'kitchen':180,'parking':0},
 'gas_kw':{'stove':12.0,'water_heater':24.0},
 'water_lps_coefficient':0.12,
 'split_capacity_btu_h':[9000,12000,18000,24000,30000,36000],
 'radiator_section_w':130.0,
}

WATER_SERVICE_COMMON_FIELDS={
 'service_mode','design_flow_lps','static_head_m','remote_residual_pressure_m',
 'meter_loss_m','valve_loss_m','critical_path_segment_ids',
}
WATER_SERVICE_TANK_FIELDS={
 'occupants','demand_l_per_person_day','autonomy_days','reserve_factor',
}

def _merge(basis, overrides):
 out={k:(dict(v) if isinstance(v,dict) else list(v) if isinstance(v,list) else v) for k,v in basis.items()}
 for k,v in (overrides or {}).items():
  if isinstance(v,dict) and isinstance(out.get(k),dict): out[k].update(v)
  else: out[k]=v
 return out

def _area_m2(room,units):
 if room.get('area_m2') is not None: return float(room['area_m2'])
 if room.get('area') is None: return None
 return float(room['area'])/1_000_000 if units==4 else float(room['area'])

def _select_split(cooling_w,capacities):
 if cooling_w<=0: return None
 need_btu=cooling_w*3.412142
 selected=next((x for x in capacities if x>=need_btu),capacities[-1] if capacities else None)
 return {'required_btu_h':round(need_btu),'selected_btu_h':selected,'selection_basis':'next_available_capacity'} if selected else None

def _calc_id(room_id, systems):
 payload=json.dumps({'room_id':str(room_id),'systems':sorted(systems)},sort_keys=True,separators=(',',':'))
 return 'CALC-'+sha256(payload.encode()).hexdigest()[:16].upper()

def _pmm_sources(pmm, source_ids):
 aliases=((pmm or {}).get('identity_registry') or {}).get('alias_to_entity_id') or {}
 return sorted({aliases[str(value)] for value in source_ids if value is not None and str(value) in aliases})

def calculate_water_service(water_basis, hydraulic_segments):
 """Calculate critical-path duty and storage only from declared project basis."""
 basis=water_basis or {}; missing=sorted(WATER_SERVICE_COMMON_FIELDS-set(basis))
 mode=basis.get('service_mode')
 if mode not in {'direct_city','inline_booster','break_tank_pump'}:
  missing.append('service_mode:direct_city|inline_booster|break_tank_pump')
 if mode in {'direct_city','inline_booster'} and 'utility_pressure_m' not in basis: missing.append('utility_pressure_m')
 if mode=='break_tank_pump':
  missing.extend(sorted(WATER_SERVICE_TANK_FIELDS-set(basis)))
  if 'available_suction_head_m' not in basis: missing.append('available_suction_head_m')
 if missing:
  return {'status':'INPUT_REQUIRED','missing_inputs':sorted(set(missing)),'pump':None,'tank':None}
 by_id={row.get('segment_id'):row for row in hydraulic_segments or []}
 path=list(basis['critical_path_segment_ids'])
 unknown=sorted(set(path)-set(by_id))
 incomplete=sorted(segment_id for segment_id in path if by_id.get(segment_id,{}).get('friction_head_m') is None)
 if unknown or incomplete:
  return {'status':'FAIL','errors':(['CRITICAL_PATH_UNKNOWN:'+','.join(unknown)] if unknown else [])+
          (['CRITICAL_PATH_HYDRAULICS_MISSING:'+','.join(incomplete)] if incomplete else []),'pump':None,'tank':None}
 friction=sum(float(by_id[segment_id]['friction_head_m']) for segment_id in path)
 required=float(basis['static_head_m'])+float(basis['remote_residual_pressure_m'])+friction+float(basis['meter_loss_m'])+float(basis['valve_loss_m'])
 if mode=='inline_booster': available=float(basis['utility_pressure_m'])
 elif mode=='break_tank_pump': available=float(basis['available_suction_head_m'])
 else: available=float(basis.get('utility_pressure_m',0))
 duty_head=max(0.0,required-available)
 calc_seed=json.dumps({'basis':basis,'path':[(sid,by_id[sid].get('calc_id')) for sid in path]},sort_keys=True,separators=(',',':'))
 calc_id='CALC-WATER-SERVICE-'+sha256(calc_seed.encode()).hexdigest()[:12].upper()
 pump=None
 if mode!='direct_city':
  pump={'calc_id':calc_id,'q_design_lps':round(float(basis['design_flow_lps']),4),
        'q_design_gpm':round(float(basis['design_flow_lps'])*15.850323,3),
        'h_design_m':round(duty_head,3),'operating_point':{'flow_lps':round(float(basis['design_flow_lps']),4),'head_m':round(duty_head,3)},
        'critical_path_segment_ids':path,'source_segment_calc_ids':[by_id[sid].get('calc_id') for sid in path],
        'head_components_m':{'static':float(basis['static_head_m']),'friction':round(friction,3),
          'meter':float(basis['meter_loss_m']),'valves':float(basis['valve_loss_m']),
          'remote_residual':float(basis['remote_residual_pressure_m']),'available_at_pump':available}}
 tank=None
 if mode=='break_tank_pump':
  volume=float(basis['occupants'])*float(basis['demand_l_per_person_day'])*float(basis['autonomy_days'])*float(basis['reserve_factor'])
  tank={'calc_id':calc_id,'required_volume_l':round(volume,2),'selected_volume_l':basis.get('selected_tank_volume_l'),
        'basis':{key:basis[key] for key in sorted(WATER_SERVICE_TANK_FIELDS)}}
  if tank['selected_volume_l'] is not None and float(tank['selected_volume_l'])<volume:
   return {'status':'FAIL','errors':['SELECTED_TANK_BELOW_REQUIRED_VOLUME'],'pump':pump,'tank':tank,'calc_id':calc_id}
 status='PASS'
 if mode=='direct_city' and duty_head>0: status='FAIL'
 if mode=='break_tank_pump' and tank['selected_volume_l'] is None: status='INPUT_REQUIRED'
 errors=['DIRECT_CITY_PRESSURE_INSUFFICIENT'] if mode=='direct_city' and duty_head>0 else []
 return {'status':status,'errors':errors,'missing_inputs':['selected_tank_volume_l'] if status=='INPUT_REQUIRED' else [],
         'calc_id':calc_id,'service_mode':mode,'required_head_m':round(required,3),'available_head_m':round(available,3),
         'pump':pump,'tank':tank,'basis_status':'FINAL' if status=='PASS' else 'PRE_SUBMISSION'}

def calculate_mechanical_loads(architecture,recognition,requirements,design_basis=None,pmm=None):
 basis=_merge(DEFAULT_BASIS,design_basis)
 room_req={x['room_id']:set(x.get('required') or x.get('systems') or []) for x in requirements.get('rooms') or []}
 items_by_room={r['id']:[] for r in architecture.get('rooms') or []}
 for item in recognition.get('detections') or []:
  if item.get('room_id') in items_by_room: items_by_room[item['room_id']].append(item)
 rows=[]; totals={'water_fu':0.0,'sanitary_dfu':0.0,'heating_w':0.0,'cooling_w':0.0,'exhaust_cfm':0.0,'gas_kw':0.0}
 for room in architecture.get('rooms') or []:
  rid=room['id']; systems=room_req.get(rid,set()); items=items_by_room[rid]; area=_area_m2(room,architecture.get('units'))
  fixtures=[x for x in items if x.get('category')=='fixture']; equipment=[x for x in items if x.get('category')=='equipment']
  water_fu=sum(float(basis['water_fixture_units'].get(x.get('type'),0)) for x in fixtures) if 'cold_water' in systems or 'hot_water' in systems else 0
  sanitary_dfu=sum(float(basis['sanitary_dfu'].get(x.get('type'),0)) for x in fixtures) if 'sanitary' in systems else 0
  heating=(area or 0)*float(basis['heating_w_m2'].get(room.get('type'),0)) if 'heating' in systems else 0
  cooling=(area or 0)*float(basis['cooling_w_m2'].get(room.get('type'),0)) if 'cooling' in systems else 0
  exhaust=float(basis['exhaust_cfm'].get(room.get('type'),0)) if ('exhaust' in systems or 'ventilation' in systems) else 0
  gas=sum(float(basis['gas_kw'].get(x.get('type'),0)) for x in equipment) if 'gas' in systems else 0
  radiator_sections=math.ceil(heating/float(basis['radiator_section_w'])) if heating>0 and basis.get('radiator_section_w') else 0
  split=_select_split(cooling,list(basis.get('split_capacity_btu_h') or []))
  source_ids=[x.get('id') for x in items]
  row={'calc_id':_calc_id(rid,systems),'room_id':rid,'room_type':room.get('type'),'area_m2':round(area,2) if area is not None else None,
       'systems':sorted(systems),'water_fu':round(water_fu,2),'sanitary_dfu':round(sanitary_dfu,2),
       'heating_w':round(heating,1),'cooling_w':round(cooling,1),'exhaust_cfm':round(exhaust,1),'gas_kw':round(gas,2),
       'radiator_candidate':{'sections':radiator_sections,'section_w':basis.get('radiator_section_w')} if radiator_sections else None,
       'split_candidate':split,'source_object_ids':source_ids,'source_pmm_ids':_pmm_sources(pmm,source_ids)}
  rows.append(row)
  for k in totals: totals[k]+=row[k]
 totals={k:round(v,2) for k,v in totals.items()}
 totals['preliminary_water_lps']=round(float(basis['water_lps_coefficient'])*math.sqrt(max(totals['water_fu'],0)),3)
 water_service=None
 if design_basis and 'water_service' in design_basis:
  water_service=calculate_water_service(design_basis['water_service'],design_basis.get('water_hydraulic_segments') or [])
 calc_ids=[row['calc_id'] for row in rows]
 return {'version':'mechanical-calculations-v14.5','rooms':rows,'totals':totals,'design_basis':basis,
         'basis_status':'PROJECT_OVERRIDE_REQUIRED_FOR_FINAL_DESIGN',
         'traceability':{'room_results_reference_detection_ids':True,'all_assumptions_exposed':True,
                         'calculation_ids_unique':len(calc_ids)==len(set(calc_ids)),'pmm_schema':(pmm or {}).get('schema')},
         'water_service':water_service,
         'quality':{'rooms_calculated':len(rows),'rooms_with_area':sum(x['area_m2'] is not None for x in rows),
                    'traceable_basis':True,'selection_candidates':sum(bool(x['radiator_candidate'] or x['split_candidate']) for x in rows)}}
