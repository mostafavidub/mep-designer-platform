"""Stage 9 — dynamic mechanical detail/schedule library.

Templates define required engineering content; values come from project data.
They are not decorative symbols or static screenshots.
"""
from __future__ import annotations

DETAIL_TEMPLATES = {
    'sanitary_riser': {'title':'SANITARY / VENT RISER','required':['stack_id','levels','branch_sizes','stack_size','cleanout','vent_termination']},
    'cleanout': {'title':'TYPICAL CLEANOUT DETAIL','required':['pipe_size','access_required']},
    'vent_termination': {'title':'VENT TERMINATION AT ROOF','required':['vent_size','roof_reference']},
    'roof_drain': {'title':'ROOF DRAIN / RAINWATER DETAIL','required':['drain_size','slope_percent','riser_id']},
    'water_riser': {'title':'COLD / HOT WATER RISER','required':['riser_id','cold_size','hot_size','levels']},
    'pump_schedule': {'title':'PUMP SCHEDULE','required':['flow','head','location','tag']},
    'tank_schedule': {'title':'WATER TANK SCHEDULE','required':['capacity','location','tag']},
    'radiator': {'title':'RADIATOR CONNECTION DETAIL','required':['capacity','supply_size','return_size','tag']},
    'split_connection': {'title':'SPLIT UNIT CONNECTION','required':['capacity','liquid_gas','condensate_size','tag']},
    'exhaust_fan': {'title':'EXHAUST FAN SCHEDULE','required':['airflow_cfm','location','tag']},
    'gas_connection': {'title':'GAS APPLIANCE CONNECTION','required':['load_kw','pipe_size','tag']},
}


def _main_size(sizing, system):
    row=next((x for x in sizing.get('vertical_mains') or [] if x.get('system')==system),None)
    return row.get('size_mm') if row else None


def build_details_schedules(requirements, recognition, calculations, sizing, topology, project_overrides=None):
    systems=set(requirements.get('project_systems') or [])
    overrides=project_overrides or {}
    details=[]; schedules=[]
    def add_detail(kind, params):
        template=DETAIL_TEMPLATES[kind]
        details.append({'id':f'DET-{len(details)+1:03d}','kind':kind,'title':template['title'],'required_fields':template['required'],'parameters':params})
    def add_schedule(kind, params):
        template=DETAIL_TEMPLATES[kind]
        schedules.append({'id':f'SCH-{len(schedules)+1:03d}','kind':kind,'title':template['title'],'required_fields':template['required'],'parameters':params})

    if 'sanitary' in systems:
        add_detail('sanitary_riser',{'stack_id':'S1','levels':overrides.get('levels',[]),'branch_sizes':sorted({x.get('size_mm') for x in sizing.get('segments') or [] if x.get('system')=='sanitary' and x.get('size_mm')}),
                                      'stack_size':_main_size(sizing,'sanitary'),'cleanout':True,'vent_termination':True})
        add_detail('cleanout',{'pipe_size':_main_size(sizing,'sanitary'),'access_required':True})
    if 'vent' in systems:
        add_detail('vent_termination',{'vent_size':_main_size(sizing,'vent'),'roof_reference':'ROOF PLAN'})
    if 'cold_water' in systems or 'hot_water' in systems:
        add_detail('water_riser',{'riser_id':'W1','cold_size':_main_size(sizing,'cold_water'),'hot_size':_main_size(sizing,'hot_water'),'levels':overrides.get('levels',[])})
    for item in recognition.get('detections') or []:
        rc=next((x for x in calculations.get('rooms') or [] if x.get('room_id')==item.get('room_id')),{})
        if item.get('type')=='pump':
            add_schedule('pump_schedule',{'flow':overrides.get('pump_flow_lps',calculations.get('totals',{}).get('preliminary_water_lps')),
                                           'head':overrides.get('pump_head_m'),'location':item.get('room_id'),'tag':item.get('id')})
        elif item.get('type')=='tank':
            add_schedule('tank_schedule',{'capacity':overrides.get('tank_capacity_l'),'location':item.get('room_id'),'tag':item.get('id')})
        elif item.get('type')=='radiator':
            add_detail('radiator',{'capacity':rc.get('heating_w'),'supply_size':_main_size(sizing,'heating'),'return_size':_main_size(sizing,'heating'),'tag':item.get('id')})
        elif item.get('type')=='split_indoor':
            add_detail('split_connection',{'capacity':rc.get('cooling_w'),'liquid_gas':'PROJECT SELECTION','condensate_size':_main_size(sizing,'condensate'),'tag':item.get('id')})
        elif item.get('type')=='exhaust_fan':
            add_schedule('exhaust_fan',{'airflow_cfm':rc.get('exhaust_cfm'),'location':item.get('room_id'),'tag':item.get('id')})
        elif item.get('type') in {'stove','water_heater'}:
            add_detail('gas_connection',{'load_kw':rc.get('gas_kw'),'pipe_size':_main_size(sizing,'gas'),'tag':item.get('id')})
    return {'version':'detail-schedule-library-v13.9','details':details,'schedules':schedules,
            'quality':{'details':len(details),'schedules':len(schedules),'all_templates_traceable':all(x.get('required_fields') for x in details+schedules)}}
