import base64
import io
import math
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import ezdxf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter
from ezdxf import bbox
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

app = FastAPI(title="EngiTools CAD Designer", version="0.3.0")

SYSTEMS = {
    "electrical": ["lighting","power","dedicated_loads","fire_alarm","elv","earthing_bonding","panels","single_line_diagram","electrical_risers","electrical_legend_notes"],
    "mechanical": ["cold_water","hot_water","sanitary","vent","gas","heating_supply","heating_return","cooling","condensate","exhaust_ventilation","mechanical_risers","mechanical_details_legend_notes"],
}
PREFIX = {"electrical":"E","mechanical":"M"}
OUTPUT_ROOT = Path(os.getenv("CAD_OUTPUT_DIR", "/data/cad-engine")); OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
ROOM_RULES = {
    "kitchen":["kitchen","آشپزخانه","اشپزخانه"], "bath":["bath","bathroom","حمام"], "toilet":["toilet","wc","w.c","سرویس","توالت"],
    "bedroom":["bed","bedroom","خواب","اتاق خواب"], "living":["living","lounge","پذیرایی","نشیمن","هال"], "parking":["parking","پارکینگ"],
    "office":["office","اداری","دفتر"], "shop":["shop","commercial","تجاری","فروشگاه","مغازه"],
    "corridor":["corridor","hall","راهرو","لابی"], "shaft":["shaft","duct","شفت","داکت"], "roof":["roof","بام"], "stair":["stair","staircase","پله","راه پله"],
}
STANDARD_BREAKERS_A=[6,10,13,16,20,25,32,40,50,63,80,100,125,160,200,250,315,400]
STANDARD_PIPE_MM=[16,20,25,32,40,50,63,75,90,110,125,160,200]
COPPER_RESISTIVITY=0.0175

class DesignRequest(BaseModel):
    project_id:str; discipline:str; architecture_dir:str|None=None; architecture_archive_b64:str|None=None
    answers:dict=Field(default_factory=dict); plan_analysis:dict=Field(default_factory=dict); output_scope:dict; revision:int=1; revision_instructions:str=""

@app.get("/health")
def health(): return {"ok":True,"service":"cad-designer","version":"0.3.0","mode":"rule-driven-with-calculation-assist"}

def safe_extract_b64(payload,target):
    raw=base64.b64decode(payload,validate=True); useful=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for info in zf.infolist():
            if info.is_dir(): continue
            p=Path(info.filename)
            if "__MACOSX" in p.parts or p.name.startswith(".") or p.name.startswith("._"): continue
            if p.suffix.lower()!=".dxf": raise ValueError(f"archive contains non-DXF file: {info.filename}")
            dest=(target/p.name).resolve()
            if not str(dest).startswith(str(target.resolve())): raise ValueError("unsafe ZIP member")
            with zf.open(info) as src, dest.open("wb") as dst: shutil.copyfileobj(src,dst)
            useful.append(dest)
    if not useful: raise ValueError("no DXF files found in archive")
    return useful

def source_files(req,temp_input):
    if req.architecture_archive_b64: return safe_extract_b64(req.architecture_archive_b64,temp_input)
    if req.architecture_dir:
        root=Path(req.architecture_dir).resolve()
        if not root.exists() or not root.is_dir(): raise ValueError("architecture_dir does not exist")
        files=[p for p in sorted(root.rglob("*.dxf")) if p.is_file() and "__MACOSX" not in p.parts and not p.name.startswith(".") and not p.name.startswith("._")]
        if not files: raise ValueError("no DXF files found in architecture_dir")
        return files
    raise ValueError("architecture_dir or architecture_archive_b64 is required")

def ensure_layer(doc,name):
    if name not in doc.layers: doc.layers.add(name=name)

def text_value(e):
    try:
        return (e.dxf.text if e.dxftype()=="TEXT" else e.plain_text()) or ""
    except Exception:return ""

def text_point(e):
    try: p=e.dxf.insert; return float(p.x),float(p.y)
    except Exception:return None

def classify_room(text):
    s=(text or "").strip().lower()
    for room,keys in ROOM_RULES.items():
        if any(k.lower() in s for k in keys): return room
    return None

