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
    return {'version':'project-model-v14.1','status':'PASS' if not errors else 'FAIL','errors':errors,
            'levels':levels,'roof_present':bool(roof_present),'occupancy':occupancy,'excluded_frame_count':excluded_frames}


def resolve_design_basis(project, overrides):
    b=dict(overrides or {})
    missing=[k for k in ('city','cooling_system','heating_system') if not b.get(k)]
    b.setdefault('occupancy',project.get('occupancy'))
    b.setdefault('required_external_inputs',[])
    return {'version':'design-basis-v14.1','status':'PASS' if not missing else 'INPUT_REQUIRED','missing':missing,'basis':b}


def derive_system_requirements(project, design_basis):
    by_level={}
    for level,ev in (project.get('levels') or {}).items():
        systems=set()
        if ev.get('wet'): systems.update({'sanitary','vent','cold_water','hot_water'})
        if ev.get('habitable'):
            if design_basis['basis'].get('heating_system'): systems.add('heating')
            if design_basis['basis'].get('cooling_system'): systems.add('split_ac')
        if ev.get('exhaust'): systems.add('exhaust')
        if ev.get('gas_appliance') and design_basis['basis'].get('gas_service'): systems.add('gas')
        by_level[level]=sorted(systems)
    project_systems={s for row in by_level.values() for s in row}
    if project.get('roof_present'):
        project_systems.update({'rainwater','vent_termination'})
        if design_basis['basis'].get('cooling_system')=='wall_mounted_split_ac': project_systems.add('split_outdoor')
    return {'version':'system-requirements-v14.1','status':'PASS','by_level':by_level,'project_systems':sorted(project_systems)}


def build_reference_driven_manifest(project, requirements):
    """Build only sheets justified by project evidence and selected systems."""
    rows=[]
    def add(family,level='MULTI',purpose='PLAN',title=None):
        rows.append({'sheet':None,'family':family,'level':level,'purpose':purpose,'title':title or family.replace('_',' ')})

    project_systems=set(requirements.get('project_systems') or [])
    levels=list(project.get('levels') or {})
    add('COVER',purpose='COVER',title='MECHANICAL COVER / DRAWING INDEX')
    add('GENERAL_NOTES',purpose='NOTES',title='MECHANICAL GENERAL NOTES / DESIGN BASIS')

    if project.get('roof_present') and ({'rainwater','vent_termination','split_outdoor'} & project_systems):
        add('ROOF','ROOF',title='ROOF / RAINWATER / VENT TERMINATION')

    water_levels=[]
    for level in levels:
        systems=set(requirements['by_level'].get(level) or [])
        if {'sanitary','vent'} & systems: add('SANITARY_VENT',level)
        if {'cold_water','hot_water'} & systems:
            add('WATER',level); water_levels.append(level)
        if 'heating' in systems: add('HEATING',level)
        if 'gas' in systems: add('GAS',level)
        if 'split_ac' in systems: add('SPLIT_AC',level)
        if 'exhaust' in systems: add('EXHAUST',level)

    if len(water_levels)>=2:
        add('WATER','SERVICE',title='WATER SERVICE / SOURCE / PUMP-TANK COORDINATION')
    if 'sanitary' in project_systems:
        add('PLUMBING_RISER',purpose='RISER',title='PLUMBING RISER DIAGRAM')
    if water_levels:
        add('WATER_SERVICE_CALC',purpose='CALC',title='WATER SERVICE / PUMP CALCULATION')
    if 'split_ac' in project_systems and project.get('roof_present'):
        add('SPLIT_AC','ROOF',title='SPLIT AC OUTDOOR UNIT / ROOF COORDINATION')

    detail_groups=[]
    if {'sanitary','vent','cold_water','hot_water'} & project_systems: detail_groups.append('PLUMBING')
    if {'heating','split_ac','exhaust'} & project_systems: detail_groups.append('HVAC')
    if 'gas' in project_systems: detail_groups.append('GAS')
    for i,group in enumerate(detail_groups,1):
        add('GENERAL_DETAIL',f'DETAIL-{i}','DETAIL',f'{group} PROJECT-APPLICABLE DETAILS')

    equipment_systems={'heating','split_ac','exhaust','gas'} & project_systems
    if equipment_systems:
        add('EQUIPMENT_SCHEDULE',purpose='SCHEDULE',title='MECHANICAL EQUIPMENT / PIPE SCHEDULE')

    for i,row in enumerate(rows): row['sheet']=f'M-{i:02d}'
    counts=Counter(r['family'] for r in rows)
    return {'version':'adaptive-sheet-planner-v14.1','status':'PASS','sheet_count':len(rows),'family_counts':dict(counts),'sheets':rows}


