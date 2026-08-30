"""Engineering pipeline orchestration with strict print-plan isolation."""
from __future__ import annotations
import math
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


def _inside(point, polygon):
    x,y=point; hit=False; j=len(polygon)-1
    for i,(xi,yi) in enumerate(polygon):
        xj,yj=polygon[j]
        if ((yi>y)!=(yj>y)) and x < (xj-xi)*(y-yi)/((yj-yi) or 1e-12)+xi:
            hit=not hit
        j=i
    return hit


def _room_point(room):
    p=room.get('label_point') or room.get('centroid') or room.get('point')
    try:
        return float(p[0]),float(p[1])
    except Exception:
        return None


def _plan_for_point(architecture, point):
    primary=set(architecture.get('primary_floor_plan_ids') or [])
    plans=[p for p in architecture.get('plans') or [] if not primary or p.get('plan_id') in primary]
    for plan in plans:
        b=plan.get('bounds')
        if b and b[0] <= point[0] <= b[2] and b[1] <= point[1] <= b[3]:
            return plan
    return None


def _compatible_room(kind, room_type):
    allowed={
        'wc':{'toilet','bathroom'},
        'basin':{'toilet','bathroom'},
        'sink':{'kitchen'},
        'shower':{'bathroom','toilet'},
        'floor_drain':{'bathroom','toilet','kitchen'},
    }
    return room_type in allowed.get(kind,set())


def _nearest_compatible_room(architecture, rooms, point, kind):
    """Conservative fallback when a valid fixture sits just outside a bad room polygon.

    Consultant DXFs frequently contain small closed annotation polylines around room
    labels. The v13 reconstructor can select one of those as the room polygon. We only
    use this fallback for coordinate-backed fixture evidence already recognized by the
    browser analyzer, require semantic room compatibility, keep the fixture on the same
    print plan, and cap distance to 18% of that plan's diagonal. Distant legend symbols
    therefore remain unassigned.
    """
    plan=_plan_for_point(architecture,point)
    if not plan:
        return None
    pid=plan.get('plan_id'); b=plan.get('bounds') or []
    if len(b)!=4:
        return None
    max_distance=math.hypot(b[2]-b[0],b[3]-b[1])*.18
    candidates=[]
    for room in rooms:
        if room.get('plan_id') != pid or not _compatible_room(kind,room.get('type')):
            continue
        rp=_room_point(room)
        if not rp:
            continue
        distance=math.dist(point,rp)
        if distance <= max_distance:
            candidates.append((distance,room))
    return min(candidates,key=lambda x:x[0])[1] if candidates else None


def _merge_browser_fixture_evidence(architecture, recognition, evidence):
    """Merge traceable browser evidence, with a bounded same-plan room fallback."""
    aliases={'faucet':'basin','basin':'basin','sink':'sink','toilet':'wc','wc':'wc',
             'bath':'shower','bathtub':'shower','shower':'shower','floor_drain':'floor_drain'}
    rows=list(recognition.get('detections') or [])
    rooms=list(architecture.get('rooms') or [])
    polygon_rooms=[r for r in rooms if r.get('polygon')]
    accepted=0; fallback_accepted=0
    for raw in evidence or []:
        kind=aliases.get(str(raw.get('kind') or '').strip().lower())
        try: point=(float(raw.get('x')),float(raw.get('y')))
        except (TypeError,ValueError): continue
        if not kind or any(r.get('type')==kind and ((r.get('point') or (0,0))[0]-point[0])**2+((r.get('point') or (0,0))[1]-point[1])**2 < 2500 for r in rows):
            continue
        room=next((r for r in polygon_rooms if _inside(point,r['polygon'])),None)
        evidence_tags=['browser_upload_analyzer']
        confidence=.90
        if room:
            evidence_tags.append('coordinate_in_reconstructed_room')
        else:
            room=_nearest_compatible_room(architecture,rooms,point,kind)
            if not room:
                continue
            evidence_tags.extend(['strong_source_block','bounded_same_plan_semantic_room_fallback'])
            confidence=.84; fallback_accepted+=1
        row={'id':f"MEP-{len(rows)+1:03d}",'category':'fixture','type':kind,'point':point,
             'block':raw.get('name') or '','layer':'ANALYZED-SOURCE-BLOCK','room_id':room.get('id'),
             'plan_id':room.get('plan_id'),'confidence':confidence,'status':'detected','installed':True,
             'evidence':evidence_tags,'source_file':raw.get('source_file')}
        rows.append(row); accepted+=1
    recognition['detections']=rows
    recognition['fixtures']=[r for r in rows if r.get('category')=='fixture']
    recognition['equipment']=[r for r in rows if r.get('category')=='equipment']
    quality=dict(recognition.get('quality') or {})
    quality.update({'detected':len(rows),'room_assigned':sum(bool(r.get('room_id')) for r in rows),
                    'browser_evidence_accepted':accepted,'browser_evidence_fallback_accepted':fallback_accepted})
    recognition['quality']=quality
    return recognition


def run_engineering_pipeline(src,design_basis=None,project_overrides=None):
    architecture=reconstruct_architecture(src)
    recognition=recognize_fixtures_equipment(architecture)
    architecture,recognition=apply_plan_scopes(src,architecture,recognition)
    recognition=_merge_browser_fixture_evidence(architecture,recognition,(project_overrides or {}).get('fixture_evidence'))
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
    return {'version':'engineering-pipeline-v13.15','architecture':architecture,'recognition':recognition,'requirements':requirements,
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
