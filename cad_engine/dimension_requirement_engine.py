"""Drawing-profile Dimension Requirement Engine v2."""
from __future__ import annotations
import math

PROFILE_POLICIES={
 "ARCHITECTURAL_FLOOR_PLAN":{
   "context":{"PROPERTY","SETBACK","BUILDING_OVERALL","GRID"},
   "targets":{"WALL","PARTITION","SHAFT","STAIR","OPENING","STRUCTURE"},
 },
 "MECHANICAL_PLAN":{
   "context":{"BUILDING_OVERALL","GRID","SHAFT","STAIR"},
   "targets":{"RISER","STACK","FLOOR_DRAIN","ROOF_DRAIN","CLEANOUT","SLEEVE","PENETRATION","MECHANICAL_OPENING","PUMP","TANK","INDOOR_UNIT","OUTDOOR_UNIT","EQUIPMENT"},
 },
 "PARKING_PLAN":{
   "context":{"BUILDING_OVERALL","GRID","SHAFT","STAIR"},
   "targets":{"PARKING_BAY","AISLE","RAMP","STRUCTURAL_OBSTACLE","CORE","MANEUVER_CLEARANCE"},
 },
 "ROOF_PLAN":{
   "context":{"BUILDING_OVERALL","GRID","SHAFT","STAIR"},
   "targets":{"ROOF_DRAIN","PARAPET","ROOF_EQUIPMENT","PENETRATION"},
 },
 "DETAIL":{"context":set(),"targets":{"DETAIL_SCOPE"}},
}

MECH_KIND={
 "shaft":"RISER","riser":"RISER","vertical":"RISER","stack":"STACK",
 "floor_drain":"FLOOR_DRAIN","roof_drain":"ROOF_DRAIN","cleanout":"CLEANOUT",
 "sleeve":"SLEEVE","penetration":"PENETRATION","mechanical_opening":"MECHANICAL_OPENING",
 "pump":"PUMP","tank":"TANK","indoor_unit":"INDOOR_UNIT","outdoor_unit":"OUTDOOR_UNIT",
}
ARCH_COLLECTIONS=[
 ("walls","WALL","P1"),("partitions","PARTITION","P1"),("shafts","SHAFT","P0"),
 ("stairs","STAIR","P1"),("openings","OPENING","P1"),("columns","STRUCTURE","P1"),
]


def _norm(v):return str(v or "").strip().lower()
def _mid(seg):return ((seg[0][0]+seg[1][0])/2.0,(seg[0][1]+seg[1][1])/2.0)
def _item_segment(item):
    a=item.get("start");b=item.get("end")
    if a and b and len(a)>=2 and len(b)>=2:return ((float(a[0]),float(a[1])),(float(b[0]),float(b[1])))
    pts=item.get("polygon") or item.get("points") or []
    pts=[(float(p[0]),float(p[1])) for p in pts if len(p)>=2]
    return (pts[0],pts[1]) if len(pts)>=2 else None
def _point(item):
    p=item.get("point") or item.get("center")
    if p and len(p)>=2:return (float(p[0]),float(p[1]))
    seg=_item_segment(item)
    return _mid(seg) if seg else None


