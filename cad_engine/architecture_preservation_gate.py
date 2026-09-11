"""Architecture Preservation Gate canonical.
Fail-closed protection for architectural evidence used by mechanical design.
Uncertain entities are preserved, never deleted by default.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from collections import defaultdict
from hashlib import sha256
import json
from typing import Iterable, Optional
import ezdxf
from ezdxf import bbox
from ezdxf.math import Matrix44

CRITICAL_CLASSES={"WALL","DOOR","WINDOW","OPENING","SHAFT","COLUMN","GRID","STAIR","RAMP","SLAB","ROOM_BOUNDARY","STRUCTURAL"}
IMPORTANT_CLASSES={"DIMENSION","LEVEL","NORTH","ROOM_TEXT"}
PRESENTATION_CLASSES={"TITLE","SCALE_TEXT","SHEET_FRAME","DECORATION"}
REMOVABLE_CLASSES={"LEGACY_TITLE","LEGACY_SEPARATOR","LEGACY_FOOTER_ARTIFACT"}
CLASS_LAYER_HINTS={
 "WALL":("wall","walls","a-wall","دیوار"),"DOOR":("door","doors","a-door","در"),"WINDOW":("window","windows","a-glaz","پنجره"),
 "SHAFT":("shaft","duct","void","داکت","شفت"),"COLUMN":("column","col","ستون"),"GRID":("grid","axis","axes","محور"),
 "STAIR":("stair","stairs","پله"),"RAMP":("ramp","رمپ"),"SLAB":("slab","floor","سقف"),"STRUCTURAL":("struct","beam","تیر","سازه")}
TEXT_MARKERS={"LEGACY_TITLE":("پلان معماری","arc -","architectural plan"),"SCALE_TEXT":("sc:","scale","مقیاس"),"NORTH":("north",)}

@dataclass(frozen=True)
class EntityRecord:
    key:str; handle:str; entity_type:str; layer:str; block:Optional[str]; plan_id:Optional[str]
    bbox:tuple[float,float,float,float]; length:float; area:float; text:str; geometry_hash:str
    semantic_class:str="UNKNOWN"; confidence:float=0.0; criticality:str="CRITICAL"

def _norm(v): return str(v or "").strip().lower().replace("ي","ی").replace("ك","ک")
def _ext(e):
    try:
        ex=bbox.extents([e],fast=True); return ex if ex.has_data else None
    except Exception:return None
def _text(e):
    try:
        if e.dxftype()=="TEXT":return str(e.dxf.text or "")
        if e.dxftype()=="MTEXT":return str(e.plain_text() or "")
    except Exception:pass
    return ""
def _xy(v): return (round(float(v.x),6),round(float(v.y),6))

def _geom_signature(e):
    parts=[e.dxftype(),str(getattr(e.dxf,"layer",""))]; ex=_ext(e)
    if ex: parts += [f"{float(ex.extmin.x):.6f}",f"{float(ex.extmin.y):.6f}",f"{float(ex.extmax.x):.6f}",f"{float(ex.extmax.y):.6f}"]
    if e.dxftype()=="LINE": parts += [str(_xy(e.dxf.start)),str(_xy(e.dxf.end))]
    elif e.dxftype()=="LWPOLYLINE":
        try:parts.append(str([(round(float(x),6),round(float(y),6)) for x,y,*_ in e.get_points()]))
        except Exception:pass
    elif e.dxftype()=="INSERT": parts += [str(e.dxf.name),str(_xy(e.dxf.insert)),str(round(float(getattr(e.dxf,"rotation",0)),6))]
    parts.append(_text(e)); return sha256("|".join(parts).encode("utf-8","ignore")).hexdigest()

def _measure(e):
    length=area=0.0
    try:
        if e.dxftype()=="LINE": length=float(e.dxf.start.distance(e.dxf.end))
        elif e.dxftype()=="LWPOLYLINE":
            length=float(e.length())
            if e.closed:
                pts=[(float(x),float(y)) for x,y,*_ in e.get_points()]
                area=abs(sum(pts[i][0]*pts[(i+1)%len(pts)][1]-pts[(i+1)%len(pts)][0]*pts[i][1] for i in range(len(pts)))/2) if len(pts)>=3 else 0.0
    except Exception:pass
    return length,area

def classify_entity(e):
    layer=_norm(getattr(e.dxf,"layer","")); typ=e.dxftype().upper(); txt=_norm(_text(e)); block=_norm(getattr(e.dxf,"name","")) if typ=="INSERT" else ""; blob=" ".join((layer,txt,block))
    for cls,hints in CLASS_LAYER_HINTS.items():
        if any(h in blob for h in hints):return cls,.97
    for cls,markers in TEXT_MARKERS.items():
        if any(m in txt for m in markers):return cls,.96
    if typ=="DIMENSION":return "DIMENSION",.99
    if typ=="INSERT":
        if any(x in block for x in ("door","در")):return "DOOR",.95
        if any(x in block for x in ("window","پنجره")):return "WINDOW",.95
        if any(x in block for x in ("north","compass")):return "NORTH",.95
    if typ in {"TEXT","MTEXT"}:
        if txt.strip().upper()=="N":return "NORTH",.90
        return "ROOM_TEXT",.55
    if typ in {"LINE","LWPOLYLINE","POLYLINE","ARC","CIRCLE","SPLINE"}:return "UNKNOWN_GEOMETRY",.35
    return "UNKNOWN",.20

def criticality_for(semantic_class,confidence):
    if confidence<.70:return "CRITICAL"
    if semantic_class in CRITICAL_CLASSES:return "CRITICAL"
    if semantic_class in IMPORTANT_CLASSES:return "IMPORTANT"
    if semantic_class in REMOVABLE_CLASSES:return "REMOVABLE"
    if semantic_class in PRESENTATION_CLASSES:return "PRESENTATION"
    return "CRITICAL"

def snapshot_architecture(doc_or_path,plan_id=None,plan_bounds=None):
    doc=ezdxf.readfile(doc_or_path) if isinstance(doc_or_path,(str,bytes)) else doc_or_path; records=[]
    for e in doc.modelspace():
        ex=_ext(e)
        if not ex:continue
        cx=(ex.extmin.x+ex.extmax.x)/2; cy=(ex.extmin.y+ex.extmax.y)/2
        if plan_bounds and not(plan_bounds[0]<=cx<=plan_bounds[2] and plan_bounds[1]<=cy<=plan_bounds[3]):continue
        cls,conf=classify_entity(e); crit=criticality_for(cls,conf); length,area=_measure(e); handle=str(getattr(e.dxf,"handle","") or "")
        rec=EntityRecord(key=f"{plan_id or 'PLAN'}:{handle or _geom_signature(e)[:12]}",handle=handle,entity_type=e.dxftype(),layer=str(getattr(e.dxf,"layer","")),block=str(getattr(e.dxf,"name","")) if e.dxftype()=="INSERT" else None,plan_id=plan_id,bbox=(float(ex.extmin.x),float(ex.extmin.y),float(ex.extmax.x),float(ex.extmax.y)),length=round(length,6),area=round(area,6),text=_text(e),geometry_hash=_geom_signature(e),semantic_class=cls,confidence=conf,criticality=crit)
        records.append(asdict(rec))
    layouts=[]
    for layout in doc.layouts:
        layouts.append({"name":str(layout.name),"entity_count":len(layout)})
    blocks=[]
    for block in doc.blocks:
        blocks.append({"name":str(block.name),"entity_count":len(block)})
    xrefs=[]
    for block in doc.blocks:
        try:
            if block.block.is_xref:
                xrefs.append({"name":str(block.name),"path":str(block.block.dxf.xref_path or "")})
        except Exception:
            continue
    ext=bbox.extents(doc.modelspace(),fast=True)
    drawing_bounds=(float(ext.extmin.x),float(ext.extmin.y),float(ext.extmax.x),float(ext.extmax.y)) if ext.has_data else None
    metadata={
        "units":int(doc.header.get("$INSUNITS",0) or 0),
        "measurement":int(doc.header.get("$MEASUREMENT",0) or 0),
        "insertion_base":tuple(float(v) for v in doc.header.get("$INSBASE",(0,0,0))),
        "drawing_bounds":drawing_bounds,
        "layers":sorted(str(layer.dxf.name) for layer in doc.layers),
        "blocks":sorted(blocks,key=lambda item:item["name"]),
        "xrefs":sorted(xrefs,key=lambda item:item["name"]),
        "layouts":sorted(layouts,key=lambda item:item["name"]),
    }
    metadata["metadata_hash"]=sha256(json.dumps(metadata,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    payload={"plan_id":plan_id,"entity_count":len(records),"entities":records,"document":metadata}
    payload["snapshot_hash"]=sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest(); return payload

def build_dependency_graph(snapshot,mechanical):
    by_class=defaultdict(list)
    for r in snapshot.get("entities",[]):by_class[r["semantic_class"]].append(r)
    deps=[]
    for obj in mechanical.get("equipment",[]):
        required="WALL" if _norm(obj.get("kind")) in {"split_indoor","radiator","package"} else "ROOM_BOUNDARY"; deps.append({"mechanical_id":obj.get("id"),"requires":required,"candidate_hosts":[r["key"] for r in by_class.get(required,[])],"hard":True})
    for route in mechanical.get("routes",[]):deps.append({"mechanical_id":route.get("id"),"requires":"SHAFT_OR_OPENING","candidate_hosts":[r["key"] for c in ("SHAFT","OPENING") for r in by_class.get(c,[])],"hard":False})
    return {"dependencies":deps,"unhosted_hard":[d for d in deps if d["hard"] and not d["candidate_hosts"]]}

def authorize_mutation(record,action,confidence=1.0):
    action=action.upper(); crit=record.get("criticality","CRITICAL")
    allowed=(crit=="REMOVABLE" and confidence>=.95) if action=="DELETE" else (True if action=="TRANSFORM" else action in {"PRESERVE","COPY"})
    return {"allowed":allowed,"action":action,"reason":"AUTHORIZED" if allowed else f"{crit}_ENTITY_PROTECTED"}

def atomic_transform(doc,entity_handles:Iterable[str],matrix:Matrix44):
    handles=list(entity_handles); by_handle={str(getattr(e.dxf,"handle","")):e for e in doc.modelspace()}; targets=[by_handle[h] for h in handles if h in by_handle]
    if len(targets)!=len(handles):return {"status":"FAIL","reason":"MISSING_ENTITY_BEFORE_ATOMIC_TRANSFORM"}
    failures=[]
    for e in targets:
        try:e.transform(matrix)
        except Exception as exc:failures.append({"handle":str(e.dxf.handle),"error":str(exc)})
    return {"status":"PASS" if not failures else "FAIL","transformed":len(targets)-len(failures),"failures":failures}

def diff_snapshots(before,after,tolerance=1e-6,compare_coordinates=True):
    b={r["key"]:r for r in before.get("entities",[])}; a={r["key"]:r for r in after.get("entities",[])}; deleted=[r for k,r in b.items() if k not in a]; added=[r for k,r in a.items() if k not in b]; changed=[]
    for k in b.keys()&a.keys():
        rb,ra=b[k],a[k]
        numeric_changed=(
            abs(rb["length"]-ra["length"])>tolerance
            or abs(rb["area"]-ra["area"])>tolerance
            or (compare_coordinates and any(abs(float(x)-float(y))>tolerance for x,y in zip(rb["bbox"],ra["bbox"])))
        )
        fields=("semantic_class","entity_type","layer","block","text","geometry_hash")
        field_changes=[field for field in fields if rb.get(field)!=ra.get(field)]
        if numeric_changed or field_changes:
            changed.append({"key":k,"before":rb,"after":ra,"changed_fields":field_changes + (["numeric_geometry"] if numeric_changed else [])})
    critical_deleted=[r for r in deleted if r.get("criticality")=="CRITICAL"]; important_deleted=[r for r in deleted if r.get("criticality")=="IMPORTANT"]
    protected_changed=[item for item in changed if item["before"].get("criticality") in {"CRITICAL","IMPORTANT"}]
    document_changed=before.get("document")!=after.get("document") if before.get("document") is not None and after.get("document") is not None else False
    return {"deleted":deleted,"added":added,"changed":changed,"critical_deleted":critical_deleted,"important_deleted":important_deleted,
            "protected_changed":protected_changed,"document_changed":document_changed,
            "pass":not critical_deleted and not important_deleted and not protected_changed and not document_changed}

def _endpoint_key(p,tol=1e-4):return (round(p[0]/tol)*tol,round(p[1]/tol)*tol)
def wall_topology(snapshot):
    walls=[r for r in snapshot.get("entities",[]) if r.get("semantic_class")=="WALL"]; nodes=defaultdict(int)
    for w in walls:
        x1,y1,x2,y2=w["bbox"]; nodes[_endpoint_key((x1,y1))]+=1; nodes[_endpoint_key((x2,y2))]+=1
    return {"wall_count":len(walls),"node_degrees":sorted(nodes.values())}
def validate_topology(before,after):
    tb,ta=wall_topology(before),wall_topology(after); classes=("DOOR","WINDOW","OPENING","SHAFT","STAIR"); cb={c:sum(1 for r in before.get("entities",[]) if r.get("semantic_class")==c) for c in classes}; ca={c:sum(1 for r in after.get("entities",[]) if r.get("semantic_class")==c) for c in classes}; ok=tb==ta and cb==ca
    return {"pass":ok,"wall_topology_before":tb,"wall_topology_after":ta,"critical_counts_before":cb,"critical_counts_after":ca}
def validate_visibility(snapshot,safe_area,occluded_keys:Optional[set]=None):
    occluded_keys=occluded_keys or set(); clipped=[]; hidden=[]; sx1,sy1,sx2,sy2=safe_area
    for r in snapshot.get("entities",[]):
        if r.get("criticality")!="CRITICAL":continue
        if r.get("entity_type")=="INSERT" and r.get("insertion_point"):
            x1,y1=r["insertion_point"];x2,y2=x1,y1
        else:
            x1,y1,x2,y2=r["bbox"]
        if x1<sx1 or y1<sy1 or x2>sx2 or y2>sy2:clipped.append(r["key"])
        if r["key"] in occluded_keys:hidden.append(r["key"])
    return {"pass":not clipped and not hidden,"clipped":clipped,"hidden":hidden}
def validate_mechanical_impact(snapshot,dependency_graph):
    keys={r["key"] for r in snapshot.get("entities",[])}; broken=[]
    for d in dependency_graph.get("dependencies",[]):
        if d.get("hard") and not any(k in keys for k in d.get("candidate_hosts",[])):broken.append(d["mechanical_id"])
    return {"pass":not broken,"broken_hard_dependencies":broken}
def run_golden_regression(cases):
    results=[]
    for case in cases:
        d=diff_snapshots(case["before"],case["after"],compare_coordinates=False); t=validate_topology(case["before"],case["after"]); ok=d["pass"] and t["pass"]; results.append({"name":case.get("name"),"pass":ok,"critical_deleted":len(d["critical_deleted"]),"topology_pass":t["pass"]})
    return {"pass":all(r["pass"] for r in results),"results":results}
def finalize_gate(*,diff,topology,visibility,mechanical,regression):
    checks={"critical_deleted_zero":len(diff.get("critical_deleted",[]))==0,"topology_preserved":bool(topology.get("pass")),"visibility_preserved":bool(visibility.get("pass")),"mechanical_dependencies_preserved":bool(mechanical.get("pass")),"golden_regression_green":bool(regression.get("pass"))}; ok=all(checks.values()); failures=[k for k,v in checks.items() if not v]
    return {"status":"PASS" if ok else "FAIL","checks":checks,"failures":failures,"action":"COMMIT_OUTPUT" if ok else "ROLLBACK_AND_BLOCK_DELIVERY"}


ARCHITECTURE_100_RUBRIC={
    "geometry_topology":30,
    "frame_level_binding":20,
    "layers_blocks_text":15,
    "underlay_visibility":15,
    "unauthorized_change_collision":10,
    "exact_reopen_diff":10,
}


def evaluate_eighteen_step_contract(*, checks:dict, evidence:dict|None=None):
    """Score the complete architecture-preservation chain without averaging away a failure.

    Every named control is mandatory.  Missing/unknown controls fail closed, and
    any critical control failure prevents a 100 score and blocks delivery.
    """
    required=(
        "immutable_snapshot","coordinate_calibration","drawing_separation","level_binding",
        "wall_reconstruction","typed_openings_and_verticals","closed_room_identity","shaft_wet_core_evidence",
        "safe_deduplication","mutation_prohibition","work_copy_only","atomic_rollback",
        "exact_entity_diff","topology_preservation","per_sheet_visibility","graphical_sheet_qa",
        "destructive_regression","exact_file_reopen",
    )
    normalized={name:bool(checks.get(name) is True) for name in required}
    groups={
        "geometry_topology":required[4:9]+("exact_entity_diff","topology_preservation"),
        "frame_level_binding":required[1:4],
        "layers_blocks_text":("immutable_snapshot","typed_openings_and_verticals","closed_room_identity"),
        "underlay_visibility":("per_sheet_visibility","graphical_sheet_qa"),
        "unauthorized_change_collision":("mutation_prohibition","work_copy_only","atomic_rollback"),
        "exact_reopen_diff":("exact_file_reopen","exact_entity_diff","destructive_regression"),
    }
    category_scores={}
    for category,names in groups.items():
        weight=ARCHITECTURE_100_RUBRIC[category]
        category_scores[category]=round(weight*sum(normalized[name] for name in names)/len(names),2)
    score=round(sum(category_scores.values()),2)
    failures=[name for name,value in normalized.items() if not value]
    status="PASS" if not failures and score==100 else "FAIL"
    return {
        "version":"architecture-preservation-18/1",
        "status":status,"score":score,"maximum_score":100,
        "checks":normalized,"failures":failures,"category_scores":category_scores,
        "rubric":dict(ARCHITECTURE_100_RUBRIC),"evidence":dict(evidence or {}),
        "action":"COMMIT_OUTPUT" if status=="PASS" else "ROLLBACK_AND_BLOCK_DELIVERY",
    }
