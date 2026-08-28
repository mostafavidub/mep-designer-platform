"""CAD documentation enhancer v17.

Adds project-agnostic registers/tables to non-plan authority sheets only. It
never edits architectural plan geometry. The goal is information completeness
and traceability for Detail, Riser, Calculation and General Notes sheets.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import ezdxf
from .reference_parity_engine_v17 import ProjectContext, build_documentation_package

LAYER="ENGITOOLS-V17-DOCUMENTATION"
TEXT_LAYER="ENGITOOLS-V17-DOCUMENTATION-TEXT"


def _ensure_layers(doc):
    if LAYER not in doc.layers: doc.layers.add(LAYER,color=7)
    if TEXT_LAYER not in doc.layers: doc.layers.add(TEXT_LAYER,color=7)


def _mtext(msp,text,x,y,h=.18,width=8.5):
    e=msp.add_mtext(text,dxfattribs={"layer":TEXT_LAYER,"char_height":h})
    e.set_location((x,y)); e.dxf.width=width
    return e


def _box(msp,x1,y1,x2,y2):
    msp.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2),(x1,y1)],dxfattribs={"layer":LAYER})


def _board_map(report:dict[str,Any]):
    comp=report.get("composition") or {}; boards=comp.get("boards") or {}; manifest=comp.get("manifest") or []; out=[]
    for row in manifest:
        b=boards.get(row.get("old_sheet"))
        if b: out.append((row,b))
    return out


def _write_detail_register(msp,bounds,pkg):
    x1,y1,x2,y2=map(float,bounds); w=x2-x1; h=y2-y1; bx1=x1+w*.04; bx2=x1+w*.46; by2=y2-h*.08; by1=max(y1+h*.48,by2-h*.34)
    _box(msp,bx1,by1,bx2,by2); details=pkg["details"]["selected_details"]
    _mtext(msp,"\n".join(["PROJECT-SPECIFIC DETAIL REGISTER"]+[f"{i+1:02d}  {d}" for i,d in enumerate(details[:18])]),bx1+.18,by2-.22,h=.13,width=max(bx2-bx1-.36,1))


def _write_riser_register(msp,bounds,pkg):
    x1,y1,x2,y2=map(float,bounds); w=x2-x1; h=y2-y1; bx1=x1+w*.55; bx2=x2-w*.04; by2=y2-h*.08; by1=max(y1+h*.48,by2-h*.34)
    _box(msp,bx1,by1,bx2,by2); g=pkg["riser"]["graph"]; lines=["RISER / PLAN RECONCILIATION","RISER | SYSTEM | LEVELS | BRANCHES"]
    for riser in sorted({n["riser"] for n in g.get("nodes",[])})[:12]:
        nodes=[n for n in g["nodes"] if n["riser"]==riser]; system=nodes[0]["system"] if nodes else "-"; levels=",".join(n["level"] for n in nodes); count=sum(1 for e in g.get("edges",[]) if e.get("type")=="PLAN_BRANCH" and e.get("system")==system); lines.append(f"{riser} | {system} | {levels} | {count}")
    lines.append("STATUS: "+str(pkg["riser"]["reconciliation"]["pass"]).upper()); _mtext(msp,"\n".join(lines),bx1+.18,by2-.22,h=.13,width=max(bx2-bx1-.36,1))


def _write_calc_register(msp,bounds,pkg):
    x1,y1,x2,y2=map(float,bounds); w=x2-x1; h=y2-y1; bx1=x1+w*.04; bx2=x2-w*.04; by2=y2-h*.08; by1=max(y1+h*.38,by2-h*.46)
    _box(msp,bx1,by1,bx2,by2); lines=["TRACEABLE CALCULATION REGISTER","ID | SOURCE / DEPENDENCY | STATUS"]
    for sec in pkg["calculations"]["sections"]:
        for row in sec["rows"]: lines.append(f"{row['id']} | {', '.join(row['sources'])} | {row['result_status']}")
    _mtext(msp,"\n".join(lines[:24]),bx1+.18,by2-.22,h=.13,width=max(bx2-bx1-.36,1))


def _write_notes_register(msp,bounds,pkg):
    x1,y1,x2,y2=map(float,bounds); w=x2-x1; h=y2-y1; bx1=x1+w*.04; bx2=x2-w*.04; by2=y2-h*.08; by1=y1+h*.26
    _box(msp,bx1,by1,bx2,by2); lines=["PROJECT-SPECIFIC GENERAL NOTES"]
    for i,n in enumerate(pkg["general_notes"],1): lines.append(f"{i:02d}. [{n['system']}] {n['text']}  BASIS: {n['reference_basis']}")
    _mtext(msp,"\n".join(lines[:28]),bx1+.18,by2-.22,h=.12,width=max(bx2-bx1-.36,1))


def apply_documentation_enhancements(dxf_path:Path, report:dict[str,Any], context:ProjectContext)->dict[str,Any]:
    dxf_path=Path(dxf_path); doc=ezdxf.readfile(dxf_path); _ensure_layers(doc); msp=doc.modelspace(); pkg=build_documentation_package(context); written=[]
    for row,b in _board_map(report):
        family=str(row.get("family") or ""); bounds=b.get("bounds")
        if not bounds: continue
        if family=="GENERAL_DETAIL": _write_detail_register(msp,bounds,pkg); written.append({"sheet":row.get("code"),"type":"DETAIL_REGISTER"})
        elif family=="PLUMBING_RISER": _write_riser_register(msp,bounds,pkg); written.append({"sheet":row.get("code"),"type":"RISER_REGISTER"})
        elif family=="WATER_SERVICE_CALC": _write_calc_register(msp,bounds,pkg); written.append({"sheet":row.get("code"),"type":"CALC_REGISTER"})
        elif family=="GENERAL_NOTES": _write_notes_register(msp,bounds,pkg); written.append({"sheet":row.get("code"),"type":"NOTES_REGISTER"})
    doc.saveas(dxf_path); reopened=ezdxf.readfile(dxf_path); count=sum(1 for e in reopened.modelspace() if str(getattr(e.dxf,"layer","")) in {LAYER,TEXT_LAYER})
    return {"version":"17.0.0","status":"PASS" if written and count>0 else "FAIL","written":written,"generated_entity_count":count,"exact_file_reopened":True,"documentation_package":pkg}
