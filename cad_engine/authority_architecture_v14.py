from __future__ import annotations
from collections import Counter

REQUIRED_REFERENCE_FAMILIES = {
    'COVER','GENERAL_DETAIL','ROOF','SANITARY_VENT','WATER','HEATING','GAS',
    'PLUMBING_RISER','WATER_SERVICE_CALC','GENERAL_NOTES','SPLIT_AC','EXHAUST',
    'EQUIPMENT_SCHEDULE'
}


def build_project_model(levels, roof_present, occupancy='residential', excluded_frames=0):
    errors=[]
    if not levels: errors.append('no_mechanical_floor_levels')
    if any(not isinstance(v,dict) for v in levels.values()): errors.append('invalid_level_evidence')
    return {'version':'project-model-v14.0','status':'PASS' if not errors else 'FAIL','errors':errors,
            'levels':levels,'roof_present':bool(roof_present),'occupancy':occupancy,'excluded_frame_count':excluded_frames}


def resolve_design_basis(project, overrides):
    b=dict(overrides or {})
    missing=[k for k in ('city','cooling_system','heating_system') if not b.get(k)]
    b.setdefault('occupancy',project.get('occupancy'))
    b.setdefault('required_external_inputs',[])
    return {'version':'design-basis-v14.0','status':'PASS' if not missing else 'INPUT_REQUIRED','missing':missing,'basis':b}


def derive_system_requirements(project, design_basis):
    by_level={}
    for level,ev in (project.get('levels') or {}).items():
        systems=set()
        if ev.get('wet'): systems.update({'sanitary','vent','cold_water','hot_water'})
        if ev.get('habitable'):
            systems.add('heating')
            if design_basis['basis'].get('cooling_system'): systems.add('split_ac')
        if ev.get('exhaust'): systems.add('exhaust')
        if ev.get('gas_appliance') and design_basis['basis'].get('gas_service'): systems.add('gas')
        by_level[level]=sorted(systems)
    project_systems={s for row in by_level.values() for s in row}
    if project.get('roof_present'):
        project_systems.update({'rainwater','vent_termination'})
        if design_basis['basis'].get('cooling_system')=='wall_mounted_split_ac': project_systems.add('split_outdoor')
    return {'version':'system-requirements-v14.0','status':'PASS','by_level':by_level,'project_systems':sorted(project_systems)}


def build_reference_driven_manifest(project, requirements):
    rows=[]
    def add(family,level='MULTI',purpose='PLAN',title=None):
        rows.append({'sheet':None,'family':family,'level':level,'purpose':purpose,'title':title or family.replace('_',' ')})
    add('COVER',purpose='COVER',title='MECHANICAL COVER / DRAWING INDEX')
    for i in range(1,4): add('GENERAL_DETAIL',f'DETAIL-{i}','DETAIL',f'GENERAL / TYPICAL MECHANICAL DETAILS {i}')
    if project.get('roof_present'): add('ROOF','ROOF',title='ROOF / RAINWATER / VENT TERMINATION')
    levels=list(project.get('levels') or {})
    for level in levels:
        systems=set(requirements['by_level'].get(level) or [])
        if {'sanitary','vent'} & systems: add('SANITARY_VENT',level)
    water_levels=[]
    for level in levels:
        systems=set(requirements['by_level'].get(level) or [])
        if {'cold_water','hot_water'} & systems: add('WATER',level); water_levels.append(level)
    if len(water_levels)>=2: add('WATER','SERVICE',title='WATER SERVICE / SOURCE / PUMP-TANK COORDINATION')
    for level in levels:
        systems=set(requirements['by_level'].get(level) or [])
        if 'heating' in systems: add('HEATING',level)
    for level in levels:
        if 'gas' in set(requirements['by_level'].get(level) or []): add('GAS',level)
    if 'sanitary' in requirements.get('project_systems',[]): add('PLUMBING_RISER',purpose='RISER',title='PLUMBING RISER DIAGRAM')
    if water_levels: add('WATER_SERVICE_CALC',purpose='CALC',title='WATER SERVICE / PUMP CALCULATION')
    add('GENERAL_NOTES',purpose='NOTES',title='MECHANICAL GENERAL NOTES / DESIGN BASIS')
    split_levels=[]
    for level in levels:
        if 'split_ac' in set(requirements['by_level'].get(level) or []): add('SPLIT_AC',level); split_levels.append(level)
    if split_levels and project.get('roof_present'): add('SPLIT_AC','ROOF',title='SPLIT AC OUTDOOR UNIT / ROOF COORDINATION')
    for level in levels:
        if 'exhaust' in set(requirements['by_level'].get(level) or []): add('EXHAUST',level)
    add('EQUIPMENT_SCHEDULE',purpose='SCHEDULE',title='MECHANICAL EQUIPMENT / PIPE SCHEDULE')
    for i,row in enumerate(rows): row['sheet']=f'M-{i:02d}'
    counts=Counter(r['family'] for r in rows)
    return {'version':'adaptive-sheet-planner-v14.0','status':'PASS','sheet_count':len(rows),'family_counts':dict(counts),'sheets':rows}


