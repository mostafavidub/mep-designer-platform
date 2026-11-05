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

def _probable_flow(fu,curve,exact=False):
 for row in sorted(curve,key=lambda x:float(x['max_fixture_units'])):
  boundary=float(row['max_fixture_units'])
  if (abs(fu-boundary)<=1e-9) if exact else (fu<=boundary): return float(row['flow_lps'])
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
  values=[]
  for value in segment['downstream_fixture_ids']:
   fixture_value=fixture_fu[value]
   if isinstance(fixture_value,dict): fixture_value=fixture_value.get(segment['system'])
   if fixture_value is None:
    input_required.append(f"{segment['id']}:fixture_units:{value}:{segment['system']}")
    values=[];break
   values.append(float(fixture_value))
  if not values: continue
  fu=sum(values)
  flow=_probable_flow(fu,design_basis['probable_flow_curve'],bool(design_basis.get('probable_flow_exact_rows')))
  if flow is None:
   input_required.append(f"{segment['id']}:probable_flow_curve_range")
   continue
  selected=None; candidates=[]
  minimum_by_fixture=design_basis.get('minimum_fixture_branch_dn_mm_by_fixture_id') or {}
  minimum_dn=max((float(minimum_by_fixture.get(value) or 0) for value in segment['downstream_fixture_ids']),default=0)
  for diameter in sorted(float(x) for x in design_basis['candidate_diameters_mm']):
   area=math.pi*(diameter/1000.0)**2/4.0
   velocity=(flow/1000.0)/area
   gradient=10.67*(flow/1000.0)**1.852/(float(design_basis['hazen_williams_c'])**1.852*(diameter/1000.0)**4.87)
   pressure_drop_pa_m=gradient*float(design_basis.get('water_density_kg_m3',998.2))*9.80665
   candidate={'diameter_mm':diameter,'velocity_m_s':round(velocity,3),
              'pressure_drop_pa_m':round(pressure_drop_pa_m,1)}
   candidate['pass']=(diameter>=minimum_dn and velocity<=float(design_basis['max_velocity_m_s'])
                      and pressure_drop_pa_m<=float(design_basis['max_pressure_drop_pa_m']))
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

