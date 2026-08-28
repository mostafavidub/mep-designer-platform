"""Site production orchestrator for the complete mechanical authority flow v15.

This module wraps the core authority composer with the engineering enrichments
developed during real-project acceptance:
- roof/rainwater
- water service / tank / pump topology
- table-based gas sizing
- exhaust CFM
- split outdoor-unit roof coordination
- exact-file semantic and sheet-content QA

It is intentionally conservative: missing utility/manufacturer/envelope inputs
remain INPUT_REQUIRED/PRELIMINARY and are never silently promoted to FINAL.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import math
from pathlib import Path

import ezdxf
from ezdxf import bbox

from .engineering_runner_v13 import run_engineering_pipeline, validate_pipeline
from .acceptance_v13 import evaluate_engineering_acceptance
from .mechanical_authority_v15 import (
    build_design_overrides,
    build_authority_model,
    compose_authority_dxf,
    qa_authority_dxf,
    _ensure_layer,
    _numeric,
    _find_roof_plan,
    _find_plan_for_level,
    _map_point,
    _answer,
    GAS_TABLE_P22,
    GAS_SIZES_IN,
    GAS_DN,
)


def _board_by_family(report, family, level=None):
    manifest=(report.get("manifest") or [])
    boards=report.get("boards") or {}
    for row in manifest:
        if row.get("family") != family:
            continue
        if level is not None and row.get("level") != level:
            continue
        b=boards.get(row.get("old_sheet"))
        if b:
            return row,b
    return None,None


def _boards_by_family(report, family):
    boards=report.get("boards") or {}
    out=[]
    for row in report.get("manifest") or []:
        if row.get("family")==family and boards.get(row.get("old_sheet")):
            out.append((row,boards[row["old_sheet"]]))
    return out


def _mtext(msp, layer, text, x, y, width, height=.065):
    t=msp.add_mtext(text,dxfattribs={"layer":layer,"char_height":height})
    t.dxf.insert=(x,y)
    t.dxf.width=width
    return t


def _rect(msp, layer, x1,y1,x2,y2):
    return msp.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2)],close=True,dxfattribs={"layer":layer})


def _gas_select(demand_m3h, eq_len_m):
    row=next((L for L in sorted(GAS_TABLE_P22) if L>=eq_len_m),max(GAS_TABLE_P22))
    for size,cap in zip(GAS_SIZES_IN,GAS_TABLE_P22[row]):
        if cap>=demand_m3h:
            return {"table_length_m":row,"size_in":size,"dn_mm":GAS_DN[size],"capacity_m3h":cap}
    return None


def _wall_bbox_for_plan(pipeline, plan):
    b=plan.get("bounds")
    xs=[];ys=[]
    for w in pipeline["architecture"].get("walls") or []:
        for key in ("start","end"):
            p=tuple(w.get(key) or ())
            if len(p)==2 and b and b[0]-.5<=p[0]<=b[2]+.5 and b[1]-.5<=p[1]<=b[3]+.5:
                xs.append(p[0]);ys.append(p[1])
    if len(xs)<4:
        return None
    return min(xs),min(ys),max(xs),max(ys)


def enrich_roof_rainwater(doc, msp, pipeline, authority, compose, answers):
    row,b=_board_by_family(compose,"ROOF","ROOF")
    if not b:
        return {"status":"SKIPPED","reason":"NO_ROOF_SHEET"}
    layer="ENGITOOLS-M-RAINWATER-CALC"
    _ensure_layer(doc,layer,6,20)
    plan=_find_roof_plan(pipeline["architecture"])
    if not plan:
        return {"status":"INPUT_REQUIRED","reason":"NO_ROOF_ARCHITECTURE"}
    source_box=_wall_bbox_for_plan(pipeline,plan)
    if not source_box:
        return {"status":"INPUT_REQUIRED","reason":"NO_ROOF_ENVELOPE"}
    x1,y1,x2,y2=source_box
    area=max(0,(x2-x1)*(y2-y1))
    intensity=_numeric(_answer(answers,"rainfall_intensity"))
    runoff=1.0
    q_total=(intensity*area*runoff/3600.0) if intensity is not None else None

    board_plan=tuple(b["plan_area"])
    mapped=[_map_point(p,plan["bounds"],board_plan) for p in [(x1,y1),(x2,y1),(x2,y2),(x1,y2)]]
    drains=[]
    for i,p in enumerate(mapped,1):
        msp.add_circle(p,.13,dxfattribs={"layer":layer})
        _mtext(msp,layer,f"RD-{i:02d}",p[0]+.16,p[1]+.10,1.2,.055)
        drains.append(p)
    px1,py1,px2,py2=board_plan
    lines=[
        "ROOF RAINWATER CALCULATION",
        f"Catchment ≈ {area:.1f} m² (roof wall-envelope bbox)",
        f"Rainfall intensity = {intensity:.1f} mm/h" if intensity is not None else "Rainfall intensity = INPUT REQUIRED",
        f"Total Q ≈ {q_total:.2f} L/s" if q_total is not None else "Total Q = PENDING RAINFALL INPUT",
        f"Primary roof drains = {len(drains)}",
        "Provide emergency overflow / secondary drainage.",
    ]
    bx=px2-6.9;top=py2-.9
    _rect(msp,layer,bx,top-5.2,px2-.3,top)
    for i,line in enumerate(lines):
        _mtext(msp,layer,line,bx+.25,top-.40-i*.72,6.1,.075 if i==0 else .058)
    return {
        "status":"PASS" if intensity is not None else "INPUT_REQUIRED",
        "catchment_m2":round(area,2),"rainfall_mm_h":intensity,"flow_lps":round(q_total,3) if q_total is not None else None,
        "drains":len(drains),"provenance":"roof-wall-envelope-bbox + project rainfall input",
    }


def _water_fixture_proxy(pipeline):
    fixture_weights={"wc":3.0,"basin":1.0,"sink":1.5,"shower":2.0,"floor_drain":1.0}
    total=0.0
    for d in pipeline["recognition"].get("detections") or []:
        total += fixture_weights.get(d.get("type"),0.0)
    if total<=0:
        total=max(1.0,len(pipeline["architecture"].get("rooms") or [])*.6)
    q=0.12*math.sqrt(total)
    return total,q


def enrich_water_service(doc,msp,pipeline,authority,compose,answers):
    row,b=_board_by_family(compose,"WATER","SERVICE")
    if not b:
        return {"status":"SKIPPED","reason":"NO_WATER_SERVICE_SHEET"}
    layer="ENGITOOLS-M-WATER-SERVICE"
    _ensure_layer(doc,layer,5,30)
    x1,y1,x2,y2=tuple(b["plan_area"])
    fu,q=_water_fixture_proxy(pipeline)
    pressure_bar=_numeric(_answer(answers,"water_pressure","water"))
    service_head=pressure_bar*10.197 if pressure_bar is not None else None
    nlevels=len(authority["project"].get("levels") or {})
    static=max(3.2,3.2*nlevels)
    residual=15.0
    friction=max(4.0,.25*(static+residual))
    gross=static+residual+friction
    pump_head=max(0,gross-service_head) if service_head is not None else None
    autonomy_min=15
    storage_l=q*60*autonomy_min
    selected_l=max(500,int(math.ceil(storage_l/500.0)*500))

    y=(y1+y2)/2+.6
    xs=[x1+1.1,x1+4.0,x1+7.2,x1+10.6,x1+13.7,x1+16.6]
    labels=[
        ("CITY","CITY WATER"),("WM","WATER METER"),("T-01",f"{selected_l} L TANK"),
        ("P-01",f"PUMP\nQ≈{q:.2f} L/s\nH≈{pump_head:.1f} m" if pump_head is not None else f"PUMP\nQ≈{q:.2f} L/s\nH=PENDING"),
        ("CV-01","CHECK VALVE"),("CW1","DISTRIBUTION\nRISER"),
    ]
    for a,bb in zip(xs,xs[1:]):
        msp.add_line((a,y),(bb,y),dxfattribs={"layer":layer})
    msp.add_circle((xs[0],y),.18,dxfattribs={"layer":layer})
    msp.add_circle((xs[1],y),.38,dxfattribs={"layer":layer})
    _rect(msp,layer,xs[2]-.65,y-.75,xs[2]+.65,y+.75)
    msp.add_circle((xs[3],y),.48,dxfattribs={"layer":layer})
    msp.add_line((xs[3]-.30,y-.30),(xs[3]+.30,y+.30),dxfattribs={"layer":layer})
    msp.add_lwpolyline([(xs[4]-.22,y-.22),(xs[4],y),(xs[4]-.22,y+.22)],dxfattribs={"layer":layer})
    msp.add_lwpolyline([(xs[4]+.22,y-.22),(xs[4],y),(xs[4]+.22,y+.22)],dxfattribs={"layer":layer})
    msp.add_line((xs[5],y-1.2),(xs[5],y+2.1),dxfattribs={"layer":layer})
    for x,(tag,text) in zip(xs,labels):
        _mtext(msp,layer,f"{tag}\n{text}",x-.55,y+1.0,1.5,.055)

    lines=[
        "WATER SERVICE / BOOSTER BASIS",
        f"Fixture-unit proxy ≈ {fu:.1f}",
        f"Peak flow Q ≈ {q:.2f} L/s PRELIM.",
        f"Storage ≈ {storage_l:.0f} L → selected {selected_l} L PRELIM.",
        f"Utility pressure = {pressure_bar:.2f} bar" if pressure_bar is not None else "Utility pressure = INPUT REQUIRED",
        f"Gross head ≈ {gross:.1f} m",
        f"Pump head ≈ {pump_head:.1f} m" if pump_head is not None else "Final pump head = PENDING UTILITY PRESSURE",
    ]
    for i,line in enumerate(lines):
        _mtext(msp,layer,line,x1+.7,y2-.8-i*.65,8.2,.07 if i==0 else .055)
    return {
        "status":"PASS" if pressure_bar is not None else "INPUT_REQUIRED",
        "fixture_unit_proxy":round(fu,2),"q_lps":round(q,3),"tank_l":selected_l,
        "utility_pressure_bar":pressure_bar,"pump_head_m":round(pump_head,2) if pump_head is not None else None,
        "provenance":"fixture detection proxy + utility pressure input",
    }


def _gas_level_load_kw(pipeline, level):
    plan=_find_plan_for_level(pipeline["architecture"],level)
    if not plan:
        return 0.0
    pid=plan["plan_id"]
    rooms=[r for r in pipeline["architecture"].get("rooms") or [] if r.get("plan_id")==pid]
    hvac=[e for e in pipeline.get("hvac",{}).get("equipment") or [] if e.get("plan_id")==pid]
    pkg=sum(float(e.get("capacity_kw") or 0) for e in hvac if e.get("kind")=="package")
    cooking=10.0 if any(r.get("type")=="kitchen" for r in rooms) else 0.0
    return pkg+cooking


def enrich_gas(doc,msp,pipeline,authority,compose,answers):
    layer="ENGITOOLS-M-GAS-TABLE"
    _ensure_layer(doc,layer,2,18)
    records=[]
    for row,b in _boards_by_family(compose,"GAS"):
        level=row.get("level")
        plan=_find_plan_for_level(pipeline["architecture"],level)
        if not plan:
            continue
        pid=plan["plan_id"]
        routes=[r for r in pipeline["routing"].get("routes") or [] if r.get("plan_id")==pid and r.get("system")=="gas"]
        load_kw=_gas_level_load_kw(pipeline,level)
        demand=load_kw/9.5 if load_kw>0 else None
        x1,y1,x2,y2=tuple(b["plan_area"])
        top=y2-.8
        _mtext(msp,layer,"GAS PIPE SIZING — TABLE P.22",x1+.7,top,10,.08)
        if not routes:
            _mtext(msp,layer,"No gas route generated from project evidence.",x1+.7,top-.8,10,.06)
            records.append({"sheet":row["code"],"status":"INPUT_REQUIRED","reason":"NO_GAS_ROUTE"})
            continue
        for i,r in enumerate(routes,1):
            length=float(r.get("length") or 0)
            eq_len=max(.1,length*1.25)
            sel=_gas_select(demand,eq_len) if demand is not None else None
            if sel:
                text=f"G{i} | Q≈{demand:.2f} m³/h | Leq≈{eq_len:.1f} m → {sel['size_in']} / DN{sel['dn_mm']} (cap {sel['capacity_m3h']:.1f})"
                status="PRELIMINARY_TABLE_SIZED"
            else:
                text=f"G{i} | connected gas demand = INPUT REQUIRED | Leq≈{eq_len:.1f} m"
                status="INPUT_REQUIRED"
            _mtext(msp,layer,text,x1+.7,top-.75-i*.68,13.5,.055)
            records.append({"sheet":row["code"],"route":r.get("id"),"status":status,"demand_m3h":demand,"eq_len_m":eq_len,**(sel or {})})
        _mtext(msp,layer,"Basis: natural-gas steel pipe capacity table P.22; final utility/code verification required.",x1+.7,top-4.5,14,.052)
    return {"status":"PASS" if records else "SKIPPED","records":records}


EXHAUST_CFM={"bathroom":80,"toilet":60,"kitchen":200,"parking":250}


def enrich_exhaust(doc,msp,pipeline,compose):
    layer="ENGITOOLS-M-EXHAUST-CFM"
    _ensure_layer(doc,layer,6,20)
    fans=[]
    for row,b in _boards_by_family(compose,"EXHAUST"):
        level=row.get("level")
        plan=_find_plan_for_level(pipeline["architecture"],level)
        if not plan:continue
        pid=plan["plan_id"]
        rooms=[r for r in pipeline["architecture"].get("rooms") or [] if r.get("plan_id")==pid and r.get("type") in EXHAUST_CFM]
        for room in rooms:
            p=_map_point(tuple(room.get("label_point")),plan["bounds"],tuple(b["plan_area"]))
            cfm=EXHAUST_CFM[room["type"]]
            msp.add_circle(p,.10,dxfattribs={"layer":layer})
            tag=f"EF-{len(fans)+1:02d}"
            _mtext(msp,layer,f"{tag} | {room['type'].upper()} | {cfm} CFM ({cfm*.471947:.0f} L/s)\nDISCHARGE TO OUTDOORS + BACKDRAFT DAMPER",p[0]+.14,p[1]+.14,4.0,.052)
            fans.append({"tag":tag,"sheet":row["code"],"room_id":room.get("id"),"room_type":room["type"],"cfm":cfm,"lps":round(cfm*.471947,1),"status":"PRELIMINARY_USE_BASIS"})
    return {"status":"PASS" if fans else "INPUT_REQUIRED","fans":fans}


def enrich_split_roof(doc,msp,pipeline,compose):
    row,b=_board_by_family(compose,"SPLIT_AC","ROOF")
    if not b:
        return {"status":"SKIPPED"}
    layer="ENGITOOLS-M-HVAC-ODU"
    _ensure_layer(doc,layer,3,25)
    indoors=[e for e in pipeline.get("hvac",{}).get("equipment") or [] if e.get("kind")=="split_indoor"]
    x1,y1,x2,y2=tuple(b["plan_area"])
    cols=max(1,min(4,len(indoors)))
    rec=[]
    for i,e in enumerate(indoors,1):
        col=(i-1)%cols;row_i=(i-1)//cols
        x=x1+1.5+col*3.5;y=y2-2.2-row_i*2.7
        _rect(msp,layer,x-.45,y-.38,x+.45,y+.38)
        msp.add_circle((x,y),.20,dxfattribs={"layer":layer})
        tag=f"ODU-{i:02d}"
        _mtext(msp,layer,f"{tag} ↔ {e.get('id')}\n{e.get('capacity_btu_h') or 'CAPACITY PRELIM.'} BTU/h",x-.65,y-.75,2.3,.052)
        rec.append({"tag":tag,"serves":e.get("id"),"capacity_btu_h":e.get("capacity_btu_h"),"status":"PRELIMINARY"})
    return {"status":"PASS" if rec else "INPUT_REQUIRED","outdoor_units":rec}


def _entity_signature(e):
    layer=str(getattr(e.dxf,"layer",""))
    typ=e.dxftype()
    if typ=="MTEXT":
        value=e.plain_text()[:120]
    elif typ=="TEXT":
        value=str(getattr(e.dxf,"text",""))[:120]
    elif typ=="INSERT":
        value=str(getattr(e.dxf,"name",""))
    else:
        value=""
    return f"{typ}|{layer}|{value}"


def qa_semantic_sheet_content(path: Path, compose):
    doc=ezdxf.readfile(path)
    msp=doc.modelspace()
    boards=compose.get("boards") or {}
    signatures={}
    content_counts={}
    missing_family_content=[]
    family_layer_need={
        "SANITARY_VENT":("ENGITOOLS-M-SANITARY","ENGITOOLS-M-VENT"),
        "WATER":("ENGITOOLS-M-COLD_WATER",),
        "HEATING":("ENGITOOLS-M-HEAT-FLOW","ENGITOOLS-M-RADIATOR"),
        "GAS":("ENGITOOLS-M-GAS",),
        "SPLIT_AC":("ENGITOOLS-M-HVAC",),
        "EXHAUST":("ENGITOOLS-M-EXHAUST",),
    }
    manifest={r["old_sheet"]:r for r in compose.get("manifest") or []}

    def intersect(ex,b):
        return not (ex.extmax.x<b[0] or ex.extmin.x>b[2] or ex.extmax.y<b[1] or ex.extmin.y>b[3])

    for old,b in boards.items():
        bounds=tuple(b["bounds"])
        tokens=[]
        layers=Counter()
        for e in msp:
            layer=str(getattr(e.dxf,"layer",""))
            if layer.startswith("ENGITOOLS-SHEET-"):
                continue
            try:
                ex=bbox.extents([e],fast=True)
                if not ex.has_data or not intersect(ex,bounds):
                    continue
            except Exception:
                continue
            tokens.append(_entity_signature(e))
            layers[layer]+=1
        content_counts[old]=len(tokens)
        signatures[old]=hashlib.sha256("\n".join(sorted(tokens)).encode()).hexdigest()
        row=manifest.get(old) or {}
        needs=family_layer_need.get(row.get("family"))
        if needs:
            if row.get("family")=="WATER" and row.get("level")=="SERVICE":
                if layers["ENGITOOLS-M-WATER-SERVICE"]<=0:
                    missing_family_content.append(f"{row.get('code')}:water_service")
            elif row.get("family")=="SPLIT_AC" and row.get("level")=="ROOF":
                if layers["ENGITOOLS-M-HVAC-ODU"]<=0:
                    missing_family_content.append(f"{row.get('code')}:odu_roof")
            elif not all(any(k in lname and count>0 for lname,count in layers.items()) for k in needs):
                missing_family_content.append(f"{row.get('code')}:{row.get('family')}")
    groups=defaultdict(list)
    for s,h in signatures.items():
        groups[h].append(s)
    duplicates=[x for x in groups.values() if len(x)>1]
    errors=[]
    if any(v==0 for v in content_counts.values()):errors.append("blank_sheet_content")
    if missing_family_content:errors.append("missing_family_specific_content")
    return {
        "version":"semantic-sheet-content-qa-v15.0",
        "status":"PASS" if not errors else "FAIL",
        "errors":errors,
        "warnings":[f"semantic_duplicate:{','.join(g)}" for g in duplicates],
        "missing_family_content":missing_family_content,
        "content_counts":content_counts,
        "duplicate_groups":duplicates,
    }


def design_mechanical_authority_site(src: Path, dst: Path, answers: dict | None=None, plan_analysis: dict | None=None) -> dict:
    answers=dict(answers or {})
    overrides=build_design_overrides(answers)
    pipeline=run_engineering_pipeline(src,design_basis=overrides,project_overrides=overrides)
    pipeline_qa=validate_pipeline(pipeline)
    acceptance=evaluate_engineering_acceptance(pipeline)
    authority=build_authority_model(pipeline,answers)
    if authority["authority_qa"]["status"]!="PASS":
        return {"status":"FAIL","stage":"authority_contract","pipeline_qa":pipeline_qa,"engineering_acceptance":acceptance,"authority":authority}
    compose=compose_authority_dxf(src,dst,pipeline,authority,answers)

    doc=ezdxf.readfile(dst)
    msp=doc.modelspace()
    enrich={
        "roof_rainwater":enrich_roof_rainwater(doc,msp,pipeline,authority,compose,answers),
        "water_service":enrich_water_service(doc,msp,pipeline,authority,compose,answers),
        "gas_table":enrich_gas(doc,msp,pipeline,authority,compose,answers),
        "exhaust_cfm":enrich_exhaust(doc,msp,pipeline,compose),
        "split_roof":enrich_split_roof(doc,msp,pipeline,compose),
    }
    ext=bbox.extents(msp,fast=True)
    if ext.has_data:
        doc.header["$EXTMIN"]=tuple(map(float,ext.extmin))
        doc.header["$EXTMAX"]=tuple(map(float,ext.extmax))
    doc.saveas(dst)

    dxf_qa=qa_authority_dxf(dst,compose)
    semantic_qa=qa_semantic_sheet_content(dst,compose)
    status="PASS" if pipeline_qa["status"]=="PASS" and dxf_qa["status"]=="PASS" and semantic_qa["status"]=="PASS" else "FAIL"
    return {
        "status":status,
        "version":"mechanical-authority-site-pipeline-v15.1",
        "pipeline_qa":pipeline_qa,
        "engineering_acceptance":acceptance,
        "authority":authority,
        "composition":compose,
        "enrichment":enrich,
        "dxf_qa":dxf_qa,
        "semantic_qa":semantic_qa,
    }
