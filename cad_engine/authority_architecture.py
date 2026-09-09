from __future__ import annotations
from collections import Counter
import re

REQUIRED_REFERENCE_FAMILIES = {
    'COVER','GENERAL_DETAIL','ROOF','SANITARY_VENT','WATER','HEATING','GAS',
    'PLUMBING_RISER','WATER_SERVICE_CALC','GENERAL_NOTES','SPLIT_AC','EXHAUST',
    'EQUIPMENT_SCHEDULE'
}
SUPPORTED_COOLING={'wall_mounted_split_ac'}
SUPPORTED_HEATING={'package_radiator'}


def _number(value):
    if value in (None,'',[]): return None
    if isinstance(value,(int,float)): return float(value)
    m=re.search(r'[-+]?\d+(?:[.,]\d+)?',str(value).replace('٫','.'))
    return float(m.group(0).replace(',','.')) if m else None


def build_project_model(levels, roof_present, occupancy='residential', excluded_frames=0):
    errors=[]
    if not levels: errors.append('no_mechanical_floor_levels')
    if any(not isinstance(v,dict) for v in levels.values()): errors.append('invalid_level_evidence')
    return {'version':'project-model-v14.2','status':'PASS' if not errors else 'FAIL','errors':errors,
            'levels':levels,'roof_present':bool(roof_present),'occupancy':occupancy,'excluded_frame_count':excluded_frames}


def resolve_design_basis(project, overrides):
    """Resolve only explicit user/project inputs; never promote an unsupported system."""
    b=dict(overrides or {}); missing=[]; unsupported=[]
    levels=list((project.get('levels') or {}).values())
    has_habitable=any(x.get('habitable') for x in levels);has_wet=any(x.get('wet') for x in levels);has_gas_evidence=any(x.get('gas_appliance') for x in levels)
    if not b.get('city'): missing.append('city')
    if has_habitable and not b.get('cooling_system'): missing.append('cooling_system')
    if has_habitable and not b.get('heating_system'): missing.append('heating_system')
    if b.get('cooling_system') and b.get('cooling_system') not in SUPPORTED_COOLING: unsupported.append('cooling_system:'+str(b.get('cooling_system')))
    if b.get('heating_system') and b.get('heating_system') not in SUPPORTED_HEATING: unsupported.append('heating_system:'+str(b.get('heating_system')))
    if has_gas_evidence and b.get('gas_service') is None: missing.append('gas_service')
    if has_wet and _number(b.get('water_inlet_pressure')) is None: missing.append('water_inlet_pressure')
    if project.get('roof_present') and _number(b.get('rainfall_intensity')) is None: missing.append('rainfall_intensity')
    if b.get('gas_service') is True and _number(b.get('gas_service_pressure')) is None: missing.append('gas_service_pressure')
    b.setdefault('occupancy',project.get('occupancy'));b.setdefault('required_external_inputs',[])
    status='PASS' if not missing and not unsupported else ('UNSUPPORTED' if unsupported else 'INPUT_REQUIRED')
    return {'version':'design-basis-v14.2','status':status,'missing':missing,'unsupported':unsupported,'basis':b}


def derive_system_requirements(project, design_basis):
    b=design_basis.get('basis') or {}; by_level={}
    for level,ev in (project.get('levels') or {}).items():
        systems=set()
        if ev.get('wet'): systems.update({'sanitary','vent','cold_water','hot_water'})
        if ev.get('habitable'):
            if b.get('heating_system')=='package_radiator': systems.add('heating')
            if b.get('cooling_system')=='wall_mounted_split_ac': systems.add('split_ac')
        if ev.get('exhaust'): systems.add('exhaust')
        if ev.get('gas_appliance') and b.get('gas_service') is True: systems.add('gas')
        by_level[level]=sorted(systems)
    project_systems={s for row in by_level.values() for s in row}
    if project.get('roof_present'):
        if 'vent' in project_systems: project_systems.add('vent_termination')
        if _number(b.get('rainfall_intensity')) is not None: project_systems.add('rainwater')
        if b.get('cooling_system')=='wall_mounted_split_ac': project_systems.add('split_outdoor')
    return {'version':'system-requirements-v14.2','status':'PASS','by_level':by_level,'project_systems':sorted(project_systems)}


