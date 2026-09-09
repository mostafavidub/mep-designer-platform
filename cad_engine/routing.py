"""Stage 6 — orthogonal routing constrained to the owning print plan."""
from __future__ import annotations
import heapq

def _ccw(a,b,c): return (c[1]-a[1])*(b[0]-a[0])>(b[1]-a[1])*(c[0]-a[0])
def _intersects(a,b,c,d):
    if a==b or c==d:return False
    return _ccw(a,c,d)!=_ccw(b,c,d) and _ccw(a,b,c)!=_ccw(a,b,d)
def _route_candidates(start,end):
    x1,y1=start;x2,y2=end
    if start==end:
        # A local endpoint may coincide with the proposed vertical core. Keep
        # the true endpoints and draw a measurable orthogonal connection loop.
        d=.20
        return (
            [start,(x1+d,y1),(x1+d,y1+d),(x1,y1+d),end],
            [start,(x1-d,y1),(x1-d,y1-d),(x1,y1-d),end],
        )
    def clean(points):
        out=[]
        for p in points:
            if not out or p!=out[-1]:out.append(p)
        return out
    return clean([start,(x2,y1),end]),clean([start,(x1,y2),end])
def _inside(p,b,tol=1e-6):
    if not b:return True
    return b[0]-tol<=p[0]<=b[2]+tol and b[1]-tol<=p[1]<=b[3]+tol
def _score(points,walls,terminal_penetration=False):
    clashes=0
    penetrations=0
    segments=list(zip(points,points[1:]))
    for segment_index,(a,b) in enumerate(segments):
        for wall in walls:
            if _intersects(a,b,tuple(wall['start']),tuple(wall['end'])):
                # Reaching a real/proposed vertical core can require entering
                # its enclosing shaft wall.  Every intersection on the final
                # terminal segment is an explicit coordinated penetration;
                # crossings on earlier route segments remain hard clashes.
                if terminal_penetration and segment_index==len(segments)-1:
                    penetrations+=1
                else:clashes+=1
    length=sum(abs(b[0]-a[0])+abs(b[1]-a[1]) for a,b in zip(points,points[1:]))
    return clashes,length,penetrations

def _wall_in_bounds(wall,bounds):
    if not bounds:return True
    (x1,y1),(x2,y2)=wall['start'],wall['end']
    return max(x1,x2)>=bounds[0] and min(x1,x2)<=bounds[2] and max(y1,y2)>=bounds[1] and min(y1,y2)<=bounds[3]

def _clear(a,b,walls):
    return not any(_intersects(a,b,tuple(w['start']),tuple(w['end'])) for w in walls)

def _grid_axis(low,high,step,extras):
    rows=[];value=low
    while value < high:
        rows.append(round(value,6));value += step
    rows.append(round(high,6));rows.extend(round(float(v),6) for v in extras if low<=float(v)<=high)
    return sorted(set(rows))

def _sparse_axis(low,high,start,end,walls,coordinate,clearance=.05):
    """Keep A* finite while retaining narrow passages beside real walls."""
    values={round(low,6),round(high,6),round(start,6),round(end,6)}
    for wall in walls:
        for point in (wall['start'],wall['end']):
            value=float(point[coordinate])
            for candidate in (value-clearance,value,value+clearance):
                if low<=candidate<=high:values.add(round(candidate,6))
    return sorted(values)

