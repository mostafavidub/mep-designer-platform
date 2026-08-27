"""Stage 6 — convert topology edges into orthogonal routes on architecture.

Routes are generated after topology, not before.  Two Manhattan candidates are
scored against architectural wall segments; the lower-clash candidate wins.
"""
from __future__ import annotations


def _ccw(a,b,c):
    return (c[1]-a[1])*(b[0]-a[0]) > (b[1]-a[1])*(c[0]-a[0])


def _intersects(a,b,c,d):
    if a == b or c == d:
        return False
    return _ccw(a,c,d) != _ccw(b,c,d) and _ccw(a,b,c) != _ccw(a,b,d)


def _route_candidates(start,end):
    x1,y1 = start; x2,y2 = end
    a = [start,(x2,y1),end]
    b = [start,(x1,y2),end]
    def clean(points):
        out=[]
        for p in points:
            if not out or p != out[-1]: out.append(p)
        return out
    return clean(a), clean(b)


def _score(points,walls):
    clashes=0
    for a,b in zip(points,points[1:]):
        for wall in walls:
            if _intersects(a,b,tuple(wall['start']),tuple(wall['end'])):
                clashes += 1
    length=sum(abs(b[0]-a[0])+abs(b[1]-a[1]) for a,b in zip(points,points[1:]))
    return clashes,length


def route_topology(architecture, topology):
    node_by_id={n['id']:n for n in topology.get('nodes') or []}
    walls=architecture.get('walls') or []
    routes=[]
    for edge in topology.get('edges') or []:
        start=node_by_id.get(edge.get('from')); end=node_by_id.get(edge.get('to'))
        if not start or not end or not start.get('point') or not end.get('point'):
            continue
        candidates=_route_candidates(tuple(start['point']),tuple(end['point']))
        ranked=sorted(((_score(points,walls),points) for points in candidates), key=lambda x:(x[0][0],x[0][1]))
        (clashes,length),points=ranked[0]
        routes.append({'id':f"ROUTE-{len(routes)+1:03d}",'edge_id':edge['id'],'system':edge['system'],'points':points,
                       'length':round(length,3),'wall_crossings':clashes,'routing':'orthogonal_manhattan_min_wall_crossing'})
    return {'version':'geometry-routing-v13.6','routes':routes,
            'quality':{'routed_edges':len(routes),'wall_crossings':sum(r['wall_crossings'] for r in routes),
                       'all_orthogonal':all(all(a[0]==b[0] or a[1]==b[1] for a,b in zip(r['points'],r['points'][1:])) for r in routes)}}
