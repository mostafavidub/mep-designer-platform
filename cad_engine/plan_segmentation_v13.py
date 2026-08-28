"""Stage 0/1 helper: detect, classify, deduplicate and scope print-frame drawings."""
from __future__ import annotations
import re
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


def _text(entity):
    try:
        return str(entity.dxf.text if entity.dxftype()=="TEXT" else entity.plain_text()).strip()
    except Exception:
        return ""


def _norm(value):
    value=str(value or "").replace("ي","ی").replace("ك","ک").replace("\u200c"," ").lower()
    return re.sub(r"\s+"," ",value).strip()


def _classify(text_blob):
    s=_norm(text_blob)
    if "نمای شمالی" in s or "نمای جنوبی" in s or "نمای شرقی" in s or "نمای غربی" in s:
        return "ELEVATION"
    if "برش" in s or re.search(r"\b[a-z]-[a-z]\b",s):
        return "SECTION"
    if "پلان شیب بندی" in s or "پلان شیب‌بندی" in s:
        return "ROOF_PLAN"
    if "پلان نعل درگاه" in s:
        return "LINTEL_PLAN"
    if "پلان مبلمان" in s:
        return "FURNITURE_PLAN"
    if "پلان معماری" in s:
        return "ARCH_FLOOR_PLAN"
    if "جزییات" in s or "جزئیات" in s or "detail" in s:
        return "DETAIL"
    return "UNKNOWN"


def _level(text_blob):
    s=_norm(text_blob)
    if "طبقه دوم" in s: return "LEVEL-02"
    if "طبقه اول" in s: return "LEVEL-01"
    if "طبقه همکف" in s: return "GROUND"
    if "بام" in s or "شیب بندی" in s or "شیب‌بندی" in s: return "ROOF"
    return None


def detect_print_plans(src):
    doc=ezdxf.readfile(src); msp=doc.modelspace(); frames=[]
    for e in msp:
        if e.dxftype()!="LWPOLYLINE" or not e.closed: continue
        pts=[(float(x),float(y)) for x,y,*_ in e.get_points()]
        if len(pts)<4: continue
        xs=[x for x,y in pts]; ys=[y for x,y in pts]; w=max(xs)-min(xs); h=max(ys)-min(ys)
        layer=str(getattr(e.dxf,"layer","") or "").lower()
        if layer=="suport" and 20<=w<=22 and 28<=h<=31:
            frames.append([min(xs),min(ys),max(xs),max(ys)])
    frames=sorted(frames,key=lambda b:(-b[1],b[0]))
    plans=[]
    for i,b in enumerate(frames):
        frame_text=[]; entity_count=0
        for e in msp:
            p=_point(e)
            if not p or not _inside(p,b): continue
            entity_count += 1
            if e.dxftype() in {"TEXT","MTEXT"}:
                value=_text(e)
                if value: frame_text.append(value)
        blob="\n".join(frame_text)
        arc=next((x for x in frame_text if re.search(r"arc\s*-\s*\d+",_norm(x))),None)
        plans.append({"plan_id":f"PLAN-{i+1:02d}","bounds":b,"drawing_type":_classify(blob),
                      "level":_level(blob),"title_text":frame_text,"arc_sheet":arc,
                      "entity_count":entity_count,"mechanical_role":"EXCLUDE"})

    # Canonical floor plans: prefer titled Arc sheets and richer geometry.
    floor_candidates=[p for p in plans if p["drawing_type"]=="ARCH_FLOOR_PLAN"]
    by_level={}
    for p in floor_candidates:
        if not p.get("level"): continue
        score=(1 if p.get("arc_sheet") else 0,p.get("entity_count",0))
        if p["level"] not in by_level or score>by_level[p["level"]][0]:
            by_level[p["level"]]=(score,p)
    for _,p in by_level.values():
        p["mechanical_role"]="PRIMARY_FLOOR"
    for p in plans:
        if p["drawing_type"]=="ROOF_PLAN": p["mechanical_role"]="ROOF_SUPPORT"
        elif p["drawing_type"]=="ARCH_FLOOR_PLAN" and p["mechanical_role"]!="PRIMARY_FLOOR":
            p["mechanical_role"]="DUPLICATE_REFERENCE"
    return plans


def apply_plan_scopes(src,architecture,recognition):
    plans=detect_print_plans(src)
    # Legacy/single-plan drawings without office print frames remain valid.
    if not plans:
        bounds=architecture.get("bounds") or [0,0,0,0]
        plans=[{"plan_id":"PLAN-01","bounds":list(bounds),"source":"single_plan_fallback",
                "drawing_type":"ARCH_FLOOR_PLAN","level":None,"mechanical_role":"PRIMARY_FLOOR"}]
    def owner(point):
        return next((p for p in plans if _inside(point,p["bounds"])),None)
    for room in architecture.get("rooms") or []:
        p=owner(room.get("label_point")); room["plan_id"]=p["plan_id"] if p else None
    for item in recognition.get("detections") or []:
        p=owner(item.get("point")); item["plan_id"]=p["plan_id"] if p else None

    doc=ezdxf.readfile(src); text_shafts=[]
    for e in doc.modelspace():
        if e.dxftype() not in {"TEXT","MTEXT"}: continue
        text=_text(e); point=_point(e)
        if not point or not ("داکت" in text or "شفت" in text): continue
        p=owner(point)
        if p:text_shafts.append({"layer":str(e.dxf.layer),"polygon":None,"point":point,"area":None,
                                 "plan_id":p["plan_id"],"source":"textual_vertical_core"})
    for shaft in architecture.get("shafts") or []:
        point=shaft.get("point")
        if point is None and shaft.get("polygon"):
            poly=shaft["polygon"]; point=(sum(x for x,y in poly)/len(poly),sum(y for x,y in poly)/len(poly))
        p=owner(point); shaft["plan_id"]=p["plan_id"] if p else None; shaft["point"]=point
    architecture["shafts"]=(architecture.get("shafts") or [])+text_shafts
    architecture["plans"]=plans
    architecture["mechanical_plan_ids"]=[p["plan_id"] for p in plans if p.get("mechanical_role") in {"PRIMARY_FLOOR","ROOF_SUPPORT"}]
    architecture["primary_floor_plan_ids"]=[p["plan_id"] for p in plans if p.get("mechanical_role")=="PRIMARY_FLOOR"]
    architecture.setdefault("quality",{})["plan_count"]=len(plans)
    architecture["quality"]["primary_floor_count"]=len(architecture["primary_floor_plan_ids"])
    architecture["quality"]["excluded_frame_count"]=sum(1 for p in plans if p.get("mechanical_role") in {"EXCLUDE","DUPLICATE_REFERENCE"})

    # Only canonical floor plans feed room/fixture driven mechanical design.
    primary=set(architecture["primary_floor_plan_ids"])
    if primary:
        architecture["rooms_all_frames"]=list(architecture.get("rooms") or [])
        recognition["detections_all_frames"]=list(recognition.get("detections") or [])
        architecture["rooms"]=[r for r in architecture.get("rooms") or [] if r.get("plan_id") in primary]
        recognition["detections"]=[x for x in recognition.get("detections") or [] if x.get("plan_id") in primary]
        recognition["fixtures"]=[x for x in recognition.get("detections") or [] if x.get("category")=="fixture"]
        recognition["equipment"]=[x for x in recognition.get("detections") or [] if x.get("category")=="equipment"]
    return architecture,recognition
