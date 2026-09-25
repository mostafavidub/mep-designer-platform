"""Architectural dimension requirement generation from semantic geometry."""
from __future__ import annotations
import math
from .chains import build_dimension_chain
from .model import intent
from .profiles import normalize_profile, requirements_for
from .specialists import opening_intents, stair_intents, shaft_intents, site_intents, parking_intents

def _mid(ref):
    a=ref.get("a") or (0,0); b=ref.get("b") or a
    return ((float(a[0])+float(b[0]))/2,(float(a[1])+float(b[1]))/2)

def _axis_angle(ref):
    a=ref.get("a"); b=ref.get("b")
    if not a or not b or a==b:return None
    return math.atan2(b[1]-a[1],b[0]-a[0]) % math.pi

def _parallel_group(refs, target_angle, tol=math.radians(7)):
    out=[]
    for r in refs:
        a=_axis_angle(r)
        if a is None: continue
        diff=abs((a-target_angle)%math.pi); diff=min(diff,math.pi-diff)
        if diff<=tol: out.append(r)
    return out

def _building_overall(references, frame, zone_id):
    exterior=[r for r in references or [] if r.get("subfeature") in {"FINISH_FACE","OUTER_FACE"} and (r.get("metadata") or {}).get("exterior")]
    if len(exterior)<2:return [],[{"reason":"PROVEN_EXTERIOR_ENVELOPE_REQUIRED"}]
    angle=math.radians(float(frame.get("angle_deg") or 0))
    primary_parallel=_parallel_group(exterior,angle+math.pi/2)
    secondary_parallel=_parallel_group(exterior,angle)
    out=[];errors=[]
    for idx,(rows,axis) in enumerate(((primary_parallel,"PRIMARY"),(secondary_parallel,"SECONDARY"))):
        if len(rows)<2:
            errors.append({"reason":"BUILDING_OVERALL_AXIS_INCOMPLETE","axis":axis});continue
        result=build_dimension_chain(rows,frame,purpose="BUILDING_OVERALL",axis=axis,
                                     chain_id=f"OVERALL-{zone_id}-{frame['id']}-{idx}",add_check=False,zone_id=zone_id)
        if result["intents"]:
            # Only the extreme overall is wanted, not intermediate envelope segments.
            ints=result["intents"]
            if len(ints)>1:
                first=ints[0]["reference_a"]; last=ints[-1]["reference_b"]
                p1=ints[0]["world_p1"]; p2=ints[-1]["world_p2"]
                out.append(intent(f"OVERALL-{zone_id}-{frame['id']}-{idx}","BUILDING_OVERALL",first,last,p1,p2,
                                  priority=98,zone_id=zone_id,coordinate_frame_id=frame["id"],tier=1))
            else:
                row=ints[0];row["tier"]=1;out.append(row)
        else: errors.extend(result["errors"])
    return out,errors

def _grid_chains(references, frame, zone_id):
    grids=[r for r in references or [] if r.get("subfeature")=="GRID_AXIS"]
    if len(grids)<2:return [],[]
    angle=math.radians(float(frame.get("angle_deg") or 0))
    groups=[(_parallel_group(grids,angle+math.pi/2),"PRIMARY"),(_parallel_group(grids,angle),"SECONDARY")]
    out=[];errors=[]
    for idx,(rows,axis) in enumerate(groups):
        if len(rows)<2:continue
        r=build_dimension_chain(rows,frame,purpose="GRID",axis=axis,chain_id=f"GRID-{zone_id}-{frame['id']}-{idx}",
                                add_check=True,zone_id=zone_id)
        for row in r["intents"]:row["tier"]=2
        out.extend(r["intents"]);errors.extend(r["errors"])
    return out,errors

def _wall_chains(references, frame, zone_id):
    walls=[r for r in references or [] if r.get("kind")=="WALL" and r.get("subfeature") in {"FINISH_FACE","CORE_FACE","CENTERLINE"}]
    if len(walls)<2:return [],[]
    angle=math.radians(float(frame.get("angle_deg") or 0))
    out=[];errors=[]
    for idx,(rows,axis) in enumerate(((_parallel_group(walls,angle+math.pi/2),"PRIMARY"),(_parallel_group(walls,angle),"SECONDARY"))):
        if len(rows)<2:continue
        # Keep one reference basis per chain; never mix finish/core/centerline.
        by_class={}
        for r in rows:by_class.setdefault(r.get("reference_class"),[]).append(r)
        for cls,subset in by_class.items():
            if len(subset)<2:continue
            result=build_dimension_chain(subset,frame,purpose="WALL_SETOUT",axis=axis,
                                         chain_id=f"WALL-{zone_id}-{frame['id']}-{idx}-{cls}",add_check=True,zone_id=zone_id)
            out.extend(result["intents"]);errors.extend(result["errors"])
    return out,errors