def collect_profile_elements(profile,architecture=None,pipeline=None,plan_id=None):
    policy=PROFILE_POLICIES.get(profile)
    if not policy:return {"status":"FAIL","errors":["UNSUPPORTED_DRAWING_PROFILE"],"elements":[]}
    architecture=architecture or {};pipeline=pipeline or {};rows=[]
    if profile=="ARCHITECTURAL_FLOOR_PLAN":
        for key,kind,priority in ARCH_COLLECTIONS:
            for i,item in enumerate(architecture.get(key) or []):
                if not isinstance(item,dict) or (plan_id and item.get("plan_id") not in (None,plan_id)):continue
                p=_point(item)
                if not p:continue
                eid=str(item.get("id") or f"{kind}-{i:04d}")
                seg=_item_segment(item)
                if seg:
                    start_host=item.get("start_reference_id") or item.get("start_host_reference_id")
                    end_host=item.get("end_reference_id") or item.get("end_host_reference_id")
                    required_dofs=["OFFSET"]
                    if not start_host: required_dofs.append("START")
                    if not end_host: required_dofs.append("END")
                    rows.append({"id":eid,"kind":kind,"point":p,"geometry_kind":"LINE","segment":seg,
                                 "priority_class":priority,"required_constraints":len(required_dofs),
                                 "required_dofs":required_dofs,"start_host_reference_id":start_host,
                                 "end_host_reference_id":end_host,"intrinsically_hosted":False})
                else:
                    rows.append({"id":eid,"kind":kind,"point":p,"geometry_kind":"POINT",
                                 "priority_class":priority,"required_constraints":2,
                                 "required_dofs":["LOC_0","LOC_1"],"intrinsically_hosted":bool(item.get("host_id"))})
    elif profile=="MECHANICAL_PLAN":
        for i,node in enumerate((pipeline.get("topology") or {}).get("nodes") or []):
            if not isinstance(node,dict) or (plan_id and node.get("plan_id") not in (None,plan_id)):continue
            p=_point(node)
            if not p:continue
            kind=MECH_KIND.get(_norm(node.get("kind")))
            if not kind and _norm(node.get("category"))=="equipment":kind="EQUIPMENT"
            if kind not in policy["targets"]:continue
            rows.append({"id":str(node.get("id") or f"MECH-{i:04d}"),"kind":kind,"point":p,"geometry_kind":"POINT",
                         "priority_class":"P0" if kind in {"RISER","STACK","PENETRATION"} else "P1",
                         "required_dofs":[] if node.get("host_reference_id") else ["LOC_0","LOC_1"],
                         "required_constraints":0 if node.get("host_reference_id") else 2,
                         "intrinsically_hosted":bool(node.get("host_reference_id"))})
        for i,e in enumerate((pipeline.get("hvac") or {}).get("equipment") or []):
            if not isinstance(e,dict) or (plan_id and e.get("plan_id") not in (None,plan_id)):continue
            p=_point(e)
            if p:rows.append({"id":str(e.get("id") or f"EQUIPMENT-{i:04d}"),"kind":"EQUIPMENT","point":p,
                              "geometry_kind":"POINT","priority_class":"P1",
                              "required_dofs":[] if e.get("host_reference_id") else ["LOC_0","LOC_1"],
                              "required_constraints":0 if e.get("host_reference_id") else 2,
                              "intrinsically_hosted":bool(e.get("host_reference_id"))})
    else:
        # Parking/Roof/Detail use explicit semantic collections; no geometry guessing.
        key={"PARKING_PLAN":"parking_dimension_targets","ROOF_PLAN":"roof_dimension_targets","DETAIL":"detail_dimension_targets"}[profile]
        for i,item in enumerate(architecture.get(key) or []):
            if not isinstance(item,dict) or (plan_id and item.get("plan_id") not in (None,plan_id)):continue
            p=_point(item)
            if p:rows.append({"id":str(item.get("id") or f"{profile}-{i:04d}"),"kind":str(item.get("kind") or "DETAIL_SCOPE").upper(),
                              "point":p,"geometry_kind":str(item.get("geometry_kind") or "POINT"),"priority_class":str(item.get("priority_class") or "P1"),
                              "intrinsically_hosted":bool(item.get("host_reference_id"))})
    seen=set();dedup=[]
    for r in rows:
        k=(r["id"],round(r["point"][0],8),round(r["point"][1],8))
        if k not in seen:seen.add(k);dedup.append(r)
    return {"status":"PASS","errors":[],"elements":dedup,"policy":policy}


def _segment(ref):
    g=ref.get("geometry") or {}
    if g.get("type")=="SEGMENT":return tuple(g["a"]),tuple(g["b"])
    return None

def _projection(point,a,b):
    px,py=point;ax,ay=a;bx,by=b;vx,vy=bx-ax,by-ay
    den=vx*vx+vy*vy
    if den<=1e-18:return a,math.dist(point,a)
    t=((px-ax)*vx+(py-ay)*vy)/den;t=max(0.0,min(1.0,t))
    q=(ax+t*vx,ay+t*vy);return q,math.dist(point,q)

def _axis_deg(a,b):return math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))%180.0
def _axis_delta(a,b):
    d=abs((a-b)%180.0);return min(d,180.0-d)