def design_water_network_from_rulebook(segments,fixtures,project_hydraulic_basis):
 """Size water segments using exact verified M16 demand rows.

 Fixture SFU values, exact probable demand and minimum branch DN come from the
 canonical water Rulebook. Candidate diameters and hydraulic criteria remain
 explicit project/internal design-basis inputs; no graphical sizing curve is
 digitized or inferred here.
 """
 from .water_rulebook import water_design_profile
 profile=water_design_profile(); method=profile['probable_demand_method']
 required={'system_mode','candidate_diameters_mm','max_velocity_m_s',
           'max_pressure_drop_pa_m','hazen_williams_c'}
 missing=sorted(required-set(project_hydraulic_basis or {}))
 if missing:
  return {'status':'INPUT_REQUIRED','missing_inputs':missing,'segments':[],'reducers':[],
          'rulebook_module_version':profile['minimum_fixture_branch_dn_provenance']['module_version']}
 mode=str(project_hydraulic_basis['system_mode'])
 demand=method['probable_flow_l_s']
 if mode not in demand:
  return {'status':'INPUT_REQUIRED','missing_inputs':['system_mode'],'segments':[],'reducers':[],
          'rulebook_module_version':profile['minimum_fixture_branch_dn_provenance']['module_version']}
 fixture_sfu=method['fixture_sfu']; prepared=[]; minimum_by_id={}; preparation_missing=[]
 for index,fixture in enumerate(fixtures or []):
  fixture_id=fixture.get('id'); kind=str(fixture.get('fixture_sfu_type') or '')
  count=fixture.get('count',1)
  if not fixture_id: preparation_missing.append(f'fixtures[{index}].id');continue
  if kind not in fixture_sfu: preparation_missing.append(f'fixtures[{index}].supported_fixture_sfu_type');continue
  try: numeric_count=float(count)
  except (TypeError,ValueError): numeric_count=0
  if numeric_count<=0 or not numeric_count.is_integer():
   preparation_missing.append(f'fixtures[{index}].count');continue
  units={}
  for system,scope in (('cold_water','cold'),('hot_water','hot')):
   value=fixture_sfu[kind].get(scope)
   if value is not None: units[system]=float(value)*int(numeric_count)
  prepared.append({'id':fixture_id,'fixture_units':units})
  fixture_class=str(fixture.get('fixture_type') or '')
  minimum=profile['minimum_fixture_branch_dn_mm'].get(fixture_class)
  if minimum is not None: minimum_by_id[fixture_id]=float(minimum)
 if preparation_missing or not prepared:
  return {'status':'INPUT_REQUIRED','missing_inputs':sorted(preparation_missing or ['fixtures']),
          'segments':[],'reducers':[],
          'rulebook_module_version':profile['minimum_fixture_branch_dn_provenance']['module_version']}
 exact_curve=[{'max_fixture_units':float(sfu),'flow_lps':float(flow)}
              for sfu,flow in demand[mode].items()]
 basis={key:project_hydraulic_basis[key] for key in required if key!='system_mode'}
 basis.update({'probable_flow_curve':exact_curve,'probable_flow_exact_rows':True,
               'minimum_fixture_branch_dn_mm_by_fixture_id':minimum_by_id,
               'probable_demand_rule_id':method['rule_id'],
               'minimum_dn_rule_id':profile['minimum_fixture_branch_dn_provenance']['rule_id']})
 result=design_water_network(segments,prepared,basis)
 equivalent_method=profile['galvanized_fitting_equivalent_length_method']
 segment_inputs={row.get('id'):row for row in segments or []}
 integration_missing=[]; integration_errors=[]
 for row in result.get('segments') or []:
  source=segment_inputs.get(row['segment_id']) or {}
  if source.get('pipe_material')!='GALVANIZED_STEEL':
   row['fitting_equivalent_length_source']='EXPLICIT_PROJECT_INPUT'
   continue
  dn=f"{float(row['selected_dn_mm']):g}" if row.get('selected_dn_mm') is not None else ''
  table=equivalent_method['equivalent_length_m'].get(dn)
  fittings=source.get('fittings')
  if table is None:
   integration_missing.append(f"{row['segment_id']}:galvanized_equivalent_length_dn:{dn}")
   continue
  if not isinstance(fittings,list):
   integration_missing.append(f"{row['segment_id']}:fittings")
   continue
  total=0.0; valid=True
  for index,fitting in enumerate(fittings):
   kind=str(fitting.get('type') or ''); quantity=fitting.get('quantity')
   if kind not in table:
    integration_missing.append(f"{row['segment_id']}:fittings[{index}].supported_type");valid=False
   try: numeric_quantity=float(quantity)
   except (TypeError,ValueError): numeric_quantity=-1
   if numeric_quantity<0 or not numeric_quantity.is_integer():
    integration_missing.append(f"{row['segment_id']}:fittings[{index}].quantity");valid=False
   if valid: total+=float(table[kind])*int(numeric_quantity)
  if not valid: continue
  declared=source.get('fittings_equivalent_length_m')
  if declared is not None and (not isinstance(declared,(int,float)) or abs(float(declared)-total)>1e-9):
   integration_errors.append(f"{row['segment_id']}:declared_fitting_equivalent_length_m_mismatch")
  effective_length=float(source['length_m'])+total
  density=float(basis.get('water_density_kg_m3',998.2)); gradient=float(row['pressure_drop_pa_m'])
  row.update({'fittings_equivalent_length_m':round(total,6),
              'total_effective_length_m':round(effective_length,6),
              'friction_head_m':round((gradient*effective_length)/(density*9.80665),3),
              'fitting_equivalent_length_source':equivalent_method['rule_id'],
              'fitting_equivalent_length_method':equivalent_method['method']})
 if integration_errors:
  result['errors']=sorted(set((result.get('errors') or [])+integration_errors));result['status']='FAIL'
 elif integration_missing and result.get('status')!='FAIL':
  result['missing_inputs']=sorted(set((result.get('missing_inputs') or [])+integration_missing));result['status']='INPUT_REQUIRED'
 result.update({'rulebook_module_version':profile['minimum_fixture_branch_dn_provenance']['module_version'],
                'probable_demand_rule_id':method['rule_id'],
                'minimum_dn_rule_id':profile['minimum_fixture_branch_dn_provenance']['rule_id'],
                'galvanized_equivalent_length_rule_id':equivalent_method['rule_id'],
                'probable_demand_method':method['method'],
                'coverage_limit':'EXACT_VERIFIED_ROWS_ONLY_NO_INTERPOLATION'})
 return result

