"""Professional drafting placement solver for Dimension Engine v2."""
from __future__ import annotations
import math


def _bbox(points,pad=0.0):
    xs=[p[0] for p in points];ys=[p[1] for p in points]
    return (min(xs)-pad,min(ys)-pad,max(xs)+pad,max(ys)+pad)
def _overlap(a,b):
    return not (a[2]<=b[0] or b[2]<=a[0] or a[3]<=b[1] or b[3]<=a[1])
def _orient(a,b):
    return math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))
def _text_box(base,text):
    w=max(.28,.052*max(len(str(text or "")),4));h=.12
    return (base[0]-w/2,base[1]-h/2,base[0]+w/2,base[1]+h/2)
def _map(p,source,target):
    sx1,sy1,sx2,sy2=map(float,source);tx1,ty1,tx2,ty2=map(float,target)
    scale=min((tx2-tx1)/max(sx2-sx1,1e-9),(ty2-ty1)/max(sy2-sy1,1e-9))
    dx=tx1+((tx2-tx1)-(sx2-sx1)*scale)/2;dy=ty1+((ty2-ty1)-(sy2-sy1)*scale)/2
    return (dx+(p[0]-sx1)*scale,dy+(p[1]-sy1)*scale)
def _seg_intersect(a,b,c,d):
    def orient(p,q,r):
        return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    o1,o2,o3,o4=orient(a,b,c),orient(a,b,d),orient(c,d,a),orient(c,d,b)
    return (o1*o2<0 and o3*o4<0)

def _point_in_box(p,box,tol=1e-9):
    return box[0]-tol<=p[0]<=box[2]+tol and box[1]-tol<=p[1]<=box[3]+tol

def _segment_box_intersects(a,b,box):
    if _point_in_box(a,box) or _point_in_box(b,box):return True
    p1=(box[0],box[1]);p2=(box[2],box[1]);p3=(box[2],box[3]);p4=(box[0],box[3])
    return any(_seg_intersect(a,b,x,y) for x,y in ((p1,p2),(p2,p3),(p3,p4),(p4,p1)))

def _dimension_box_conflict(dimsegs,box):
    """Dimension line may not cross obstacles; extension lines may leave their host.

    dimsegs[0] is the dimension line. dimsegs[1:] start at the measured
    geometry and terminate at the dimension line. If an extension starts
    inside/on an architectural obstacle (shaft/core/column), leaving that host
    is legitimate and must not be misclassified as a collision.
    """
    if not dimsegs:return False
    if _segment_box_intersects(dimsegs[0][0],dimsegs[0][1],box):
        return True
    for a,b in dimsegs[1:]:
        if _segment_box_intersects(a,b,box) and not _point_in_box(a,box):
            return True
    return False

def _dimension_segments(p1,p2,base):
    vx,vy=p2[0]-p1[0],p2[1]-p1[1];L=math.hypot(vx,vy)
    if L<=1e-12:return [(p1,p2)]
    tx,ty=vx/L,vy/L
    def project(p):
        u=(p[0]-base[0])*tx+(p[1]-base[1])*ty
        return (base[0]+u*tx,base[1]+u*ty)
    q1,q2=project(p1),project(p2)
    return [(q1,q2),(p1,q1),(p2,q2)]

def build_drafting_obstacles(architecture,source_bounds,board):
    """Map trusted semantic/text/symbol obstacles into board coordinates."""
    boxes=[]
    def add_source_box(x1,y1,x2,y2):
        a=_map((x1,y1),source_bounds,tuple(board["plan_area"]))
        b=_map((x2,y2),source_bounds,tuple(board["plan_area"]))
        boxes.append((min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1])))
    for row in (architecture or {}).get("all_texts") or []:
        p=row.get("point")
        if p:
            # Source-space label guard; deliberately conservative and not text-metric authority.
            add_source_box(float(p[0])-.12,float(p[1])-.06,float(p[0])+.55,float(p[1])+.14)
    for row in (architecture or {}).get("all_inserts") or []:
        p=row.get("point")
        if p:add_source_box(float(p[0])-.16,float(p[1])-.16,float(p[0])+.16,float(p[1])+.16)
    for key in ("columns","shafts"):
        for item in (architecture or {}).get(key) or []:
            pts=item.get("polygon") or item.get("points") or []
            pts=[(float(p[0]),float(p[1])) for p in pts if len(p)>=2]
            if pts:
                xs=[p[0] for p in pts];ys=[p[1] for p in pts]
                add_source_box(min(xs),min(ys),max(xs),max(ys))
    return boxes