def _ranked_datum(point,stable,datum_axis,exclude_element_id=None):
    ranked=[]
    for ref in stable:
        if exclude_element_id and str(ref.get("element_id") or "")==str(exclude_element_id):continue
        seg=_segment(ref)
        if not seg:continue
        if _axis_delta(_axis_deg(*seg),datum_axis)>7.5:continue
        q,dist=_projection(point,*seg)
        ranked.append((int(ref.get("priority",50)),dist,-float(ref.get("confidence",1.0)),str(ref.get("id")),ref,q))
    return min(ranked,key=lambda x:(x[0],x[1],x[2],x[3])) if ranked else None


def _target_subfeature(kind):
    if kind in {"RISER","STACK"}:return "PIPE_RISER_CENTER"
    if kind in {"PENETRATION","SLEEVE"}:return "PENETRATION_CENTER"
    return "EQUIPMENT_CENTER"


def generate_setout_candidates(elements,reference_model,profile):
    """Generate explainable candidates for every unresolved locating DOF."""
    refs=reference_model.get("references") or [];axis=float(reference_model.get("local_axis_deg") or 0.0)
    stable=[r for r in refs if r.get("subfeature") in {"GRID_AXIS","GRID_INTERSECTION","STRUCTURAL_CENTERLINE","STRUCTURAL_FACE",
        "WALL_CORE_FACE","WALL_INNER_FINISH_FACE","WALL_OUTER_FINISH_FACE","BUILDING_ENVELOPE_FACE","PROPERTY_BOUNDARY",
        "SHAFT_FACE","STAIR_CORE_FACE","OPENING_JAMB"}]
    intents=[];reviews=[]
    for e in elements or []:
        if e.get("intrinsically_hosted"):continue
        required=list(e.get("required_dofs") or (["LOC_0","LOC_1"] if e.get("geometry_kind")=="POINT" else ["OFFSET","START","END"]))
        created=set()
        if e.get("geometry_kind")=="POINT":
            p=e["point"]
            for ai,wanted in enumerate((axis,(axis+90.0)%180.0)):
                dof=f"LOC_{ai}"
                if dof not in required:continue
                datum_axis=(wanted+90.0)%180.0
                ranked=_ranked_datum(p,stable,datum_axis,e.get("id"))
                if not ranked:continue
                _,dist,_,_,ref,q=ranked
                if dist<=1e-8:
                    # Coincidence is valid only when an explicit host says so;
                    # otherwise it is evidence but not a displayed dimension.
                    continue
                purpose={"RISER":"RISER","SLEEVE":"SLEEVE","PENETRATION":"PENETRATION","EQUIPMENT":"EQUIPMENT_POSITION"}.get(e["kind"],"CONSTRUCTION_CLEARANCE")
                intents.append({"id":f"V2-{profile}-{e['id']}-{dof}","purpose":purpose,"role":"SETOUT","drawing_profile":profile,
                    "plan_id":ref.get("plan_id"),"priority_class":e.get("priority_class","P1"),"required":False,
                    "constraint_dof":dof,"reference_a":{"id":e["id"],"element_id":e["id"],"subfeature":_target_subfeature(e["kind"])},
                    "reference_b":ref,"world_p1":p,"world_p2":q,"measured_value":dist,"engineering_value_m":None,
                    "display_value":None,"orientation":f"LOCAL_AXIS_{ai}","datum_class":ref.get("datum_class"),
                    "axis_deg":wanted,"evidence":("profile_requirement","stable_datum",dof)})
                created.add(dof)
        else:
            seg=e.get("segment")
            if not seg:
                reviews.append({"element_id":e["id"],"reason":"LINE_GEOMETRY_REQUIRED","required_dofs":required});continue
            a,b=seg
            line_axis=_axis_deg(a,b);normal_axis=(line_axis+90.0)%180.0
            mid=((a[0]+b[0])/2.0,(a[1]+b[1])/2.0)
            if "OFFSET" in required:
                ranked=_ranked_datum(mid,stable,line_axis,e.get("id"))
                if ranked:
                    _,dist,_,_,ref,q=ranked
                    if dist>1e-8:
                        intents.append({"id":f"V2-{profile}-{e['id']}-OFFSET","purpose":"WALL_SETOUT","role":"SETOUT",
                          "drawing_profile":profile,"priority_class":e.get("priority_class","P1"),"required":False,
                          "constraint_dof":"OFFSET","reference_a":{"id":e["id"],"element_id":e["id"],"subfeature":"WALL_CORE_FACE"},
                          "reference_b":ref,"world_p1":mid,"world_p2":q,"measured_value":dist,"engineering_value_m":None,
                          "display_value":None,"orientation":"NORMAL_OFFSET","datum_class":ref.get("datum_class"),
                          "axis_deg":normal_axis,"evidence":("profile_requirement","line_offset")})
                        created.add("OFFSET")
            for label,p in (("START",a),("END",b)):
                if label not in required:continue
                # Endpoint position along the wall axis is located from a datum
                # perpendicular to that axis.
                ranked=_ranked_datum(p,stable,normal_axis,e.get("id"))
                if ranked:
                    _,dist,_,_,ref,q=ranked
                    if dist>1e-8:
                        intents.append({"id":f"V2-{profile}-{e['id']}-{label}","purpose":"WALL_SETOUT","role":"SETOUT",
                          "drawing_profile":profile,"priority_class":e.get("priority_class","P1"),"required":False,
                          "constraint_dof":label,"reference_a":{"id":f"{e['id']}/{label}","element_id":e["id"],"subfeature":"WALL_CORE_FACE"},
                          "reference_b":ref,"world_p1":p,"world_p2":q,"measured_value":dist,"engineering_value_m":None,
                          "display_value":None,"orientation":"ALONG_WALL","datum_class":ref.get("datum_class"),
                          "axis_deg":line_axis,"evidence":("profile_requirement","line_extent",label)})
                        created.add(label)
        missing=[d for d in required if d not in created]
        if missing:
            reviews.append({"element_id":e["id"],"reason":"UNRESOLVED_ELEMENT_DOF","missing_dofs":missing,"required_dofs":required})
    return {"status":"HUMAN_REVIEW_REQUIRED" if reviews else "PASS","intents":intents,"human_review":reviews}