def detect_room_labels(msp):
    labels=[]
    for e in msp:
        if e.dxftype() not in ("TEXT","MTEXT"): continue
        room=classify_room(text_value(e)); pt=text_point(e)
        if room and pt: labels.append({"room":room,"point":pt})
    out=[]
    for item in labels:
        if not any(item["room"]==x["room"] and math.dist(item["point"],x["point"])<80 for x in out): out.append(item)
    return out

def extents(msp):
    try:
        e=bbox.extents(msp,fast=True)
        if e.has_data:return e.extmin.x,e.extmin.y,e.extmax.x,e.extmax.y
    except Exception:pass
    return 0.,0.,10000.,10000.

def add_circle(msp,p,r,layer,tag=None,h=120):
    x,y=p;msp.add_circle((x,y),radius=r,dxfattribs={"layer":layer})
    if tag:msp.add_text(tag,dxfattribs={"layer":layer,"height":h}).set_placement((x+r*1.2,y+r*.2))

def add_cross(msp,p,s,layer,tag=None,h=120):
    x,y=p;msp.add_line((x-s,y),(x+s,y),dxfattribs={"layer":layer});msp.add_line((x,y-s),(x,y+s),dxfattribs={"layer":layer})
    if tag:msp.add_text(tag,dxfattribs={"layer":layer,"height":h}).set_placement((x+s*1.3,y+s*.3))

def add_box(msp,p,s,layer,tag=None,h=120):
    x,y=p;msp.add_lwpolyline([(x-s,y-s),(x+s,y-s),(x+s,y+s),(x-s,y+s),(x-s,y-s)],dxfattribs={"layer":layer})
    if tag:msp.add_text(tag,dxfattribs={"layer":layer,"height":h}).set_placement((x+s*1.3,y+s*.3))

def nearest(origin,candidates): return min(candidates,key=lambda p:math.dist(origin,p)) if candidates else None

def ans(a,*keys):
    for k in keys:
        if a.get(k) not in (None,""):return str(a[k])
    return ""

def first_num(t):
    m=re.search(r"[-+]?\d+(?:[\.,]\d+)?",str(t or ""));return float(m.group().replace(",",".")) if m else None

def near_unit(t,units):
    s=str(t or "").lower().replace(",",".");u="|".join(re.escape(x) for x in units);m=re.search(rf"([-+]?\d+(?:\.\d+)?)\s*(?:{u})",s)
    return float(m.group(1)) if m else None

def next_std(v,seq):
    for x in seq:
        if v<=x:return x
    return None

def electrical_calc(a):
    warnings=[];missing=[];supply=ans(a,"supply")
    phase=3 if any(k in supply.lower() for k in ["three","3ph","3-ph","سه فاز","سه‌فاز"]) else 1
    voltage=near_unit(supply,["v","volt","ولت"]) or first_num(ans(a,"supply_voltage","voltage")) or (400. if phase==3 else 230.)
    if not near_unit(supply,["v","volt","ولت"]) and not ans(a,"supply_voltage","voltage"):warnings.append(f"Nominal {voltage:.0f} V assumed because voltage was not explicit.")
    loads=" ".join([ans(a,"loads"),ans(a,"power"),ans(a,"elevator"),ans(a,"emergency")])
    load_kw=near_unit(loads,["kw","کیلووات","كيلووات"]) or first_num(ans(a,"design_load_kw","total_load_kw"))
    pf=first_num(ans(a,"power_factor","pf")) or .9
    if not ans(a,"power_factor","pf"):warnings.append("PF=0.90 used as preliminary assumption.")
    pf=max(.1,min(1.,pf)); length=near_unit(ans(a,"cable_length","loads"),["m","meter","متر"]) or first_num(ans(a,"cable_length_m")); drop=first_num(ans(a,"max_voltage_drop_pct","voltage_drop")) or 3.
    if not ans(a,"max_voltage_drop_pct","voltage_drop"):warnings.append("3% voltage-drop target used provisionally.")
    r={"phase":phase,"voltage_v":round(voltage,2),"power_factor":round(pf,3),"design_load_kw":load_kw,"design_current_a":None,"preliminary_breaker_candidate_a":None,"voltage_drop_min_copper_mm2":None,"cable_ampacity_check_required":True,"warnings":warnings,"missing_inputs":missing}
    if load_kw is None:missing.append("explicit total/design load in kW");return r
    I=load_kw*1000/(math.sqrt(3)*voltage*pf) if phase==3 else load_kw*1000/(voltage*pf);r["design_current_a"]=round(I,2);r["preliminary_breaker_candidate_a"]=next_std(I*1.25,STANDARD_BREAKERS_A)
    warnings.append("Breaker candidate uses generic 125% margin; final protective-device selection requires code/coordination checks.")
    if length is None:missing.append("cable length in metres for voltage-drop calculation")
    else:
        dv=voltage*drop/100.;area=(math.sqrt(3) if phase==3 else 2)*COPPER_RESISTIVITY*length*I/max(dv,.1);r["voltage_drop_min_copper_mm2"]=round(area,2)
        warnings.append("Conductor area is voltage-drop-only; ampacity, grouping, temperature, installation method and protection checks remain mandatory.")
    return r

