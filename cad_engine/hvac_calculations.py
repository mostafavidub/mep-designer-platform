"""Fail-closed final cooling-load and exhaust-duty calculations."""
from __future__ import annotations

from hashlib import sha256
import json


def _id(prefix, payload):
    seed=json.dumps(payload,sort_keys=True,separators=(',',':'))
    return prefix+sha256(seed.encode()).hexdigest()[:12].upper()


def calculate_heating_design(rooms, design_basis):
    """Calculate room heat loss only from explicit envelope and outdoor-air inputs."""
    required_basis={'indoor_design_c','outdoor_design_c','wall_u_w_m2k','glazing_u_w_m2k',
                    'floor_u_w_m2k','ceiling_u_w_m2k','air_density_kg_m3',
                    'air_specific_heat_j_kgk','supply_c','return_c'}
    required_room={'id','pmm_id','area_m2','external_wall_area_m2','glazing_area_m2',
                   'exposed_floor_area_m2','exposed_ceiling_area_m2','infiltration_m3h',
                   'ventilation_m3h'}
    missing=sorted(required_basis-set(design_basis or {}))
    if not rooms: missing.append('heating_rooms')
    for room in rooms or []:
        missing.extend(f"{room.get('id','UNKNOWN')}:{key}" for key in sorted(required_room-set(room)))
    if missing:return {'status':'INPUT_REQUIRED','missing_inputs':sorted(set(missing)),'rooms':[]}
    dt=float(design_basis['indoor_design_c'])-float(design_basis['outdoor_design_c'])
    water_dt=float(design_basis['supply_c'])-float(design_basis['return_c'])
    if dt<=0 or water_dt<=0:
        return {'status':'FAIL','errors':['HEATING_DESIGN_DELTA_T_NOT_POSITIVE' if dt<=0 else 'HEATING_WATER_DELTA_T_NOT_POSITIVE'],'rooms':[]}
    rows=[]
    for room in rooms:
        outdoor_air=float(room['infiltration_m3h'])+float(room['ventilation_m3h'])
        components={
            'wall_w':float(room['external_wall_area_m2'])*float(design_basis['wall_u_w_m2k'])*dt,
            'glazing_w':float(room['glazing_area_m2'])*float(design_basis['glazing_u_w_m2k'])*dt,
            'floor_w':float(room['exposed_floor_area_m2'])*float(design_basis['floor_u_w_m2k'])*dt,
            'ceiling_w':float(room['exposed_ceiling_area_m2'])*float(design_basis['ceiling_u_w_m2k'])*dt,
            'outdoor_air_w':outdoor_air/3600*float(design_basis['air_density_kg_m3'])*
                            float(design_basis['air_specific_heat_j_kgk'])*dt,
        }
        load=sum(components.values())
        calc_id=_id('CALC-HEAT-ROOM-',{'room':room,'basis':design_basis})
        rows.append({'room_id':room['id'],'pmm_id':room['pmm_id'],'area_m2':float(room['area_m2']),
                     'heating_w':round(load,2),'required_output_w':round(load,2),
                     'components_w':{key:round(value,2) for key,value in components.items()},
                     'design_water_temperatures_c':{'supply':float(design_basis['supply_c']),
                                                    'return':float(design_basis['return_c']),
                                                    'room':float(design_basis['indoor_design_c'])},
                     'calc_id':calc_id,'source_pmm_ids':[room['pmm_id']]})
    return {'status':'PASS','rooms':rows,'basis':design_basis,
            'identity_policy':'PMM room -> room heat-loss calculation -> exact radiator selection'}


