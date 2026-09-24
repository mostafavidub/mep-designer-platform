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
    def ccw(p,q,r):return (r[1]-p[1])*(q[0]-p[0])>(q[1]-p[1])*(r[0]-p[0])
    return ccw(a,c,d)!=ccw(b,c,d) and ccw(a,b,c)!=ccw(a,b,d)


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
            dimseg=(p1,p2)
            if any(_seg_intersect(dimseg[0],dimseg[1],s[0],s[1]) for s in segments):continue
            chosen=(base,tb);break
        if not chosen:
            unresolved.append({"intent_id":row.get("id"),"reason":"NO_COLLISION_FREE_DIMENSION_PLACEMENT"})
            base=candidates[0];tb=_text_box(base,row.get("display_value") or row.get("measured_value"))
        else:base,tb=chosen
        occupied.append(tb);segments.append((p1,p2))
        placed.append({**row,"render_p1":p1,"render_p2":p2,"render_base":base,"text_box":tb})
    return {"status":"HUMAN_REVIEW_REQUIRED" if unresolved else "PASS","placed":placed,"unresolved":unresolved,
            "collision_count":len(unresolved),"occupied_count":len(occupied)}
