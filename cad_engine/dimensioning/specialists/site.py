"""Property/building/setback dimensions with governed regulatory separation."""
from __future__ import annotations
import math
from ..model import intent

def _mid(ref):
    a=ref["a"];b=ref["b"];return ((a[0]+b[0])/2,(a[1]+b[1])/2)

def _nearest_pair(a_refs,b_refs):
    best=None
    for a in a_refs:
        for b in b_refs:
            pa=_mid(a);pb=_mid(b);d=math.dist(pa,pb)
            if best is None or d<best[0]:best=(d,a,b,pa,pb)
    return best

def site_intents(architecture,references,*,zone_id=None,code_requirements=None):
    out=[];errors=[];checkpoints=[]
    prop=[r for r in references or [] if r.get("subfeature")=="PROPERTY_EDGE"]
    building=[r for r in references or [] if r.get("subfeature") in {"OUTER_FACE","FINISH_FACE"} and (r.get("metadata") or {}).get("exterior")]
    if prop:
        xs=[];ys=[]
        for r in prop:
            for p in (r["a"],r["b"]):xs.append(p[0]);ys.append(p[1])
        if max(xs)-min(xs)>1e-9:
            left=min(prop,key=lambda r:_mid(r)[0]);right=max(prop,key=lambda r:_mid(r)[0])
            out.append(intent("SITE-PROPERTY-W","PROPERTY",left,right,(min(xs),(min(ys)+max(ys))/2),(max(xs),(min(ys)+max(ys))/2),priority=98,zone_id=zone_id))
        if max(ys)-min(ys)>1e-9:
            bot=min(prop,key=lambda r:_mid(r)[1]);top=max(prop,key=lambda r:_mid(r)[1])
            out.append(intent("SITE-PROPERTY-D","PROPERTY",bot,top,((min(xs)+max(xs))/2,min(ys)),((min(xs)+max(xs))/2,max(ys)),priority=98,zone_id=zone_id))
    else:
        checkpoints.append({"reason":"PROPERTY_BOUNDARY_REQUIRED"})
    if prop and building:
        pair=_nearest_pair(prop,building)
        if pair and pair[0]>1e-9:
            out.append(intent("SITE-SETBACK-01","SETBACK",pair[1],pair[2],pair[3],pair[4],priority=99,zone_id=zone_id,
                              metadata={"setback_role":"GEOMETRIC_ACTUAL"}))
    elif prop:
        checkpoints.append({"reason":"BUILDING_ENVELOPE_REQUIRED_FOR_SETBACK"})
    # CODE_CLEARANCE is never inferred from the geometric setback above.
    ref_by_id={str(r.get("id")):r for r in references or []}
    for idx,row in enumerate(code_requirements or []):
        if str(row.get("purpose") or "").upper()!="CODE_CLEARANCE":continue
        rid=str(row.get("rule_id") or "")
        a=ref_by_id.get(str(row.get("reference_a_id") or ""));b=ref_by_id.get(str(row.get("reference_b_id") or ""))
        if not rid or not a or not b or row.get("minimum_value_m") is None:
            errors.append({"id":str(row.get("id") or idx),"reason":"GOVERNED_CODE_CLEARANCE_INCOMPLETE"});continue
        pa=row.get("p1");pb=row.get("p2")
        if not pa or not pb:
            pa=_mid(a);pb=_mid(b)
        out.append(intent(f"SITE-CODE-{idx:02d}","CODE_CLEARANCE",a,b,pa,pb,priority=100,zone_id=zone_id,rule_id=rid,
                          metadata={"minimum_value_m":float(row["minimum_value_m"]),"jurisdiction":row.get("jurisdiction"),"requirement":row.get("requirement")}))
    return {"intents":out,"errors":errors,"human_checkpoints":checkpoints}