def evaluate_remote_water_pressure_from_rulebook(sized_segments,outlets,service_basis):
 """Reconcile source pressure, elevation and calculated friction at each outlet."""
 from .executable_rulebook import WATER_ROOT,load_rulebook_module,rule_rows
 module=load_rulebook_module(WATER_ROOT)
 rule=next(row for row in rule_rows(module) if row['validator']=='fixture_pressure')
 required={'source_static_pressure_bar','source_flowing_pressure_bar','source_elevation_m',
           'meter_loss_m','valve_loss_m'}
 missing=sorted(required-set(service_basis or {}))
 if missing:
  return {'status':'INPUT_REQUIRED','missing_inputs':missing,'errors':[],'outlets':[],
          'rule_id':rule['rule_id'],'rulebook_module_version':module['manifest']['version']}
 numeric={key:service_basis[key] for key in required}
 try: numeric={key:float(value) for key,value in numeric.items()}
 except (TypeError,ValueError):
  return {'status':'INPUT_REQUIRED','missing_inputs':['finite_service_basis'],'errors':[],'outlets':[],
          'rule_id':rule['rule_id'],'rulebook_module_version':module['manifest']['version']}
 if any(not math.isfinite(value) for value in numeric.values()) or any(numeric[key]<0 for key in ('source_static_pressure_bar','source_flowing_pressure_bar','meter_loss_m','valve_loss_m')):
  return {'status':'INPUT_REQUIRED','missing_inputs':['finite_nonnegative_service_basis'],'errors':[],'outlets':[],
          'rule_id':rule['rule_id'],'rulebook_module_version':module['manifest']['version']}
 by_id={row.get('segment_id'):row for row in sized_segments or []}
 pressure_table=rule['parameters']['minimum_flowing_pressure_mwc']
 maximum_static=float(rule['parameters']['maximum_static_pressure_bar'])
 rows=[];missing=[];errors=[];bar_to_m=100000.0/(998.2*9.80665)
 for index,outlet in enumerate(outlets or []):
  outlet_id=str(outlet.get('outlet_id') or f'OUTLET-{index}')
  fixture_type=str(outlet.get('fixture_type') or '')
  elevation=outlet.get('elevation_m');path=outlet.get('segment_ids')
  if fixture_type not in pressure_table: missing.append(f'{outlet_id}:supported_fixture_type');continue
  try: elevation=float(elevation)
  except (TypeError,ValueError): missing.append(f'{outlet_id}:elevation_m');continue
  if not math.isfinite(elevation): missing.append(f'{outlet_id}:elevation_m');continue
  if not isinstance(path,list) or not path: missing.append(f'{outlet_id}:segment_ids');continue
  unknown=sorted(set(path)-set(by_id))
  if unknown: missing.append(f"{outlet_id}:unknown_segments:{','.join(unknown)}");continue
  if any(by_id[value].get('friction_head_m') is None for value in path):
   missing.append(f'{outlet_id}:segment_friction_head_m');continue
  friction=sum(float(by_id[value]['friction_head_m']) for value in path)
  static_head=numeric['source_static_pressure_bar']*bar_to_m-(elevation-numeric['source_elevation_m'])
  flowing_head=(numeric['source_flowing_pressure_bar']*bar_to_m-(elevation-numeric['source_elevation_m'])
                -friction-numeric['meter_loss_m']-numeric['valve_loss_m'])
  static_bar=static_head/bar_to_m;minimum=float(pressure_table[fixture_type])
  calc_id='CALC-WATER-PRESSURE-'+sha256(outlet_id.encode()).hexdigest()[:12].upper()
  row={'outlet_id':outlet_id,'fixture_type':fixture_type,'segment_ids':list(path),
       'source_static_pressure_bar':numeric['source_static_pressure_bar'],
       'source_flowing_pressure_bar':numeric['source_flowing_pressure_bar'],
       'elevation_difference_m':round(elevation-numeric['source_elevation_m'],3),
       'friction_head_m':round(friction,3),'meter_loss_m':numeric['meter_loss_m'],
       'valve_loss_m':numeric['valve_loss_m'],'calculated_static_pressure_bar':round(static_bar,3),
       'calculated_flowing_pressure_mwc':round(flowing_head,3),
       'maximum_static_pressure_bar':maximum_static,'minimum_flowing_pressure_mwc':minimum,
       'calc_id':calc_id,'rule_id':rule['rule_id']}
  row_errors=[]
  if static_bar>maximum_static+1e-9: row_errors.append('STATIC_PRESSURE_ABOVE_MAXIMUM')
  if flowing_head+1e-9<minimum: row_errors.append('FLOWING_PRESSURE_BELOW_MINIMUM')
  row['status']='FAIL' if row_errors else 'PASS';row['errors']=row_errors;rows.append(row)
  errors.extend(f'{outlet_id}:{value}' for value in row_errors)
 status='FAIL' if errors else ('INPUT_REQUIRED' if missing or not rows else 'PASS')
 return {'status':status,'missing_inputs':sorted(set(missing)),'errors':sorted(errors),'outlets':rows,
         'rule_id':rule['rule_id'],'rulebook_module_version':module['manifest']['version'],
         'identity_policy':'source pressure + elevation + exact sized-path friction + explicit local losses'}

