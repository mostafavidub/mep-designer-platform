"""CAD documentation enhancer v17.

Adds project-agnostic registers/tables to non-plan authority sheets only. It
never edits architectural plan geometry. The goal is information completeness
and traceability for Detail, Riser, Calculation and General Notes sheets.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import ezdxf
from ezdxf import bbox
from .reference_parity_engine_v17 import ProjectContext, build_documentation_package

LAYER="ENGITOOLS-V17-DOCUMENTATION"
TEXT_LAYER="ENGITOOLS-V17-DOCUMENTATION-TEXT"
DETAIL_LAYER="ENGITOOLS-M-DETAIL"
RISER_SYSTEMS={"SANITARY_VENT","WATER","HEATING","GAS"}


def _ensure_layers(doc):
    if LAYER not in doc.layers: doc.layers.add(LAYER,color=7)
    if TEXT_LAYER not in doc.layers: doc.layers.add(TEXT_LAYER,color=7)
    if DETAIL_LAYER not in doc.layers: doc.layers.add(DETAIL_LAYER,color=2)


def _mtext(msp,text,x,y,h=.18,width=8.5,layer=TEXT_LAYER):
    e=msp.add_mtext(text,dxfattribs={"layer":layer,"char_height":h})
    e.set_location((x,y)); e.dxf.width=width
    return e


def _box(msp,x1,y1,x2,y2,layer=LAYER):
    return msp.add_lwpolyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2),(x1,y1)],dxfattribs={"layer":layer})


def _plain_text(entity):
    try:
        if entity.dxftype()=="TEXT": return str(entity.dxf.text or "")
        if entity.dxftype()=="MTEXT": return str(entity.plain_text() or "")
    except Exception:
        pass
    return ""


def _entity_center(entity):
    try:
        ex=bbox.extents([entity],fast=True)
        if ex.has_data:
            return ((float(ex.extmin.x)+float(ex.extmax.x))/2,(float(ex.extmin.y)+float(ex.extmax.y))/2)
    except Exception:
        pass
    return None


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


def _detail_id(detail:str)->str:
    return str(detail or "").split(" ",1)[0].strip().upper()


def _detail_group(detail:str)->str:
    ident=_detail_id(detail)
    if ident.startswith("D-GS-"): return "GAS"
    if ident.startswith(("D-HT-","D-AC-","D-HV-")): return "HVAC"
    return "PLUMBING"


def _detail_board_group(row:dict[str,Any])->str|None:
    text=" ".join(str(row.get(k) or "") for k in ("title_fa","title","label","level")).upper()
    if "GAS" in text: return "GAS"
    if "HVAC" in text or "HEATING" in text or "COOL" in text: return "HVAC"
    if "PLUMB" in text or "WATER" in text or "SANIT" in text: return "PLUMBING"
    return None


def _detail_area(board:dict[str,Any])->tuple[float,float,float,float]|None:
    raw=board.get("plan_area") or board.get("bounds")
    if not isinstance(raw,(list,tuple)) or len(raw)!=4: return None
    try: x1,y1,x2,y2=map(float,raw)
    except Exception: return None
    if x2<=x1 or y2<=y1: return None
    mx=min(.35,(x2-x1)*.04); my=min(.35,(y2-y1)*.04)
    return (x1+mx,y1+my,x2-mx,y2-my)


def _assign_details(board_rows:list[tuple[dict[str,Any],dict[str,Any]]],details:list[str])->dict[str,list[str]]:
    detail_boards=[(row,b) for row,b in board_rows if str(row.get("family") or "").upper()=="GENERAL_DETAIL"]
    assignments={str(row.get("old_sheet")):[] for row,_ in detail_boards}
    if not detail_boards: return assignments
    for detail in details:
        group=_detail_group(detail)
        target=next((row for row,_ in detail_boards if _detail_board_group(row)==group),detail_boards[0][0])
        assignments[str(target.get("old_sheet"))].append(detail)
    return assignments


def _detail_layout(area:tuple[float,float,float,float],count:int):
    x1,y1,x2,y2=area; w=x2-x1; h=y2-y1
    register_h=min(max(1.25,.19*(count+2)),h*.24)
    register=(x1,y2-register_h,x2,y2)
    body_top=register[1]-.18
    body=(x1,y1,x2,body_top)
    cols=2 if count>1 else 1; rows=max(1,(count+cols-1)//cols); gap=min(.16,w*.012,h*.008)
    cell_w=(body[2]-body[0]-gap*(cols-1))/cols; cell_h=(body[3]-body[1]-gap*(rows-1))/rows
    cells=[]
    for i in range(count):
        col=i%cols; row=i//cols
        cx1=body[0]+col*(cell_w+gap); cx2=cx1+cell_w
        cy2=body[3]-row*(cell_h+gap); cy1=cy2-cell_h
        cells.append((cx1,cy1,cx2,cy2))
    return register,body,cells


def _write_detail_register(msp,area,details):
    register,_,_=_detail_layout(area,len(details)); x1,y1,x2,y2=register
    _box(msp,x1,y1,x2,y2)
    text=["PROJECT-SPECIFIC DETAIL REGISTER — MATERIALIZED IDS"]+[f"{i+1:02d}  {d}" for i,d in enumerate(details)]
    h=max(.045,min(.105,(y2-y1)/max(len(text)+1,2)*.70))
    _mtext(msp,"\n".join(text),x1+.12,y2-.14,h=h,width=max(x2-x1-.24,.6))
    return register


def _draw_detail_geometry(msp,cell,detail):
    """Draw a deterministic schematic without inventing project dimensions."""
    x1,y1,x2,y2=cell; w=x2-x1; h=y2-y1; ident=_detail_id(detail)
    pad_x=max(w*.045,.04); pad_y=max(h*.055,.035)
    ix1=x1+pad_x; ix2=x2-pad_x; iy1=y1+pad_y; iy2=y2-pad_y
    cx=(ix1+ix2)/2; cy=(iy1+iy2)/2; dx=max((ix2-ix1)*.14,.04); dy=max((iy2-iy1)*.11,.025)
    geometry=[]
    geometry.append(_box(msp,ix1,iy1,ix2,iy2,DETAIL_LAYER))
    family=_detail_group(detail)
    if family=="HVAC":
        geometry.append(_box(msp,cx-dx,cy-dy,cx+dx,cy+dy,DETAIL_LAYER))
        geometry.append(msp.add_line((ix1+dx,cy+dy*.35),(cx-dx,cy+dy*.35),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((ix1+dx,cy-dy*.35),(cx-dx,cy-dy*.35),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((cx+dx,cy+dy*.35),(ix2-dx,cy+dy*.35),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((cx+dx,cy-dy*.35),(ix2-dx,cy-dy*.35),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_circle((ix1+dx,cy+dy*.35),max(dy*.15,.012),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_circle((ix1+dx,cy-dy*.35),max(dy*.15,.012),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((cx,cy+dy),(cx,iy2-dy*.6),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((cx,cy-dy),(cx,iy1+dy*.6),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((ix2-dx*.7,cy),(ix2-dx*.15,cy+dy*.45),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((ix2-dx*.7,cy),(ix2-dx*.15,cy-dy*.45),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((cx-dx*.55,cy),(cx+dx*.55,cy),dxfattribs={"layer":DETAIL_LAYER}))
    else:
        geometry.append(msp.add_line((ix1+dx*.4,cy),(ix2-dx*.4,cy),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((ix1+dx*.4,cy+dy*.30),(ix2-dx*.4,cy+dy*.30),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_lwpolyline([(cx-dx,cy-dy),(cx,cy),(cx-dx,cy+dy)],dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_lwpolyline([(cx+dx,cy-dy),(cx,cy),(cx+dx,cy+dy)],dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_circle((cx-dx*1.55,cy),max(dy*.18,.012),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_circle((cx+dx*1.55,cy),max(dy*.18,.012),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((cx-dx*1.55,cy+dy*.2),(cx-dx*1.55,iy2-dy*.5),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((cx+dx*1.55,cy+dy*.2),(cx+dx*1.55,iy2-dy*.5),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((cx,cy+dy*.25),(cx,iy2-dy*.5),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((ix2-dx*.9,cy),(ix2-dx*.25,cy+dy*.45),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((ix2-dx*.9,cy),(ix2-dx*.25,cy-dy*.45),dxfattribs={"layer":DETAIL_LAYER}))
        geometry.append(msp.add_line((ix1+dx*.7,iy1+dy*.45),(ix2-dx*.7,iy1+dy*.45),dxfattribs={"layer":DETAIL_LAYER}))
    # Two exact-file tags ensure the registered id is independently visible on
    # the materialized-detail layer. No unverified project/manufacturer number is written.
    title=str(detail or ident)
    th=max(.035,min(.085,h*.055))
    _mtext(msp,title,ix1+.06,iy2-.08,h=th,width=max(ix2-ix1-.12,.4),layer=DETAIL_LAYER)
    _mtext(msp,f"{ident} | MATERIALIZED SCHEMATIC | VERIFY FINAL PROJECT / MANUFACTURER VALUES",ix1+.06,iy1+max(th*.95,.04),h=max(.028,th*.72),width=max(ix2-ix1-.12,.4),layer=DETAIL_LAYER)
    return {"detail_id":ident,"geometry_count":len(geometry),"tag_count":2,"cell":cell,"family":family}


def _materialize_detail_sheet(msp,area,details):
    _,_,cells=_detail_layout(area,len(details)); records=[]
    for detail,cell in zip(details,cells): records.append(_draw_detail_geometry(msp,cell,detail))
    return records


def validate_detail_materialization(path:Path,board_rows,assignments)->dict[str,Any]:
    """Step 7 exact-file proof: every registered id has geometry and tags in its own cell."""
    detail_boards=[(row,b) for row,b in board_rows if str(row.get("family") or "").upper()=="GENERAL_DETAIL"]
    if not detail_boards:
        return {"version":"detail-materialization-step7/1","status":"NOT_APPLICABLE","errors":[],"details":[],"materialized_count":0}
    try:
        doc=ezdxf.readfile(Path(path)); entities=list(doc.modelspace())
    except Exception as exc:
        return {"version":"detail-materialization-step7/1","status":"FAIL","errors":["exact_dxf_reopen_failed"],"detail":str(exc),"details":[],"materialized_count":0}
    errors=[]; records=[]
    for row,board in detail_boards:
        key=str(row.get("old_sheet")); details=assignments.get(key) or []; area=_detail_area(board)
        if not area:
            errors.append(f"detail_board_area_missing:{row.get('code') or key}"); continue
        if not details:
            errors.append(f"detail_board_selection_empty:{row.get('code') or key}"); continue
        _,_,cells=_detail_layout(area,len(details))
        for detail,cell in zip(details,cells):
            ident=_detail_id(detail); local=[]
            for entity in entities:
                if str(getattr(entity.dxf,"layer","") or "").upper()!=DETAIL_LAYER: continue
                p=_entity_center(entity)
                if p and cell[0]<=p[0]<=cell[2] and cell[1]<=p[1]<=cell[3]: local.append(entity)
            geometry=sum(e.dxftype() not in {"TEXT","MTEXT"} for e in local)
            tags=sum(ident in _plain_text(e).upper() for e in local if e.dxftype() in {"TEXT","MTEXT"})
            status="PASS" if geometry>=12 and tags>=2 else "FAIL"
            if geometry<12: errors.append(f"detail_geometry_missing:{ident}:{geometry}<12")
            if tags<2: errors.append(f"detail_tag_missing:{ident}:{tags}<2")
            records.append({"detail_id":ident,"sheet":row.get("code"),"geometry_count":geometry,"tag_count":tags,"status":status})
    expected=sum(len(v) for v in assignments.values()); passed=sum(r["status"]=="PASS" for r in records)
    if passed!=expected: errors.append(f"detail_materialization_count:{passed}!={expected}")
    return {"version":"detail-materialization-step7/1","status":"PASS" if not errors else "FAIL","errors":sorted(set(errors)),
            "details":records,"materialized_count":passed,"expected_count":expected,"exact_file_reopened":True,
            "policy":"REGISTER_ID_REQUIRES_GEOMETRY_AND_LAYER_TAG_NO_UNVERIFIED_VALUES"}


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
    details=list((pkg.get("details") or {}).get("selected_details") or [])
    assignments=_assign_details(board_rows,details)
    if assignments and (not details or any(not rows for rows in assignments.values())):
        missing=[]
        if not details: missing.append("PROJECT_SPECIFIC_DETAIL_SELECTION")
        missing.extend("DETAIL_SELECTION:"+key for key,rows in assignments.items() if not rows)
        return {"version":"17.0.0","status":"INPUT_REQUIRED","written":[],"generated_entity_count":0,
                "exact_file_reopened":False,"documentation_package":pkg,"riser_integrity":riser_qa,
                "detail_materialization":{"version":"detail-materialization-step7/1","status":"INPUT_REQUIRED","missing_inputs":sorted(set(missing)),"errors":[]},
                "policy":"FAIL_CLOSED_BEFORE_DXF_MUTATION"}
    doc=ezdxf.readfile(dxf_path); _ensure_layers(doc); msp=doc.modelspace(); written=[]; generated_detail_records=[]
    for row,b in board_rows:
        family=str(row.get("family") or "").upper(); bounds=b.get("bounds")
        if not bounds: continue
        if family=="GENERAL_DETAIL":
            key=str(row.get("old_sheet")); selected=assignments.get(key) or []; area=_detail_area(b)
            if not area: continue
            _write_detail_register(msp,area,selected); generated_detail_records.extend(_materialize_detail_sheet(msp,area,selected))
            written.append({"sheet":row.get("code"),"type":"DETAIL_REGISTER_AND_GEOMETRY","detail_count":len(selected)})
        elif family=="PLUMBING_RISER": _write_riser_register(msp,bounds,pkg); written.append({"sheet":row.get("code"),"type":"RISER_REGISTER"})
        elif family=="WATER_SERVICE_CALC": _write_calc_register(msp,bounds,pkg); written.append({"sheet":row.get("code"),"type":"CALC_REGISTER"})
        elif family=="GENERAL_NOTES": _write_notes_register(msp,bounds,pkg); written.append({"sheet":row.get("code"),"type":"NOTES_REGISTER"})
    doc.saveas(dxf_path)
    detail_qa=validate_detail_materialization(dxf_path,board_rows,assignments)
    reopened=ezdxf.readfile(dxf_path); count=sum(1 for e in reopened.modelspace() if str(getattr(e.dxf,"layer","")) in {LAYER,TEXT_LAYER,DETAIL_LAYER})
    detail_ok=detail_qa["status"] in {"PASS","NOT_APPLICABLE"}
    status="PASS" if written and count>0 and detail_ok else "FAIL"
    return {"version":"17.0.0","status":status,"written":written,"generated_entity_count":count,"exact_file_reopened":True,
            "documentation_package":pkg,"riser_integrity":riser_qa,"detail_materialization":detail_qa,
            "generated_detail_records":generated_detail_records}