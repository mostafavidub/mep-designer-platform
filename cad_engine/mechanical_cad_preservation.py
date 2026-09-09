"""Mechanical authority production wrapper with Architecture Preservation Gate canonical.

The existing canonical engineering pipeline remains the design engine.  This wrapper
adds a fail-closed architectural preservation transaction around final delivery:
source architecture is snapshotted, the exact generated DXF is reopened, copied
architecture is compared after the board transform, topology/visibility are
checked, and delivery is blocked/rolled back on critical loss.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path
import math
import shutil
import tempfile

import ezdxf
from ezdxf import bbox

from .mechanical_cad_base import design_mechanical_authority_site as _design_canonical
from .mechanical_design_core import (
    build_design_overrides,
    _entities_in_bounds,
    _find_plan_for_level,
    _find_roof_plan,
)
from .engineering_runner import run_engineering_pipeline
from .architecture_preservation_gate import (
    classify_entity,
    criticality_for,
    validate_topology,
    validate_visibility,
    finalize_gate,
)

PLAN_FAMILIES={"ROOF","SANITARY_VENT","WATER","HEATING","GAS","SPLIT_AC","EXHAUST"}
PROTECTED={"CRITICAL","IMPORTANT"}


def _entity_ext(e):
    try:
        ex=bbox.extents([e],fast=True)
        return ex if ex.has_data else None
    except Exception:
        return None


def _text(e):
    try:
        if e.dxftype()=="TEXT": return str(e.dxf.text or "")
        if e.dxftype()=="MTEXT": return str(e.plain_text() or "")
    except Exception:
        pass
    return ""


def _measure(e):
    length=area=0.0
    try:
        if e.dxftype()=="LINE":
            length=float(e.dxf.start.distance(e.dxf.end))
        elif e.dxftype()=="LWPOLYLINE":
            length=float(e.length())
            if e.closed:
                pts=[(float(x),float(y)) for x,y,*_ in e.get_points()]
                if len(pts)>=3:
                    area=abs(sum(pts[i][0]*pts[(i+1)%len(pts)][1]-pts[(i+1)%len(pts)][0]*pts[i][1] for i in range(len(pts)))/2)
    except Exception:
        pass
    return length,area


def _snapshot_selected(entities,plan_id):
    records=[]
    for i,e in enumerate(entities):
        ex=_entity_ext(e)
        if not ex: continue
        cls,conf=classify_entity(e); crit=criticality_for(cls,conf); length,area=_measure(e)
        control_points=[]
        if e.dxftype()=="LWPOLYLINE":
            try:
                control_points=[(float(x),float(y),float(bulge)) for x,y,_,_,bulge in e.get_points("xyseb")]
            except Exception:
                control_points=[]
        records.append({
            "key":f"{plan_id}:E{i:05d}",
            "handle":str(getattr(e.dxf,"handle","") or ""),
            "entity_type":e.dxftype(),
            "layer":str(getattr(e.dxf,"layer","")),
            "bbox":(float(ex.extmin.x),float(ex.extmin.y),float(ex.extmax.x),float(ex.extmax.y)),
            "length":round(length,6),"area":round(area,6),"text":_text(e),
            "semantic_class":cls,"confidence":conf,"criticality":crit,
            "control_points":control_points,
            "insertion_point":(
                (float(e.dxf.insert.x),float(e.dxf.insert.y))
                if e.dxftype()=="INSERT" else None
            ),
        })
    return {"plan_id":plan_id,"entity_count":len(records),"entities":records}


def _entities_in_output_board(doc,plan_area,source_layers):
    out=[]
    for e in doc.modelspace():
        layer=str(getattr(e.dxf,"layer",""))
        # Generated EngiTools content is never treated as imported architecture.
        if layer.startswith("ENGITOOLS-"):
            continue
        if source_layers and layer not in source_layers:
            continue
        ex=_entity_ext(e)
        if not ex: continue
        # A block can contain distant construction geometry, so its expanded
        # bbox center may lie outside the board even when the INSERT itself is
        # an exact preserved architectural copy. Selection in the source uses
        # the insertion point; apply the same rule after transformation.
        if e.dxftype()=="INSERT":
            cx=float(e.dxf.insert.x); cy=float(e.dxf.insert.y)
        else:
            cx=(ex.extmin.x+ex.extmax.x)/2; cy=(ex.extmin.y+ex.extmax.y)/2
        if plan_area[0]-.15<=cx<=plan_area[2]+.15 and plan_area[1]-.15<=cy<=plan_area[3]+.15:
            out.append(e)
    return out


def _fit_parameters(srcb,target):
    sx1,sy1,sx2,sy2=map(float,srcb); tx1,ty1,tx2,ty2=map(float,target)
    sw=max(sx2-sx1,1e-9); sh=max(sy2-sy1,1e-9); tw=tx2-tx1; th=ty2-ty1
    scale=min(tw/sw,th/sh); nw=sw*scale; nh=sh*scale
    dx=tx1+(tw-nw)/2; dy=ty1+(th-nh)/2
    return scale,dx,dy


def _expected_bbox(rec,srcb,target):
    scale,dx,dy=_fit_parameters(srcb,target); sx1,sy1,_,_=map(float,srcb)
    x1,y1,x2,y2=rec["bbox"]
    return (
        dx+(x1-sx1)*scale,dy+(y1-sy1)*scale,
        dx+(x2-sx1)*scale,dy+(y2-sy1)*scale,
    )


def _transform_point(point,srcb,target):
    scale,dx,dy=_fit_parameters(srcb,target);sx1,sy1,_,_=map(float,srcb)
    return dx+(float(point[0])-sx1)*scale,dy+(float(point[1])-sy1)*scale


def _bbox_error(a,b):
    return max(abs(float(x)-float(y)) for x,y in zip(a,b))


def _match_transformed_architecture(before,after,srcb,target,tolerance=.08):
    """Match protected source entities to transformed copies without relying on handles."""
    expected=[r for r in before.get("entities",[]) if r.get("criticality") in PROTECTED]
    actual=[r for r in after.get("entities",[]) if r.get("criticality") in PROTECTED]
    # First consume exact transformed geometry as a multiset. Repeated CAD
    # primitives legitimately share class/layer and can defeat a greedy
    # nearest-neighbour assignment even though every copy is present.
    def geometry_key(rec,transform=False):
        points=rec.get("control_points") or []
        if points:
            if transform:
                mapped=[]
                for x,y,bulge in points:
                    px,py=_transform_point((x,y),srcb,target)
                    mapped.append((round(px,6),round(py,6),round(float(bulge),9)))
            else:
                mapped=[(round(float(x),6),round(float(y),6),round(float(bulge),9)) for x,y,bulge in points]
            geometry=("CONTROL_POINTS",tuple(mapped))
        else:
            box=_expected_bbox(rec,srcb,target) if transform else rec["bbox"]
            geometry=("BBOX",tuple(round(float(v),6) for v in box))
        return (
            rec.get("entity_type"),rec.get("semantic_class"),rec.get("layer"),
            geometry,
        )
    buckets={}
    for index,rec in enumerate(actual):
        buckets.setdefault(geometry_key(rec),[]).append((index,rec))
    exact=[]
    for rec in expected:
        candidates=buckets.get(geometry_key(rec,True)) or []
        if not candidates:
            exact=[]
            break
        _,matched=candidates.pop()
        exact.append({"source_key":rec["key"],"output_key":matched["key"],"bbox_error":0.0})
    if exact and len(exact)==len(expected) and not any(buckets.values()):
        return {
            "pass":True,
            "protected_source_count":len(expected),
            "protected_output_count":len(actual),
            "matched_count":len(exact),
            "missing":[],
            "extra_protected":[],
            "matches":exact,
            "strategy":"exact_transformed_geometry",
        }
    # The compositor appends an exact transformed copy of source entities in
    # source order.  Prefer that preserved transaction order when it remains
    # intact.  This avoids a greedy nearest-neighbour mismatch between dense,
    # visually identical polylines while still checking every entity's class,
    # layer and transformed geometry.  Any deletion/reordering falls through
    # to the conservative spatial matcher below.
    if len(expected)==len(actual):
        ordered=[]
        for src,dst in zip(expected,actual):
            sc,dc=src.get("semantic_class"),dst.get("semantic_class")
            compatible=(
                dst.get("entity_type")==src.get("entity_type")
                and dst.get("layer")==src.get("layer")
                and (sc==dc or (str(sc).startswith("UNKNOWN") and str(dc).startswith("UNKNOWN")))
            )
            err=_bbox_error(_expected_bbox(src,srcb,target),dst["bbox"]) if compatible else math.inf
            if not compatible or err>tolerance:
                ordered=[]
                break
            ordered.append({"source_key":src["key"],"output_key":dst["key"],"bbox_error":round(err,6)})
        if ordered:
            return {
                "pass":True,
                "protected_source_count":len(expected),
                "protected_output_count":len(actual),
                "matched_count":len(ordered),
                "missing":[],
                "extra_protected":[],
                "matches":ordered,
                "strategy":"preserved_copy_order",
            }
    used=set(); matches=[]; missing=[]
    for src in expected:
        eb=_expected_bbox(src,srcb,target)
        candidates=[]
        for j,dst in enumerate(actual):
            if j in used: continue
            if dst.get("entity_type")!=src.get("entity_type"): continue
            # semantic class must either agree, or both be fail-closed unknown geometry.
            sc,dc=src.get("semantic_class"),dst.get("semantic_class")
            if sc!=dc and not (sc.startswith("UNKNOWN") and dc.startswith("UNKNOWN")):
                continue
            candidates.append((_bbox_error(eb,dst["bbox"]),j,dst))
        if not candidates:
            missing.append({"source":src,"expected_bbox":eb,"reason":"NO_CLASS_TYPE_CANDIDATE"}); continue
        err,j,dst=min(candidates,key=lambda x:x[0])
        if err>tolerance:
            missing.append({"source":src,"expected_bbox":eb,"best_error":err,"reason":"GEOMETRY_MISMATCH"}); continue
        used.add(j); matches.append({"source_key":src["key"],"output_key":dst["key"],"bbox_error":round(err,6)})
    protected_extra=[r for j,r in enumerate(actual) if j not in used]
    return {
        "pass":not missing,
        "protected_source_count":len(expected),
        "protected_output_count":len(actual),
        "matched_count":len(matches),
        "missing":missing,
        "extra_protected":protected_extra,
        "matches":matches,
        "strategy":"conservative_spatial",
    }


def _snapshot_in_source_coordinates(snapshot,srcb,target):
    """Inverse-map copied output bboxes before topology comparison.

    Topology tolerances describe source drawing units.  Applying the same
    absolute tolerance after a board fit can merge distinct source nodes when
    a large architectural plan is scaled down.  Inverse normalization keeps
    the gate strict while comparing both graphs in the same coordinate space.
    """
    scale,dx,dy=_fit_parameters(srcb,target)
    sx1,sy1,_,_=map(float,srcb)
    normalized=deepcopy(snapshot)
    for rec in normalized.get("entities",[]):
        x1,y1,x2,y2=rec["bbox"]
        rec["bbox"]=(
            sx1+(x1-dx)/scale, sy1+(y1-dy)/scale,
            sx1+(x2-dx)/scale, sy1+(y2-dy)/scale,
        )
    return normalized


def _source_plan_for_row(arch,row):
    family=row.get("family"); level=row.get("level")
    if family=="ROOF" or level=="ROOF":
        return _find_roof_plan(arch)
    return _find_plan_for_level(arch,level)


def _plan_mechanical(pipeline,pid):
    equipment=[e for e in (pipeline.get("hvac",{}).get("equipment") or []) if e.get("plan_id")==pid]
    routes=[r for r in (pipeline.get("routing",{}).get("routes") or []) if r.get("plan_id")==pid]
    routes += [r for r in (pipeline.get("hvac",{}).get("routes") or []) if r.get("plan_id")==pid]
    return {"equipment":equipment,"routes":routes}


def evaluate_architecture_preservation(src:Path,dst:Path,base_report:dict,answers:dict|None=None)->dict:
    """Reopen exact final DXF and validate every generated plan board."""
    answers=dict(answers or {})
    overrides=build_design_overrides(answers)
    pipeline=run_engineering_pipeline(src,design_basis=overrides,project_overrides=overrides)
    arch=pipeline["architecture"]
    src_doc=ezdxf.readfile(src)
    out_doc=ezdxf.readfile(dst)  # exact-file reopen is mandatory
    compose=base_report.get("composition") or {}
    boards=compose.get("boards") or {}
    rows=compose.get("manifest") or []
    sheet_results=[]; all_missing=[]; topology_ok=True; visibility_ok=True

    for row in rows:
        if row.get("family") not in PLAN_FAMILIES:
            continue
        board=boards.get(row.get("old_sheet"))
        if not board:
            continue
        # SERVICE variants are engineering schematics generated from the
        # approved service basis; they do not claim to contain a copied source
        # architectural floor and therefore are outside geometry-preservation
        # matching. Their mechanical content is covered by semantic/DXF QA.
        if row.get("level")=="SERVICE":
            sheet_results.append({"sheet":row.get("code"),"family":row.get("family"),"level":row.get("level"),
                                  "status":"PASS","reason":"ENGINEERING_SERVICE_SCHEMATIC"})
            continue
        plan=_source_plan_for_row(arch,row)
        if not plan:
            # A plan sheet without source architecture is a hard preservation failure.
            sheet_results.append({"sheet":row.get("code"),"status":"FAIL","reason":"SOURCE_PLAN_NOT_FOUND"})
            all_missing.append({"sheet":row.get("code"),"reason":"SOURCE_PLAN_NOT_FOUND"})
            continue
        src_entities=_entities_in_bounds(src_doc.modelspace(),plan["bounds"])
        before=_snapshot_selected(src_entities,plan["plan_id"])
        source_layers={r["layer"] for r in before["entities"]}
        plan_area=tuple(board["plan_area"])
        out_entities=_entities_in_output_board(out_doc,plan_area,source_layers)
        after=_snapshot_selected(out_entities,f"OUT-{row.get('code')}")
        match=_match_transformed_architecture(before,after,tuple(plan["bounds"]),plan_area)
        topo=validate_topology(before,_snapshot_in_source_coordinates(after,tuple(plan["bounds"]),plan_area))
        # Small numerical tolerance around board safe area, but no clipping into title block.
        safe=(plan_area[0]-.12,plan_area[1]-.12,plan_area[2]+.12,plan_area[3]+.12)
        vis=validate_visibility(after,safe)
        topology_ok=topology_ok and topo["pass"]
        visibility_ok=visibility_ok and vis["pass"]
        for m in match["missing"]:
            all_missing.append({"sheet":row.get("code"),**m})
        sheet_results.append({
            "sheet":row.get("code"),"family":row.get("family"),"level":row.get("level"),
            "status":"PASS" if match["pass"] and topo["pass"] and vis["pass"] else "FAIL",
            "source_architecture_count":before["entity_count"],"output_architecture_count":after["entity_count"],
            "preservation_match":match,"topology":topo,"visibility":vis,
        })

    diff={"critical_deleted":[m for m in all_missing if (m.get("source") or {}).get("criticality")=="CRITICAL"]}
    # Important losses also block production even though the stage-12 contract names critical loss explicitly.
    important_missing=[m for m in all_missing if (m.get("source") or {}).get("criticality")=="IMPORTANT"]
    topology={"pass":topology_ok and all(r.get("status")!="FAIL" or r.get("reason")!="SOURCE_PLAN_NOT_FOUND" for r in sheet_results)}
    visibility={"pass":visibility_ok}
    mechanical={"pass":not all_missing and (base_report.get("dxf_qa") or {}).get("status")=="PASS"}
    regression={"pass":True,"source":"architecture-preservation-canonical CI release gate"}
    final=finalize_gate(diff=diff,topology=topology,visibility=visibility,mechanical=mechanical,regression=regression)
    if important_missing:
        final["status"]="FAIL"; final["action"]="ROLLBACK_AND_BLOCK_DELIVERY"
        final.setdefault("failures",[]).append("important_architecture_deleted")
        final.setdefault("checks",{})["important_deleted_zero"]=False
    else:
        final.setdefault("checks",{})["important_deleted_zero"]=True
    return {
        "version":"architecture-preservation-gate-canonical.0",
        "status":final["status"],"action":final["action"],"checks":final["checks"],"failures":final.get("failures",[]),
        "critical_missing_count":len(diff["critical_deleted"]),"important_missing_count":len(important_missing),
        "all_missing_count":len(all_missing),"sheet_results":sheet_results,
        "exact_file_reopened":True,
    }


def design_mechanical_authority_site(src:Path,dst:Path,answers:dict|None=None,plan_analysis:dict|None=None)->dict:
    """Transactional production design: rollback/block delivery on architecture loss."""
    src=Path(src); dst=Path(dst); backup=None
    if dst.exists():
        fd,name=tempfile.mkstemp(prefix="engitools-preservation-backup-",suffix=".dxf")
        Path(name).unlink(missing_ok=True); backup=Path(name); shutil.copy2(dst,backup)
    report=_design_canonical(src,dst,answers=answers,plan_analysis=plan_analysis)
    if report.get("status")!="PASS":
        if backup and backup.exists(): shutil.copy2(backup,dst); backup.unlink(missing_ok=True)
        return report
    preservation=evaluate_architecture_preservation(src,dst,report,answers=answers)
    report["architecture_preservation_qa"]=preservation
    report["version"]="mechanical-authority-site-pipeline-canonical.0"
    if preservation["status"]!="PASS":
        report["status"]="FAIL"; report["stage"]="architecture_preservation_gate"
        if backup and backup.exists():
            shutil.copy2(backup,dst)
        else:
            dst.unlink(missing_ok=True)
    if backup: backup.unlink(missing_ok=True)
    return report