def design_sanitary_main_from_rulebook(segments,fixtures):
 """Select main-horizontal sanitary DN from exact M16 DFU/slope table rows."""
 from .sanitary_vent_rulebook import sanitary_vent_design_profile,load_sanitary_vent_rulebook
 from .executable_rulebook import rule_rows
 profile=sanitary_vent_design_profile();module=load_sanitary_vent_rulebook()
 rules={row['validator']:row for row in rule_rows(module)}
 fixture_rule_id=rules['fixture_dfu']['rule_id'];capacity_rule_id=rules['main_horizontal_dfu_capacity']['rule_id']
 fixture_table=profile['fixture_dfu'];capacity=profile['main_horizontal_capacity']
 fixture_loads={};missing=[]
 for index,fixture in enumerate(fixtures or []):
  fixture_id=fixture.get('id');kind=str(fixture.get('fixture_dfu_type') or '');count=fixture.get('count',1)
  if not fixture_id: missing.append(f'fixtures[{index}].id');continue
  if kind not in fixture_table: missing.append(f'fixtures[{index}].supported_fixture_dfu_type');continue
  try: numeric_count=float(count)
  except (TypeError,ValueError): numeric_count=0
  if numeric_count<=0 or not numeric_count.is_integer(): missing.append(f'fixtures[{index}].count');continue
  fixture_loads[fixture_id]=float(fixture_table[kind])*int(numeric_count)
 if missing or not fixture_loads:
  return {'status':'INPUT_REQUIRED','missing_inputs':sorted(missing or ['fixtures']),'errors':[],
          'segments':[],'rulebook_module_version':profile['module_version']}
 rows=[];errors=[];input_required=[]
 for segment in segments or []:
  segment_id=str(segment.get('id') or 'UNKNOWN');downstream=segment.get('downstream_fixture_ids');slope=segment.get('slope_percent')
  if not isinstance(downstream,list) or not downstream:
   input_required.append(f'{segment_id}:downstream_fixture_ids');continue
  unknown=sorted(set(downstream)-set(fixture_loads))
  if unknown: input_required.append(f"{segment_id}:unknown_fixtures:{','.join(unknown)}");continue
  try: slope_key=f"{float(slope):g}"
  except (TypeError,ValueError): input_required.append(f'{segment_id}:slope_percent');continue
  candidates=[];load=sum(fixture_loads[value] for value in downstream)
  for dn_text,by_slope in sorted(capacity.items(),key=lambda item:float(item[0])):
   maximum=by_slope.get(slope_key)
   if maximum is not None:
    candidates.append({'dn_mm':float(dn_text),'maximum_dfu':float(maximum),
                       'pass':load<=float(maximum)})
  if not candidates:
   input_required.append(f'{segment_id}:exact_supported_slope_row:{slope_key}');continue
  selected=next((candidate for candidate in candidates if candidate['pass']),None)
  calc_id='CALC-SANITARY-'+sha256(segment_id.encode()).hexdigest()[:12].upper()
  drawing_dn=segment.get('drawing_dn_mm',selected['dn_mm'] if selected else None)
  if selected is None: errors.append(f'{segment_id}:capacity_exceeded')
  elif float(drawing_dn)!=selected['dn_mm']: errors.append(f'{segment_id}:drawing_dn_mismatch')
  rows.append({'segment_id':segment_id,'downstream_fixture_ids':sorted(downstream),
               'calculated_dfu':load,'slope_percent':float(slope),'selected_dn_mm':selected['dn_mm'] if selected else None,
               'drawing_dn_mm':drawing_dn,'calc_id':calc_id,'size_source':calc_id,'candidates':candidates,
               'capacity_rule_id':capacity_rule_id,'fixture_dfu_rule_id':fixture_rule_id})
 status='FAIL' if errors else ('INPUT_REQUIRED' if input_required else 'PASS')
 return {'status':status,'missing_inputs':sorted(input_required),'errors':sorted(errors),'segments':rows,
         'rulebook_module_version':profile['module_version'],
         'coverage_limit':'EXACT_M16_MAIN_HORIZONTAL_DN_SLOPE_ROWS_NO_INTERPOLATION'}

