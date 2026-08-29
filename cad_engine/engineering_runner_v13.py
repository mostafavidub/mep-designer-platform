"""Engineering pipeline orchestration with strict print-plan isolation."""
from __future__ import annotations
from .engineering_pipeline_v13 import reconstruct_architecture,recognize_fixtures_equipment
from .plan_segmentation_v13 import apply_plan_scopes
from .system_requirements_v13 import derive_system_requirements
from .mechanical_calculations_v13 import calculate_mechanical_loads
from .topology_v13 import build_system_topology
from .routing_v13 import route_topology
from .sizing_v13 import size_networks
from .annotation_v13 import build_annotations
from .detail_library_v13 import build_details_schedules
from .project_hvac_v13 import design_project_hvac

def run_engineering_pipeline(src,design_basis=None,project_overrides=None):
    architecture=reconstruct_architecture(src)
    recognition=recognize_fixtures_equipment(architecture)
    architecture,recognition=apply_plan_scopes(src,architecture,recognition)
    requirements=derive_system_requirements(architecture,recognition)
    calculations=calculate_mechanical_loads(architecture,recognition,requirements,design_basis=design_basis)
    topology=build_system_topology(architecture,recognition,requirements,calculations)
    routing=route_topology(architecture,topology)
    sizing=size_networks(topology,routing,recognition,calculations)
    annotations=build_annotations(routing,sizing,recognition,calculations,topology)
    detail_overrides=dict(project_overrides or {})
    if not detail_overrides.get('levels'):
        primary=set(architecture.get('primary_floor_plan_ids') or [])
        levels=[]
        for plan in architecture.get('plans') or []:
            if primary and plan.get('plan_id') not in primary:
                continue
            level=plan.get('level') or plan.get('plan_id')
            if level and level not in levels:
                levels.append(level)
        detail_overrides['levels']=levels or ['GROUND']
    details=build_details_schedules(requirements,recognition,calculations,sizing,topology,project_overrides=detail_overrides)
    hvac=design_project_hvac(architecture,project_overrides=project_overrides)
    return {'version':'engineering-pipeline-v13.13','architecture':architecture,'recognition':recognition,'requirements':requirements,
            'calculations':calculations,'topology':topology,'routing':routing,'sizing':sizing,'annotations':annotations,'details':details,'hvac':hvac}

def validate_pipeline(result):
    errors=[];arch=result.get('architecture') or {};rec=result.get('recognition') or {};req=result.get('requirements') or {}
    topology=result.get('topology') or {};routing=result.get('routing') or {};sizing=result.get('sizing') or {};annotations=result.get('annotations') or {};hvac=result.get('hvac') or {}
    if not arch.get('rooms'):errors.append('no_reconstructed_rooms')
    if not req.get('project_systems'):errors.append('no_mechanical_system_requirements')
    if arch.get('plans') and not arch.get('primary_floor_plan_ids'):errors.append('no_primary_mechanical_floor_plans')
    if arch.get('plans') and (topology.get('quality') or {}).get('cross_plan_edges',0):errors.append('cross_plan_topology')
    if (routing.get('quality') or {}).get('cross_plan_routes',0):errors.append('cross_plan_routes')
    if hvac.get('status')=='FAIL':errors.append('project_hvac_geometry_invalid')
    if (hvac.get('quality') or {}).get('cross_plan_routes',0):errors.append('cross_plan_hvac_routes')
    if (hvac.get('quality') or {}).get('out_of_bounds',0):errors.append('hvac_route_out_of_plan')
    sized_ids={x.get('route_id') for x in sizing.get('segments') or [] if x.get('size_mm') is not None};route_ids={x.get('id') for x in routing.get('routes') or []}
    if route_ids-sized_ids:errors.append('unsized_routes')
    annotated_ids={x.get('route_id') for x in annotations.get('annotations') or [] if x.get('route_id')}
    if route_ids-annotated_ids:errors.append('unannotated_routes')
    return {'status':'PASS' if not errors else 'FAIL','errors':errors,
            'metrics':{'plans':len(arch.get('plans') or []),'primary_floor_plans':len(arch.get('primary_floor_plan_ids') or []),
                       'rooms':len(arch.get('rooms') or []),'detections':len(rec.get('detections') or []),
                       'systems':len(req.get('project_systems') or []),'routes':len(route_ids),'sized_routes':len(sized_ids),
                       'annotated_routes':len(annotated_ids),'unresolved_local_shafts':len(topology.get('unresolved') or []),
                       'hvac_equipment':len(hvac.get('equipment') or []),'hvac_routes':len(hvac.get('routes') or [])}}