def _midpoint(ref):
    seg=_segment(ref)
    return ((seg[0][0]+seg[1][0])/2.0,(seg[0][1]+seg[1][1])/2.0) if seg else None

def _project_scalar(point,axis_deg):
    a=math.radians(axis_deg);return point[0]*math.cos(a)+point[1]*math.sin(a)

def generate_context_intents(reference_model,profile):
    """Generate only profile-required global/context dimensions from proven semantics."""
    policy=PROFILE_POLICIES.get(profile) or {"context":set()}
    refs=reference_model.get("references") or [];axis=float(reference_model.get("local_axis_deg") or 0.0)
    rows=[]
    env=[r for r in refs if r.get("subfeature")=="BUILDING_ENVELOPE_FACE"]
    if "BUILDING_OVERALL" in policy["context"] and env:
        for ai,measure_axis in enumerate((axis,(axis+90.0)%180.0)):
            face_axis=(measure_axis+90.0)%180.0
            candidates=[]
            for r in env:
                seg=_segment(r)
                if not seg or _axis_delta(_axis_deg(*seg),face_axis)>7.5:continue
                mid=_midpoint(r);candidates.append((_project_scalar(mid,measure_axis),r,mid))
            if len(candidates)>=2:
                candidates.sort(key=lambda x:x[0]);lo,hi=candidates[0],candidates[-1]
                value=abs(hi[0]-lo[0])
                if value>1e-8:
                    rows.append({"id":f"V2-{profile}-OVERALL-{ai}","purpose":"BUILDING_OVERALL","role":"CHECK",
                        "drawing_profile":profile,"priority_class":"P0","required":True,
                        "reference_a":lo[1],"reference_b":hi[1],"world_p1":lo[2],"world_p2":hi[2],
                        "measured_value":value,"engineering_value_m":None,"display_value":None,
                        "orientation":f"LOCAL_AXIS_{ai}","datum_class":"ENVELOPE","axis_deg":measure_axis,
                        "chain_id":f"OVERALL-{ai}","chain_role":"TOTAL","evidence":("semantic_envelope","profile_context")})
    if "GRID" in policy["context"]:
        grids=[r for r in refs if r.get("subfeature")=="GRID_AXIS" and _segment(r)]
        for ai,measure_axis in enumerate((axis,(axis+90.0)%180.0)):
            grid_axis=(measure_axis+90.0)%180.0
            g=[]
            for r in grids:
                seg=_segment(r)
                if _axis_delta(_axis_deg(*seg),grid_axis)>7.5:continue
                mid=_midpoint(r);g.append((_project_scalar(mid,measure_axis),r,mid))
            g=sorted(g,key=lambda x:(x[0],str(x[1].get("id"))))
            for j,(a,b) in enumerate(zip(g,g[1:])):
                value=abs(b[0]-a[0])
                if value<=1e-8:continue
                rows.append({"id":f"V2-{profile}-GRID-{ai}-{j}","purpose":"GRID","role":"SETOUT",
                    "drawing_profile":profile,"priority_class":"P0","required":True,
                    "reference_a":a[1],"reference_b":b[1],"world_p1":a[2],"world_p2":b[2],
                    "measured_value":value,"engineering_value_m":None,"display_value":None,
                    "orientation":f"LOCAL_AXIS_{ai}","datum_class":"GRID","axis_deg":measure_axis,
                    "chain_id":f"GRID-{ai}","chain_role":"PART","evidence":("semantic_grid","profile_context")})
    return rows


