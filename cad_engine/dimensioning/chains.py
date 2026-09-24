"""Dimension Chain Builder and closure logic."""
from __future__ import annotations
import math
from .model import intent, reference_class
from .coordinate_frames import project, unproject

def _anchor(ref):
    a=ref.get("a") or (0.0,0.0); b=ref.get("b") or a
    return ((float(a[0])+float(b[0]))/2, (float(a[1])+float(b[1]))/2)

def build_dimension_chain(references, frame, *, purpose="WALL_SETOUT", axis="PRIMARY",
                          chain_id="CHAIN-1", add_check=True, required=True, zone_id=None,
                          tolerance=1e-8):
    """Create consecutive dimensions only; never all pairwise distances."""
    refs=list(references or [])
    if len(refs)<2:
        return {"intents":[],"errors":["CHAIN_REQUIRES_TWO_REFERENCES"],"chain_id":chain_id}
    axis_index=0 if str(axis).upper()=="PRIMARY" else 1
    rows=[]
    for ref in refs:
        p=_anchor(ref); local=project(p,frame)
        rows.append((local[axis_index],local[1-axis_index],ref,p))
    rows.sort(key=lambda x:(x[0],x[1],str(x[2].get("id"))))
    collapsed=[]
    for row in rows:
        if collapsed and abs(row[0]-collapsed[-1][0]) <= tolerance:
            # Coincident refs do not create zero dimension segments.
            continue
        collapsed.append(row)
    out=[]
    # Measure only along the selected local axis. Midpoints of unequal-length
    # parallel references must not create a diagonal/euclidean false value.
    common_other=sum(row[1] for row in collapsed)/len(collapsed)
    def measure_point(row):
        local=(row[0],common_other) if axis_index==0 else (common_other,row[0])
        return unproject(local,frame)
    for idx,(left,right) in enumerate(zip(collapsed,collapsed[1:])):
        a=measure_point(left); b=measure_point(right)
        if math.dist(a,b)<=tolerance:
            continue
        out.append(intent(
            f"{chain_id}-S{idx+1:02d}",purpose,left[2],right[2],a,b,required=required,
            priority=80,chain_id=chain_id,coordinate_frame_id=frame["id"],zone_id=zone_id,
            metadata={"chain_role":"SEGMENT","reference_class":reference_class(left[2])},
        ))
    if add_check and len(collapsed)>=3:
        a=measure_point(collapsed[0]); b=measure_point(collapsed[-1])
        out.append(intent(
            f"{chain_id}-CHECK","CHECK",collapsed[0][2],collapsed[-1][2],a,b,
            required=False,priority=55,chain_id=chain_id,check_group_id=chain_id,
            coordinate_frame_id=frame["id"],zone_id=zone_id,
            metadata={"chain_role":"CHECK","reference_class":reference_class(collapsed[0][2])},
        ))
    return {"intents":out,"errors":[],"chain_id":chain_id,"reference_count":len(collapsed)}

def closure_check(intents, *, abs_tolerance=1e-8):
    groups={}
    for row in intents or []:
        cid=row.get("chain_id")
        if cid:
            groups.setdefault(cid,[]).append(row)
    results=[]; errors=[]
    for cid,rows in groups.items():
        seg=[r for r in rows if (r.get("metadata") or {}).get("chain_role")=="SEGMENT"]
        chk=[r for r in rows if (r.get("metadata") or {}).get("chain_role")=="CHECK"]
        if not chk:
            continue
        classes={reference_class(r.get("reference_a")) for r in rows}|{reference_class(r.get("reference_b")) for r in rows}
        classes.discard("UNKNOWN")
        if len(classes)>1:
            errors.append({"chain_id":cid,"reason":"INCOMPATIBLE_REFERENCE_CLASSES","classes":sorted(classes)})
            continue
        total=sum(float(r.get("measured_value") or 0.0) for r in seg)
        overall=float(chk[0].get("measured_value") or 0.0)
        ok=abs(total-overall)<=abs_tolerance
        results.append({"chain_id":cid,"segments":total,"overall":overall,"pass":ok})
        if not ok:
            errors.append({"chain_id":cid,"reason":"CHAIN_CLOSURE_FAILED","segments":total,"overall":overall})
    return {"status":"PASS" if not errors else "FAIL","results":results,"errors":errors}