def design_sanitary_branch_stack_from_rulebook(segments,fixtures):
 from .sanitary_vent_rulebook import sanitary_vent_design_profile,load_sanitary_vent_rulebook
 from .executable_rulebook import rule_rows
 profile=sanitary_vent_design_profile();module=load_sanitary_vent_rulebook();rules={r['validator']:r for r in rule_rows(module)}
 loads={};missing=[]
 for i,f in enumerate(fixtures or []):
  fid=f.get('id');kind=str(f.get('fixture_dfu_type') or '');count=f.get('count',1)
  if not fid or kind not in profile['fixture_dfu']: missing.append(f'fixtures[{i}].identity_or_supported_type');continue
  try: count=float(count)
  except (TypeError,ValueError): count=0
  if count<=0 or not count.is_integer(): missing.append(f'fixtures[{i}].count');continue
  loads[fid]=float(profile['fixture_dfu'][kind])*int(count)
 if missing or not loads:return {'status':'INPUT_REQUIRED','missing_inputs':sorted(missing or ['fixtures']),'errors':[],'segments':[]}
 key_by_kind={'HORIZONTAL_BRANCH':'horizontal_branch','STACK_PER_FLOOR':'stack_per_floor','STACK_UP_TO_3_FLOORS':'stack_up_to_3_floors','STACK_OVER_3_FLOORS':'stack_over_3_floors'}
 rows=[];needed=[];errors=[]
 for segment in segments or []:
  sid=str(segment.get('id') or 'UNKNOWN');kind=str(segment.get('segment_kind') or '');down=segment.get('downstream_fixture_ids')
  if kind not in key_by_kind:needed.append(f'{sid}:supported_segment_kind');continue
  if not isinstance(down,list) or not down:needed.append(f'{sid}:downstream_fixture_ids');continue
  unknown=sorted(set(down)-set(loads))
  if unknown:needed.append(f"{sid}:unknown_fixtures:{','.join(unknown)}");continue
  load=sum(loads[x] for x in down);candidates=[]
  for dn,limits in sorted(profile['branch_stack_capacity'].items(),key=lambda x:float(x[0])):
   limit=limits.get(key_by_kind[kind])
   if limit is not None:candidates.append({'dn_mm':float(dn),'maximum_dfu':float(limit),'pass':load<=float(limit)})
  selected=next((x for x in candidates if x['pass']),None);calc='CALC-SANITARY-'+sha256(sid.encode()).hexdigest()[:12].upper()
  if selected is None:errors.append(f'{sid}:capacity_exceeded')
  drawing=segment.get('drawing_dn_mm',selected['dn_mm'] if selected else None)
  if selected and float(drawing)!=selected['dn_mm']:errors.append(f'{sid}:drawing_dn_mismatch')
  rows.append({'segment_id':sid,'segment_kind':kind,'calculated_dfu':load,'selected_dn_mm':selected['dn_mm'] if selected else None,'drawing_dn_mm':drawing,'calc_id':calc,'size_source':calc,'candidates':candidates,'rule_id':rules['branch_stack_dfu_capacity']['rule_id']})
 return {'status':'FAIL' if errors else ('INPUT_REQUIRED' if needed else 'PASS'),'missing_inputs':sorted(needed),'errors':sorted(errors),'segments':rows,'rulebook_module_version':profile['module_version']}

