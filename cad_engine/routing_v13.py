"""Stage 6 — orthogonal routing constrained to the owning print plan."""
from __future__ import annotations

def _ccw(a,b,c): return (c[1]-a[1])*(b[0]-a[0])>(b[1]-a[1])*(c[0]-a[0])
def _intersects(a,b,c,d):
    if a==b or c==d:return False
    return _ccw(a,c,d)!=_ccw(b,c,d) and _ccw(a,b,c)!=_ccw(a,b,d)
def _route_candidates(start,end):
    x1,y1=start;x2,y2=end
    def clean(points):
        out=[]
        for p in points:
            if not out or p!=out[-1]:out.append(p)
        return out
    return clean([start,(x2,y1),end]),clean([start,(x1,y2),end])
def _inside(p,b,tol=1e-6):
    if not b:return True
    return b[0]-tol<=p[0]<=b[2]+tol and b[1]-tol<=p[1]<=b[3]+tol
def _score(points,walls):
    clashes=0
    for a,b in zip(points,points[1:]):
        for wall in walls:
            if _intersects(a,b,tuple(wall['start']),tuple(wall['end'])):clashes+=1
    length=sum(abs(b[0]-a[0])+abs(b[1]-a[1]) for a,b in zip(points,points[1:]))
    return clashes,length

def route_topology(architecture,topology):
    node_by_id={n['id']:n for n in topology.get('nodes') or []}; walls=architecture.get('walls') or []
    plan_bounds={p['plan_id']:p['bounds'] for p in architecture.get('plans') or []};routes=[];rejected=[]
    for edge in topology.get('edges') or []:
        start=node_by_id.get(edge.get('from'));end=node_by_id.get(edge.get('to'));pid=edge.get('plan_id')
        if not start or not end or not start.get('point') or not end.get('point'):continue
        if start.get('plan_id')!=end.get('plan_id') or (pid and start.get('plan_id')!=pid):
            rejected.append({'edge_id':edge['id'],'reason':'CROSS_PLAN_TOPOLOGY'});continue
        bounds=plan_bounds.get(pid)
        candidates=[pts for pts in _route_candidates(tuple(start['point']),tuple(end['point'])) if all(_inside(p,bounds) for p in pts)]
        if not candidates:
            rejected.append({'edge_id':edge['id'],'reason':'ROUTE_OUTSIDE_PLAN'});continue
        ranked=sorted(((_score(points,walls),points) for points in candidates),key=lambda x:(x[0][0],x[0][1]))
        (clashes,length),points=ranked[0]
        routes.append({'id':f'ROUTE-{len(routes)+1:03d}','edge_id':edge['id'],'system':edge['system'],'plan_id':pid,'points':points,
                       'length':round(length,3),'wall_crossings':clashes,'routing':'orthogonal_plan_isolated'})
    return {'version':'geometry-routing-v13.12','routes':routes,'rejected':rejected,
            'quality':{'routed_edges':len(routes),'wall_crossings':sum(r['wall_crossings'] for r in routes),
                       'cross_plan_routes':0,'rejected_edges':len(rejected),
                       'all_orthogonal':all(all(a[0]==b[0] or a[1]==b[1] for a,b in zip(r['points'],r['points'][1:])) for r in routes)}}