def build_network_contract(requirements):
    topologies={'sanitary':'fixture->branch->main->stack','vent':'fixture-vent->vent-main->roof',
                'cold_water':'service->main->branch->fixture','hot_water':'source->main->branch->fixture',
                'heating':'package->flow->emitter->return','split_ac':'indoor->refrigerant-pair->vertical-ref->outdoor',
                'gas':'meter->main->appliance','exhaust':'room-point->fan->discharge'}
    graphs=[]
    for level,systems in (requirements.get('by_level') or {}).items():
        for system in systems: graphs.append({'level':level,'system':system,'topology':topologies.get(system,'system-specific-network')})
    return {'version':'network-contract-v14.0','status':'PASS','graphs':graphs,'cross_level_physical_edges':0}


def build_calculation_contract():
    calculations={'sanitary':{'method':'DFU+slope','status':'PRELIMINARY'},
                  'water':{'method':'FU+pressure-loss','status':'INPUT_REQUIRED'},
                  'heating':{'method':'room-heat-loss+deltaT+flow','status':'PRELIMINARY'},
                  'split_ac':{'method':'room-load+manufacturer-selection','status':'INPUT_REQUIRED'},
                  'condensate':{'method':'drain-rule','status':'DESIGN_RULE','dn_min_mm':25,'slope_min_percent':1.0},
                  'gas':{'method':'connected-load+equivalent-length','status':'INPUT_REQUIRED'},
                  'rainwater':{'method':'catchment+design-rainfall','status':'INPUT_REQUIRED'},
                  'exhaust':{'method':'ACH/CFM-by-use','status':'PRELIMINARY'}}
    return {'version':'calculation-contract-v14.0','status':'PASS','fabricated_final_values':0,'calculations':calculations}


def validate_authority_contract(project, design_basis, requirements, manifest, network, calculations):
    errors=[]
    if project.get('status')!='PASS': errors.append('project_model_invalid')
    if design_basis.get('status') not in {'PASS','INPUT_REQUIRED'}: errors.append('design_basis_invalid')
    families=set(manifest.get('family_counts') or {})
    # Only families required by project evidence are mandatory; COVER/DETAIL/NOTES/SCHEDULE always are.
    always={'COVER','GENERAL_DETAIL','GENERAL_NOTES','EQUIPMENT_SCHEDULE'}
    if project.get('roof_present'): always.add('ROOF')
    if 'sanitary' in requirements.get('project_systems',[]): always.update({'SANITARY_VENT','PLUMBING_RISER'})
    if 'cold_water' in requirements.get('project_systems',[]): always.update({'WATER','WATER_SERVICE_CALC'})
    if 'heating' in requirements.get('project_systems',[]): always.add('HEATING')
    if 'gas' in requirements.get('project_systems',[]): always.add('GAS')
    if 'split_ac' in requirements.get('project_systems',[]): always.add('SPLIT_AC')
    if 'exhaust' in requirements.get('project_systems',[]): always.add('EXHAUST')
    missing=always-families
    if missing: errors.append('missing_sheet_families:'+','.join(sorted(missing)))
    if network.get('cross_level_physical_edges')!=0: errors.append('cross_level_physical_geometry')
    if calculations.get('fabricated_final_values')!=0: errors.append('fabricated_final_engineering_values')
    return {'version':'authority-contract-qa-v14.0','status':'PASS' if not errors else 'FAIL','errors':errors}