def design_vent_stack_from_rulebook(rows):
 from .sanitary_vent_rulebook import sanitary_vent_design_profile,load_sanitary_vent_rulebook
 from .executable_rulebook import rule_rows
 profile=sanitary_vent_design_profile();module=load_sanitary_vent_rulebook();rules={r['validator']:r for r in rule_rows(module)}
 table=profile['vent_stack_capacity'];out=[];missing=[];errors=[]
 for i,row in enumerate(rows or []):
  sid=str(row.get('id') or f'VENT-{i}')
  try:waste=float(row['waste_diameter_in']);load=float(row['connected_dfu']);length=float(row['developed_length_ft'])
  except (KeyError,TypeError,ValueError):missing.append(f'{sid}:positive_numeric_source_units');continue
  key=f'{waste:g}@{load:g}';options=table.get(key)
  if not options:missing.append(f'{sid}:exact_supported_waste_dfu_row');continue
  candidates=[{'vent_diameter_in':float(d),'maximum_length_ft':float(maxlen),'pass':length<=float(maxlen)} for d,maxlen in sorted(options.items(),key=lambda x:float(x[0]))]
  selected=next((x for x in candidates if x['pass']),None)
  if selected is None:errors.append(f'{sid}:developed_length_exceeds_table')
  drawing=row.get('drawing_vent_diameter_in',selected['vent_diameter_in'] if selected else None)
  if selected and float(drawing)!=selected['vent_diameter_in']:errors.append(f'{sid}:drawing_diameter_mismatch')
  calc='CALC-VENT-'+sha256(sid.encode()).hexdigest()[:12].upper()
  out.append({'segment_id':sid,'waste_diameter_in':waste,'connected_dfu':load,'developed_length_ft':length,'selected_vent_diameter_in':selected['vent_diameter_in'] if selected else None,'drawing_vent_diameter_in':drawing,'calc_id':calc,'size_source':calc,'candidates':candidates,'rule_id':rules['vent_stack_dfu_length_capacity']['rule_id']})
 return {'status':'FAIL' if errors else ('INPUT_REQUIRED' if missing or not out else 'PASS'),'missing_inputs':sorted(missing),'errors':sorted(errors),'segments':out,'rulebook_module_version':profile['module_version'],'coverage_limit':'EXACT_WASTE_DFU_VENT_DIAMETER_ROWS_IN_ORIGINAL_INCH_FOOT_UNITS'}

def validate_sanitary_cleanouts_from_rulebook(cleanouts,inventory_complete):
 from .sanitary_vent_rulebook import load_sanitary_vent_rulebook,VALIDATORS
 from .executable_rulebook import rule_rows
 module=load_sanitary_vent_rulebook();rule=next(r for r in rule_rows(module) if r['validator']=='cleanout_inventory')
 result=VALIDATORS['cleanout_inventory'](rule,{'sanitary':{'cleanouts':cleanouts,'cleanout_inventory_complete':inventory_complete}})
 result['calc_id']='CALC-CLEANOUT-'+sha256(json.dumps(cleanouts or [],sort_keys=True,separators=(',',':')).encode()).hexdigest()[:12].upper()
 result['rulebook_module_version']=module['manifest']['version'];return result