def mechanical_calc(a):
    warnings=[];missing=[];water=" ".join([ans(a,"water"),ans(a,"plumbing")]);flow=near_unit(water,["l/s","lps","لیتر/ثانیه","ليتر/ثانيه"]) or first_num(ans(a,"design_water_flow_lps"));vel=first_num(ans(a,"target_water_velocity_mps","water_velocity")) or 1.5
    if not ans(a,"target_water_velocity_mps","water_velocity"):warnings.append("Water velocity 1.5 m/s used provisionally.")
    cool=" ".join([ans(a,"cooling"),ans(a,"hvac")]);ckw=near_unit(cool,["kw","کیلووات","كيلووات"]) or first_num(ans(a,"cooling_load_kw"));btuh=near_unit(cool,["btu/h","btuhr","btu"])
    if ckw is None and btuh is not None:ckw=btuh/3412.142
    heat=ans(a,"heating");hkw=near_unit(heat,["kw","کیلووات","كيلووات"]) or first_num(ans(a,"heating_load_kw"))
    r={"design_water_flow_lps":flow,"target_water_velocity_mps":round(vel,2),"preliminary_hydraulic_diameter_mm":None,"preliminary_nominal_pipe_candidate_mm":None,"cooling_load_kw":round(ckw,2) if ckw is not None else None,"cooling_load_btuh":round(ckw*3412.142) if ckw is not None else None,"cooling_tons_refrigeration":round(ckw/3.51685,2) if ckw is not None else None,"heating_load_kw":round(hkw,2) if hkw is not None else None,"sanitary_pipe_sizing_status":"requires fixture-unit/code inputs","gas_pipe_sizing_status":"requires appliance loads, gas properties and authority/code inputs","warnings":warnings,"missing_inputs":missing}
    if flow is None:missing.append("design water flow in L/s")
    else:
        d=math.sqrt(4*(flow/1000)/(math.pi*max(vel,.1)))*1000;r["preliminary_hydraulic_diameter_mm"]=round(d,1);r["preliminary_nominal_pipe_candidate_mm"]=next_std(d,STANDARD_PIPE_MM)
        warnings.append("Pipe candidate uses Q=vA only; pressure loss, material ID, available pressure, simultaneity and code checks remain mandatory.")
    if ckw is None:missing.append("explicit cooling load/capacity in kW or BTU/h")
    if hkw is None:missing.append("explicit heating load in kW")
    return r

def calc_for(d,a):
    c=electrical_calc(a) if d=="electrical" else mechanical_calc(a)
    return {"discipline":d,"status":"preliminary_calculation_assist","final_design":False,"professional_verification_required":True,**c}