def _room_clear(architecture, zone_id):
    out=[];checkpoints=[]
    for idx,room in enumerate((architecture or {}).get("rooms") or []):
        if zone_id and room.get("zone_id") not in (None,zone_id):continue
        rid=str(room.get("id") or f"ROOM-{idx:04d}")
        bounds=room.get("clear_bounds") or room.get("bounds")
        if not isinstance(bounds,(list,tuple)) or len(bounds)!=4:
            checkpoints.append({"element_id":rid,"reason":"ROOM_CLEAR_BASIS_NOT_PROVEN"});continue
        if str(room.get("dimension_clear_basis") or "FINISH").upper()!="FINISH":
            checkpoints.append({"element_id":rid,"reason":"ROOM_FINISH_FACE_BASIS_REQUIRED"});continue
        x1,y1,x2,y2=map(float,bounds)
        refs=[
            {"id":rid+":LEFT","element_id":rid,"kind":"ROOM","subfeature":"FINISH_FACE","reference_class":"FINISH"},
            {"id":rid+":RIGHT","element_id":rid,"kind":"ROOM","subfeature":"FINISH_FACE","reference_class":"FINISH"},
            {"id":rid+":BOTTOM","element_id":rid,"kind":"ROOM","subfeature":"FINISH_FACE","reference_class":"FINISH"},
            {"id":rid+":TOP","element_id":rid,"kind":"ROOM","subfeature":"FINISH_FACE","reference_class":"FINISH"},
        ]
        if x2>x1:out.append(intent(f"ROOM-{rid}-W","ROOM_CLEAR",refs[0],refs[1],(x1,(y1+y2)/2),(x2,(y1+y2)/2),required=False,priority=50,zone_id=zone_id))
        if y2>y1:out.append(intent(f"ROOM-{rid}-D","ROOM_CLEAR",refs[2],refs[3],((x1+x2)/2,y1),((x1+x2)/2,y2),required=False,priority=50,zone_id=zone_id))
    return out,checkpoints

def build_requirements(architecture,references,frame,profile,*,zone_id=None,code_requirements=None):
    profile=normalize_profile(profile); allowed=requirements_for(profile)
    intents=[];errors=[];checkpoints=[];sections={}
    if "BUILDING_OVERALL" in allowed:
        rows,errs=_building_overall(references,frame,zone_id);intents+=rows;errors+=errs;sections["BUILDING_OVERALL"]=len(rows)
    if "GRID" in allowed:
        rows,errs=_grid_chains(references,frame,zone_id);intents+=rows;errors+=errs;sections["GRID"]=len(rows)
    if "WALL_SETOUT" in allowed:
        rows,errs=_wall_chains(references,frame,zone_id);intents+=rows;errors+=errs;sections["WALL_SETOUT"]=len(rows)
    if "ROOM_CLEAR" in allowed:
        rows,cp=_room_clear(architecture,zone_id);intents+=rows;checkpoints+=cp;sections["ROOM_CLEAR"]=len(rows)
    if "OPENING" in allowed:
        r=opening_intents(architecture,references,zone_id=zone_id);intents+=r["intents"];errors+=r["errors"];checkpoints+=r["human_checkpoints"];sections["OPENING"]=len(r["intents"])
    if "STAIR_CORE" in allowed:
        r=stair_intents(architecture,references,zone_id=zone_id);intents+=r["intents"];errors+=r["errors"];checkpoints+=r["human_checkpoints"];sections["STAIR_CORE"]=len(r["intents"])
    if "SHAFT" in allowed:
        r=shaft_intents(architecture,references,zone_id=zone_id);intents+=r["intents"];errors+=r["errors"];checkpoints+=r["human_checkpoints"];sections["SHAFT"]=len(r["intents"])
    if profile=="SITE_PLAN":
        r=site_intents(architecture,references,zone_id=zone_id,code_requirements=code_requirements);intents+=r["intents"];errors+=r["errors"];checkpoints+=r["human_checkpoints"];sections["SITE"]=len(r["intents"])
    if profile=="PARKING_PLAN":
        r=parking_intents(architecture,references,zone_id=zone_id,code_requirements=code_requirements);intents+=r["intents"];errors+=r["errors"];checkpoints+=r["human_checkpoints"];sections["PARKING"]=len(r["intents"])
    return {"profile":profile,"intents":intents,"errors":errors,"human_checkpoints":checkpoints,"sections":sections}
