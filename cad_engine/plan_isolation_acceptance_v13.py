"""Stage 12 — hard QA for independent plan/sheet isolation."""
from __future__ import annotations

def _inside(p,b,tol=1e-6): return b[0]-tol<=p[0]<=b[2]+tol and b[1]-tol<=p[1]<=b[3]+tol

def evaluate_plan_isolation(pipeline):
    arch=pipeline.get('architecture') or {};topology=pipeline.get('topology') or {};routing=pipeline.get('routing') or {}
    plans={p['plan_id']:p['bounds'] for p in arch.get('plans') or []};nodes={n['id']:n for n in topology.get('nodes') or []};errors=[]
    for edge in topology.get('edges') or []:
        a=nodes.get(edge.get('from'));b=nodes.get(edge.get('to'));pid=edge.get('plan_id')
        if not a or not b:continue
        if not pid or a.get('plan_id')!=pid or b.get('plan_id')!=pid:errors.append(f"cross_plan_topology:{edge.get('id')}")
    for route in routing.get('routes') or []:
        pid=route.get('plan_id');bounds=plans.get(pid)
        if not pid or not bounds:errors.append(f"route_without_plan:{route.get('id')}");continue
        if not all(_inside(p,bounds) for p in route.get('points') or []):errors.append(f"route_outside_plan:{route.get('id')}")
    if (routing.get('quality') or {}).get('cross_plan_routes',0):errors.append('routing_reports_cross_plan_routes')
    return {'version':'plan-isolation-acceptance-v13.12','status':'PASS' if not errors else 'FAIL','errors':errors,
            'metrics':{'plans':len(plans),'edges':len(topology.get('edges') or []),'routes':len(routing.get('routes') or []),
                       'unresolved_local_shafts':len(topology.get('unresolved') or [])}}
