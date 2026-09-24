"""Placement intent planning; engineering values are immutable."""
from __future__ import annotations

EXTERNAL_PURPOSES={"BUILDING_OVERALL","GRID","PROPERTY","SETBACK","CHECK"}

def assign_dimension_zones(intents):
    """Assign deterministic presentation zones/tiers without changing measurement."""
    out=[]
    counters={"EXTERNAL":0,"LOCAL":0}
    for row in intents or []:
        item=dict(row)
        if item.get("purpose") in EXTERNAL_PURPOSES:
            counters["EXTERNAL"]+=1
            item["placement_zone"]="EXTERNAL"
            if item.get("tier") is None:
                item["tier"]={"BUILDING_OVERALL":1,"GRID":2,"PROPERTY":3,"SETBACK":3,"CHECK":3}.get(item.get("purpose"),2)
        else:
            counters["LOCAL"]+=1
            item["placement_zone"]="LOCAL"
            if item.get("tier") is None:item["tier"]=0
        out.append(item)
    return {"intents":out,"counts":counters}

def extension_line_qa(placed_intents, obstacles=None):
    """Conservative geometric extension-line check using supplied obstacle boxes."""
    obstacles=list(obstacles or []); errors=[]
    for row in placed_intents or []:
        p1=row.get("render_p1") or row.get("world_p1");p2=row.get("render_p2") or row.get("world_p2");base=row.get("render_base")
        if not p1 or not p2 or not base:continue
        for label,p in (("A",p1),("B",p2)):
            box=_segment_box(p,base)
            for idx,obs in enumerate(obstacles):
                if _overlap(box,obs):
                    errors.append({"intent_id":row.get("id"),"reason":"EXTENSION_LINE_OBSTACLE_CROSSING","endpoint":label,"obstacle":idx})
                    break
    return {"status":"PASS" if not errors else "FAIL","errors":errors}

def _segment_box(a,b,pad=.005):
    return (min(a[0],b[0])-pad,min(a[1],b[1])-pad,max(a[0],b[0])+pad,max(a[1],b[1])+pad)

def _overlap(a,b):
    return not (a[2]<b[0] or b[2]<a[0] or a[3]<b[1] or b[3]<a[1])