TIER_ORDER={"WALL_SETOUT":1,"OPENING_POSITION":1,"EQUIPMENT_POSITION":1,"RISER":1,"SLEEVE":1,"PENETRATION":1,
            "GRID":2,"BUILDING_OVERALL":3,"CHECK":3,"PROPERTY":4,"SETBACK":4}


def solve_dimension_placement(intents,source_bounds,board,obstacles=None,dimension_segments=None):
    """Place complete dimension line/text hierarchy without changing engineering refs."""
    plan=tuple(board["plan_area"]);bounds=tuple(board["bounds"]);title=tuple(board["title_area"])
    occupied=list(obstacles or []);segments=list(dimension_segments or []);placed=[];unresolved=[]
    tier_counters={}
    for row in sorted(intents or [],key=lambda r:(TIER_ORDER.get(r.get("purpose"),1),str(r.get("id")))):
        p1=_map(tuple(row["world_p1"]),source_bounds,plan);p2=_map(tuple(row["world_p2"]),source_bounds,plan)
        angle=math.radians(float(row.get("axis_deg",_orient(p1,p2))))
        purpose=row.get("purpose");tier=TIER_ORDER.get(purpose,1)
        horizontal=abs(math.cos(angle))>=abs(math.sin(angle))
        key=(tier,"H" if horizontal else "V");idx=tier_counters.get(key,0);tier_counters[key]=idx+1
        mid=((p1[0]+p2[0])/2,(p1[1]+p2[1])/2)
        normal=(-math.sin(angle),math.cos(angle))
        if tier>=2:
            if horizontal:
                candidates=[(mid[0],max(title[3]+.15,plan[1]-(.24*tier+.18*idx))), (mid[0],min(bounds[3]-.15,plan[3]+(.24*tier+.18*idx)))]
            else:
                candidates=[(max(bounds[0]+.15,plan[0]-(.24*tier+.18*idx)),mid[1]),(min(bounds[2]-.15,plan[2]+(.24*tier+.18*idx)),mid[1])]
        else:
            candidates=[(mid[0]+normal[0]*o,mid[1]+normal[1]*o) for o in (.22,-.22,.38,-.38,.58,-.58,.82,-.82)]
        chosen=None
        for base in candidates:
            tb=_text_box(base,row.get("display_value") or row.get("measured_value"))
            if tb[0]<bounds[0] or tb[1]<max(bounds[1],title[3]) or tb[2]>bounds[2] or tb[3]>bounds[3]:continue
            if any(_overlap(tb,o) for o in occupied):continue
            dimsegs=_dimension_segments(p1,p2,base)
            if any(_dimension_box_conflict(dimsegs,o) for o in occupied):continue
            if any(_seg_intersect(a,b,s[0],s[1]) for a,b in dimsegs for s in segments):continue
            chosen=(base,tb,dimsegs);break
        if not chosen:
            unresolved.append({"intent_id":row.get("id"),"reason":"NO_COLLISION_FREE_DIMENSION_PLACEMENT"})
            base=candidates[0];tb=_text_box(base,row.get("display_value") or row.get("measured_value"))
        else:base,tb,dimsegs=chosen
        occupied.append(tb)
        segments.extend(dimsegs if chosen is not None else _dimension_segments(p1,p2,base))
        placed.append({**row,"render_p1":p1,"render_p2":p2,"render_base":base,"text_box":tb})
    return {"status":"HUMAN_REVIEW_REQUIRED" if unresolved else "PASS","placed":placed,"unresolved":unresolved,
            "collision_count":len(unresolved),"occupied_count":len(occupied)}