def generate_governed_requirement_intents(requirements,reference_model,profile,plan_id=None):
    refs={str(r.get("id")):r for r in reference_model.get("references") or []}
    allowed={"CODE_CLEARANCE","OPENING_SIZE","OPENING_POSITION","CONSTRUCTION_CLEARANCE","CHECK","SETOUT"}
    rows=[];errors=[]
    for i,req in enumerate(requirements or []):
        if not isinstance(req,dict) or (plan_id and req.get("plan_id") not in (None,plan_id)):continue
        rid=str(req.get("id") or f"GOV-{i:04d}");purpose=str(req.get("purpose") or "").upper()
        if purpose not in allowed:errors.append({"id":rid,"reason":"UNSUPPORTED_GOVERNED_PURPOSE"});continue
        rule_id=str(req.get("rule_id") or "")
        if purpose=="CODE_CLEARANCE" and not rule_id:errors.append({"id":rid,"reason":"CODE_CLEARANCE_RULE_ID_REQUIRED"});continue
        ra=refs.get(str(req.get("reference_a_id") or ""));rb=refs.get(str(req.get("reference_b_id") or ""))
        if not ra or not rb:errors.append({"id":rid,"reason":"STABLE_REFERENCE_REQUIRED"});continue
        try:
            p1=tuple(map(float,req["p1"][:2]));p2=tuple(map(float,req["p2"][:2]))
        except Exception:
            errors.append({"id":rid,"reason":"ACTUAL_GEOMETRY_REQUIRED"});continue
        measured=math.dist(p1,p2)
        minimum=req.get("minimum_value_m")
        if purpose=="CODE_CLEARANCE" and minimum is None:errors.append({"id":rid,"reason":"CANONICAL_MINIMUM_REQUIRED"});continue
        rows.append({"id":rid,"purpose":purpose,"role":"CHECK" if purpose in {"CODE_CLEARANCE","CHECK"} else "SETOUT",
          "drawing_profile":profile,"plan_id":plan_id,"priority_class":"P0" if purpose=="CODE_CLEARANCE" else "P1",
          "required":bool(req.get("required",True)),"rule_id":rule_id or None,"reference_a":ra,"reference_b":rb,
          "world_p1":p1,"world_p2":p2,"measured_value":measured,"engineering_value_m":req.get("actual_value_m"),
          "minimum_value_m":minimum,"display_value":None,"orientation":req.get("orientation"),"datum_class":req.get("datum_class"),
          "axis_deg":float(req.get("axis_deg",_axis_deg(p1,p2))),"evidence":("governed_requirement",rule_id) if rule_id else ("governed_requirement",)})
    return {"status":"FAIL" if errors else "PASS","intents":rows,"errors":errors}