def electrical_design(msp,rooms,systems,scale):
    st={"lighting":0,"power":0,"dedicated_loads":0,"fire_alarm":0,"elv":0,"panels":0};r=max(scale*.004,90.);h=max(scale*.0045,90.);shafts=[x["point"] for x in rooms if x["room"]=="shaft"];anchor=shafts[0] if shafts else None
    for it in rooms:
        room=it["room"];x,y=it["point"]
        if "lighting" in systems and room!="shaft":add_cross(msp,(x,y),r,"ENGITOOLS-E-LIGHTING","L",h);st["lighting"]+=1
        if "power" in systems and room in ("bedroom","living","kitchen","parking","corridor"):
            offs=[(-2.2*r,-1.7*r),(2.2*r,-1.7*r)] if room in ("bedroom","living","kitchen") else [(2*r,-1.5*r)]
            for dx,dy in offs:add_circle(msp,(x+dx,y+dy),r*.55,"ENGITOOLS-E-POWER","P",h*.85);st["power"]+=1
        if "dedicated_loads" in systems and room=="kitchen":
            for i,t in enumerate(("REF","WM","DW")):add_box(msp,(x+(i-1)*2.4*r,y+2.4*r),r*.65,"ENGITOOLS-E-DEDICATED_LOADS",t,h*.75);st["dedicated_loads"]+=1
        if "fire_alarm" in systems and room in ("bedroom","living","corridor","stair","parking"):add_circle(msp,(x,y+2.2*r),r*.65,"ENGITOOLS-E-FIRE_ALARM","SD",h*.8);st["fire_alarm"]+=1
        if "elv" in systems and room in ("living","bedroom"):add_box(msp,(x-2.3*r,y+2*r),r*.55,"ENGITOOLS-E-ELV","DATA",h*.7);st["elv"]+=1
    if rooms and "panels" in systems:
        p=anchor or rooms[0]["point"];add_box(msp,(p[0]+4*r,p[1]),r*.9,"ENGITOOLS-E-PANELS","DB",h);st["panels"]+=1
    if anchor and "lighting" in systems:
        for it in rooms:
            if it["room"]!="shaft":msp.add_line(it["point"],anchor,dxfattribs={"layer":"ENGITOOLS-E-LIGHTING"})
    return st

def mechanical_design(msp,rooms,systems,scale):
    st={"cold_water":0,"hot_water":0,"sanitary":0,"vent":0,"gas":0,"cooling":0,"condensate":0,"exhaust_ventilation":0};r=max(scale*.004,90.);h=max(scale*.0045,90.);shafts=[x["point"] for x in rooms if x["room"]=="shaft"];services=[]
    for it in rooms:
        room=it["room"];x,y=it["point"]
        if room in ("kitchen","bath","toilet"):
            services.append((x,y))
            if "cold_water" in systems:add_circle(msp,(x-1.7*r,y),r*.5,"ENGITOOLS-M-COLD_WATER","CW",h*.75);st["cold_water"]+=1
            if "hot_water" in systems and room in ("kitchen","bath"):add_circle(msp,(x,y),r*.5,"ENGITOOLS-M-HOT_WATER","HW",h*.75);st["hot_water"]+=1
            if "sanitary" in systems:add_circle(msp,(x+1.7*r,y),r*.55,"ENGITOOLS-M-SANITARY","S",h*.75);st["sanitary"]+=1
            if "vent" in systems and room in ("bath","toilet"):add_cross(msp,(x+1.7*r,y+1.8*r),r*.55,"ENGITOOLS-M-VENT","V",h*.75);st["vent"]+=1
            if "exhaust_ventilation" in systems and room in ("bath","toilet"):add_box(msp,(x-1.7*r,y+1.8*r),r*.55,"ENGITOOLS-M-EXHAUST_VENTILATION","EF",h*.75);st["exhaust_ventilation"]+=1
        if room=="kitchen" and "gas" in systems:add_box(msp,(x,y+2.1*r),r*.55,"ENGITOOLS-M-GAS","G",h*.8);st["gas"]+=1
        if room in ("bedroom","living") and "cooling" in systems:
            add_box(msp,(x,y+2*r),r*.8,"ENGITOOLS-M-COOLING","AC",h*.8);st["cooling"]+=1
            if "condensate" in systems:add_circle(msp,(x+1.8*r,y+2*r),r*.4,"ENGITOOLS-M-CONDENSATE","C",h*.7);st["condensate"]+=1
    if shafts:
        for p in services:
            sh=nearest(p,shafts)
            if "sanitary" in systems:msp.add_line(p,sh,dxfattribs={"layer":"ENGITOOLS-M-SANITARY"})
            if "cold_water" in systems:msp.add_line((p[0]-1.7*r,p[1]),sh,dxfattribs={"layer":"ENGITOOLS-M-COLD_WATER"})
        if "mechanical_risers" in systems:
            for p in shafts:add_box(msp,p,r*.9,"ENGITOOLS-M-MECHANICAL_RISERS","R",h)
    return st

