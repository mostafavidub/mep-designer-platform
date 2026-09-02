"""Stage 5 — build mechanical topology with strict per-plan isolation."""
from __future__ import annotations
import math

SYSTEM_TARGETS={
 'cold_water':{'wc','basin','sink','shower'},'hot_water':{'basin','sink','shower'},
 'sanitary':{'wc','basin','sink','shower','floor_drain'},'vent':{'wc','basin','sink','shower','floor_drain'},
 'heating':{'radiator','fan_coil'},'cooling':{'fan_coil','split_indoor'},'condensate':{'fan_coil','split_indoor'},
 'exhaust':{'exhaust_fan','hood'},'gas':{'stove','water_heater'},
}

def _centroid(poly):
    if not poly:return None
    return (sum(p[0] for p in poly)/len(poly),sum(p[1] for p in poly)/len(poly))

def build_system_topology(architecture,recognition,requirements,calculations,design_basis=None):
    nodes=[]
    for item in recognition.get('detections') or []:
        nodes.append({'id':item['id'],'kind':item.get('type'),'category':item.get('category'),'point':item.get('point'),
                      'room_id':item.get('room_id'),'plan_id':item.get('plan_id')})
    shafts=[]
    plans=architecture.get('plans') or []
    for index,shaft in enumerate(architecture.get('shafts') or [],1):
        point=shaft.get('point') or _centroid(shaft.get('polygon'))
        if not point:continue
        plan_id=shaft.get('plan_id')
        if not plan_id:
            containing=[p for p in plans if p.get('bounds') and p['bounds'][0]<=point[0]<=p['bounds'][2] and p['bounds'][1]<=point[1]<=p['bounds'][3]]
            if containing:
                plan_id=min(containing,key=lambda p:(p['bounds'][2]-p['bounds'][0])*(p['bounds'][3]-p['bounds'][1])).get('plan_id')
        row={'id':f'SHAFT-{index:02d}','kind':'shaft','category':'vertical','point':point,'plan_id':plan_id,
             'source':shaft.get('source','geometry')}
        shafts.append(row);nodes.append(row)
    # Propose one local vertical core for each primary floor that has no
    # explicit shaft.  The user-approved workflow permits a shaft proposal near
    # wet rooms; keeping it local preserves the no-cross-plan contract.
    plan_ids=list(architecture.get('primary_floor_plan_ids') or [])
    for pid in plan_ids:
        if any(s.get('plan_id')==pid for s in shafts):
            continue
        wet=[r for r in architecture.get('rooms') or [] if r.get('plan_id')==pid and r.get('type') in ('bathroom','toilet','kitchen')]
        points=[tuple(r.get('label_point')) for r in wet if r.get('label_point')]
        if points:
            point=(sum(p[0] for p in points)/len(points),sum(p[1] for p in points)/len(points))
        else:
            plan=next((p for p in architecture.get('plans') or [] if p.get('plan_id')==pid),{})
            b=plan.get('bounds') or architecture.get('bounds') or [0,0,0,0]
            point=((b[0]+b[2])/2,(b[1]+b[3])/2)
        approved=(design_basis or {}).get('mechanical_shaft_route')=='propose_near_wet_core'
        row={'id':f'SHAFT-PROPOSED-{len(shafts)+1:02d}','kind':'shaft','category':'vertical',
             'point':point,'plan_id':pid,'source':'proposed_near_wet_core','provisional':not approved,
             'proposal_approved':approved}
        shafts.append(row);nodes.append(row)

    project_systems=set(requirements.get('project_systems') or [])
    edges=[];system_graphs={};unresolved=[]
    for system in sorted(project_systems):
        allowed=SYSTEM_TARGETS.get(system,set()); endpoints=[n for n in nodes if n.get('kind') in allowed]
        graph_nodes=[n['id'] for n in endpoints]
        for endpoint in endpoints:
            pid=endpoint.get('plan_id')
            # Synthetic and legacy single-plan inputs legitimately omit a
            # plan_id on both endpoints and shafts.  Equal missing identifiers
            # still mean the same isolated plan; never reject that local shaft.
            candidates=[s for s in shafts if s.get('plan_id')==pid]
            if not candidates:
                unresolved.append({'system':system,'endpoint_id':endpoint['id'],'plan_id':pid,'reason':'NO_LOCAL_SHAFT'})
                continue
            shaft=min(candidates,key=lambda s:math.dist(endpoint['point'],s['point']))
            if shaft['id'] not in graph_nodes:graph_nodes.append(shaft['id'])
            edges.append({'id':f'{system.upper()}-E{len(edges)+1:03d}','system':system,'from':endpoint['id'],'to':shaft['id'],
                          'plan_id':pid,'load_source':endpoint['id'],'topology':'endpoint_to_local_vertical_core'})
        system_graphs[system]={'nodes':graph_nodes,'edges':[e['id'] for e in edges if e['system']==system]}
    cross_plan=sum(1 for e in edges if next(n for n in nodes if n['id']==e['from']).get('plan_id')!=next(n for n in nodes if n['id']==e['to']).get('plan_id'))
    return {'version':'mechanical-topology-v13.12','nodes':nodes,'edges':edges,'systems':system_graphs,'unresolved':unresolved,
            'quality':{'systems':len(system_graphs),'edges':len(edges),'provisional_shaft':any(s.get('provisional') for s in shafts),'cross_plan_edges':cross_plan,
                       'unresolved_without_local_shaft':len(unresolved)}}
