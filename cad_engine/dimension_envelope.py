"""Semantic building-envelope extraction for Dimension Engine v2."""
from __future__ import annotations
import math


def _pt(p): return (round(float(p[0]),8),round(float(p[1]),8))
def _area(poly):
    return abs(sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly)))/2.0) if len(poly)>=3 else 0.0


def _explicit_polygons(architecture,plan_id):
    rows=[]
    for key in ("building_envelopes","envelopes","courtyards"):
        for i,item in enumerate((architecture or {}).get(key) or []):
            if not isinstance(item,dict) or (plan_id and item.get("plan_id") not in (None,plan_id)): continue
            pts=item.get("polygon") or item.get("points") or []
            pts=[_pt(p) for p in pts if len(p)>=2]
            if len(pts)>=3:
                rows.append({"id":str(item.get("id") or f"{key.upper()}-{i}"),"points":pts,
                             "kind":"COURTYARD_BOUNDARY" if key=="courtyards" else str(item.get("kind") or "PRIMARY_ENVELOPE").upper(),
                             "source":"explicit_semantic","confidence":1.0})
    return rows


def _exterior_segments(architecture,plan_id):
    segs=[]
    for i,w in enumerate((architecture or {}).get("walls") or []):
        if not isinstance(w,dict) or (plan_id and w.get("plan_id") not in (None,plan_id)): continue
        if w.get("exterior") is not True and w.get("is_exterior") is not True: continue
        a=w.get("start");b=w.get("end")
        if a and b and len(a)>=2 and len(b)>=2 and _pt(a)!=_pt(b):
            segs.append({"id":str(w.get("id") or f"WALL-{i}"),"a":_pt(a),"b":_pt(b)})
    return segs


def _closed_loops(segments):
    if not segments:return []
    unused=list(segments);loops=[]
    while unused:
        first=unused.pop(0);start=first["a"];cur=first["b"];pts=[start,cur];guard=0
        while cur!=start and guard<10000:
            guard+=1
            match=None
            for j,s in enumerate(unused):
                if s["a"]==cur: match=(j,s["b"]);break
                if s["b"]==cur: match=(j,s["a"]);break
            if match is None: break
            j,nxt=match;unused.pop(j);cur=nxt
            if cur!=start: pts.append(cur)
        if cur==start and len(pts)>=3: loops.append(pts)
    return loops


def _rectangular_equivalence(poly):
    if len(poly)!=4:return False
    xs=sorted(set(round(p[0],8) for p in poly));ys=sorted(set(round(p[1],8) for p in poly))
    return len(xs)==2 and len(ys)==2 and set(poly)=={(xs[0],ys[0]),(xs[0],ys[1]),(xs[1],ys[0]),(xs[1],ys[1])}


def build_envelope_model(architecture,plan_id=None):
    """Return semantic envelope; never promotes a bounding box unless equivalence is proven."""
    explicit=_explicit_polygons(architecture,plan_id)
    if explicit:
        ordered=sorted(explicit,key=lambda r:_area(r["points"]),reverse=True)
        for i,row in enumerate(ordered):
            if row["kind"]=="PRIMARY_ENVELOPE" or i==0: row["role"]="PRIMARY"
            elif row["kind"]=="COURTYARD_BOUNDARY": row["role"]="COURTYARD"
            else: row["role"]="SECONDARY"
        return {"status":"PASS","envelopes":ordered,"human_review":[],"bbox_fallback_used":False}

    loops=_closed_loops(_exterior_segments(architecture,plan_id))
    if loops:
        ordered=sorted(loops,key=_area,reverse=True)
        rows=[]
        for i,poly in enumerate(ordered):
            rows.append({"id":f"ENVELOPE-{i+1}","points":poly,"kind":"PRIMARY_ENVELOPE" if i==0 else "COURTYARD_BOUNDARY",
                         "role":"PRIMARY" if i==0 else "COURTYARD","source":"explicit_exterior_wall_loop",
                         "confidence":0.98,"bbox_equivalent":_rectangular_equivalence(poly)})
        return {"status":"PASS","envelopes":rows,"human_review":[],"bbox_fallback_used":False}

    return {"status":"HUMAN_REVIEW_REQUIRED","envelopes":[],"human_review":["BUILDING_ENVELOPE_NOT_PROVEN"],"bbox_fallback_used":False}


def envelope_edges(model):
    refs=[]
    for env in (model or {}).get("envelopes") or []:
        pts=env.get("points") or []
        for i,a in enumerate(pts):
            b=pts[(i+1)%len(pts)]
            refs.append({"id":f"{env['id']}-FACE-{i+1}","element_id":env["id"],"subfeature":"BUILDING_ENVELOPE_FACE",
                         "geometry":{"type":"SEGMENT","a":a,"b":b},"source":env.get("source"),"confidence":env.get("confidence",1.0),
                         "datum_class":"ENVELOPE","evidence":("semantic_envelope",)})
    return refs
