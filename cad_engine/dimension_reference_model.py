"""Building Reference Model v2 for professional dimensioning."""
from __future__ import annotations
import math
from .dimension_intent_model import SemanticReference
from .dimension_envelope import build_envelope_model,envelope_edges
from .semantic_dimension_engine import detect_local_axis


def _seg(item):
    a=item.get("start");b=item.get("end")
    if a and b and len(a)>=2 and len(b)>=2:
        return {"type":"SEGMENT","a":(float(a[0]),float(a[1])),"b":(float(b[0]),float(b[1]))}
    return None

def _poly_edges(item):
    pts=item.get("polygon") or item.get("points") or []
    pts=[(float(p[0]),float(p[1])) for p in pts if len(p)>=2]
    if len(pts)<2:return []
    return [{"type":"SEGMENT","a":pts[i],"b":pts[(i+1)%len(pts)]} for i in range(len(pts))]

def _line_intersection(a,b,c,d,tol=1e-8):
    x1,y1=a;x2,y2=b;x3,y3=c;x4,y4=d
    den=(x1-x2)*(y3-y4)-(y1-y2)*(x3-x4)
    if abs(den)<=tol:return None
    px=((x1*y2-y1*x2)*(x3-x4)-(x1-x2)*(x3*y4-y3*x4))/den
    py=((x1*y2-y1*x2)*(y3-y4)-(y1-y2)*(x3*y4-y3*x4))/den
    return (px,py)

def _ref(ref_id,element_id,subfeature,geometry,priority,source,confidence,evidence,plan_id=None,level=None,datum_class=None):
    return SemanticReference(ref_id,element_id,subfeature,geometry,plan_id,level,priority,source,confidence,tuple(evidence),datum_class).to_dict()

def _wall_subfeature(wall,basis):
    basis=str(basis or "").upper()
    if basis=="CORE_FACE":return "WALL_CORE_FACE"
    if basis=="INNER_FINISH_FACE":return "WALL_INNER_FINISH_FACE"
    if basis=="OUTER_FINISH_FACE":return "WALL_OUTER_FINISH_FACE"
    if basis=="STRUCTURAL_FACE":return "STRUCTURAL_FACE"
    if basis=="CENTERLINE":return "WALL_CENTERLINE"
    return None


