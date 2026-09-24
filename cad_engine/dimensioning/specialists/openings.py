"""Door/window/opening size and position dimensioning."""
from __future__ import annotations
import math
from ..model import intent

def _point_ref(refs, element_id, subfeature):
    for r in refs or []:
        if str(r.get("element_id"))==str(element_id) and r.get("subfeature")==subfeature:
            a=r.get("a") or (0,0); b=r.get("b") or a
            return r,((a[0]+b[0])/2,(a[1]+b[1])/2)
    return None,None

def opening_intents(architecture, references, *, zone_id=None):
    out=[]; errors=[]; checkpoints=[]
    stable=[r for r in references or [] if r.get("subfeature") in {"GRID_AXIS","FINISH_FACE","CORE_FACE","CENTERLINE"}]
    for collection in ("doors","windows","openings"):
        for idx,row in enumerate((architecture or {}).get(collection) or []):
            if zone_id and row.get("zone_id") not in (None,zone_id):
                continue
            eid=str(row.get("id") or f"{collection[:-1].upper()}-{idx:04d}")
            left,lp=_point_ref(references,eid,"OPENING_JAMB_LEFT")
            right,rp=_point_ref(references,eid,"OPENING_JAMB_RIGHT")
            if not left or not right:
                errors.append({"element_id":eid,"reason":"OPENING_JAMBS_REQUIRED"}); continue
            if math.dist(lp,rp)>1e-9:
                out.append(intent(f"OPEN-{eid}-WIDTH","OPENING",left,right,lp,rp,priority=92,zone_id=zone_id,
                                  metadata={"opening_role":"SIZE","host_wall_id":row.get("host_wall_id")}))
            host=str(row.get("host_wall_id") or "")
            if not host:
                checkpoints.append({"element_id":eid,"reason":"OPENING_HOST_UNCERTAIN"}); continue
            datum_candidates=[r for r in stable if str(r.get("element_id"))==host or r.get("subfeature")=="GRID_AXIS"]
            if not datum_candidates:
                checkpoints.append({"element_id":eid,"reason":"OPENING_STABLE_DATUM_REQUIRED"}); continue
            # Prefer host-wall reference, then grid. Use nearest line projection.
            best=None
            for ref in datum_candidates:
                a=ref.get("a"); b=ref.get("b")
                if not a or not b or a==b: continue
                vx=b[0]-a[0]; vy=b[1]-a[1]; den=vx*vx+vy*vy
                t=((lp[0]-a[0])*vx+(lp[1]-a[1])*vy)/den
                q=(a[0]+max(0,min(1,t))*vx,a[1]+max(0,min(1,t))*vy)
                d=math.dist(lp,q)
                score=(0 if str(ref.get("element_id"))==host else 1,d)
                if best is None or score<best[0]: best=(score,ref,q,d)
            if best and best[3]>1e-9:
                out.append(intent(f"OPEN-{eid}-POS","OPENING",best[1],left,best[2],lp,priority=90,zone_id=zone_id,
                                  metadata={"opening_role":"POSITION","host_wall_id":host}))
    return {"intents":out,"errors":errors,"human_checkpoints":checkpoints}
