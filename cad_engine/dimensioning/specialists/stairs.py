"""Specialist stair/core dimensions without inventing code minima."""
from __future__ import annotations
from ..model import intent

def stair_intents(architecture, references, *, zone_id=None):
    out=[]; errors=[]; checkpoints=[]
    for idx,row in enumerate((architecture or {}).get("stairs") or []):
        if zone_id and row.get("zone_id") not in (None,zone_id): continue
        eid=str(row.get("id") or f"STAIR-{idx:04d}")
        refs=[r for r in references or [] if str(r.get("element_id"))==eid and r.get("subfeature") in {"STAIR_EDGE","LANDING_EDGE"}]
        if len(refs)<2:
            checkpoints.append({"element_id":eid,"reason":"STAIR_GEOMETRY_INCOMPLETE"}); continue
        xs=[];ys=[]
        for r in refs:
            for p in (r.get("a"),r.get("b")):
                if p: xs.append(float(p[0]));ys.append(float(p[1]))
        x1,x2=min(xs),max(xs);y1,y2=min(ys),max(ys)
        left=min(refs,key=lambda r:(r["a"][0]+r["b"][0])/2); right=max(refs,key=lambda r:(r["a"][0]+r["b"][0])/2)
        bottom=min(refs,key=lambda r:(r["a"][1]+r["b"][1])/2); top=max(refs,key=lambda r:(r["a"][1]+r["b"][1])/2)
        if x2-x1>1e-9:
            out.append(intent(f"STAIR-{eid}-W","STAIR_CORE",left,right,(x1,(y1+y2)/2),(x2,(y1+y2)/2),
                              priority=95,zone_id=zone_id,metadata={"stair_role":"OVERALL_WIDTH"}))
        if y2-y1>1e-9:
            out.append(intent(f"STAIR-{eid}-D","STAIR_CORE",bottom,top,((x1+x2)/2,y1),((x1+x2)/2,y2),
                              priority=95,zone_id=zone_id,metadata={"stair_role":"OVERALL_DEPTH"}))
        # Flight/landing/riser/tread dimensions are generated only from explicit
        # semantic fields. No regulatory minimum is inferred here.
        if row.get("flight_width") is None:
            checkpoints.append({"element_id":eid,"reason":"STAIR_FLIGHT_SEMANTICS_NOT_PROVEN"})
    return {"intents":out,"errors":errors,"human_checkpoints":checkpoints}
