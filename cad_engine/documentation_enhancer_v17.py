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
RISER_SYSTEMS={"SANITARY_VENT","WATER","HEATING","GAS"}


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


def validate_riser_integrity(package:dict[str,Any],has_riser_board:bool=False)->dict[str,Any]:
    """Step 6: a riser may pass only when real plan-branch evidence exists.

    The validator never fabricates a branch. Missing branch evidence is
    INPUT_REQUIRED; contradictory reconciliation remains a hard FAIL.
    """
    riser=(package or {}).get("riser") or {}; graph=riser.get("graph") or {}; reconciliation=riser.get("reconciliation") or {}
    nodes=[n for n in graph.get("nodes") or [] if str(n.get("system") or "").upper() in RISER_SYSTEMS]
    node_by_id={str(n.get("id")):n for n in nodes if n.get("id")}
    counts={}
    for node in nodes:
        key=(str(node.get("riser") or ""),str(node.get("system") or "").upper())
        if key[0]: counts.setdefault(key,0)
    orphan_edges=[]
    for edge in graph.get("edges") or []:
        if edge.get("type")!="PLAN_BRANCH": continue
        target=node_by_id.get(str(edge.get("to") or ""))
        if not target:
            orphan_edges.append(str(edge.get("from") or edge.get("id") or "UNKNOWN")); continue
        key=(str(target.get("riser") or ""),str(target.get("system") or "").upper())
        if key in counts: counts[key]+=1
    zero=sorted(f"{riser_id}:{system}" for (riser_id,system),count in counts.items() if count<1)
    reconciliation_ok=bool(reconciliation.get("pass"))
    errors=[]; missing=[]
    if not reconciliation_ok:
        errors.append("plan_riser_reconciliation_failed")
    if orphan_edges:
        errors.append("orphan_plan_branch:"+",".join(sorted(orphan_edges)))
    if zero:
        missing.extend("PLAN_BRANCH:"+item for item in zero)
    if has_riser_board and not counts:
        missing.append("RISER_GRAPH")
    if errors:
        status="FAIL"
    elif missing:
        status="INPUT_REQUIRED"
    else:
        status="PASS"
    return {
        "version":"riser-integrity-step6/1",
        "status":status,
        "errors":errors,
        "missing_inputs":sorted(set(missing)),
        "riser_branch_counts":{f"{riser_id}:{system}":count for (riser_id,system),count in sorted(counts.items())},
        "zero_branch_risers":zero,
        "reconciliation_pass":reconciliation_ok,
        "policy":"NO_ZERO_BRANCH_PASS_NO_SYNTHETIC_BRANCHES",
    }


def _write_detail_register(msp,bounds,pkg):
    x1,y1,x2,y2=map(float,bounds); w=x2-x1; h=y2-y1; bx1=x1+w*.04; bx2=x1+w*.46; by2=y2-h*.08; by1=max(y1+h*.48,by2-h*.34)
    _box(msp,bx1,by1,bx2,by2); details=pkg["details"]["selected_details"]
    _mtext(msp,"\n".join(["PROJECT-SPECIFIC DETAIL REGISTER"]+[f"{i+1:02d}  {d}" for i,d in enumerate(details[:18])]),bx1+.18,by2-.22,h=.13,width=max(bx2-bx1-.36,1))


def _write_riser_register(msp,bounds,pkg):
    x1,y1,x2,y2=map(float,bounds); w=x2-x1; h=y2-y1; bx1=x1+w*.55; bx2=x2-w*.04; by2=y2-h*.08; by1=max(y1+h*.48,by2-h*.34)
    _box(msp,bx1,by1,bx2,by2); g=pkg["riser"]["graph"]; lines=["RISER / PLAN RECONCILIATION","RISER | SYSTEM | LEVELS | BRANCHES"]
    for riser in sorted({n["riser"] for n in g.get("nodes",[])})[:12]:
        nodes=[n for n in g["nodes"] if n["riser"]==riser]; system=nodes[0]["system"] if nodes else "-"; levels=",".join(n["level"] for n in nodes); count=sum(1 for e in g.get("edges",[]) if e.get("type")=="PLAN_BRANCH" and e.get("system")==system); lines.append(f"{riser} | {system} | {levels} | {count}")
    lines.append("STATUS: PASS"); _mtext(msp,"\n".join(lines),bx1+.18,by2-.22,h=.13,width=max(bx2-bx1-.36,1))


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
    dxf_path=Path(dxf_path); board_rows=_board_map(report); pkg=build_documentation_package(context)
    has_riser_board=any(str(row.get("family") or "").upper()=="PLUMBING_RISER" for row,_ in board_rows)
    riser_qa=validate_riser_integrity(pkg,has_riser_board=has_riser_board)
    if riser_qa["status"]!="PASS":
        return {"version":"17.0.0","status":riser_qa["status"],"written":[],"generated_entity_count":0,
                "exact_file_reopened":False,"documentation_package":pkg,"riser_integrity":riser_qa,
                "policy":"FAIL_CLOSED_BEFORE_DXF_MUTATION"}
    doc=ezdxf.readfile(dxf_path); _ensure_layers(doc); msp=doc.modelspace(); written=[]
    for row,b in board_rows:
        family=str(row.get("family") or ""); bounds=b.get("bounds")
        if not bounds: continue
        if family=="GENERAL_DETAIL": _write_detail_register(msp,bounds,pkg); written.append({"sheet":row.get("code"),"type":"DETAIL_REGISTER"})
        elif family=="PLUMBING_RISER": _write_riser_register(msp,bounds,pkg); written.append({"sheet":row.get("code"),"type":"RISER_REGISTER"})
        elif family=="WATER_SERVICE_CALC": _write_calc_register(msp,bounds,pkg); written.append({"sheet":row.get("code"),"type":"CALC_REGISTER"})
        elif family=="GENERAL_NOTES": _write_notes_register(msp,bounds,pkg); written.append({"sheet":row.get("code"),"type":"NOTES_REGISTER"})
    doc.saveas(dxf_path); reopened=ezdxf.readfile(dxf_path); count=sum(1 for e in reopened.modelspace() if str(getattr(e.dxf,"layer","")) in {LAYER,TEXT_LAYER})
    return {"version":"17.0.0","status":"PASS" if written and count>0 else "FAIL","written":written,"generated_entity_count":count,"exact_file_reopened":True,"documentation_package":pkg,"riser_integrity":riser_qa}