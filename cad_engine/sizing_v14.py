"""Downstream-load network sizing v14.

Each route is sized from the endpoint set carried by topology, so branch, floor
main and riser loads increase naturally. Tables/slopes are project-overridable
engineering bases, never hidden statutory claims.
"""
from __future__ import annotations
from hashlib import sha256
import json
import math

DEFAULT_TABLES={
 'cold_water':[(1.5,16),(4,20),(8,25),(16,32),(999,40)],
 'hot_water':[(1.5,16),(4,20),(8,25),(16,32),(999,40)],
 'sanitary':[(1,50),(3,63),(8,75),(16,90),(999,110)],
 'vent':[(2,50),(8,63),(20,75),(999,90)],
 'heating_supply':[(1500,16),(3500,20),(7000,25),(14000,32),(999999,40)],
 'heating_return':[(1500,16),(3500,20),(7000,25),(14000,32),(999999,40)],
 'cooling_supply':[(2500,16),(6000,20),(12000,25),(24000,32),(999999,40)],
 'cooling_return':[(2500,16),(6000,20),(12000,25),(24000,32),(999999,40)],
 'condensate':[(5000,25),(12000,32),(30000,40),(999999,50)],
 'gas':[(12,20),(30,25),(60,32),(9999,40)],
 'refrigerant_liquid':[(9000,6),(18000,9),(30000,12),(999999,16)],
 'refrigerant_gas':[(9000,10),(18000,12),(30000,16),(999999,19)],
}
FIXTURE_LOAD={
 'wc':{'cold_water':2.5,'sanitary':4,'vent':4},'basin':{'cold_water':1,'hot_water':1,'sanitary':1,'vent':1},
 'sink':{'cold_water':1.5,'hot_water':1.5,'sanitary':2,'vent':2},'shower':{'cold_water':2,'hot_water':2,'sanitary':2,'vent':2},
 'floor_drain':{'sanitary':2},
}

def _pick(system,load,tables):
 for threshold,size in tables.get(system,[]):
  if load<=threshold:return size
 return None

WATER_HYDRAULIC_BASIS_FIELDS={
 'probable_flow_curve','candidate_diameters_mm','max_velocity_m_s',
 'max_pressure_drop_pa_m','hazen_williams_c',
}

def _stable_water_calc_id(segment_id):
 return 'CALC-WATER-'+sha256(str(segment_id).encode()).hexdigest()[:12].upper()

def _probable_flow(fu,curve):
 for row in sorted(curve,key=lambda x:float(x['max_fixture_units'])):
  if fu<=float(row['max_fixture_units']): return float(row['flow_lps'])
 return None

