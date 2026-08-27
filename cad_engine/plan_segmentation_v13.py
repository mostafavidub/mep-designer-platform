"""Stage 0/1 helper: detect independent print frames and scope entities per plan."""
from __future__ import annotations
import ezdxf


def _point(entity):
    for attr in ("insert","location","start","center"):
        try:
            p=getattr(entity.dxf,attr); return (float(p.x),float(p.y))
        except Exception: pass
    if entity.dxftype()=="LWPOLYLINE":
        pts=[(float(x),float(y)) for x,y,*_ in entity.get_points()]
        if pts: return (sum(x for x,y in pts)/len(pts),sum(y for x,y in pts)/len(pts))
    return None


def _inside(point,bounds,tol=1e-6):
    if not point:return False
    x,y=point; x1,y1,x2,y2=bounds
    return x1-tol<=x<=x2+tol and y1-tol<=y<=y2+tol


def detect_print_plans(src):
    doc=ezdxf.readfile(src); msp=doc.modelspace(); frames=[]
    for e in msp:
        if e.dxftype()!="LWPOLYLINE" or not e.closed: continue
        pts=[(float(x),float(y)) for x,y,*_ in e.get_points()]
        if len(pts)<4: continue
        xs=[x for x,y in pts]; ys=[y for x,y in pts]; w=max(xs)-min(xs); h=max(ys)-min(ys)
        layer=str(getattr(e.dxf,"layer","") or "").lower()
        # Exact office A4 support frames used by the current architectural set.
        if layer=="suport" and 20<=w<=22 and 28<=h<=31:
            frames.append([min(xs),min(ys),max(xs),max(ys)])
    frames=sorted(frames,key=lambda b:(-b[1],b[0]))
    return [{"plan_id":f"PLAN-{i+1:02d}","bounds":b} for i,b in enumerate(frames)]


def apply_plan_scopes(src,architecture,recognition):
    plans=detect_print_plans(src)
    def owner(point):
        return next((p for p in plans if _inside(point,p["bounds"])),None)
    for room in architecture.get("rooms") or []:
        p=owner(room.get("label_point")); room["plan_id"]=p["plan_id"] if p else None
    for item in recognition.get("detections") or []:
        p=owner(item.get("point")); item["plan_id"]=p["plan_id"] if p else None
    # Persian shaft/duct evidence can be textual instead of a SHAFT layer.
    doc=ezdxf.readfile(src); text_shafts=[]
    for e in doc.modelspace():
        if e.dxftype() not in {"TEXT","MTEXT"}: continue
        try:text=str(e.dxf.text if e.dxftype()=="TEXT" else e.plain_text()).strip(); point=_point(e)
        except Exception:continue
        if not point or not ("داکت" in text or "شفت" in text): continue
        p=owner(point)
        if p:text_shafts.append({"layer":str(e.dxf.layer),"polygon":None,"point":point,"area":None,"plan_id":p["plan_id"],"source":"textual_vertical_core"})
    for shaft in architecture.get("shafts") or []:
        point=shaft.get("point")
        if point is None and shaft.get("polygon"):
            poly=shaft["polygon"]; point=(sum(x for x,y in poly)/len(poly),sum(y for x,y in poly)/len(poly))
        p=owner(point); shaft["plan_id"]=p["plan_id"] if p else None; shaft["point"]=point
    architecture["shafts"]=(architecture.get("shafts") or [])+text_shafts
    architecture["plans"]=plans
    architecture.setdefault("quality",{})["plan_count"]=len(plans)
    return architecture,recognition
