"""Shaft/lightwell/core clear-size and location dimensions."""
from __future__ import annotations
from ..model import intent

def shaft_intents(architecture, references, *, zone_id=None):
    out=[];errors=[];checkpoints=[]
    for collection in ("shafts","lightwells"):
        for idx,row in enumerate((architecture or {}).get(collection) or []):
            if zone_id and row.get("zone_id") not in (None,zone_id): continue
            eid=str(row.get("id") or f"{collection[:-1].upper()}-{idx:04d}")
            refs=[r for r in references or [] if str(r.get("element_id"))==eid and r.get("subfeature")=="SHAFT_FACE"]
            if len(refs)<4:
                checkpoints.append({"element_id":eid,"reason":"SHAFT_CLEAR_FACES_INCOMPLETE"}); continue
            xs=[];ys=[]
            for r in refs:
                for p in (r.get("a"),r.get("b")):
                    if p: xs.append(float(p[0]));ys.append(float(p[1]))
            x1,x2=min(xs),max(xs);y1,y2=min(ys),max(ys)
            vertical=sorted(refs,key=lambda r:sum(float(p[0]) for p in (r["a"],r["b"]))/2)
            horizontal=sorted(refs,key=lambda r:sum(float(p[1]) for p in (r["a"],r["b"]))/2)
            if x2-x1>1e-9:
                out.append(intent(f"SHAFT-{eid}-W","SHAFT",vertical[0],vertical[-1],(x1,(y1+y2)/2),(x2,(y1+y2)/2),
                                  priority=96,zone_id=zone_id,metadata={"shaft_role":"CLEAR_WIDTH"}))
            if y2-y1>1e-9:
                out.append(intent(f"SHAFT-{eid}-D","SHAFT",horizontal[0],horizontal[-1],((x1+x2)/2,y1),((x1+x2)/2,y2),
                                  priority=96,zone_id=zone_id,metadata={"shaft_role":"CLEAR_DEPTH"}))
    return {"intents":out,"errors":errors,"human_checkpoints":checkpoints}