def design_vent_routes_from_rulebook(routes):
 from .sanitary_vent_rulebook import sanitary_vent_design_profile,load_sanitary_vent_rulebook
 from .executable_rulebook import rule_rows
 profile=sanitary_vent_design_profile();module=load_sanitary_vent_rulebook();rules={r['validator']:r for r in rule_rows(module)}
 p=profile['vent_minimum_size'];series=[float(x) for x in p['nominal_dn_series_mm']]
 out=[];missing=[];errors=[]
 for i,route in enumerate(routes or []):
  rid=str(route.get('id') or f'VENT-ROUTE-{i}')
  try:waste=float(route['waste_dn_mm']);length=float(route['length_m'])
  except (KeyError,TypeError,ValueError):missing.append(f'{rid}:waste_dn_mm_and_length_m');continue
  base=max(float(p['minimum_dn_mm']),waste/2.0);required=next((x for x in series if x>=base),None)
  if required is None:missing.append(f'{rid}:supported_nominal_dn');continue
  if length>float(p['length_size_up_trigger_m']):
   index=series.index(required)
   if index+1>=len(series):missing.append(f'{rid}:next_nominal_dn');continue
   required=series[index+1]
  drawing=route.get('drawing_dn_mm',required)
  if float(drawing)!=required:errors.append(f'{rid}:drawing_dn_mismatch')
  calc='CALC-VENT-ROUTE-'+sha256(rid.encode()).hexdigest()[:12].upper()
  out.append({'route_id':rid,'waste_dn_mm':waste,'length_m':length,'selected_vent_dn_mm':required,'drawing_dn_mm':drawing,'plan_path':route.get('plan_path'),'riser_levels':route.get('riser_levels') or [],'calc_id':calc,'size_source':calc,'rule_id':rules['vent_minimum_size']['rule_id']})
 return {'status':'FAIL' if errors else ('INPUT_REQUIRED' if missing or not out else 'PASS'),'missing_inputs':sorted(missing),'errors':sorted(errors),'routes':out,'rulebook_module_version':profile['module_version']}

def evaluate_vent_geometry_from_rulebook(fixture_connections,terminations):
 from .sanitary_vent_rulebook import load_sanitary_vent_rulebook,VALIDATORS
 from .executable_rulebook import rule_rows
 module=load_sanitary_vent_rulebook();rules={r['validator']:r for r in rule_rows(module)};missing=[]
 connections=[]
 for i,row in enumerate(fixture_connections or []):
  points=row.get('trap_to_vent_path')
  if not isinstance(points,list) or len(points)<2 or any(not isinstance(p,(list,tuple)) or len(p)<2 for p in points):missing.append(f'fixture_connections[{i}].trap_to_vent_path');continue
  distance=sum(math.dist(tuple(a[:2]),tuple(b[:2])) for a,b in zip(points,points[1:]))
  connections.append({'waste_dn_mm':row.get('waste_dn_mm'),'waste_slope_percent':row.get('waste_slope_percent'),'trap_weir_to_vent_m':distance})
 termination_rows=[]
 for i,row in enumerate(terminations or []):
  point=row.get('point_xyz');openings=row.get('opening_points_xyz')
  if not isinstance(point,(list,tuple)) or len(point)!=3 or not isinstance(openings,list) or not openings:missing.append(f'terminations[{i}].point_and_openings');continue
  nearest=min(openings,key=lambda p:math.dist(tuple(point),tuple(p)))
  horizontal=math.dist(tuple(point[:2]),tuple(nearest[:2]));vertical=float(point[2])-float(nearest[2])
  built={'horizontal_to_opening_m':horizontal,'vertical_above_opening_m':vertical,'directly_below_opening':horizontal<=1e-9 and vertical<0,'wall_exit':row.get('wall_exit')}
  if row.get('wall_exit') is True:
   prop=row.get('nearest_property_point_xy');ground=row.get('ground_elevation_m')
   if not isinstance(prop,(list,tuple)) or len(prop)!=2 or ground is None:missing.append(f'terminations[{i}].wall_exit_geometry');continue
   built.update({'horizontal_to_property_m':math.dist(tuple(point[:2]),tuple(prop)),'height_above_ground_m':float(point[2])-float(ground),'under_balcony_or_canopy':row.get('under_balcony_or_canopy')})
  termination_rows.append(built)
 trap=VALIDATORS['trap_vent_distance'](rules['trap_vent_distance'],{'vent':{'fixture_connections':connections}})
 term=VALIDATORS['vent_termination_clearance'](rules['vent_termination_clearance'],{'vent':{'terminations':termination_rows}})
 all_missing=sorted(set(missing+trap['missing_inputs']+term['missing_inputs']));all_errors=sorted(set(trap['errors']+term['errors']))
 return {'status':'FAIL' if all_errors else ('INPUT_REQUIRED' if all_missing else 'PASS'),'missing_inputs':all_missing,'errors':all_errors,'trap_vent':trap,'termination':term,'rulebook_module_version':module['manifest']['version']}

