"""Parking geometry dimensions; regulatory checks require explicit rule evidence."""
from __future__ import annotations
from ..model import intent

def parking_intents(architecture,references,*,zone_id=None,code_requirements=None):
    out=[];errors=[];checkpoints=[]
    for collection,role in (("parking_spaces","BAY"),("drive_aisles","DRIVE_AISLE"),("ramps","RAMP")):
        for idx,row in enumerate((architecture or {}).get(collection) or []):
            if zone_id and row.get("zone_id") not in (None,zone_id):continue
            bounds=row.get("bounds")
            if not isinstance(bounds,(list,tuple)) or len(bounds)!=4:
                checkpoints.append({"element_id":row.get("id") or f"{role}-{idx}","reason":"PARKING_GEOMETRY_REQUIRED"});continue
            x1,y1,x2,y2=map(float,bounds)
            eid=str(row.get("id") or f"{role}-{idx:04d}")
            ra={"id":eid+":A","element_id":eid,"subfeature":"FINISH_FACE","kind":role}
            rb={"id":eid+":B","element_id":eid,"subfeature":"FINISH_FACE","kind":role}
            if x2>x1:
                out.append(intent(f"PARK-{eid}-W","LOCAL_CONSTRUCTION",ra,rb,(x1,(y1+y2)/2),(x2,(y1+y2)/2),priority=86,zone_id=zone_id,metadata={"parking_role":role}))
            if y2>y1:
                out.append(intent(f"PARK-{eid}-D","LOCAL_CONSTRUCTION",ra,rb,((x1+x2)/2,y1),((x1+x2)/2,y2),priority=86,zone_id=zone_id,metadata={"parking_role":role}))
    # Regulatory minimums are not inferred here; caller must provide governed
    # CODE_CLEARANCE requirements to the common requirement engine.
    return {"intents":out,"errors":errors,"human_checkpoints":checkpoints}