def calc_lines(c):
    lines=["CALCULATION ASSIST - PRELIMINARY / NOT FOR CONSTRUCTION"]
    if c["discipline"]=="electrical":
        if c.get("design_load_kw") is not None:lines.append(f"LOAD={c['design_load_kw']:.2f} kW")
        if c.get("design_current_a") is not None:lines.append(f"CALC CURRENT={c['design_current_a']:.2f} A")
        if c.get("preliminary_breaker_candidate_a") is not None:lines.append(f"BREAKER CANDIDATE={c['preliminary_breaker_candidate_a']} A - VERIFY")
        if c.get("voltage_drop_min_copper_mm2") is not None:lines.append(f"V-DROP-ONLY Cu AREA>={c['voltage_drop_min_copper_mm2']:.2f} mm2 - AMPACITY CHECK REQUIRED")
    else:
        if c.get("design_water_flow_lps") is not None:lines.append(f"WATER FLOW={c['design_water_flow_lps']:.3f} L/s")
        if c.get("preliminary_hydraulic_diameter_mm") is not None:lines.append(f"HYDRAULIC D>={c['preliminary_hydraulic_diameter_mm']:.1f} mm @ {c['target_water_velocity_mps']:.2f} m/s")
        if c.get("preliminary_nominal_pipe_candidate_mm") is not None:lines.append(f"PIPE CANDIDATE={c['preliminary_nominal_pipe_candidate_mm']} mm - VERIFY")
        if c.get("cooling_load_kw") is not None:lines.append(f"COOLING={c['cooling_load_kw']:.2f} kW = {c['cooling_load_btuh']:.0f} BTU/h = {c['cooling_tons_refrigeration']:.2f} TR")
        if c.get("heating_load_kw") is not None:lines.append(f"HEATING={c['heating_load_kw']:.2f} kW")
    for x in c.get("missing_inputs",[])[:4]:lines.append(f"NEEDS INPUT: {x}")
    return lines

def design_dxf(src,dst,discipline,systems,revision,calc):
    doc=ezdxf.readfile(src);msp=doc.modelspace();prefix=PREFIX[discipline]
    for s in systems:ensure_layer(doc,f"ENGITOOLS-{prefix}-{s.upper()}")
    note=f"ENGITOOLS-{prefix}-NOTES";cl=f"ENGITOOLS-{prefix}-CALC";ensure_layer(doc,note);ensure_layer(doc,cl)
    minx,miny,maxx,maxy=extents(msp);w=max(maxx-minx,1000.);h=max(maxy-miny,1000.);scale=max(w,h);rooms=detect_room_labels(msp);stats=electrical_design(msp,rooms,systems,scale) if discipline=="electrical" else mechanical_design(msp,rooms,systems,scale)
    gap=max(w*.08,500.);x0,y0=maxx+gap,maxy;th=max(min(w,h)*.018,60.);yy=y0
    for line in [f"ENGITOOLS {discipline.upper()} RULE-DRIVEN DESIGN - REV {revision}","AUTOMATED PRELIMINARY DESIGN - PROFESSIONAL ENGINEERING REVIEW REQUIRED",f"DETECTED ROOM LABELS: {len(rooms)}"]:
        msp.add_text(line,dxfattribs={"layer":note,"height":th*.72}).set_placement((x0,yy));yy-=th*1.2
    for k,v in stats.items():
        if v:msp.add_text(f"{k}: {v}",dxfattribs={"layer":note,"height":th*.62}).set_placement((x0,yy));yy-=th
    yy-=th*.4
    for line in calc_lines(calc):msp.add_text(line,dxfattribs={"layer":cl,"height":th*.58}).set_placement((x0,yy));yy-=th*.95
    if not rooms:msp.add_text("WARNING: NO RECOGNIZED ROOM LABELS; ONLY LAYERS/NOTES/CALCULATION ASSIST WERE GENERATED",dxfattribs={"layer":note,"height":th*.58}).set_placement((x0,yy))
    doc.saveas(dst);return {"room_labels":len(rooms),"placements":stats,"calculation":calc}