def _open_space_route(start,end,bounds,walls,step=.25):
    """Find an orthogonal route through real wall openings using bounded A*."""
    if not bounds:return None
    direct=abs(start[0]-end[0])+abs(start[1]-end[1])
    margin=min(25.0,max(2.0,direct*.5))
    local=(max(bounds[0],min(start[0],end[0])-margin),max(bounds[1],min(start[1],end[1])-margin),
           min(bounds[2],max(start[0],end[0])+margin),min(bounds[3],max(start[1],end[1])+margin))
    walls=[wall for wall in walls if _wall_in_bounds(wall,local)]
    xs=_sparse_axis(local[0],local[2],start[0],end[0],walls,0)
    ys=_sparse_axis(local[1],local[3],start[1],end[1],walls,1)
    sx=xs.index(round(start[0],6));sy=ys.index(round(start[1],6))
    ex=xs.index(round(end[0],6));ey=ys.index(round(end[1],6));source=(sx,sy);target=(ex,ey)
    queue=[(abs(start[0]-end[0])+abs(start[1]-end[1]),0.0,source)]
    cost={source:0.0};parent={};visited=set()
    while queue:
        _,spent,node=heapq.heappop(queue)
        if node in visited:continue
        visited.add(node)
        if node==target:
            indices=[]
            while node in parent:indices.append(node);node=parent[node]
            indices.append(source);indices.reverse();points=[(xs[i],ys[j]) for i,j in indices]
            compact=[]
            for point in points:
                if len(compact)>=2 and (compact[-2][0]==compact[-1][0]==point[0] or compact[-2][1]==compact[-1][1]==point[1]):
                    compact[-1]=point
                else:compact.append(point)
            return compact
        i,j=node
        for nxt in ((i-1,j),(i+1,j),(i,j-1),(i,j+1)):
            ni,nj=nxt
            if not (0<=ni<len(xs) and 0<=nj<len(ys)) or nxt in visited:continue
            a=(xs[i],ys[j]);b=(xs[ni],ys[nj])
            if not _clear(a,b,walls):continue
            new=spent+abs(a[0]-b[0])+abs(a[1]-b[1])
            if new >= cost.get(nxt,float('inf')):continue
            cost[nxt]=new;parent[nxt]=node
            heuristic=abs(b[0]-end[0])+abs(b[1]-end[1])
            heapq.heappush(queue,(new+heuristic,new,nxt))
    return None

def route_topology(architecture,topology):
    node_by_id={n['id']:n for n in topology.get('nodes') or []}; walls=architecture.get('walls') or []
    plan_bounds={p['plan_id']:p['bounds'] for p in architecture.get('plans') or []};routes=[];rejected=[]
    for edge in topology.get('edges') or []:
        start=node_by_id.get(edge.get('from'));end=node_by_id.get(edge.get('to'));pid=edge.get('plan_id')
        if not start or not end or not start.get('point') or not end.get('point'):continue
        if start.get('plan_id')!=end.get('plan_id') or (pid and start.get('plan_id')!=pid):
            rejected.append({'edge_id':edge['id'],'reason':'CROSS_PLAN_TOPOLOGY'});continue
        bounds=plan_bounds.get(pid)
        plan_walls=[w for w in walls if _wall_in_bounds(w,bounds)]
        candidates=[pts for pts in _route_candidates(tuple(start['point']),tuple(end['point'])) if all(_inside(p,bounds) for p in pts)]
        if not candidates:
            rejected.append({'edge_id':edge['id'],'reason':'ROUTE_OUTSIDE_PLAN'});continue
        terminal_penetration=end.get('category')=='vertical'
        ranked=sorted(((_score(points,plan_walls,terminal_penetration),points) for points in candidates),key=lambda x:(x[0][0],x[0][1]))
        (clashes,length,penetrations),points=ranked[0]
        used_astar=False
        if clashes:
            open_route=_open_space_route(tuple(start['point']),tuple(end['point']),bounds,plan_walls)
            if open_route:
                points=open_route;clashes,length,penetrations=_score(points,plan_walls,terminal_penetration);used_astar=True
        routes.append({'id':f'ROUTE-{len(routes)+1:03d}','edge_id':edge['id'],'system':edge['system'],'plan_id':pid,'points':points,
                       'length':round(length,3),'wall_crossings':clashes,
                       'coordinated_terminal_penetrations':penetrations,
                       'routing':'orthogonal_open_space_astar' if used_astar else 'orthogonal_plan_isolated'})
    return {'version':'geometry-routing-v13.12','routes':routes,'rejected':rejected,
            'quality':{'routed_edges':len(routes),'wall_crossings':sum(r['wall_crossings'] for r in routes),
                       'coordinated_terminal_penetrations':sum(r['coordinated_terminal_penetrations'] for r in routes),
                       'cross_plan_routes':0,'rejected_edges':len(rejected),
                       'all_orthogonal':all(all(a[0]==b[0] or a[1]==b[1] for a,b in zip(r['points'],r['points'][1:])) for r in routes)}}