def design_heating_installation_from_rulebook(heating_inventory):
 """Consume source-backed M14 safety/installation rules into design schedules."""
 from .heating_rulebook import evaluate_heating_rulebook
 evaluated=evaluate_heating_rulebook({'heating':heating_inventory or {}})
 systems=(heating_inventory or {}).get('hot_water_heating_systems') or []
 tanks=[]
 for index,system in enumerate(systems):
  tank=system.get('expansion_tank')
  if not isinstance(tank,dict):continue
  system_id=str(system.get('system_id') or f'HEATING-{index}')
  calc='CALC-HEATING-TANK-'+sha256(system_id.encode()).hexdigest()[:12].upper()
  tanks.append({'system_id':system_id,'tank_type':tank.get('type'),'selected_capacity_l':tank.get('selected_capacity_l'),
                'capacity_basis':{key:tank.get(key) for key in ('system_water_volume_l','minimum_operating_temperature_c','maximum_operating_temperature_c','maximum_working_pressure_kpa')},
                'normal_water_level_above_highest_component_mm':tank.get('normal_water_level_above_highest_component_mm'),
                'certified_test_pressure_kpa':tank.get('certified_test_pressure_kpa'),'accredited_test_report':tank.get('accredited_test_report'),
                'calc_id':calc,'selection_authority':'EXPLICIT_PROJECT_OR_ENGINEER_SELECTION','release_allowed':False})
 surfaces=[]
 for index,row in enumerate((heating_inventory or {}).get('exposed_surfaces') or []):
  surfaces.append({'surface_id':str(row.get('surface_id') or f'SURFACE-{index}'),'maximum_accessible_surface_temperature_c':row.get('maximum_accessible_surface_temperature_c'),'direct_contact_guard':row.get('direct_contact_guard'),'rule_id':'IR-M14-1391-14.3.5.1-HEATING-SURFACE-GUARD'})
 equipment=[]
 for index,row in enumerate((heating_inventory or {}).get('floor_mounted_equipment') or []):
  equipment.append({'equipment_id':str(row.get('equipment_id') or f'EQUIPMENT-{index}'),'base_height_mm':row.get('base_height_mm'),'rule_id':'IR-M14-1391-14.3.5.2-FLOOR-BASE-HEIGHT'})
 return {'status':evaluated['status'],'module_id':evaluated['module_id'],'rulebook_module_version':evaluated['module_version'],'rule_results':evaluated['results'],'expansion_tank_schedule':tanks,'surface_guard_schedule':surfaces,'equipment_base_schedule':equipment,'release_allowed':False,'coverage_limit':'M14_BOUNDED_HEATING_INSTALLATION_RULES_NO_CAPACITY_FORMULA'}

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
 required_basis={'capacity_table','service_pressure_mbar','allowable_pressure_drop_mbar',
                 'meter','regulator','service_shutoff','riser','fittings','sleeves'}
 missing=sorted(required_basis-set(design_basis or {}))
 if missing:return {'status':'INPUT_REQUIRED','missing_inputs':missing,'segments':[],'components':[]}
 if not appliances or not segments:
  return {'status':'INPUT_REQUIRED','missing_inputs':['gas_appliances' if not appliances else 'gas_segments'],
          'segments':[],'components':[]}
 required_app={'id','pmm_id','manufacturer','model','thermal_input_kw','gas_consumption_m3h','datasheet',
              'appliance_valve','flue','combustion_air'}
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
               'calc_id':calc_id,'size_source':calc_id,
               'source_pmm_ids':sorted(by_id[x]['pmm_id'] for x in segment['downstream_appliance_ids']),
               'status':'PASS' if selected else 'FAIL'})
 components=[{'type':'METER','evidence':design_basis['meter']},{'type':'REGULATOR','evidence':design_basis['regulator']},
             {'type':'SERVICE_SHUTOFF','evidence':design_basis['service_shutoff']},
             {'type':'RISER','evidence':design_basis['riser']},{'type':'FITTINGS','evidence':design_basis['fittings']},
             {'type':'SLEEVES','evidence':design_basis['sleeves']}]
 for app in by_id.values():
  components.extend([{'type':'APPLIANCE_VALVE','appliance_id':app['id'],'evidence':app['appliance_valve']},
                     {'type':'FLUE','appliance_id':app['id'],'evidence':app['flue']},
                     {'type':'COMBUSTION_AIR','appliance_id':app['id'],'evidence':app['combustion_air']}])
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