def build_reference_driven_manifest(project, requirements, design_basis=None):
    """Build only sheets justified by project evidence and locked basis."""
    rows=[];basis=(design_basis or {}).get('basis') if isinstance(design_basis,dict) else {};basis=basis or {}
    def add(family,level='MULTI',purpose='PLAN',title=None): rows.append({'sheet':None,'family':family,'level':level,'purpose':purpose,'title':title or family.replace('_',' ')})
    project_systems=set(requirements.get('project_systems') or []);levels=list(project.get('levels') or {})
    add('COVER',purpose='COVER',title='MECHANICAL COVER / DRAWING INDEX');add('GENERAL_NOTES',purpose='NOTES',title='MECHANICAL GENERAL NOTES / DESIGN BASIS')
    if project.get('roof_present') and ({'rainwater','vent_termination','split_outdoor'} & project_systems): add('ROOF','ROOF',title='ROOF / PROJECT-APPLICABLE MECHANICAL SERVICES')
    water_levels=[]
    for level in levels:
        systems=set(requirements['by_level'].get(level) or [])
        if {'sanitary','vent'} & systems:add('SANITARY_VENT',level)
        if {'cold_water','hot_water'} & systems:add('WATER',level);water_levels.append(level)
        if 'heating' in systems:add('HEATING',level)
        if 'gas' in systems:add('GAS',level)
        if 'split_ac' in systems:add('SPLIT_AC',level)
        if 'exhaust' in systems:add('EXHAUST',level)
    water_mode=str(basis.get('water_service_mode') or '')
    water_service_required=bool(water_levels and ('pump' in water_mode or 'tank' in water_mode or len(water_levels)>=2))
    if water_service_required:add('WATER','SERVICE',title='WATER SERVICE / SOURCE / PUMP-TANK COORDINATION')
    if 'sanitary' in project_systems:add('PLUMBING_RISER',purpose='RISER',title='PLUMBING RISER DIAGRAM')
    if water_service_required:add('WATER_SERVICE_CALC',purpose='CALC',title='WATER SERVICE / PUMP CALCULATION')
    if 'split_ac' in project_systems and project.get('roof_present'):add('SPLIT_AC','ROOF',title='SPLIT AC OUTDOOR UNIT / ROOF COORDINATION')
    detail_groups=[]
    if {'sanitary','vent','cold_water','hot_water'} & project_systems:detail_groups.append('PLUMBING')
    if {'heating','split_ac','exhaust'} & project_systems:detail_groups.append('HVAC')
    if 'gas' in project_systems:detail_groups.append('GAS')
    for i,group in enumerate(detail_groups,1):add('GENERAL_DETAIL',f'DETAIL-{i}','DETAIL',f'{group} PROJECT-APPLICABLE DETAILS')
    if {'heating','split_ac','exhaust','gas'} & project_systems:add('EQUIPMENT_SCHEDULE',purpose='SCHEDULE',title='MECHANICAL EQUIPMENT / PIPE SCHEDULE')
    for i,row in enumerate(rows):row['sheet']=f'M-{i:02d}'
    counts=Counter(r['family'] for r in rows)
    return {'version':'adaptive-sheet-planner-v14.2','status':'PASS','sheet_count':len(rows),'family_counts':dict(counts),'sheets':rows}


def build_network_contract(requirements):
    topologies={'sanitary':'fixture->branch->main->stack','vent':'fixture-vent->vent-main->roof','cold_water':'service->main->branch->fixture','hot_water':'source->main->branch->fixture','heating':'package->flow->emitter->return','split_ac':'indoor->refrigerant-pair->vertical-ref->outdoor','gas':'meter->main->appliance','exhaust':'room-point->fan->discharge'}
    graphs=[]
    for level,systems in (requirements.get('by_level') or {}).items():
        for system in systems:graphs.append({'level':level,'system':system,'topology':topologies.get(system,'system-specific-network')})
    return {'version':'network-contract-v14.2','status':'PASS','graphs':graphs,'cross_level_physical_edges':0}


def build_calculation_contract():
    calculations={'sanitary':{'method':'DFU+slope','status':'PRELIMINARY'},'water':{'method':'FU+pressure-loss','status':'INPUT_REQUIRED'},'heating':{'method':'room-heat-loss+deltaT+flow','status':'PRELIMINARY'},'split_ac':{'method':'room-load+manufacturer-selection','status':'INPUT_REQUIRED'},'condensate':{'method':'drain-rule','status':'DESIGN_RULE','dn_min_mm':25,'slope_min_percent':1.0},'gas':{'method':'connected-load+equivalent-length','status':'INPUT_REQUIRED'},'rainwater':{'method':'catchment+design-rainfall','status':'INPUT_REQUIRED'},'exhaust':{'method':'ACH/CFM-by-use','status':'PRELIMINARY'}}
    return {'version':'calculation-contract-v14.2','status':'PASS','fabricated_final_values':0,'calculations':calculations}


def validate_authority_contract(project, design_basis, requirements, manifest, network, calculations):
    errors=[]
    if project.get('status')!='PASS':errors.append('project_model_invalid')
    if design_basis.get('status')!='PASS':
        if design_basis.get('missing'):errors.append('design_basis_input_required:'+','.join(design_basis.get('missing') or []))
        if design_basis.get('unsupported'):errors.append('unsupported_design_basis:'+','.join(design_basis.get('unsupported') or []))
    families=set(manifest.get('family_counts') or {});mandatory={'COVER','GENERAL_NOTES'};systems=set(requirements.get('project_systems') or [])
    if project.get('roof_present') and ({'rainwater','vent_termination','split_outdoor'} & systems):mandatory.add('ROOF')
    if 'sanitary' in systems:mandatory.update({'SANITARY_VENT','PLUMBING_RISER'})
    if 'cold_water' in systems:mandatory.add('WATER')
    water_service_required='WATER_SERVICE_CALC' in families
    if water_service_required:mandatory.add('WATER_SERVICE_CALC')
    if 'heating' in systems:mandatory.add('HEATING')
    if 'gas' in systems:mandatory.add('GAS')
    if 'split_ac' in systems:mandatory.add('SPLIT_AC')
    if 'exhaust' in systems:mandatory.add('EXHAUST')
    missing=mandatory-families
    if missing:errors.append('missing_sheet_families:'+','.join(sorted(missing)))
    allowed=mandatory|{'GENERAL_DETAIL','EQUIPMENT_SCHEDULE','WATER'}
    unexpected=families-allowed
    if unexpected:errors.append('unjustified_sheet_families:'+','.join(sorted(unexpected)))
    if network.get('cross_level_physical_edges')!=0:errors.append('cross_level_physical_geometry')
    if calculations.get('fabricated_final_values')!=0:errors.append('fabricated_final_engineering_values')
    return {'version':'authority-contract-qa-v14.2','status':'PASS' if not errors else 'FAIL','errors':errors}
