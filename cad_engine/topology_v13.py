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


def _point(value):
    try:
        x,y=float(value[0]),float(value[1])
        if not (math.isfinite(x) and math.isfinite(y)):return None
        return x,y
    except (TypeError,ValueError,IndexError):
        return None


def _unresolved(rows, system, endpoint, reason):
    rows.append({'system':system,'endpoint_id':endpoint.get('id'),'plan_id':endpoint.get('plan_id'),
                 'reason':reason,'status':'INPUT_REQUIRED'})


def build_system_topology(architecture,recognition,requirements,calculations,design_basis=None):
    nodes=[]
    for item in recognition.get('detections') or []:
        nodes.append({'id':item['id'],'kind':item.get('type'),'category':item.get('category'),'point':item.get('point'),
                      'room_id':item.get('room_id'),'plan_id':item.get('plan_id')})
    shafts=[]
    plans=architecture.get('plans') or []
    for index,shaft in enumerate(architecture.get('shafts') or [],1):
        point=_point(shaft.get('point') or _centroid(shaft.get('polygon')))
        if not point:continue
        plan_id=shaft.get('plan_id')
        if not plan_id:
            containing=[p for p in plans if p.get('bounds') and p['bounds'][0]<=point[0]<=p['bounds'][2] and p['bounds'][1]<=point[1]<=p['bounds'][3]]
            if containing:
                plan_id=min(containing,key=lambda p:(p['bounds'][2]-p['bounds'][0])*(p['bounds'][3]-p['bounds'][1])).get('plan_id')
        row={'id':f'SHAFT-{index:02d}','kind':'shaft','category':'vertical','point':point,'plan_id':plan_id,
             'source':shaft.get('source','geometry')}
        shafts.append(row);nodes.append(row)
    # Propose local vertical cores for diagnostic/pre-submission purposes. A
    # provisional proposal remains visible, but Step 4 never lets it become a
    # routable network core until the proposal is explicitly approved.
    plan_ids=list(architecture.get('primary_floor_plan_ids') or [])
    for pid in plan_ids:
        wet=[r for r in architecture.get('rooms') or [] if r.get('plan_id')==pid and r.get('type') in ('bathroom','toilet','kitchen')]
        points=[tuple(r.get('label_point')) for r in wet if _point(r.get('label_point'))]
        plan=next((p for p in architecture.get('plans') or [] if p.get('plan_id')==pid),{})
        b=plan.get('bounds') or architecture.get('bounds') or [0,0,0,0]
        clusters=[points] if points else [[((b[0]+b[2])/2,(b[1]+b[3])/2)]]
        basis=design_basis or {}; approval=basis.get('mechanical_shaft_approval') or {}
        strategy=approval.get('strategy') or basis.get('mechanical_shaft_route')
        proposal_strategies={'propose_near_wet_core','propose_adjacent_to_stair','proposal_authorized'}
        # Canonical route values were the signed approval contract before
        # v18.5; keep those releases reproducible while new submissions carry
        # the richer approval/provenance object.
        approved=strategy in proposal_strategies and (
            approval.get('status')=='APPROVED' or basis.get('mechanical_shaft_route') in proposal_strategies
        )
        if any(s.get('plan_id')==pid for s in shafts) and not approved:
            continue
        # Once the customer has explicitly approved wet-core proposals, keep
        # each reconstructed wet room connected to its own local riser point.
        if approved and points:
            clusters=[[point] for point in points]
        for cluster in clusters:
            point=(sum(p[0] for p in cluster)/len(cluster),sum(p[1] for p in cluster)/len(cluster))
            row={'id':f'SHAFT-PROPOSED-{len(shafts)+1:02d}','kind':'shaft','category':'vertical',
                 'point':point,'plan_id':pid,'source':'proposed_near_wet_core','provisional':not approved,
                 'proposal_approved':approved,'cluster_radius':max((math.dist(point,p) for p in cluster),default=0),
                 'approval':({**approval,'strategy':strategy,'plan_id':pid,'approved_point':point}
                             if approved else {'status':'INPUT_REQUIRED','strategy':strategy,'plan_id':pid})}
            shafts.append(row);nodes.append(row)

    project_systems=set(requirements.get('project_systems') or [])
    edges=[];system_graphs={};unresolved=[]
    for system in sorted(project_systems):
        allowed=SYSTEM_TARGETS.get(system,set()); endpoints=[n for n in nodes if n.get('kind') in allowed]
        graph_nodes=[n['id'] for n in endpoints]
        for endpoint in endpoints:
            pid=endpoint.get('plan_id'); endpoint_point=_point(endpoint.get('point'))
            if endpoint_point is None:
                _unresolved(unresolved,system,endpoint,'INVALID_ENDPOINT_POINT');continue
            # Synthetic and legacy single-plan inputs legitimately omit a
            # plan_id on both endpoints and shafts. Equal missing identifiers
            # still mean the same isolated plan.
            candidates=[s for s in shafts if s.get('plan_id')==pid and _point(s.get('point'))]
            if not candidates:
                _unresolved(unresolved,system,endpoint,'NO_LOCAL_SHAFT');continue
            approved_candidates=[s for s in candidates if not s.get('provisional') or s.get('proposal_approved')]
            if not approved_candidates:
                _unresolved(unresolved,system,endpoint,'UNAPPROVED_LOCAL_SHAFT');continue
            # Coincident representative points do not prove a physical branch.
            # The old router fabricated a tiny closed loop here; Step 4 instead
            # requires real/distinct project geometry.
            routable=[s for s in approved_candidates if math.dist(endpoint_point,_point(s.get('point'))) > 1e-9]
            if not routable:
                _unresolved(unresolved,system,endpoint,'DEGENERATE_LOCAL_CONNECTION');continue
            shaft=min(routable,key=lambda s:math.dist(endpoint_point,_point(s.get('point'))))
            if shaft['id'] not in graph_nodes:graph_nodes.append(shaft['id'])
            edges.append({'id':f'{system.upper()}-E{len(edges)+1:03d}','system':system,'from':endpoint['id'],'to':shaft['id'],
                          'plan_id':pid,'load_source':endpoint['id'],'topology':'endpoint_to_local_vertical_core'})
        system_graphs[system]={'nodes':graph_nodes,'edges':[e['id'] for e in edges if e['system']==system]}
    node_by_id={n['id']:n for n in nodes}
    cross_plan=sum(1 for e in edges if node_by_id[e['from']].get('plan_id')!=node_by_id[e['to']].get('plan_id'))
    reason_counts={reason:sum(1 for row in unresolved if row.get('reason')==reason) for reason in sorted({row.get('reason') for row in unresolved})}
    return {'version':'mechanical-topology-v13.13','nodes':nodes,'edges':edges,'systems':system_graphs,'unresolved':unresolved,
            'quality':{'systems':len(system_graphs),'edges':len(edges),'provisional_shaft':any(s.get('provisional') for s in shafts),'cross_plan_edges':cross_plan,
                       'unresolved_without_local_shaft':len(unresolved),'input_required':len(unresolved),
                       'unresolved_reasons':reason_counts}}