def build_network_contract(requirements):
    topologies={'sanitary':'fixture->branch->main->stack','vent':'fixture-vent->vent-main->roof',
                'cold_water':'service->main->branch->fixture','hot_water':'source->main->branch->fixture',
                'heating':'package->flow->emitter->return','split_ac':'indoor->refrigerant-pair->vertical-ref->outdoor',
                'gas':'meter->main->appliance','exhaust':'room-point->fan->discharge'}
    graphs=[]
    for level,systems in (requirements.get('by_level') or {}).items():
        for system in systems: graphs.append({'level':level,'system':system,'topology':topologies.get(system,'system-specific-network')})
    return {'version':'network-contract-v14.1','status':'PASS','graphs':graphs,'cross_level_physical_edges':0}


def build_calculation_contract():
    calculations={'sanitary':{'method':'DFU+slope','status':'PRELIMINARY'},
                  'water':{'method':'FU+pressure-loss','status':'INPUT_REQUIRED'},
                  'heating':{'method':'room-heat-loss+deltaT+flow','status':'PRELIMINARY'},
                  'split_ac':{'method':'room-load+manufacturer-selection','status':'INPUT_REQUIRED'},
                  'condensate':{'method':'drain-rule','status':'DESIGN_RULE','dn_min_mm':25,'slope_min_percent':1.0},
                  'gas':{'method':'connected-load+equivalent-length','status':'INPUT_REQUIRED'},
                  'rainwater':{'method':'catchment+design-rainfall','status':'INPUT_REQUIRED'},
                  'exhaust':{'method':'ACH/CFM-by-use','status':'PRELIMINARY'}}
    return {'version':'calculation-contract-v14.1','status':'PASS','fabricated_final_values':0,'calculations':calculations}


def validate_authority_contract(project, design_basis, requirements, manifest, network, calculations):
    errors=[]
    if project.get('status')!='PASS': errors.append('project_model_invalid')
    # Production design is fail-closed: unresolved basis may be asked from the user,
    # but it may never progress into an issued drawing package.
    if design_basis.get('status')!='PASS':
        errors.append('design_basis_input_required:'+','.join(design_basis.get('missing') or []))
    families=set(manifest.get('family_counts') or {})
    mandatory={'COVER','GENERAL_NOTES'}
    if project.get('roof_present') and ({'rainwater','vent_termination','split_outdoor'} & set(requirements.get('project_systems') or [])): mandatory.add('ROOF')
    if 'sanitary' in requirements.get('project_systems',[]): mandatory.update({'SANITARY_VENT','PLUMBING_RISER'})
    if 'cold_water' in requirements.get('project_systems',[]): mandatory.update({'WATER','WATER_SERVICE_CALC'})
    if 'heating' in requirements.get('project_systems',[]): mandatory.add('HEATING')
    if 'gas' in requirements.get('project_systems',[]): mandatory.add('GAS')
    if 'split_ac' in requirements.get('project_systems',[]): mandatory.add('SPLIT_AC')
    if 'exhaust' in requirements.get('project_systems',[]): mandatory.add('EXHAUST')
    missing=mandatory-families
    if missing: errors.append('missing_sheet_families:'+','.join(sorted(missing)))
    allowed=mandatory|{'GENERAL_DETAIL','EQUIPMENT_SCHEDULE'}
    unexpected=families-allowed
    if unexpected: errors.append('unjustified_sheet_families:'+','.join(sorted(unexpected)))
    if network.get('cross_level_physical_edges')!=0: errors.append('cross_level_physical_geometry')
    if calculations.get('fabricated_final_values')!=0: errors.append('fabricated_final_engineering_values')
    return {'version':'authority-contract-qa-v14.1','status':'PASS' if not errors else 'FAIL','errors':errors}