def render_pdf(dxf_path,pdf_path,discipline):
    doc=ezdxf.readfile(dxf_path);msp=doc.modelspace();fig=plt.figure(figsize=(11.69,8.27));ax=fig.add_axes([.03,.06,.94,.88]);ax.set_aspect("equal",adjustable="datalim");ax.axis("off")
    try:ctx=RenderContext(doc);out=MatplotlibBackend(ax);Frontend(ctx,out).draw_layout(msp,finalize=True)
    except Exception:ax.text(.5,.5,"DXF preview rendering unavailable",ha="center",va="center",transform=ax.transAxes)
    fig.suptitle(f"EngiTools {discipline.title()} - PRELIMINARY DESIGN + CALCULATION ASSIST - ENGINEERING REVIEW REQUIRED",fontsize=10);fig.savefig(pdf_path,format="pdf",bbox_inches="tight");plt.close(fig)

def merge_pdfs(paths,out_path):
    w=PdfWriter()
    for p in paths:
        for page in PdfReader(str(p)).pages:w.add_page(page)
    with out_path.open("wb") as f:w.write(f)

def zip_outputs(paths,out_path):
    with zipfile.ZipFile(out_path,"w",zipfile.ZIP_DEFLATED) as z:
        for p in paths:z.write(p,arcname=p.name)

@app.post("/design")
def design(req:DesignRequest):
    discipline=req.discipline.strip().lower()
    if discipline not in SYSTEMS:raise HTTPException(400,"discipline must be mechanical or electrical")
    scope=req.output_scope or {}
    if scope.get("discipline")!=discipline:raise HTTPException(400,"output_scope discipline mismatch")
    if scope.get("only_this_discipline") is not True or scope.get("include_other_disciplines") is not False:raise HTTPException(400,"discipline isolation flags are required")
    requested=scope.get("systems") or [];allowed=SYSTEMS[discipline]
    if any(s not in allowed for s in requested):raise HTTPException(400,"output_scope contains unsupported or cross-discipline systems")
    systems=requested or allowed;calc=calc_for(discipline,req.answers or {})
    calc["_design_inputs"] = dict(req.answers or {})
    calc["_plan_analysis"] = dict(req.plan_analysis or {})
    if discipline == "mechanical":
        drawing_set = (req.plan_analysis or {}).get("drawing_set") or {}
        manifest = drawing_set.get("approved_manifest")
        if not drawing_set.get("approved") or not manifest:
            raise HTTPException(409, "Approved mechanical drawing manifest is required.")
        sheets = manifest.get("sheets") or []
        expected = int(manifest.get("total_sheets") or -1)
        codes = [str(x.get("code") or "") for x in sheets]
        if expected != len(sheets) or expected < 1 or any(not x for x in codes) or len(codes) != len(set(codes)):
            raise HTTPException(409, "Approved mechanical drawing manifest is invalid.")
        calc["_approved_drawing_manifest"] = manifest
    project_out=OUTPUT_ROOT/str(req.project_id)/f"R{req.revision:03d}"/discipline;shutil.rmtree(project_out,ignore_errors=True);project_out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="engitools-cad-") as td:
        ti=Path(td)/"input";ti.mkdir()
        try:sources=source_files(req,ti)
        except Exception as exc:raise HTTPException(400,str(exc))
        generated=[];pages=[];reports=[]
        for idx,src in enumerate(sources,start=1):
            stem="".join(c if c.isalnum() or c in "-_" else "_" for c in src.stem)[:80] or f"plan_{idx}";dxf=project_out/f"{idx:02d}_{stem}_{discipline}.dxf";reports.append({"source":src.name,**design_dxf(src,dxf,discipline,systems,req.revision,calc)});generated.append(dxf);page=project_out/f"{idx:02d}_{discipline}.pdf";render_pdf(dxf,page,discipline);pages.append(page)
        merged=project_out/f"EngiTools_{req.project_id}_{discipline}_R{req.revision}.pdf";merge_pdfs(pages,merged);package=project_out/f"EngiTools_{req.project_id}_{discipline}_R{req.revision}_DXF.zip";zip_outputs(generated,package)
        return {"ok":True,"project_id":req.project_id,"discipline":discipline,"engine_version":"0.3.0","mode":"rule-driven-with-calculation-assist","preliminary":True,"requires_professional_review":True,"systems":systems,"calculation_report":calc,"design_reports":reports,"generated_files":[p.name for p in generated],"pdf_path":str(merged),"zip_path":str(package),"pdf_base64":base64.b64encode(merged.read_bytes()).decode("ascii"),"zip_base64":base64.b64encode(package.read_bytes()).decode("ascii")}
