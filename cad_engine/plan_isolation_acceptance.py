"""Stage 12 — hard QA for independent plan/sheet isolation."""
from __future__ import annotations

def _inside(p,b,tol=1e-6): return b[0]-tol<=p[0]<=b[2]+tol and b[1]-tol<=p[1]<=b[3]+tol

def evaluate_plan_isolation(pipeline):
    arch=pipeline.get('architecture') or {};topology=pipeline.get('topology') or {};routing=pipeline.get('routing') or {}
    plans={p['plan_id']:p['bounds'] for p in arch.get('plans') or []};nodes={n['id']:n for n in topology.get('nodes') or []};errors=[]
    ownership=arch.get('level_ownership_contract') or {}
    if ownership and ownership.get('status')!='PASS':
        errors.append('architectural_level_ownership_unresolved')
    quality=arch.get('quality') or {}
    if quality.get('ambiguous_plan_ownership_count',0):errors.append('ambiguous_plan_ownership')
    if quality.get('unassigned_plan_entity_count',0):errors.append('unassigned_plan_entities')
    fingerprints={}
    for row in ownership.get('plans') or []:
        signature=row.get('source_geometry_fingerprint'); represented=row.get('represented_levels') or []
        level=str(row.get('level') or '').upper()
        if not signature or len(represented)>1 or 'TYPICAL' in level:continue
        fingerprints.setdefault(signature,[]).append(row.get('plan_id'))
    for plan_ids in fingerprints.values():
        if len(plan_ids)>1:errors.append('duplicate_architecture_across_levels:'+':'.join(sorted(plan_ids)))
    for edge in topology.get('edges') or []:
        a=nodes.get(edge.get('from'));b=nodes.get(edge.get('to'));pid=edge.get('plan_id')
        if not a or not b:continue
        if not pid or a.get('plan_id')!=pid or b.get('plan_id')!=pid:errors.append(f"cross_plan_topology:{edge.get('id')}")
    for route in routing.get('routes') or []:
        pid=route.get('plan_id');bounds=plans.get(pid)
        if not pid or not bounds:errors.append(f"route_without_plan:{route.get('id')}");continue
        if not all(_inside(p,bounds) for p in route.get('points') or []):errors.append(f"route_outside_plan:{route.get('id')}")
    if (routing.get('quality') or {}).get('cross_plan_routes',0):errors.append('routing_reports_cross_plan_routes')
    return {'version':'plan-isolation-acceptance-v13.13','status':'PASS' if not errors else 'FAIL','errors':sorted(set(errors)),
            'metrics':{'plans':len(plans),'edges':len(topology.get('edges') or []),'routes':len(routing.get('routes') or []),
                       'unresolved_local_shafts':len(topology.get('unresolved') or [])}}
