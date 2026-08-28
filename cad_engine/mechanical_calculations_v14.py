"""Traceable Mechanical Calculation Engine v14.

All numerical design assumptions are explicit and overrideable.  Nothing in this
module is represented as a statutory/code constant unless supplied by the caller.
The engine produces room loads plus network-driving quantities and selection
candidates so CAD annotations can be tied back to calculation evidence.
"""
from __future__ import annotations
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

def calculate_mechanical_loads(architecture,recognition,requirements,design_basis=None):
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
  row={'room_id':rid,'room_type':room.get('type'),'area_m2':round(area,2) if area is not None else None,
       'systems':sorted(systems),'water_fu':round(water_fu,2),'sanitary_dfu':round(sanitary_dfu,2),
       'heating_w':round(heating,1),'cooling_w':round(cooling,1),'exhaust_cfm':round(exhaust,1),'gas_kw':round(gas,2),
       'radiator_candidate':{'sections':radiator_sections,'section_w':basis.get('radiator_section_w')} if radiator_sections else None,
       'split_candidate':split,'source_object_ids':[x.get('id') for x in items]}
  rows.append(row)
  for k in totals: totals[k]+=row[k]
 totals={k:round(v,2) for k,v in totals.items()}
 totals['preliminary_water_lps']=round(float(basis['water_lps_coefficient'])*math.sqrt(max(totals['water_fu'],0)),3)
 return {'version':'mechanical-calculations-v14.4','rooms':rows,'totals':totals,'design_basis':basis,
         'basis_status':'PROJECT_OVERRIDE_REQUIRED_FOR_FINAL_DESIGN',
         'traceability':{'room_results_reference_detection_ids':True,'all_assumptions_exposed':True},
         'quality':{'rooms_calculated':len(rows),'rooms_with_area':sum(x['area_m2'] is not None for x in rows),
                    'traceable_basis':True,'selection_candidates':sum(bool(x['radiator_candidate'] or x['split_candidate']) for x in rows)}}