def design_water_network(segments,fixtures,design_basis):
 """Hydraulically size every water segment from explicit project inputs.

 No implicit design curve, velocity limit, material coefficient, or route
 geometry is supplied here. Missing authority data remains INPUT_REQUIRED.
 """
 missing=sorted(WATER_HYDRAULIC_BASIS_FIELDS-set(design_basis or {}))
 if missing:
  return {'status':'INPUT_REQUIRED','missing_inputs':missing,'segments':[],'reducers':[]}
 fixture_fu={row.get('id'):row.get('fixture_units') for row in fixtures or []}
 if not fixture_fu or any(value is None for value in fixture_fu.values()):
  return {'status':'INPUT_REQUIRED','missing_inputs':['fixture_units'],'segments':[],'reducers':[]}
 required_segment={'id','system','downstream_fixture_ids','length_m','fittings_equivalent_length_m'}
 rows=[]; errors=[]; input_required=[]
 for segment in segments or []:
  absent=sorted(required_segment-set(segment))
  if absent:
   input_required.extend(f"{segment.get('id','UNKNOWN')}:{name}" for name in absent)
   continue
  unknown=sorted(set(segment['downstream_fixture_ids'])-set(fixture_fu))
  if unknown:
   errors.append(f"{segment['id']}:unknown_fixtures:{','.join(unknown)}")
   continue
  fu=sum(float(fixture_fu[value]) for value in segment['downstream_fixture_ids'])
  flow=_probable_flow(fu,design_basis['probable_flow_curve'])
  if flow is None:
   input_required.append(f"{segment['id']}:probable_flow_curve_range")
   continue
  selected=None; candidates=[]
  for diameter in sorted(float(x) for x in design_basis['candidate_diameters_mm']):
   area=math.pi*(diameter/1000.0)**2/4.0
   velocity=(flow/1000.0)/area
   gradient=10.67*(flow/1000.0)**1.852/(float(design_basis['hazen_williams_c'])**1.852*(diameter/1000.0)**4.87)
   pressure_drop_pa_m=gradient*float(design_basis.get('water_density_kg_m3',998.2))*9.80665
   candidate={'diameter_mm':diameter,'velocity_m_s':round(velocity,3),
              'pressure_drop_pa_m':round(pressure_drop_pa_m,1)}
   candidate['pass']=velocity<=float(design_basis['max_velocity_m_s']) and pressure_drop_pa_m<=float(design_basis['max_pressure_drop_pa_m'])
   candidates.append(candidate)
   if candidate['pass'] and selected is None: selected=candidate
  calc_id=_stable_water_calc_id(segment['id'])
  if selected is None:
   errors.append(f"{segment['id']}:no_compliant_diameter")
  drawing_dn=segment.get('drawing_dn_mm',selected['diameter_mm'] if selected else None)
  if selected and drawing_dn!=selected['diameter_mm']:
   errors.append(f"{segment['id']}:drawing_dn_mismatch")
  total_length=float(segment['length_m'])+float(segment['fittings_equivalent_length_m'])
  rows.append({'segment_id':segment['id'],'system':segment['system'],'parent_segment_id':segment.get('parent_segment_id'),
               'downstream_fixture_ids':sorted(segment['downstream_fixture_ids']),'downstream_fixture_units':round(fu,3),
               'probable_flow_lps':round(flow,4),'selected_dn_mm':selected['diameter_mm'] if selected else None,
               'velocity_m_s':selected['velocity_m_s'] if selected else None,
               'pressure_drop_pa_m':selected['pressure_drop_pa_m'] if selected else None,
               'friction_head_m':round((selected['pressure_drop_pa_m']*total_length)/(float(design_basis.get('water_density_kg_m3',998.2))*9.80665),3) if selected else None,
               'calc_id':calc_id,'size_source':calc_id,'drawing_dn_mm':drawing_dn,'candidates':candidates})
 by_id={row['segment_id']:row for row in rows}; reducers=[]
 for row in rows:
  parent=by_id.get(row.get('parent_segment_id'))
  if parent and parent.get('selected_dn_mm') and row.get('selected_dn_mm') and parent['selected_dn_mm']!=row['selected_dn_mm']:
   seed=f"{parent['segment_id']}->{row['segment_id']}"
   reducers.append({'id':'RED-'+sha256(seed.encode()).hexdigest()[:12].upper(),'entity_type':'REDUCER',
                    'from_dn_mm':parent['selected_dn_mm'],'to_dn_mm':row['selected_dn_mm'],
                    'upstream_segment_id':parent['segment_id'],'downstream_segment_id':row['segment_id'],
                    'source_calc_ids':[parent['calc_id'],row['calc_id']]})
 status='FAIL' if errors else ('INPUT_REQUIRED' if input_required else 'PASS')
 return {'status':status,'missing_inputs':sorted(input_required),'errors':sorted(errors),'segments':rows,'reducers':reducers,
         'basis_hash':sha256(json.dumps(design_basis,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
         'identity_policy':'drawing DN = calculation DN; size_source = calculation_id'}

def validate_water_drawing_sizes(calculated_segments,drawing_entities):
 expected={row['segment_id']:row for row in calculated_segments or []}
 actual={row.get('segment_id'):row for row in drawing_entities or []}
 missing=sorted(set(expected)-set(actual)); unknown=sorted(set(actual)-set(expected))
 mismatch=sorted(segment_id for segment_id in set(expected)&set(actual)
                 if expected[segment_id].get('selected_dn_mm')!=actual[segment_id].get('dn_mm')
                 or expected[segment_id].get('calc_id')!=actual[segment_id].get('size_source'))
 errors=[]
 if missing: errors.append('DRAWING_SEGMENTS_MISSING:'+','.join(missing))
 if unknown: errors.append('DRAWING_SEGMENTS_UNKNOWN:'+','.join(unknown))
 if mismatch: errors.append('DRAWING_DN_CALC_MISMATCH:'+','.join(mismatch))
 return {'status':'PASS' if not errors else 'FAIL','errors':errors,'missing':missing,'unknown':unknown,'mismatch':mismatch,
         'coverage':len(expected)-len(missing),'expected':len(expected)}

def design_heating_network(segments,radiators,design_basis):
 required={'design_delta_t_k','fluid_density_kg_m3','fluid_specific_heat_j_kgk',
           'candidate_diameters_mm','max_velocity_m_s'}
 missing=sorted(required-set(design_basis or {}))
 if missing:return {'status':'INPUT_REQUIRED','missing_inputs':missing,'segments':[]}
 loads={row.get('radiator_id'):row.get('selected_output_w') for row in radiators or []}
 if not loads or any(value is None for value in loads.values()):
  return {'status':'INPUT_REQUIRED','missing_inputs':['manufacturer_selected_radiators'],'segments':[]}
 rows=[];errors=[];needed={'id','system','downstream_radiator_ids'}
 for segment in segments or []:
  absent=sorted(needed-set(segment))
  if absent:return {'status':'INPUT_REQUIRED','missing_inputs':[f"{segment.get('id','UNKNOWN')}:{x}" for x in absent],'segments':[]}
  unknown=sorted(set(segment['downstream_radiator_ids'])-set(loads))
  if unknown:errors.append(f"{segment['id']}:unknown_radiators:{','.join(unknown)}");continue
  load=sum(float(loads[x]) for x in segment['downstream_radiator_ids'])
  flow_m3_s=load/(float(design_basis['fluid_density_kg_m3'])*float(design_basis['fluid_specific_heat_j_kgk'])*float(design_basis['design_delta_t_k']))
  selected=None
  for dn in sorted(float(x) for x in design_basis['candidate_diameters_mm']):
   velocity=flow_m3_s/(math.pi*(dn/1000)**2/4)
   if velocity<=float(design_basis['max_velocity_m_s']):selected=(dn,velocity);break
  calc_id='CALC-HEAT-'+sha256(str(segment['id']).encode()).hexdigest()[:12].upper()
  if not selected:errors.append(f"{segment['id']}:no_compliant_diameter")
  rows.append({'segment_id':segment['id'],'system':segment['system'],'downstream_radiator_ids':sorted(segment['downstream_radiator_ids']),
               'cumulative_load_w':round(load,2),'flow_lps':round(flow_m3_s*1000,4),
               'selected_dn_mm':selected[0] if selected else None,'velocity_m_s':round(selected[1],3) if selected else None,
               'calc_id':calc_id,'size_source':calc_id,'drawing_dn_mm':segment.get('drawing_dn_mm',selected[0] if selected else None)})
  if selected and rows[-1]['drawing_dn_mm']!=selected[0]:errors.append(f"{segment['id']}:drawing_dn_mismatch")
 return {'status':'FAIL' if errors else 'PASS','errors':errors,'segments':rows,
         'identity_policy':'drawing DN = calculation DN; cumulative manufacturer-selected radiator load'}

def design_gas_network(segments,appliances,design_basis):
 required_basis={'capacity_table','service_pressure_mbar','allowable_pressure_drop_mbar'}
 missing=sorted(required_basis-set(design_basis or {}))
 if missing:return {'status':'INPUT_REQUIRED','missing_inputs':missing,'segments':[],'components':[]}
 if not appliances or not segments:
  return {'status':'INPUT_REQUIRED','missing_inputs':['gas_appliances' if not appliances else 'gas_segments'],
          'segments':[],'components':[]}
 required_app={'id','manufacturer','model','thermal_input_kw','gas_consumption_m3h','datasheet',
              'terminal_shutoff','flue','combustion_air'}
 by_id={};input_required=[]
 for app in appliances or []:
  absent=sorted(required_app-set(app))
  sheet=app.get('datasheet') or {}
  absent += [f"datasheet.{x}" for x in ('official_url','revision','sha256') if not sheet.get(x)]
  if absent:input_required.extend(f"{app.get('id','UNKNOWN')}:{x}" for x in absent)
  else:by_id[app['id']]=app
 if input_required:return {'status':'INPUT_REQUIRED','missing_inputs':sorted(input_required),'segments':[],'components':[]}
 rows=[];errors=[];needed={'id','downstream_appliance_ids','equivalent_length_m'}
 for segment in segments or []:
  absent=sorted(needed-set(segment))
  if absent:return {'status':'INPUT_REQUIRED','missing_inputs':[f"{segment.get('id','UNKNOWN')}:{x}" for x in absent],'segments':[],'components':[]}
  unknown=sorted(set(segment['downstream_appliance_ids'])-set(by_id))
  if unknown:errors.append(f"{segment['id']}:unknown_appliances:{','.join(unknown)}");continue
  flow=sum(float(by_id[x]['gas_consumption_m3h']) for x in segment['downstream_appliance_ids'])
  leq=float(segment['equivalent_length_m']); candidates=[]
  for row in design_basis['capacity_table']:
   if leq<=float(row['max_equivalent_length_m']) and flow<=float(row['max_flow_m3h']):candidates.append(row)
  selected=min(candidates,key=lambda x:float(x['dn_mm'])) if candidates else None
  calc_id='CALC-GAS-'+sha256(str(segment['id']).encode()).hexdigest()[:12].upper()
  if not selected:errors.append(f"{segment['id']}:no_capacity_table_match")
  rows.append({'segment_id':segment['id'],'downstream_appliance_ids':sorted(segment['downstream_appliance_ids']),
               'flow_m3h':round(flow,4),'equivalent_length_m':leq,'selected_dn_mm':float(selected['dn_mm']) if selected else None,
               'service_pressure_mbar':float(design_basis['service_pressure_mbar']),
               'allowable_pressure_drop_mbar':float(design_basis['allowable_pressure_drop_mbar']),
               'calc_id':calc_id,'size_source':calc_id})
 components=[{'type':'METER','evidence':design_basis.get('meter')},{'type':'REGULATOR','evidence':design_basis.get('regulator')}]
 for app in by_id.values():
  components.extend([{'type':'APPLIANCE_SHUTOFF','appliance_id':app['id'],'evidence':app['terminal_shutoff']},
                     {'type':'FLUE','appliance_id':app['id'],'evidence':app['flue']},
                     {'type':'COMBUSTION_AIR','appliance_id':app['id'],'evidence':app['combustion_air']}])
 if not design_basis.get('meter'):input_required.append('meter')
 if not design_basis.get('regulator'):input_required.append('regulator')
 status='FAIL' if errors else ('INPUT_REQUIRED' if input_required else 'PASS')
 return {'status':status,'errors':errors,'missing_inputs':sorted(input_required),'segments':rows,'components':components,
         'appliances':[by_id[key] for key in sorted(by_id)],
         'identity_policy':'Flow + Leq + DN + Calc ID required for every segment'}

def _endpoint_load(item,system,room_calc):
 if not item:return 0.0
 if item.get('category')=='fixture': return float(FIXTURE_LOAD.get(item.get('type'),{}).get(system,0) or 0)
 rc=room_calc.get(item.get('room_id'),{})
 if system in ('heating_supply','heating_return'): return float(rc.get('heating_w',0) or 0)
 if system in ('cooling_supply','cooling_return','condensate'): return float(rc.get('cooling_w',0) or 0)
 if system=='gas': return float(rc.get('gas_kw',0) or 0)
 if system in ('refrigerant_liquid','refrigerant_gas'):
  cand=rc.get('split_candidate') or {}; return float(cand.get('selected_btu_h',0) or 0)
 return 0.0

def size_networks(topology,routing,recognition,calculations,tables=None,design_basis=None):
 tbl={k:list(v) for k,v in DEFAULT_TABLES.items()}
 for k,v in (tables or {}).items(): tbl[k]=list(v)
 basis={'sanitary_slope_percent':2.0}; basis.update(design_basis or {})
 item_by_id={x['id']:x for x in recognition.get('detections') or []}; room_calc={x['room_id']:x for x in calculations.get('rooms') or []}
 edge_by_id={x['id']:x for x in topology.get('edges') or []}; segments=[]
 for route in routing.get('routes') or []:
  edge=edge_by_id.get(route.get('edge_id'),{}); system=route.get('system'); endpoint_ids=list(route.get('endpoint_ids') or edge.get('endpoint_ids') or [])
  if not endpoint_ids and edge.get('from') in item_by_id: endpoint_ids=[edge['from']]
  loads=[_endpoint_load(item_by_id.get(eid),system,room_calc) for eid in endpoint_ids]
  load=sum(loads); size=_pick(system,load,tbl)
  segments.append({'route_id':route['id'],'edge_id':route.get('edge_id'),'system':system,'role':route.get('role'),
                   'endpoint_ids':endpoint_ids,'downstream_load':round(load,2),'size_mm':size,
                   'slope_percent':float(basis['sanitary_slope_percent']) if system=='sanitary' else None,
                   'sizing_basis':'accumulated_downstream_endpoint_load'})
 # system mains are the maximum accumulated-load routes, not a second independent sum.
 mains=[]
 for system in sorted({x['system'] for x in segments}):
  ss=[x for x in segments if x['system']==system]
  if ss:
   maxseg=max(ss,key=lambda x:x['downstream_load']); mains.append({'system':system,'downstream_load':maxseg['downstream_load'],'size_mm':maxseg['size_mm'],'role':'largest_accumulated_route','route_id':maxseg['route_id']})
 unsized=[x['route_id'] for x in segments if x['size_mm'] is None]
 return {'version':'network-sizing-v14.7','segments':segments,'system_mains':mains,'tables':tbl,'design_basis':basis,
         'quality':{'segments':len(segments),'segments_sized':len(segments)-len(unsized),'unsized_routes':unsized,
                    'sanitary_slopes_assigned':all(x['slope_percent'] is not None for x in segments if x['system']=='sanitary'),
                    'downstream_accumulation':True}}