def build_reference_model_v2(doc,plan_bounds,architecture=None,plan_id=None,level=None,wall_reference_basis=None):
    architecture=architecture or {}
    refs=[];reviews=[]
    env=build_envelope_model(architecture,plan_id)
    for row in envelope_edges(env):
        ref=_ref(row["id"],row["element_id"],row["subfeature"],row["geometry"],5,row["source"],row["confidence"],row["evidence"],plan_id,level,row["datum_class"])
        ref["envelope_side"]=row.get("envelope_side")
        refs.append(ref)

    walls=[w for w in architecture.get("walls") or [] if isinstance(w,dict) and (not plan_id or w.get("plan_id") in (None,plan_id))]
    wall_sf=_wall_subfeature({},wall_reference_basis)
    if walls and not wall_sf:
        reviews.append("WALL_REFERENCE_BASIS_REQUIRED")
    for i,w in enumerate(walls):
        geom=_seg(w)
        if not geom:continue
        if wall_sf:
            eid=str(w.get("id") or f"WALL-{i:04d}")
            ref=_ref(f"{eid}/{wall_sf}",eid,wall_sf,geom,20,"semantic_geometry",1.0,("wall_reference_basis:"+str(wall_reference_basis),),plan_id,level,"WALL")
            ref["metadata"]={"wall_reference_basis":str(wall_reference_basis),"wall_type_id":w.get("wall_type_id"),"assembly_id":w.get("assembly_id")}
            refs.append(ref)

    # Openings are represented by two jamb points plus a centerline.
    # Treating the whole opening segment as one "jamb" loses size/position semantics.
    for key in ("openings","doors","windows"):
        for i,item in enumerate(architecture.get(key) or []):
            if not isinstance(item,dict) or (plan_id and item.get("plan_id") not in (None,plan_id)):continue
            eid=str(item.get("id") or f"{key.upper()}-{i:04d}")
            seg=_seg(item)
            if seg:
                a=tuple(seg["a"]);b=tuple(seg["b"]);mid=((a[0]+b[0])/2.0,(a[1]+b[1])/2.0)
                refs.append(_ref(f"{eid}/JAMB-A",eid,"OPENING_JAMB",{"type":"POINT","point":a},15,"semantic_geometry",1.0,(key,"jamb_a"),plan_id,level,"OPENING"))
                refs.append(_ref(f"{eid}/JAMB-B",eid,"OPENING_JAMB",{"type":"POINT","point":b},15,"semantic_geometry",1.0,(key,"jamb_b"),plan_id,level,"OPENING"))
                refs.append(_ref(f"{eid}/CENTERLINE",eid,"OPENING_CENTERLINE",{"type":"SEGMENT","a":a,"b":b},15,"semantic_geometry",1.0,(key,"centerline"),plan_id,level,"OPENING"))
            else:
                for j,g in enumerate(_poly_edges(item)):
                    refs.append(_ref(f"{eid}/JAMB/{j}",eid,"OPENING_JAMB",g,15,"semantic_geometry",.9,(key,"polygon_edge"),plan_id,level,"OPENING"))

    mappings=[
      ("grids","GRID_AXIS",0,"GRID"),
      ("columns","STRUCTURAL_FACE",10,"STRUCTURE"),
      ("shafts","SHAFT_FACE",10,"SHAFT"),
      ("stairs","STAIR_CORE_FACE",12,"STAIR"),
      ("property_boundaries","PROPERTY_BOUNDARY",5,"PROPERTY"),
    ]
    for key,sf,priority,datum in mappings:
        for i,item in enumerate(architecture.get(key) or []):
            if not isinstance(item,dict) or (plan_id and item.get("plan_id") not in (None,plan_id)):continue
            eid=str(item.get("id") or f"{key.upper()}-{i:04d}")
            geoms=[_seg(item)] if _seg(item) else _poly_edges(item)
            for j,g in enumerate(x for x in geoms if x):
                refs.append(_ref(f"{eid}/{sf}/{j}",eid,sf,g,priority,"semantic_geometry",1.0,(key,),plan_id,level,datum))

    grids=[r for r in refs if r["subfeature"]=="GRID_AXIS"]
    for i,a in enumerate(grids):
        for b in grids[i+1:]:
            pa=_line_intersection(tuple(a["geometry"]["a"]),tuple(a["geometry"]["b"]),tuple(b["geometry"]["a"]),tuple(b["geometry"]["b"]))
            if pa is None:continue
            eid=f"{a['element_id']}x{b['element_id']}"
            refs.append(_ref(f"{eid}/GRID_INTERSECTION",eid,"GRID_INTERSECTION",{"type":"POINT","point":pa},0,"derived_semantic",1.0,(a["id"],b["id"]),plan_id,level,"GRID"))

    legacy=[{"kind":r["subfeature"],"a":r["geometry"].get("a",r["geometry"].get("point")),"b":r["geometry"].get("b",r["geometry"].get("point")),"priority":r["priority"]} for r in refs if r["geometry"].get("type")=="SEGMENT"]
    axis=math.degrees(detect_local_axis(legacy)) if legacy else 0.0
    for r in refs:r["local_axis_deg"]=axis
    errors=[]
    for r in refs:
        errors.extend({"reference_id":r["id"],"error":e} for e in SemanticReference(**{k:r[k] for k in SemanticReference.__dataclass_fields__}).validate())
    # Wall-basis ambiguity is scoped: wall-face references are withheld until
    # confirmed, while independent GRID/ENVELOPE/STRUCTURE/SHAFT datums remain
    # usable for Mechanical set-out. Consumers decide whether the review blocks
    # their drawing profile.
    status="FAIL" if errors else ("HUMAN_REVIEW_REQUIRED" if reviews or env["status"]!="PASS" else "PASS")
    human_review=sorted(set(reviews+env.get("human_review",[])))
    checkpoints=[]
    if "WALL_REFERENCE_BASIS_REQUIRED" in human_review:
        checkpoints.append({
          "id":"WALL_REFERENCE_BASIS","type":"POLICY_DECISION","blocking_profiles":["ARCHITECTURAL_FLOOR_PLAN"],
          "question":"Which wall subfeature is the authoritative dimension datum for this drawing/profile?",
          "allowed_values":["CORE_FACE","INNER_FINISH_FACE","OUTER_FINISH_FACE","STRUCTURAL_FACE","CENTERLINE"],
          "reason":"Wall-face meaning cannot be proven from imported geometry alone."
        })
    if "BUILDING_ENVELOPE_NOT_PROVEN" in human_review:
        checkpoints.append({
          "id":"BUILDING_ENVELOPE_CONFIRMATION","type":"GEOMETRY_REVIEW","blocking_profiles":["ARCHITECTURAL_FLOOR_PLAN"],
          "reason":"No explicit semantic envelope or proven exterior-wall closed loop is available."
        })
    return {"status":status,"references":refs,"envelope":env,"local_axis_deg":axis,
            "wall_reference_basis":wall_reference_basis,"wall_references_enabled":bool(wall_sf),
            "human_review":human_review,"review_checkpoints":checkpoints,"errors":errors}