def calculate_cooling_design(rooms, design_basis):
    """Calculate room and diversified zone sensible loads from explicit inputs."""
    required_basis={'indoor_design_c','outdoor_design_c','wall_u_w_m2k','glazing_u_w_m2k',
                    'solar_gain_w_m2_by_orientation','people_sensible_w','air_density_kg_m3',
                    'air_specific_heat_j_kgk','zone_diversity'}
    missing=sorted(required_basis-set(design_basis or {}))
    required_room={'id','pmm_id','zone_id','area_m2','orientation','glazing_area_m2','external_wall_area_m2',
                   'occupancy','lighting_w','equipment_w','infiltration_m3h','ventilation_m3h'}
    for room in rooms or []:
        missing.extend(f"{room.get('id','UNKNOWN')}:{key}" for key in sorted(required_room-set(room)))
    if not rooms: missing.append('cooling_rooms')
    if missing:return {'status':'INPUT_REQUIRED','missing_inputs':sorted(set(missing)),'rooms':[],'zones':[]}
    dt=float(design_basis['outdoor_design_c'])-float(design_basis['indoor_design_c'])
    if dt<=0:return {'status':'FAIL','errors':['COOLING_DESIGN_DELTA_T_NOT_POSITIVE'],'rooms':[],'zones':[]}
    rows=[]
    solar_table=design_basis['solar_gain_w_m2_by_orientation']
    for room in rooms:
        if room['orientation'] not in solar_table:
            return {'status':'INPUT_REQUIRED','missing_inputs':[f"{room['id']}:solar_gain:{room['orientation']}"],
                    'rooms':[],'zones':[]}
        air_m3h=float(room['infiltration_m3h'])+float(room['ventilation_m3h'])
        components={
          'wall_w':float(room['external_wall_area_m2'])*float(design_basis['wall_u_w_m2k'])*dt,
          'glazing_conduction_w':float(room['glazing_area_m2'])*float(design_basis['glazing_u_w_m2k'])*dt,
          'glazing_solar_w':float(room['glazing_area_m2'])*float(solar_table[room['orientation']]),
          'people_w':float(room['occupancy'])*float(design_basis['people_sensible_w']),
          'lighting_w':float(room['lighting_w']),'equipment_w':float(room['equipment_w']),
          'outdoor_air_w':air_m3h/3600*float(design_basis['air_density_kg_m3'])*
                          float(design_basis['air_specific_heat_j_kgk'])*dt,
        }
        total=sum(components.values()); calc_id=_id('CALC-COOL-',{'room':room,'basis':design_basis})
        rows.append({'room_id':room['id'],'zone_id':room['zone_id'],'area_m2':float(room['area_m2']),
                     'calculated_load_w':round(total,2),'calculated_load_btu_h':round(total*3.412142),
                     'components_w':{k:round(v,2) for k,v in components.items()},'calc_id':calc_id,
                     'pmm_id':room['pmm_id'],'source_pmm_ids':[room['pmm_id']]})
    zones=[]
    for zone_id in sorted({row['zone_id'] for row in rows}):
        diversity=(design_basis['zone_diversity'] or {}).get(zone_id)
        if diversity is None:
            return {'status':'INPUT_REQUIRED','missing_inputs':[f'zone_diversity:{zone_id}'],'rooms':rows,'zones':[]}
        connected=sum(row['calculated_load_w'] for row in rows if row['zone_id']==zone_id)
        design=connected*float(diversity)
        zones.append({'zone_id':zone_id,'connected_load_w':round(connected,2),'diversity':float(diversity),
                      'design_load_w':round(design,2),'design_load_btu_h':round(design*3.412142),
                      'source_calc_ids':[row['calc_id'] for row in rows if row['zone_id']==zone_id],
                      'source_pmm_ids':[row['pmm_id'] for row in rows if row['zone_id']==zone_id]})
    return {'status':'PASS','rooms':rows,'zones':zones,'basis':design_basis}


def calculate_exhaust_design(rooms, criteria):
    """Determine every applicable room duty and ESP without implicit room defaults."""
    required_room={'id','room_type','volume_m3','duct_path'}; missing=[]; rows=[]
    if not rooms:missing.append('exhaust_rooms')
    for room in rooms or []:
        missing.extend(f"{room.get('id','UNKNOWN')}:{key}" for key in sorted(required_room-set(room)))
        rule=(criteria or {}).get(room.get('room_type'))
        if not rule:missing.append(f"criteria:{room.get('room_type')}")
        elif not ({'minimum_cfm','ach'} & set(rule)):missing.append(f"criteria:{room.get('room_type')}:minimum_cfm_or_ach")
        for key in ('duct_friction_pa','fitting_loss_pa','terminal_loss_pa'):
            if key not in (room.get('duct_path') or {}):missing.append(f"{room.get('id','UNKNOWN')}:duct_path.{key}")
    if missing:return {'status':'INPUT_REQUIRED','missing_inputs':sorted(set(missing)),'rooms':[],'unserved_room_ids':[]}
    for room in rooms:
        rule=criteria[room['room_type']]
        ach_cfm=float(rule.get('ach',0))*float(room['volume_m3'])*35.314667/60
        required=max(float(rule.get('minimum_cfm',0)),ach_cfm)
        path=room['duct_path']; esp=sum(float(path[key]) for key in ('duct_friction_pa','fitting_loss_pa','terminal_loss_pa'))
        rows.append({'room_id':room['id'],'room_type':room['room_type'],'required_cfm':round(required,2),
                     'required_esp_pa':round(esp,2),'calc_id':_id('CALC-EXH-',{'room':room,'rule':rule})})
    return {'status':'PASS','rooms':rows,'unserved_room_ids':[],'coverage':1.0}
