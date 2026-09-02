"""Geometry-aware orthogonal routing v14.

Routes topology edges with multiple Manhattan/dog-leg candidates, heavy penalties
for structural obstacles, lighter penalties for wall crossings, and deterministic
bend/length costs.  The output records why a path won so QA can reject routes
that still require coordination.
"""
from __future__ import annotations


def _clean(points):
 out=[]
 for p in points:
  p=(float(p[0]),float(p[1]))
  if not out or p!=out[-1]: out.append(p)
 # remove collinear middle points
 changed=True
 while changed and len(out)>2:
  changed=False; tmp=[out[0]]
  for i in range(1,len(out)-1):
   a=tmp[-1]; b=out[i]; c=out[i+1]
   if (a[0]==b[0]==c[0]) or (a[1]==b[1]==c[1]): changed=True; continue
   tmp.append(b)
  tmp.append(out[-1]); out=tmp
 return out

def _ccw(a,b,c): return (c[1]-a[1])*(b[0]-a[0])>(b[1]-a[1])*(c[0]-a[0])
def _intersects(a,b,c,d):
 if a==b or c==d:return False
 return _ccw(a,c,d)!=_ccw(b,c,d) and _ccw(a,b,c)!=_ccw(a,b,d)

def _point_in_rect(p,rect): return rect[0]<=p[0]<=rect[2] and rect[1]<=p[1]<=rect[3]
def _poly_bbox(poly):
 xs=[p[0] for p in poly]; ys=[p[1] for p in poly]; return (min(xs),min(ys),max(xs),max(ys))
def _seg_hits_rect(a,b,rect):
 if _point_in_rect(a,rect) or _point_in_rect(b,rect): return True
 x1,y1,x2,y2=rect; edges=[((x1,y1),(x2,y1)),((x2,y1),(x2,y2)),((x2,y2),(x1,y2)),((x1,y2),(x1,y1))]
 return any(_intersects(a,b,c,d) for c,d in edges)

def _candidates(start,end,clearance):
 x1,y1=start; x2,y2=end; out=[]
 out.append(_clean([start,(x2,y1),end])); out.append(_clean([start,(x1,y2),end]))
 for off in (clearance,-clearance,2*clearance,-2*clearance):
  out.append(_clean([start,(x1+off,y1),(x1+off,y2),end]))
  out.append(_clean([start,(x1,y1+off),(x2,y1+off),end]))
 # shared midline trunks often create cleaner plans than endpoint-radial routes
 mx=(x1+x2)/2; my=(y1+y2)/2
 out.append(_clean([start,(mx,y1),(mx,y2),end])); out.append(_clean([start,(x1,my),(x2,my),end]))
 unique=[]; seen=set()
 for pts in out:
  key=tuple(pts)
  if key not in seen: seen.add(key); unique.append(pts)
 return unique

def _score(points,walls,obstacles):
 wall_cross=0; obstacle_hits=0
 rects=[_poly_bbox(o.get('points') or o.get('polygon') or []) for o in obstacles if len(o.get('points') or o.get('polygon') or [])>=3]
 length=0.0
 for a,b in zip(points,points[1:]):
  length+=abs(b[0]-a[0])+abs(b[1]-a[1])
  for wall in walls:
   if _intersects(a,b,tuple(wall['start']),tuple(wall['end'])): wall_cross+=1
  obstacle_hits+=sum(_seg_hits_rect(a,b,r) for r in rects)
 bends=max(0,len(points)-2)
 penalty=obstacle_hits*1_000_000+wall_cross*10_000+bends*100+length
 return {'penalty':penalty,'obstacle_hits':obstacle_hits,'wall_crossings':wall_cross,'length':length,'bends':bends}

def route_topology(architecture,topology,clearance=None):
 units=architecture.get('units'); clearance=float(clearance or (300 if units==4 else 0.3))
 node_by_id={n['id']:n for n in topology.get('nodes') or []}; walls=architecture.get('walls') or []; obstacles=architecture.get('obstacles') or []
 edge_by_id={e['id']:e for e in topology.get('edges') or []}; routes=[]
 for edge in topology.get('edges') or []:
  a=node_by_id.get(edge.get('from')); b=node_by_id.get(edge.get('to'))
  if not a or not b or not a.get('point') or not b.get('point'): continue
  start=tuple(a['point']); end=tuple(b['point'])
  if start == end:
   # A proposed wet-core can coincide with a room-program endpoint. Emit a
   # visible orthogonal service loop instead of a zero-length "route" that the
   # CAD composer cannot draw or verify after exact-file reopen.
   x,y=start; points=[start,(x+clearance,y),(x+clearance,y+clearance),(x,y+clearance),end]
   score=_score(points,walls,obstacles)
   routes.append({'id':f"ROUTE-{len(routes)+1:04d}",'edge_id':edge['id'],'system':edge['system'],'role':edge.get('role'),
                  'from':edge.get('from'),'to':edge.get('to'),'endpoint_ids':list(edge.get('endpoint_ids') or []),
                  'points':points,'length':round(score['length'],3),'wall_crossings':score['wall_crossings'],
                  'obstacle_hits':score['obstacle_hits'],'bends':3,'routing':'orthogonal_coincident_endpoint_service_loop'})
   continue
  ranked=[]
  for pts in _candidates(start,end,clearance):
   score=_score(pts,walls,obstacles); ranked.append((score['penalty'],score,pts))
  _,score,points=min(ranked,key=lambda x:x[0])
  routes.append({'id':f"ROUTE-{len(routes)+1:04d}",'edge_id':edge['id'],'system':edge['system'],'role':edge.get('role'),
                 'from':edge.get('from'),'to':edge.get('to'),'endpoint_ids':list(edge.get('endpoint_ids') or []),
                 'points':points,'length':round(score['length'],3),'wall_crossings':score['wall_crossings'],
                 'obstacle_hits':score['obstacle_hits'],'bends':score['bends'],'routing':'orthogonal_multi_candidate_min_coordination_cost'})
 all_ortho=all(all(a[0]==b[0] or a[1]==b[1] for a,b in zip(r['points'],r['points'][1:])) for r in routes)
 return {'version':'geometry-routing-v14.6','routes':routes,
         'quality':{'topology_edges':len(edge_by_id),'routed_edges':len(routes),'all_orthogonal':all_ortho,
                    'wall_crossings':sum(r['wall_crossings'] for r in routes),'obstacle_hits':sum(r['obstacle_hits'] for r in routes),
                    'unrouted_edges':len(edge_by_id)-len(routes),'coordination_required':sum(bool(r['obstacle_hits']) for r in routes)}}
