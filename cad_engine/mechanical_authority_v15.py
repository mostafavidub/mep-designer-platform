"""Mechanical authority delivery v15.

Project-agnostic production pipeline for EngiTools mechanical drawings.
It converts the existing engineering analysis pipeline into a repeatable
authority-style drawing package while preserving architectural evidence.

Key contracts:
- project-driven sheet manifest; never hard-code a 28-sheet project globally
- plan isolation; no cross-frame physical routing
- conservative architecture handling; source architectural entities are not deleted
- preliminary/final provenance on every engineering value
- integrated A4 sheet frame + compact bottom title block
- north direction inherited from architecture when evidence exists
- no drawing/title-block overlap
- exact-file reopen QA before package is returned
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import re
from pathlib import Path

import ezdxf
from ezdxf import bbox
from ezdxf.math import Matrix44

from .engineering_runner_v13 import run_engineering_pipeline, validate_pipeline
from .acceptance_v13 import evaluate_engineering_acceptance
from .authority_architecture_v14 import (
    build_project_model,
    resolve_design_basis,
    derive_system_requirements as derive_authority_requirements,
    build_reference_driven_manifest,
    build_network_contract,
    build_calculation_contract,
    validate_authority_contract,
)
from .equipment_representation_v14 import validate_split_representation


A4_W = 21.0
A4_H = 29.7
TITLE_H = 3.10
OUTER_MARGIN = 0.60
PLAN_MARGIN = 1.05
UNDERPLAN_H = 0.90

PLAN_FAMILIES = {
    "ROOF", "SANITARY_VENT", "WATER", "HEATING", "GAS",
    "SPLIT_AC", "EXHAUST",
}

LEGACY_SHEET_TEXT_RE = re.compile(
    r"(?:پلان\s+معماری|arc\s*-\s*\d+|^\s*sc\s*:\s*1/100\s*$)",
    re.IGNORECASE,
)

GAS_TABLE_P22 = {
    2:[5.9,12.3,23.3,47.9,72.0,138.3,220.0,390.7,801.9],
    4:[4.0,8.5,16.0,32.9,49.4,95.1,151.2,268.5,551.1],
    6:[3.2,6.8,12.9,26.4,39.7,76.4,121.5,215.7,442.8],
    8:[2.8,5.8,11.0,22.6,34.0,65.4,104.0,184.7,379.1],
    10:[2.4,5.0,9.6,19.7,29.6,56.9,90.4,160.6,329.7],
    12:[2.2,4.7,8.8,18.1,27.3,52.5,83.4,148.2,304.3],
    14:[2.0,4.3,8.1,16.7,25.0,48.2,76.6,121.5,279.4],
    16:[1.9,4.0,7.5,15.5,23.3,44.8,71.3,126.7,260.0],
    18:[1.8,3.7,7.1,14.6,21.9,42.2,67.1,119.3,244.8],
    20:[1.7,3.5,6.7,13.8,20.7,39.8,63.3,112.5,231.0],
    22:[1.6,3.3,6.3,13.1,19.6,37.8,60.1,106.8,219.2],
    24:[1.5,3.2,6.1,12.5,18.7,36.1,57.4,101.9,209.2],
    26:[1.4,3.1,5.8,12.0,18.0,34.6,55.1,97.9,200.9],
    28:[1.4,2.9,5.5,11.4,17.2,33.1,52.6,93.6,191.0],
    30:[1.3,2.8,5.3,11.0,16.6,31.9,50.8,90.2,185.1],
    35:[1.2,2.6,4.9,10.2,15.3,29.4,46.8,83.1,170.6],
    40:[1.1,2.4,4.6,9.4,14.1,27.1,43.3,76.9,157.9],
    45:[1.1,2.2,4.3,8.8,13.3,25.5,40.6,72.2,148.1],
    50:[1.0,2.1,4.1,8.4,12.6,24.3,38.6,68.7,141.0],
}
GAS_SIZES_IN = ["1/2","3/4","1","1-1/4","1-1/2","2","2-1/2","3","4"]
GAS_DN = {"1/2":15,"3/4":20,"1":25,"1-1/4":32,"1-1/2":40,"2":50,"2-1/2":65,"3":80,"4":100}


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "").replace("ي","ی").replace("ك","ک").replace("\u200c"," ")).strip().lower()


def _text(e):
    try:
        if e.dxftype() == "TEXT":
            return str(e.dxf.text or "")
        if e.dxftype() == "MTEXT":
            return str(e.plain_text() or "")
    except Exception:
        pass
    return ""


def _point(e):
    for attr in ("insert","location","start","center"):
        try:
            p = getattr(e.dxf, attr)
            return float(p.x), float(p.y)
        except Exception:
            pass
    if e.dxftype() == "LWPOLYLINE":
        try:
            pts=[(float(x),float(y)) for x,y,*_ in e.get_points()]
            if pts:
                return sum(x for x,y in pts)/len(pts), sum(y for x,y in pts)/len(pts)
        except Exception:
            pass
    return None


def _inside(p, b, tol=1e-6):
    if not p or not b:
        return False
    return b[0]-tol <= p[0] <= b[2]+tol and b[1]-tol <= p[1] <= b[3]+tol


def _entity_ext(e):
    try:
        ex=bbox.extents([e], fast=True)
        return ex if ex.has_data else None
    except Exception:
        return None


def _center(ex):
    return ((ex.extmin.x+ex.extmax.x)/2, (ex.extmin.y+ex.extmax.y)/2)


def _ensure_layer(doc, name, color=7, lineweight=18):
    try:
        layer=doc.layers.get(name)
    except Exception:
        layer=doc.layers.add(name, color=color, lineweight=lineweight)
    layer.dxf.color=color
    layer.dxf.lineweight=lineweight
    return layer


def _answer(answers, *keys, default=None):
    for k in keys:
        v=(answers or {}).get(k)
        if v not in (None,"",[]):
            return v
    return default


def build_design_overrides(answers: dict) -> dict:
    location=_answer(answers,"location", default="")
    city=str(location).split("،")[-1].strip() if location else None
    cooling=_norm(_answer(answers,"cooling", default=""))
    heating=_norm(_answer(answers,"heating", default=""))
    gas_answer=_norm(_answer(answers,"gas", default=""))
    cooling_key="wall_mounted_split_ac" if any(x in cooling for x in ("اسپلیت","کولر گازی","split","split unit")) else None
    heating_key="package_radiator" if (
        ("پکیج" in heating and any(x in heating for x in ("رادیاتور","شوفاژ")))
        or ("radiator" in heating and any(x in heating for x in ("combi","boiler","hydronic")))
    ) else None
    return {
        "city": city,
        "cooling_system": cooling_key,
        "heating_system": heating_key,
        "gas_service": bool(gas_answer and not any(x in gas_answer for x in ("ندارد","خیر","no gas"))),
        "fixture_evidence": list(_answer(answers, "_plan_fixture_evidence", default=[]) or []),
        "hvac": {"city":city,"cooling":"split_ac" if cooling_key else None,"heating":"package_radiator" if heating_key else None},
        "water_inlet_pressure": _answer(answers,"water_pressure","water"),
        "gas_service_pressure": _answer(answers,"gas_pressure"),
        "rainfall_intensity": _answer(answers,"rainfall_intensity"),
        "envelope": {
            "u_wall": _answer(answers,"u_wall"),
            "u_roof": _answer(answers,"u_roof"),
            "u_window": _answer(answers,"u_window"),
            "infiltration_ach": _answer(answers,"infiltration_ach"),
        },
    }


def _level_evidence(pipeline):
    arch=pipeline["architecture"]
    recognition=pipeline["recognition"]
    by_plan={p["plan_id"]:p for p in arch.get("plans") or []}
    levels={}
    for pid in arch.get("primary_floor_plan_ids") or []:
        p=by_plan.get(pid) or {}; level=p.get("level") or pid
        rooms=[r for r in arch.get("rooms") or [] if r.get("plan_id")==pid]
        detections=[d for d in recognition.get("detections") or [] if d.get("plan_id")==pid]
        room_types={r.get("type") for r in rooms}; equip_types={d.get("type") for d in detections}
        levels[level]={
            "plan_id":pid,"bounds":p.get("bounds"),
            "wet":bool(room_types & {"bathroom","toilet","kitchen"}),
            "habitable":bool(room_types & {"bedroom","living","kitchen"}),
            "exhaust":bool(room_types & {"bathroom","toilet","kitchen","parking"}),
            "gas_appliance":bool("stove" in equip_types or "water_heater" in equip_types or "kitchen" in room_types),
        }
    return levels


def build_authority_model(pipeline, answers):
    levels=_level_evidence(pipeline)
    roof=any(p.get("mechanical_role")=="ROOF_SUPPORT" for p in pipeline["architecture"].get("plans") or [])
    project=build_project_model(levels=levels,roof_present=roof,occupancy=_answer(answers,"occupancy",default="residential"),excluded_frames=(pipeline["architecture"].get("quality") or {}).get("excluded_frame_count",0))
    overrides=build_design_overrides(answers)
    basis=resolve_design_basis(project,overrides)
    req=derive_authority_requirements(project,basis)
    manifest=build_reference_driven_manifest(project,req)
    network=build_network_contract(req)
    calc=build_calculation_contract()
    qa=validate_authority_contract(project,basis,req,manifest,network,calc)
    return {"project":project,"design_basis":basis,"requirements":req,"manifest":manifest,"network":network,"calculation_contract":calc,"authority_qa":qa}


def _sheet_code(family, level, ordinal):
    level_code={"GROUND":"1","LEVEL-01":"2","LEVEL-02":"3","ROOF":"4"}.get(level,"")
    groups={"COVER":"M-001","GENERAL_NOTES":"M-003","ROOF":"M-011","PLUMBING_RISER":"M-151","WATER_SERVICE_CALC":"M-152","EQUIPMENT_SCHEDULE":"M-181"}
    if family in groups:return groups[family]
    if family=="GENERAL_DETAIL":return f"M-{3+ordinal:03d}"
    bases={"SANITARY_VENT":100,"WATER":110,"HEATING":130,"GAS":140,"SPLIT_AC":160,"EXHAUST":170}
    if family in bases:
        if level=="ROOF" and family=="SPLIT_AC":return "M-164"
        return f"M-{bases[family]+int(level_code or ordinal):03d}"
    return f"M-{900+ordinal:03d}"


def _title_fa(family, level):
    level_fa={"GROUND":"طبقه همکف","LEVEL-01":"طبقه اول","LEVEL-02":"طبقه دوم","ROOF":"بام","MULTI":"کل پروژه"}.get(level,level)
    titles={"COVER":"صفحه عنوان، فهرست نقشه‌ها و مشخصات پروژه","GENERAL_NOTES":"یادداشت‌های عمومی و مبانی طراحی تأسیسات مکانیکی","ROOF":"پلان بام، آب باران و انتهای ونت","PLUMBING_RISER":"رایزر دیاگرام تأسیسات مکانیکی","WATER_SERVICE_CALC":"محاسبات و انتخاب پمپ آب","EQUIPMENT_SCHEDULE":"جدول تجهیزات و سایزبندی تأسیسات مکانیکی"}
    if family in titles:return titles[family]
    if family=="GENERAL_DETAIL":return "جزئیات تیپ تأسیسات مکانیکی"
    system={"SANITARY_VENT":"پلان لوله‌کشی فاضلاب و هواکش","WATER":"پلان لوله‌کشی آب سرد و گرم مصرفی","HEATING":"پلان لوله‌کشی گرمایش رادیاتوری","GAS":"پلان لوله‌کشی گاز","SPLIT_AC":"پلان جانمایی و لوله‌کشی اسپلیت","EXHAUST":"پلان تخلیه اجباری هوا و اگزاست"}.get(family,family)
    return f"{system} {level_fa}".strip()


def _layout_manifest(authority):
    rows=[];family_ord=defaultdict(int)
    for i,row in enumerate(authority["manifest"]["sheets"],1):
        family=row["family"];family_ord[family]+=1;level=row.get("level") or "MULTI"
        rows.append({**row,"old_sheet":row["sheet"],"code":_sheet_code(family,level,family_ord[family]),"title_fa":_title_fa(family,level),"ordinal":i})
    return rows


@dataclass
class Board:
    sheet: str
    code: str
    family: str
    level: str
    title: str
    bounds: tuple
    plan_area: tuple
    title_area: tuple
    subtitle_area: tuple


def _boards(manifest_rows):
    result={};cols=6;gap_x=3.0;gap_y=4.0
    for i,row in enumerate(manifest_rows):
        col=i%cols;row_i=i//cols;x1=col*(A4_W+gap_x);y2=-(row_i*(A4_H+gap_y));y1=y2-A4_H;x2=x1+A4_W
        title=(x1+OUTER_MARGIN,y1+.40,x2-OUTER_MARGIN,y1+.40+TITLE_H)
        subtitle=(x1+1.0,title[3],x2-1.0,title[3]+UNDERPLAN_H)
        plan=(x1+PLAN_MARGIN,subtitle[3]+.25,x2-PLAN_MARGIN,y2-1.0)
        result[row["old_sheet"]]=Board(row["old_sheet"],row["code"],row["family"],row.get("level") or "MULTI",row["title_fa"],(x1,y1,x2,y2),plan,title,subtitle)
    return result


def _entity_should_copy(e):
    layer=_norm(getattr(e.dxf,"layer",""))
    if layer in {"suport","support","frame","sheet","border"}:return False
    if e.dxftype() in {"TEXT","MTEXT"} and LEGACY_SHEET_TEXT_RE.search(_text(e)):return False
    return True


def _entities_in_bounds(msp,bounds):
    return [e for e in msp if (lambda p:p and _inside(p,bounds))(_point(e)) and _entity_should_copy(e)]


def _fit_transform(source_bounds,target_bounds):
    sx1,sy1,sx2,sy2=source_bounds;tx1,ty1,tx2,ty2=target_bounds
    sw=max(sx2-sx1,1e-9);sh=max(sy2-sy1,1e-9);tw=tx2-tx1;th=ty2-ty1
    scale=min(tw/sw,th/sh);nw=sw*scale;nh=sh*scale;dx=tx1+(tw-nw)/2;dy=ty1+(th-nh)/2
    return Matrix44.chain(Matrix44.translate(-sx1,-sy1,0),Matrix44.scale(scale,scale,1),Matrix44.translate(dx,dy,0)),scale,(dx,dy)


def _clone_entities(msp,entities,M):
    copied=[];failed=[]
    for e in entities:
        try:
            c=e.copy();c.transform(M);msp.add_entity(c);copied.append(c)
        except Exception:failed.append(str(getattr(e.dxf,"handle","")))
    return copied,failed


def _map_point(p,source_bounds,target_bounds):
    M,_,_=_fit_transform(source_bounds,target_bounds)
    try:
        v=M.transform((p[0],p[1],0));return float(v.x),float(v.y)
    except Exception:
        sx1,sy1,sx2,sy2=source_bounds;tx1,ty1,tx2,ty2=target_bounds
        rx=(p[0]-sx1)/max(sx2-sx1,1e-9);ry=(p[1]-sy1)/max(sy2-sy1,1e-9)
        return tx1+rx*(tx2-tx1),ty1+ry*(ty2-ty1)


def _find_plan_for_level(arch,level):
    return next((p for p in arch.get("plans") or [] if p.get("mechanical_role")=="PRIMARY_FLOOR" and p.get("level")==level),None)


def _find_roof_plan(arch):
    return next((p for p in arch.get("plans") or [] if p.get("mechanical_role")=="ROOF_SUPPORT"),None)


def _line_angle(a,b):return math.atan2(b[1]-a[1],b[0]-a[0])


def _project_on_segment(p,a,b):
    vx=b[0]-a[0];vy=b[1]-a[1];den=vx*vx+vy*vy
    if den<=1e-12:return a
    t=((p[0]-a[0])*vx+(p[1]-a[1])*vy)/den;t=max(0.0,min(1.0,t))
    return a[0]+t*vx,a[1]+t*vy


def _nearest_wall(p,walls):
    best=None
    for w in walls:
        a=tuple(w.get("start") or ());b=tuple(w.get("end") or ())
        if len(a)!=2 or len(b)!=2:continue
        q=_project_on_segment(p,a,b);d=math.dist(p,q)
        if best is None or d<best[0]:best=(d,q,_line_angle(a,b),a,b)
    return best


def _ensure_ac_blocks(doc):
    if "ENGI_AC_INDOOR" not in doc.blocks:
        b=doc.blocks.new("ENGI_AC_INDOOR");b.add_lwpolyline([(-.60,-.12),(.60,-.12),(.60,.12),(-.60,.12)],close=True);b.add_line((-.45,0),(.45,0));b.add_line((-.45,-.06),(.45,-.06))
    if "ENGI_AC_OUTDOOR" not in doc.blocks:
        b=doc.blocks.new("ENGI_AC_OUTDOOR");b.add_lwpolyline([(-.45,-.40),(.45,-.40),(.45,.40),(-.45,.40)],close=True);b.add_circle((0,0),.24);b.add_line((-.17,-.17),(.17,.17));b.add_line((-.17,.17),(.17,-.17))


def _add_arrow(msp,start,end,layer):
    msp.add_line(start,end,dxfattribs={"layer":layer});ang=math.atan2(end[1]-start[1],end[0]-start[0]);s=.16
    for off in (2.55,-2.55):
        a=ang+off;msp.add_line(end,(end[0]+s*math.cos(a),end[1]+s*math.sin(a)),dxfattribs={"layer":layer})


def _draw_titleblock(doc,msp,board,project_name="EngiTools Project",status="Authority Coordination"):
    for name,color,lw in (("ENGITOOLS-SHEET-GRID",7,18),("ENGITOOLS-SHEET-TEXT",7,15),("ENGITOOLS-SHEET-LOGO",3,20),("ENGITOOLS-SHEET-NORTH",7,18),("ENGITOOLS-SHEET-SUBTITLE",7,13)):_ensure_layer(doc,name,color,lw)
    x1,y1,x2,y2=board.bounds;ox1,oy1,ox2,oy2=x1+OUTER_MARGIN,y1+.40,x2-OUTER_MARGIN,y2-OUTER_MARGIN
    msp.add_lwpolyline([(ox1,oy1),(ox2,oy1),(ox2,oy2),(ox1,oy2)],close=True,dxfattribs={"layer":"ENGITOOLS-SHEET-GRID"})
    sep=board.title_area[3];msp.add_line((ox1,sep),(ox2,sep),dxfattribs={"layer":"ENGITOOLS-SHEET-GRID"})
    left=2.95;right=3.00;xL=ox1+left;xR=ox2-right;cw=xR-xL
    msp.add_line((xL,oy1),(xL,sep),dxfattribs={"layer":"ENGITOOLS-SHEET-GRID"});msp.add_line((xR,oy1),(xR,sep),dxfattribs={"layer":"ENGITOOLS-SHEET-GRID"});msp.add_line((xL,oy1+.86),(xR,oy1+.86),dxfattribs={"layer":"ENGITOOLS-SHEET-GRID"});msp.add_line((xL,oy1+2.34),(xR,oy1+2.34),dxfattribs={"layer":"ENGITOOLS-SHEET-GRID"})
    ccell=cw/4
    for i in range(1,4):msp.add_line((xL+i*ccell,oy1),(xL+i*ccell,oy1+.86),dxfattribs={"layer":"ENGITOOLS-SHEET-GRID"})
    msp.add_line((xR,oy1+1.55),(ox2,oy1+1.55),dxfattribs={"layer":"ENGITOOLS-SHEET-GRID"});msp.add_line((xR,oy1+.78),(ox2,oy1+.78),dxfattribs={"layer":"ENGITOOLS-SHEET-GRID"});msp.add_line((xR+1.45,oy1),(xR+1.45,oy1+1.55),dxfattribs={"layer":"ENGITOOLS-SHEET-GRID"})
    cx,cy=ox1+1.0,oy1+1.24;pts=[]
    for ang in (30,90,150,210,270,330):a=math.radians(ang);pts.append((cx+.42*math.cos(a),cy+.42*math.sin(a)))
    msp.add_lwpolyline(pts,close=True,dxfattribs={"layer":"ENGITOOLS-SHEET-LOGO"});msp.add_line((cx-.18,cy+.18),(cx-.18,cy-.18),dxfattribs={"layer":"ENGITOOLS-SHEET-LOGO"})
    for yy,length in ((cy+.18,.28),(cy,.23),(cy-.18,.28)):msp.add_line((cx-.18,yy),(cx-.18+length,yy),dxfattribs={"layer":"ENGITOOLS-SHEET-LOGO"})
    def mt(txt,x,y,w,h):e=msp.add_mtext(txt,dxfattribs={"layer":"ENGITOOLS-SHEET-TEXT","char_height":h});e.dxf.insert=(x,y);e.dxf.width=w;return e
    mt("EngiTools",ox1+.30,oy1+.36,2.2,.12);mt("سایت مهندسی",ox1+.72,oy1+.12,1.5,.07);mt("Project Name / نام پروژه",xL+.13,oy1+2.61,cw-.25,.065);mt(project_name,xL+.13,oy1+2.41,cw-.25,.10);mt("Drawing Title / عنوان نقشه",xL+.13,oy1+1.97,cw-.25,.07)
    h=.11 if len(board.title)<=34 else .10 if len(board.title)<=50 else .09;mt(board.title,xL+.13,oy1+1.18,cw-.25,h)
    for i,(lab,val) in enumerate((("Discipline / رشته","Mechanical"),("Status / وضعیت",status),("Designed By / طراحی","EngiTools"),("Checked / کنترل","—"))):xx=xL+i*ccell+.09;mt(lab,xx,oy1+.50,ccell-.12,.055);mt(val,xx,oy1+.16,ccell-.12,.075)
    mt("Sheet No. / شماره نقشه",xR+.10,oy1+2.60,right-.18,.065);mt(board.code,xR+.30,oy1+1.82,right-.40,.18);scale="1:100" if board.family in PLAN_FAMILIES else "NTS";mt("Scale / مقیاس",xR+.10,oy1+1.10,1.18,.06);mt(scale,xR+1.57,oy1+1.08,1.0,.075);mt("Date / تاریخ",xR+.10,oy1+.72,1.18,.06);mt("—",xR+1.57,oy1+.70,1.0,.075);mt("Revision / بازنگری",xR+.10,oy1+.14,1.18,.06);mt("Rev 0",xR+1.57,oy1+.12,1.0,.075)
    if board.family in PLAN_FAMILIES:
        sx1,sy1,sx2,sy2=board.subtitle_area;e=msp.add_mtext(board.title,dxfattribs={"layer":"ENGITOOLS-SHEET-SUBTITLE","char_height":.10});e.dxf.insert=((sx1+sx2)/2-4,sy1+.36);e.dxf.width=8;e=msp.add_mtext("SC:1/100",dxfattribs={"layer":"ENGITOOLS-SHEET-SUBTITLE","char_height":.07});e.dxf.insert=((sx1+sx2)/2-1,sy1+.12);e.dxf.width=2


def _north_from_architecture(doc,plan):
    if not plan:return None
    b=plan.get("bounds");msp=doc.modelspace();n_texts=[]
    for e in msp:
        if e.dxftype()=="TEXT" and _norm(getattr(e.dxf,"text",""))=="n":
            p=_point(e)
            if p and _inside(p,b,3.0):n_texts.append((e,p))
    if not n_texts:return None
    e,n=min(n_texts,key=lambda x:abs(x[1][0]-b[2])+abs(x[1][1]-b[3]));nearby=[]
    for g in msp:
        if g is e:continue
        ex=_entity_ext(g)
        if not ex:continue
        c=_center(ex);w=ex.extmax.x-ex.extmin.x;h=ex.extmax.y-ex.extmin.y
        if math.dist(c,n)<=5.0 and w<=5.0 and h<=5.0 and g.dxftype() in {"LINE","LWPOLYLINE","POLYLINE","ARC","CIRCLE","SOLID"}:nearby.append(c)
    if len(nearby)<2:
        rot=float(getattr(e.dxf,"rotation",0) or 0);a=math.radians(rot+90);return {"vector":(math.cos(a),math.sin(a)),"angle_deg":math.degrees(a)%360,"confidence":.45,"source":"N_TEXT_ROTATION"}
    cx=sum(p[0] for p in nearby)/len(nearby);cy=sum(p[1] for p in nearby)/len(nearby);vx=n[0]-cx;vy=n[1]-cy;length=math.hypot(vx,vy)
    if length<1e-9:return None
    vx/=length;vy/=length;return {"vector":(vx,vy),"angle_deg":math.degrees(math.atan2(vy,vx))%360,"confidence":.82,"source":"ARCH_COMPASS_CLUSTER"}


def _draw_north(msp,board,north):
    if not north:return
    vx,vy=north["vector"];px,py=-vy,vx;x1,y1,x2,y2=board.bounds;cx=x2-1.55;cy=y2-2.05;layer="ENGITOOLS-SHEET-NORTH";tip=(cx+vx*.95,cy+vy*.95);l=(cx+vx*.67+px*.16,cy+vy*.67+py*.16);r=(cx+vx*.67-px*.16,cy+vy*.67-py*.16);base1=(cx+px*.20,cy+py*.20);base2=(cx-px*.20,cy-py*.20)
    msp.add_line((cx,cy),(cx+vx*.72,cy+vy*.72),dxfattribs={"layer":layer});msp.add_lwpolyline([tip,l,r],close=True,dxfattribs={"layer":layer});msp.add_line(base1,base2,dxfattribs={"layer":layer});t=msp.add_text("N",dxfattribs={"layer":layer,"height":.20,"rotation":north["angle_deg"]-90});t.dxf.insert=(cx+vx*1.12-px*.06,cy+vy*1.12-py*.06)


def _route_layer(system):
    return {"sanitary":("ENGITOOLS-M-SANITARY",1,60),"vent":("ENGITOOLS-M-VENT",3,30),"cold_water":("ENGITOOLS-M-COLD_WATER",5,30),"hot_water":("ENGITOOLS-M-HOT_WATER",1,30),"heating_flow":("ENGITOOLS-M-HEAT-FLOW",2,35),"heating_return":("ENGITOOLS-M-HEAT-RETURN",6,35),"gas":("ENGITOOLS-M-GAS",2,35),"refrigerant":("ENGITOOLS-M-HVAC-REFRIG",6,30),"condensate":("ENGITOOLS-M-HVAC-COND",4,25),"exhaust":("ENGITOOLS-M-EXHAUST",6,30)}.get(system,(f"ENGITOOLS-M-{system.upper()}",7,25))


def _draw_route(msp,doc,points,system):
    lname,color,lw=_route_layer(system);_ensure_layer(doc,lname,color,lw)
    if len(points)>=2:msp.add_lwpolyline(points,dxfattribs={"layer":lname,"lineweight":lw})


def _annotation_text_for_segment(seg):
    size=seg.get("size_mm");system=seg.get("system")
    if system=="sanitary":
        slope=seg.get("slope_percent");return f"DN{size} S={slope:g}%" if size and slope is not None else "SANITARY"
    return f"{str(system).upper()} DN{size}" if size else str(system).upper()


def _draw_plan_overlay(doc,msp,board,plan,pipeline):
    if not plan:return {"routes":0,"equipment":0}
    srcb=plan["bounds"];target=board.plan_area;pid=plan["plan_id"]
    system_by_family={"SANITARY_VENT":{"sanitary","vent"},"WATER":{"cold_water","hot_water"},"HEATING":{"heating_flow","heating_return"},"GAS":{"gas"},"SPLIT_AC":{"refrigerant","condensate"},"EXHAUST":{"exhaust"}}
    systems=system_by_family.get(board.family,set());routes=[r for r in (pipeline["routing"].get("routes") or []) if r.get("plan_id")==pid and r.get("system") in systems];hvac_routes=[r for r in (pipeline.get("hvac",{}).get("routes") or []) if r.get("plan_id")==pid and r.get("system") in systems];all_routes=routes+hvac_routes;size_by_route={s.get("route_id"):s for s in pipeline["sizing"].get("segments") or []}
    for r in all_routes:
        pts=[_map_point(tuple(p),srcb,target) for p in r.get("points") or []];_draw_route(msp,doc,pts,r.get("system"))
        if pts:
            mid=pts[len(pts)//2];seg=size_by_route.get(r.get("id")) or {};txt=_annotation_text_for_segment({**r,**seg});layer=_route_layer(r.get("system"))[0];t=msp.add_mtext(txt,dxfattribs={"layer":layer,"char_height":.06});t.dxf.insert=(mid[0]+.08,mid[1]+.08);t.dxf.width=3.5
    # Every active plumbing plan must show its local vertical connection even
    # when that floor has no branch endpoint.  Use the topology shaft proposed
    # for this exact plan and keep each system on its authoritative layer.
    route_systems={r.get("system") for r in all_routes}
    local_shaft=next((s for s in (pipeline.get("topology",{}).get("nodes") or []) if s.get("kind")=="shaft" and s.get("plan_id")==pid and s.get("point")),None)
    if local_shaft:
        p=_map_point(tuple(local_shaft["point"]),srcb,target)
        riser_tags={"sanitary":"S1","vent":"V1","cold_water":"CW1","hot_water":"HW1"}
        for offset,system in enumerate(sorted(systems & set(riser_tags))):
            if system in route_systems:
                continue
            layer,color,lw=_route_layer(system);_ensure_layer(doc,layer,color,lw)
            q=(p[0]+offset*.22,p[1]+offset*.16)
            msp.add_circle(q,.10,dxfattribs={"layer":layer,"lineweight":lw})
            msp.add_line((q[0]-.14,q[1]),(q[0]+.14,q[1]),dxfattribs={"layer":layer,"lineweight":lw})
            t=msp.add_mtext(f"{riser_tags[system]} {system.upper()} RISER\nLOCAL VERTICAL CONNECTION",dxfattribs={"layer":layer,"char_height":.055})
            t.dxf.insert=(q[0]+.16,q[1]+.16);t.dxf.width=2.8
    equipment=[e for e in (pipeline.get("hvac",{}).get("equipment") or []) if e.get("plan_id")==pid];walls=[w for w in pipeline["architecture"].get("walls") or [] if _inside(tuple(w.get("start") or (0,0)),srcb,.5) or _inside(tuple(w.get("end") or (0,0)),srcb,.5)];_ensure_ac_blocks(doc);_ensure_layer(doc,"ENGITOOLS-M-HVAC-EQUIP",3,30);_ensure_layer(doc,"ENGITOOLS-M-HVAC-AIRFLOW",1,25);_ensure_layer(doc,"ENGITOOLS-M-HVAC-CALLOUT",2,18);_ensure_layer(doc,"ENGITOOLS-M-RADIATOR",3,25);ac_units=[]
    for e in equipment:
        kind=e.get("kind");srcp=tuple(e.get("point") or ())
        if len(srcp)!=2:continue
        if board.family=="SPLIT_AC" and kind=="split_indoor":
            near=_nearest_wall(srcp,walls)
            if near:_,wallp,angle,_,_=near;p=_map_point(wallp,srcb,target);rot=math.degrees(angle)
            else:p=_map_point(srcp,srcb,target);rot=0
            msp.add_blockref("ENGI_AC_INDOOR",p,dxfattribs={"layer":"ENGITOOLS-M-HVAC-EQUIP","rotation":rot});a=math.radians(rot+90);end=(p[0]+.55*math.cos(a),p[1]+.55*math.sin(a));_add_arrow(msp,p,end,"ENGITOOLS-M-HVAC-AIRFLOW");tag=e["id"].replace("AC-I","AC");cap=e.get("capacity_btu_h");note=f"{tag} | WALL-MOUNTED SPLIT AC"+(f" | {cap} BTU/h PRELIM." if cap else "")+"\nCOOLING & HEATING | DRAIN DN25 S=1% MIN";t=msp.add_mtext(note,dxfattribs={"layer":"ENGITOOLS-M-HVAC-CALLOUT","char_height":.06});t.dxf.insert=(p[0]+.8,p[1]+.65);t.dxf.width=4.3;ac_units.append({"tag":tag,"odu_tag":tag.replace("AC","ODU"),"level":board.level,"sheet":board.code,"equipment_type":"WALL-MOUNTED SPLIT AC","mode":"COOLING & HEATING","capacity_status":"PRELIMINARY","refrigerant_size_source":"SELECTED MANUFACTURER TABLE","condensate_nominal_diameter_mm":25,"condensate_min_slope_percent":1.0,"block":True,"airflow":True,"callout":True,"refrigerant":True,"condensate":True,"odu_destination_note":True,"schedule_match":True})
        elif board.family=="HEATING" and kind=="radiator":
            p=_map_point(srcp,srcb,target);near=_nearest_wall(srcp,walls);rot=math.degrees(near[2]) if near else 0;L=.90;a=math.radians(rot);px,py=-math.sin(a),math.cos(a);c1=(p[0]-L/2*math.cos(a),p[1]-L/2*math.sin(a));c2=(p[0]+L/2*math.cos(a),p[1]+L/2*math.sin(a));msp.add_line(c1,c2,dxfattribs={"layer":"ENGITOOLS-M-RADIATOR"});msp.add_line((c1[0]+px*.10,c1[1]+py*.10),(c2[0]+px*.10,c2[1]+py*.10),dxfattribs={"layer":"ENGITOOLS-M-RADIATOR"});t=msp.add_mtext(f"{e['id']} | LOAD≈{e.get('capacity_kw',0):.1f} kW PRELIM.",dxfattribs={"layer":"ENGITOOLS-M-RADIATOR","char_height":.055});t.dxf.insert=(p[0]+.25,p[1]+.25);t.dxf.width=3.4
    return {"routes":len(all_routes),"equipment":len(equipment),"split_contract":validate_split_representation(ac_units) if ac_units else None}


def _draw_detail_sheet(doc,msp,board,index):
    _ensure_layer(doc,"ENGITOOLS-M-DETAIL",2,18);x1,y1,x2,y2=board.plan_area;titles=[("D-PL-01","SANITARY CLEANOUT / FLOOR DRAIN","Provide accessible cleanout; coordinate waterproofing."),("D-PL-02","VENT TERMINATION ABOVE ROOF","Terminate above roof; maintain separation from openings/intakes."),("D-HV-01","WALL-MOUNTED SPLIT AC","Indoor unit on wall; refrigerant pair + DN25 condensate."),("D-HT-01","RADIATOR CONNECTION","TRV on flow, lockshield on return; accessible air vent."),("D-GS-01","GAS APPLIANCE CONNECTION","Isolation valve accessible; final code/utility verification required."),("D-WS-01","WATER SERVICE / PUMP","Meter → storage → pump → check valve → distribution header.")];start=(index-1)*2;chosen=titles[start:start+2] or titles[:2]
    for i,(tag,title,note) in enumerate(chosen):
        top=y2-1.0-i*8.7;msp.add_lwpolyline([(x1+.8,top),(x2-.8,top),(x2-.8,top-7.3),(x1+.8,top-7.3)],close=True,dxfattribs={"layer":"ENGITOOLS-M-DETAIL"});t=msp.add_mtext(f"{tag}  {title}",dxfattribs={"layer":"ENGITOOLS-M-DETAIL","char_height":.12});t.dxf.insert=(x1+1.1,top-.5);t.dxf.width=15;t=msp.add_mtext(note,dxfattribs={"layer":"ENGITOOLS-M-DETAIL","char_height":.07});t.dxf.insert=(x1+1.1,top-1.4);t.dxf.width=15;y=top-4.0;msp.add_line((x1+2,y),(x2-2,y),dxfattribs={"layer":"ENGITOOLS-M-DETAIL"});msp.add_circle(((x1+x2)/2,y),.35,dxfattribs={"layer":"ENGITOOLS-M-DETAIL"})


def _draw_riser(doc,msp,board,authority):
    _ensure_layer(doc,"ENGITOOLS-M-RISER",7,20);x1,y1,x2,y2=board.plan_area;levels=list(authority["project"].get("levels") or {})
    if not levels:return
    y_positions={lvl:y1+2.0+i*((y2-y1-4)/max(len(levels),1)) for i,lvl in enumerate(levels)}
    for lvl,y in y_positions.items():msp.add_line((x1+.7,y),(x2-.7,y),dxfattribs={"layer":"ENGITOOLS-M-RISER"});t=msp.add_mtext(lvl,dxfattribs={"layer":"ENGITOOLS-M-RISER","char_height":.07});t.dxf.insert=(x1+.8,y+.1);t.dxf.width=2
    systems=[("S1","SANITARY",110),("V1","VENT",63),("CW1","COLD WATER",32),("HW1","HOT WATER",25),("HF1","HEATING FLOW",25),("HR1","HEATING RETURN",25)]
    if "gas" in authority["requirements"].get("project_systems",[]):systems.append(("G1","GAS",25))
    xs=[x1+3.2+i*2.15 for i in range(len(systems))]
    for (tag,name,dn),x in zip(systems,xs):
        msp.add_line((x,min(y_positions.values())),(x,max(y_positions.values())+1.2),dxfattribs={"layer":"ENGITOOLS-M-RISER"});t=msp.add_mtext(f"{tag}\n{name}\nDN{dn}",dxfattribs={"layer":"ENGITOOLS-M-RISER","char_height":.055});t.dxf.insert=(x-.4,max(y_positions.values())+1.4);t.dxf.width=.9
        for lvl,y in y_positions.items():
            if tag=="G1" and "gas" not in authority["requirements"]["by_level"].get(lvl,[]):continue
            msp.add_line((x,y+.35),(x+(-1 if int(abs(y)*10)%2 else 1)*.8,y+.35),dxfattribs={"layer":"ENGITOOLS-M-RISER"})


def _numeric(v):
    if v is None:return None
    try:return float(re.search(r"-?\d+(?:\.\d+)?",str(v).replace("bar","").replace("بار","")).group())
    except Exception:return None


def _draw_calc(doc,msp,board,pipeline,authority):
    _ensure_layer(doc,"ENGITOOLS-M-CALC",7,18);x1,y1,x2,y2=board.plan_area;main=[s for s in pipeline["sizing"].get("segments") or [] if s.get("system")=="cold_water"];q=.12*math.sqrt(max(len(main),1)*3);pressure=_numeric(authority["design_basis"]["basis"].get("water_inlet_pressure"));static=9.6 if len(authority["project"].get("levels") or {})>=3 else 6.4;residual=15.0;friction=max(4.0,.25*(static+residual));gross=static+residual+friction;avail=(pressure*10.197) if pressure is not None else None;final=max(0,gross-avail) if avail is not None else None
    lines=["WATER SERVICE / PUMP DUTY CALCULATION",f"Peak demand Q ≈ {q:.2f} L/s (preliminary demand proxy)",f"Static head ≈ {static:.1f} m",f"Residual pressure target ≈ {residual:.1f} m",f"Friction + fittings allowance ≈ {friction:.1f} m",f"Gross head ≈ {gross:.1f} m",f"Utility pressure head = {avail:.1f} m" if avail is not None else "Utility pressure = INPUT REQUIRED",f"Pump head ≈ {final:.1f} m" if final is not None else "Final pump duty = PENDING UTILITY PRESSURE"]
    for i,line in enumerate(lines):t=msp.add_mtext(line,dxfattribs={"layer":"ENGITOOLS-M-CALC","char_height":.10 if i==0 else .075});t.dxf.insert=(x1+.8,y2-1.0-i*1.25);t.dxf.width=x2-x1-1.6


def _draw_notes(doc,msp,board,authority):
    _ensure_layer(doc,"ENGITOOLS-M-NOTES",7,18);x1,y1,x2,y2=board.plan_area;notes=[("A — DESIGN BASIS",[f"Location: {authority['design_basis']['basis'].get('city') or 'INPUT REQUIRED'}",f"Cooling: {authority['design_basis']['basis'].get('cooling_system') or 'INPUT REQUIRED'}",f"Heating: {authority['design_basis']['basis'].get('heating_system') or 'INPUT REQUIRED'}"]),("B — PLUMBING / WATER",["Sanitary horizontal branches: slope shall be explicitly annotated.","Cleanouts shall remain permanently accessible.","Vent termination shall be coordinated above roof."]),("C — HVAC / HEATING",["Split indoor units shall be wall hosted and parallel to wall.","Condensate minimum DN25, minimum 1% fall unless project rule overrides.","Radiator valves and service clearances shall remain accessible."]),("D — GAS / SAFETY",["Gas sizing requires connected load, equivalent length and approved pressure basis.","Provide accessible appliance isolation valves."]),("E — DOCUMENT QA",["Architectural walls, doors, windows, shafts, grids and openings are preservation-critical.","No sheet cleanup may delete architecture based only on geometric region."])]
    colw=(x2-x1-1.8)/2
    for i,(title,items) in enumerate(notes):
        col=i%2;row=i//2;x=x1+.6+col*(colw+.6);top=y2-.8-row*6.6;msp.add_lwpolyline([(x,top),(x+colw,top),(x+colw,top-5.5),(x,top-5.5)],close=True,dxfattribs={"layer":"ENGITOOLS-M-NOTES"});t=msp.add_mtext(title,dxfattribs={"layer":"ENGITOOLS-M-NOTES","char_height":.085});t.dxf.insert=(x+.2,top-.35);t.dxf.width=colw-.4
        for j,item in enumerate(items):t=msp.add_mtext(item,dxfattribs={"layer":"ENGITOOLS-M-NOTES","char_height":.06});t.dxf.insert=(x+.2,top-1.2-j*1.05);t.dxf.width=colw-.4


def _draw_schedule(doc,msp,board,pipeline,authority):
    _ensure_layer(doc,"ENGITOOLS-M-SCHEDULE",7,18);x1,y1,x2,y2=board.plan_area;headers=["TAG","TYPE","LEVEL","CAPACITY / SIZE","STATUS"];cols=[x1+.5,x1+3.1,x1+8.0,x1+11.2,x1+15.6,x2-.5];top=y2-.8;rh=.72;msp.add_lwpolyline([(cols[0],top),(cols[-1],top),(cols[-1],top-rh),(cols[0],top-rh)],close=True,dxfattribs={"layer":"ENGITOOLS-M-SCHEDULE"})
    for x in cols[1:-1]:msp.add_line((x,top),(x,top-rh),dxfattribs={"layer":"ENGITOOLS-M-SCHEDULE"})
    for i,h in enumerate(headers):t=msp.add_mtext(h,dxfattribs={"layer":"ENGITOOLS-M-SCHEDULE","char_height":.06});t.dxf.insert=(cols[i]+.08,top-.28);t.dxf.width=cols[i+1]-cols[i]-.12
    rows=[]
    for e in pipeline.get("hvac",{}).get("equipment") or []:rows.append((e.get("id"),e.get("kind"),e.get("plan_id"),str(e.get("capacity_btu_h") or e.get("capacity_kw") or "PRELIM."),"PRELIMINARY"))
    for i,row in enumerate(rows[:24],1):
        y=top-rh*i;msp.add_lwpolyline([(cols[0],y),(cols[-1],y),(cols[-1],y-rh),(cols[0],y-rh)],close=True,dxfattribs={"layer":"ENGITOOLS-M-SCHEDULE"})
        for x in cols[1:-1]:msp.add_line((x,y),(x,y-rh),dxfattribs={"layer":"ENGITOOLS-M-SCHEDULE"})
        for j,val in enumerate(row):t=msp.add_mtext(str(val),dxfattribs={"layer":"ENGITOOLS-M-SCHEDULE","char_height":.055});t.dxf.insert=(cols[j]+.08,y-.26);t.dxf.width=cols[j+1]-cols[j]-.12


def compose_authority_dxf(src: Path, dst: Path, pipeline: dict, authority: dict, answers: dict) -> dict:
    doc=ezdxf.readfile(src)
    if doc.dxfversion < 'AC1015':
        doc.dxfversion = 'AC1015'
    msp=doc.modelspace();manifest_rows=_layout_manifest(authority);boards=_boards(manifest_rows);arch=pipeline["architecture"];src_msp=doc.modelspace();project_name=_answer(answers,"project_name","name",default="پروژه تأسیسات مکانیکی")
    existing_layouts=[l.name for l in doc.layouts]
    for row in manifest_rows:
        if row["code"] not in existing_layouts:
            try:doc.layouts.new(row["code"])
            except Exception:pass
    copy_failures=[];overlay_reports=[];detail_index=0;north_records={}
    for row in manifest_rows:
        b=boards[row["old_sheet"]];_draw_titleblock(doc,msp,b,project_name=project_name);plan=None
        if b.family in PLAN_FAMILIES:
            plan=_find_roof_plan(arch) if b.family=="ROOF" or b.level=="ROOF" else _find_plan_for_level(arch,b.level)
            if plan:
                entities=_entities_in_bounds(src_msp,plan["bounds"]);M,_,_=_fit_transform(plan["bounds"],b.plan_area);_,failed=_clone_entities(msp,entities,M);copy_failures.extend(failed);north=_north_from_architecture(doc,plan);north_records[b.code]=north;_draw_north(msp,b,north)
                if b.family!="ROOF":overlay_reports.append({"sheet":b.code,**_draw_plan_overlay(doc,msp,b,plan,pipeline)})
        elif b.family=="GENERAL_DETAIL":detail_index+=1;_draw_detail_sheet(doc,msp,b,detail_index)
        elif b.family=="PLUMBING_RISER":_draw_riser(doc,msp,b,authority)
        elif b.family=="WATER_SERVICE_CALC":_draw_calc(doc,msp,b,pipeline,authority)
        elif b.family=="GENERAL_NOTES":_draw_notes(doc,msp,b,authority)
        elif b.family=="EQUIPMENT_SCHEDULE":_draw_schedule(doc,msp,b,pipeline,authority)
        elif b.family=="COVER":_draw_notes(doc,msp,b,authority)
    ext=bbox.extents(msp,fast=True)
    if ext.has_data:
        doc.header["$EXTMIN"]=tuple(map(float,ext.extmin));doc.header["$EXTMAX"]=tuple(map(float,ext.extmax));doc.header["$TILEMODE"]=1
        try:vp=doc.viewports.get("*Active")[0];vp.dxf.center=((ext.extmin.x+ext.extmax.x)/2,(ext.extmin.y+ext.extmax.y)/2);vp.dxf.height=(ext.extmax.y-ext.extmin.y)*1.03
        except Exception:pass
    doc.saveas(dst)
    return {"manifest":manifest_rows,"boards":{k:vars(v) for k,v in boards.items()},"copy_failures":copy_failures,"overlay_reports":overlay_reports,"north":north_records}


def _overlap(ex,b):return not (ex.extmax.x < b[0] or ex.extmin.x > b[2] or ex.extmax.y < b[1] or ex.extmin.y > b[3])


def qa_authority_dxf(path: Path, compose_report: dict) -> dict:
    doc=ezdxf.readfile(path);msp=doc.modelspace();boards={k:Board(**v) for k,v in compose_report["boards"].items()};title_overlaps=defaultdict(list);sheet_content=defaultdict(int)
    for e in msp:
        layer=str(getattr(e.dxf,"layer",""))
        if layer.startswith("ENGITOOLS-SHEET-"):continue
        ex=_entity_ext(e)
        if not ex:continue
        for key,b in boards.items():
            if _overlap(ex,b.bounds):
                sheet_content[key]+=1
                if _overlap(ex,b.title_area):title_overlaps[key].append(str(getattr(e.dxf,"handle","")))
                break
    errors=[]
    if compose_report.get("copy_failures"):errors.append("architecture_copy_failures")
    if sum(len(v) for v in title_overlaps.values()):errors.append("drawing_titleblock_overlap")
    if any(sheet_content[k]==0 for k in boards):errors.append("blank_sheet")
    plan_boards=[b for b in boards.values() if b.family in PLAN_FAMILIES];missing_north=[b.code for b in plan_boards if not compose_report.get("north",{}).get(b.code)]
    return {"version":"mechanical-authority-dxf-qa-v15.0","status":"PASS" if not errors else "FAIL","errors":errors,"warnings":[f"north_input_required:{x}" for x in missing_north],"metrics":{"sheets":len(boards),"titleblock_overlap":sum(len(v) for v in title_overlaps.values()),"copy_failures":len(compose_report.get("copy_failures") or []),"blank_sheets":sum(1 for k in boards if sheet_content[k]==0),"north_from_architecture":len(plan_boards)-len(missing_north)}}


def design_mechanical_authority(src: Path, dst: Path, answers: dict | None=None, plan_analysis: dict | None=None) -> dict:
    answers=dict(answers or {});overrides=build_design_overrides(answers);pipeline=run_engineering_pipeline(src,design_basis=overrides,project_overrides=overrides);pipeline_qa=validate_pipeline(pipeline);acceptance=evaluate_engineering_acceptance(pipeline);authority=build_authority_model(pipeline,answers)
    if authority["authority_qa"]["status"]!="PASS":return {"status":"FAIL","stage":"authority_contract","pipeline_qa":pipeline_qa,"acceptance":acceptance,"authority":authority}
    compose=compose_authority_dxf(src,dst,pipeline,authority,answers);dxf_qa=qa_authority_dxf(dst,compose)
    return {"status":"PASS" if dxf_qa["status"]=="PASS" and pipeline_qa["status"]=="PASS" else "FAIL","version":"mechanical-authority-site-pipeline-v15.0","pipeline_qa":pipeline_qa,"engineering_acceptance":acceptance,"authority":authority,"composition":compose,"dxf_qa":dxf_qa}
