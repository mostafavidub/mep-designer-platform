"""Detect, classify, deduplicate and safely scope architectural drawings.

Frame detection is deliberately evidence based.  A rectangle is not a plan by
itself: repeated sheet geometry, a print-layer name, drawing titles and useful
content all contribute independently to an explainable confidence score.
Uncertain rectangles are reported but never promoted to mechanical authority.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import json
import math
import re
import ezdxf
from ezdxf import bbox


def _point(entity):
    for attr in ("insert","location","start","center"):
        try:
            p=getattr(entity.dxf,attr); return (float(p.x),float(p.y))
        except Exception: pass
    if entity.dxftype()=="LWPOLYLINE":
        pts=[(float(x),float(y)) for x,y,*_ in entity.get_points()]
        if pts: return (sum(x for x,y in pts)/len(pts),sum(y for x,y in pts)/len(pts))
    return None


def _inside(point,bounds,tol=1e-6):
    if not point:return False
    x,y=point; x1,y1,x2,y2=bounds
    return x1-tol<=x<=x2+tol and y1-tol<=y<=y2+tol


def _text(entity):
    try:
        return str(entity.dxf.text if entity.dxftype()=="TEXT" else entity.plain_text()).strip()
    except Exception:
        return ""


def _norm(value):
    value=str(value or "").replace("ي","ی").replace("ك","ک").replace("\u200c"," ").lower()
    return re.sub(r"\s+"," ",value).strip()


def _classify(text_blob):
    s=_norm(text_blob)
    if "نمای شمالی" in s or "نمای جنوبی" in s or "نمای شرقی" in s or "نمای غربی" in s:
        return "ELEVATION"
    if "برش" in s or re.search(r"\b[a-z]-[a-z]\b",s):
        return "SECTION"
    if ("پلان شیب بندی" in s or "پلان شیب‌بندی" in s or
            "پلان معماری پشت بام" in s or "پلان پشت بام" in s or
            "roof plan" in s):
        return "ROOF_PLAN"
    if "پلان نعل درگاه" in s:
        return "LINTEL_PLAN"
    if "پلان مبلمان" in s:
        return "FURNITURE_PLAN"
    if "پلان جانمایی پارکینگ" in s or "parking plan" in s:
        return "PARKING_PLAN"
    if "پلان خرپشته" in s:
        return "ROOF_PLAN"
    if ("پلان معماری" in s or "architectural plan" in s or
            "پلان نیم طبقه" in s or "پلان بالکن تجاری" in s):
        return "ARCH_FLOOR_PLAN"
    if "جزییات" in s or "جزئیات" in s or "detail" in s:
        return "DETAIL"
    return "UNKNOWN"


def _level(text_blob):
    s=_norm(text_blob)
    if "زیرزمین" in s or "basement" in s: return "BASEMENT"
    if "طبقه سوم" in s: return "LEVEL-03"
    if "طبقه دوم" in s: return "LEVEL-02"
    if "طبقه اول" in s: return "LEVEL-01"
    if "طبقه همکف" in s or re.search(r"\bground\b",s): return "GROUND"
    if "نیم طبقه" in s or "بالکن تجاری" in s: return "MEZZANINE"
    if "بام" in s or "شیب بندی" in s or "شیب‌بندی" in s: return "ROOF"
    return None


def _levels(text_blob):
    """Return every level explicitly represented by a drawing title."""
    s=_norm(text_blob); result=[]
    if "همکف" in s or re.search(r"\bground\b",s): result.append("GROUND")
    names=(("اول","LEVEL-01"),("دوم","LEVEL-02"),("سوم","LEVEL-03"),
           ("چهارم","LEVEL-04"),("پنجم","LEVEL-05"))
    # Persian ranges such as "طبقات اول تا سوم" are common typical plans.
    indices={word:i for i,(word,_) in enumerate(names)}
    match=re.search(r"طبقات?\s+(اول|دوم|سوم|چهارم|پنجم)\s+تا\s+(اول|دوم|سوم|چهارم|پنجم)",s)
    if match and indices[match.group(1)]<=indices[match.group(2)]:
        result.extend(level for _,level in names[indices[match.group(1)]:indices[match.group(2)]+1])
    else:
        for word,level in names:
            if f"طبقه {word}" in s: result.append(level)
    if "نیم طبقه" in s or "بالکن تجاری" in s: result.append("MEZZANINE")
    if "بام" in s or "شیب بندی" in s or "شیب‌بندی" in s: result.append("ROOF")
    return list(dict.fromkeys(result))


PRINT_LAYER_TOKENS=("suport","support","frame","sheet","border","کادر","قاب")


def _rect_bounds(entity):
    if entity.dxftype() not in {"LWPOLYLINE","POLYLINE"}: return None
    try:
        if entity.dxftype()=="LWPOLYLINE": pts=[(float(x),float(y)) for x,y,*_ in entity.get_points()]
        else: pts=[(float(v.dxf.location.x),float(v.dxf.location.y)) for v in entity.vertices]
    except Exception:return None
    if len(pts)<4 or not bool(getattr(entity,"closed",False)):return None
    if pts[0]==pts[-1]:pts=pts[:-1]
    if len(pts)!=4:return None
    xs=[p[0] for p in pts];ys=[p[1] for p in pts]
    w=max(xs)-min(xs);h=max(ys)-min(ys)
    if min(w,h)<=0:return None
    # Accept axis-aligned rectangles, including small drafting inaccuracies.
    tol=max(w,h)*.002
    for a,b in zip(pts,pts[1:]+pts[:1]):
        if abs(a[0]-b[0])>tol and abs(a[1]-b[1])>tol:return None
    return [min(xs),min(ys),max(xs),max(ys)]


def _same_bounds(a,b,tol=.025):
    scale=max(1.0,a[2]-a[0],a[3]-a[1],b[2]-b[0],b[3]-b[1])
    return max(abs(x-y) for x,y in zip(a,b))<=tol*scale


def _contains(outer,inner,tol=1e-6):
    return (outer[0]-tol<=inner[0] and outer[1]-tol<=inner[1] and
            outer[2]+tol>=inner[2] and outer[3]+tol>=inner[3])


def analyze_plan_frames(src):
    """Return candidates plus an explainable, fail-closed separation decision."""
    doc=ezdxf.readfile(src);msp=doc.modelspace();entities=list(msp)
    raw=[]
    for e in entities:
        bounds=_rect_bounds(e)
        if not bounds:continue
        w=bounds[2]-bounds[0];h=bounds[3]-bounds[1];short,long=sorted((w,h))
        ratio=long/short
        if not (1.20<=ratio<=1.60):continue
        raw.append({"bounds":bounds,"width":w,"height":h,"short":short,"long":long,
                    "layer":str(getattr(e.dxf,"layer","") or ""),"handle":str(getattr(e.dxf,"handle","") or "")})
    # Repetition is scale independent and captures non-standard office frames.
    families=Counter((round(x["short"],1),round(x["long"],1)) for x in raw)
    candidates=[]
    for row in raw:
        layer_hit=any(t in _norm(row["layer"]) for t in PRINT_LAYER_TOKENS)
        family_count=families[(round(row["short"],1),round(row["long"],1))]
        nested=sum(1 for other in raw if other is not row and _contains(row["bounds"],other["bounds"]) and
                   .70<=((other["width"]*other["height"])/(row["width"]*row["height"]))<.98)
        texts=[];count=0;graphic=0
        for e in entities:
            p=_point(e)
            if not p or not _inside(p,row["bounds"]):continue
            count+=1
            if e.dxftype() in {"LINE","LWPOLYLINE","POLYLINE","ARC","CIRCLE","INSERT","HATCH"}:graphic+=1
            if e.dxftype() in {"TEXT","MTEXT"}:
                value=_text(e)
                if value:texts.append(value)
        blob="\n".join(texts);drawing_type=_classify(blob);levels=_levels(blob)
        title_hit=drawing_type!="UNKNOWN"
        content_hit=graphic>=25 and len(texts)>=2
        # Repeated geometry without either a print layer or a drawing title is
        # normally an inner wall/room outline, not a sheet frame.
        if not content_hit:continue
        if not layer_hit and not (family_count>=2 and title_hit):continue
        evidence={"print_layer":layer_hit,"repeated_geometry":family_count>=2,"closed_frame":True,
                  "nested_border":nested>0,"drawing_title":title_hit,"substantial_content":content_hit}
        score=(30 if layer_hit else 0)+(20 if family_count>=2 else 0)+(10 if nested else 0)+(25 if title_hit else 0)+(15 if content_hit else 0)
        candidates.append({**row,"title_text":texts,"entity_count":count,"graphic_entity_count":graphic,
                           "drawing_type":drawing_type,"level":levels[0] if len(levels)==1 else None,
                           "represented_levels":levels,"evidence":evidence,"confidence":score})
    # Suppress inset wall borders when a stronger print-layer rectangle contains
    # them.  They carry the same titles/content and otherwise look deceptively
    # like a second sheet.
    candidates=[row for row in candidates if not (
        not row["evidence"]["print_layer"] and any(
            other is not row and other["evidence"]["print_layer"] and
            _contains(other["bounds"],row["bounds"]) and
            .65<=((row["width"]*row["height"])/(other["width"]*other["height"]))<.98
            for other in candidates))]
    # Prefer one outer print frame when duplicate polylines share coordinates.
    selected=[]
    for row in sorted(candidates,key=lambda x:(x["bounds"][1],x["bounds"][0],-(x["width"]*x["height"]))):
        duplicate=next((x for x in selected if _same_bounds(x["bounds"],row["bounds"])),None)
        if duplicate:
            if row["confidence"]>duplicate["confidence"]:selected[selected.index(duplicate)]=row
            continue
        selected.append(row)
    high=[x for x in selected if x["confidence"]>=70]
    uncertain=[x for x in selected if 45<=x["confidence"]<70]
    return {"status":"PASS" if high and not uncertain else "INPUT_REQUIRED",
            "source_units":int(doc.header.get('$INSUNITS',0) or 0),"candidates":selected,
            "accepted_count":len(high),"uncertain_count":len(uncertain),
            "rejected_low_confidence_count":len(selected)-len(high)-len(uncertain)}


def detect_print_plans(src):
    analysis=analyze_plan_frames(src)
    frames=[x for x in analysis["candidates"] if x["confidence"]>=70]
    recovered=_recover_title_anchored_plan_regions(src)
    # A consultant may omit one border among an otherwise valid repeated
    # sheet family.  Recover only title anchors not already owned by a closed
    # accepted frame; never replace the stronger framed evidence.
    for row in recovered:
        anchor=row.get("title_anchor")
        if any(_inside(anchor,frame["bounds"]) for frame in frames):continue
        bounds=list(row["bounds"])
        for frame in frames:
            other=frame["bounds"]
            horizontal_overlap=min(bounds[2],other[2])-max(bounds[0],other[0])>0
            vertical_overlap=min(bounds[3],other[3])-max(bounds[1],other[1])>0
            if horizontal_overlap and anchor[1]>=other[3]:bounds[1]=max(bounds[1],other[3])
            elif horizontal_overlap and anchor[1]<=other[1]:bounds[3]=min(bounds[3],other[1])
            if vertical_overlap and anchor[0]>=other[2]:bounds[0]=max(bounds[0],other[2])
            elif vertical_overlap and anchor[0]<=other[0]:bounds[2]=min(bounds[2],other[0])
        if bounds[2]<=bounds[0] or bounds[3]<=bounds[1]:continue
        row["bounds"]=bounds;row["width"]=bounds[2]-bounds[0];row["height"]=bounds[3]-bounds[1]
        frames.append(row)
    frames=sorted(frames,key=lambda x:(-x["bounds"][1],x["bounds"][0]))
    plans=[]
    for i,frame in enumerate(frames):
        b=frame["bounds"];frame_text=frame["title_text"];blob="\n".join(frame_text)
        arc=next((x for x in frame_text if re.search(r"arc\s*-\s*\d+",_norm(x))),None)
        plans.append({"plan_id":f"PLAN-{i+1:02d}","bounds":b,"drawing_type":frame["drawing_type"],
                      "level":frame["level"] or _level(blob),"represented_levels":frame["represented_levels"],
                      "title_text":frame_text,"arc_sheet":arc,"entity_count":frame["entity_count"],
                      "frame_confidence":frame["confidence"],"frame_evidence":frame["evidence"],
                      "frame_detection_status":"CONFIRMED","mechanical_role":"EXCLUDE"})

    # Canonical floor plans: prefer titled Arc sheets and richer geometry.
    floor_candidates=[p for p in plans if p["drawing_type"]=="ARCH_FLOOR_PLAN"]
    by_level={}
    for p in floor_candidates:
        identities=p.get("represented_levels") or ([p["level"]] if p.get("level") else [])
        if not identities: continue
        score=(1 if p.get("arc_sheet") else 0,p.get("entity_count",0))
        key=tuple(identities)
        if key not in by_level or score>by_level[key][0]:by_level[key]=(score,p)
    for _,p in by_level.values():
        p["mechanical_role"]="PRIMARY_FLOOR"
    roof_candidates=[p for p in plans if p["drawing_type"]=="ROOF_PLAN"]
    if roof_candidates:
        def roof_rank(plan):
            blob=_norm("\n".join(plan.get("title_text") or []))
            architecture_title=any(token in blob for token in ("پلان معماری پشت بام","roof architectural plan"))
            slope_only=any(token in blob for token in ("پلان شیب بندی","پلان شیب‌بندی","roof slope plan"))
            return (1 if architecture_title else 0,0 if slope_only else 1,1 if plan.get("arc_sheet") else 0,plan.get("entity_count",0))
        roof_primary=max(roof_candidates,key=roof_rank)
        for p in roof_candidates:
            blob=_norm("\n".join(p.get("title_text") or []))
            if p is roof_primary:p["mechanical_role"]="ROOF_SUPPORT";p["roof_view_role"]="ARCHITECTURAL_BASE"
            elif any(token in blob for token in ("پلان شیب بندی","پلان شیب‌بندی","roof slope plan")):
                p["mechanical_role"]="ROOF_ANALYSIS_SUPPORT";p["roof_view_role"]="SLOPE_DRAINAGE_SUPPORT"
            else:p["mechanical_role"]="DUPLICATE_REFERENCE";p["roof_view_role"]="REJECTED_DUPLICATE"
    for p in plans:
        if p["drawing_type"]=="ARCH_FLOOR_PLAN" and p["mechanical_role"]!="PRIMARY_FLOOR":
            p["mechanical_role"]="DUPLICATE_REFERENCE"
    return plans


def _recover_title_anchored_plan_regions(src):
    """Recover genuine plan regions when the consultant omitted closed frames.

    This is deliberately not a whole-file fallback.  An accepted region needs
    an explicit plan title, independent neighbouring title separators and a
    substantial local population of drawable entities.  The resulting bounds
    are therefore evidence from the uploaded architecture, not invented sheet
    geometry.  Files without enough evidence remain unresolved.
    """
    doc=ezdxf.readfile(src);entities=list(doc.modelspace());anchors=[]
    for entity in entities:
        if entity.dxftype() not in {"TEXT","MTEXT"}:continue
        value=_text(entity);point=_point(entity);kind=_classify(value)
        if not point or "پلان" not in _norm(value) and "plan" not in _norm(value):continue
        if kind=="UNKNOWN":continue
        anchors.append({"point":point,"text":value,"drawing_type":kind,
                        "represented_levels":_levels(value)})
    if not anchors:return []
    # Keep the original coordinate: rounding can turn the current anchor into
    # its own apparent right-hand neighbour and clip the recovered region at
    # the title insertion point.
    xs=sorted(set(row["point"][0] for row in anchors))
    if len(xs)<2:return []
    gaps=sorted(b-a for a,b in zip(xs,xs[1:]) if b-a>1e-6)
    typical_gap=gaps[len(gaps)//2] if gaps else None
    if not typical_gap:return []
    recovered=[]
    for anchor in anchors:
        if anchor["drawing_type"] not in {"ARCH_FLOOR_PLAN","ROOF_PLAN"}:continue
        x,y=anchor["point"];lefts=[value for value in xs if value<x-1e-9];rights=[value for value in xs if value>x+1e-9]
        left=(x+max(lefts))/2 if lefts else x-typical_gap/2
        right=(x+min(rights))/2 if rights else x+typical_gap/2
        width=right-left
        if width<=0:continue
        column_ys=sorted(row["point"][1] for row in anchors
                         if abs(row["point"][0]-x)<=typical_gap*.35 and abs(row["point"][1]-y)>1e-9)
        below=[value for value in column_ys if value<y];above=[value for value in column_ys if value>y]
        search_bottom=(y+max(below))/2 if below else y-width*4
        search_top=(y+min(above))/2 if above else y+width*4
        local=[]
        for entity in entities:
            if entity.dxftype() in {"TEXT","MTEXT","ATTRIB","ATTDEF","DIMENSION","LEADER"}:continue
            try:
                extent=bbox.extents([entity],fast=True)
                if not extent.has_data:continue
                box=(float(extent.extmin.x),float(extent.extmin.y),float(extent.extmax.x),float(extent.extmax.y))
            except Exception:continue
            center=((box[0]+box[2])/2,(box[1]+box[3])/2)
            if left<=center[0]<=right and search_bottom<=center[1]<=search_top:
                local.append((box,center))
        if len(local)<25:continue
        centers_y=[row[1][1] for row in local]
        low=_quantile(centers_y,.01);high=_quantile(centers_y,.99)
        retained=[row for row in local if low<=row[1][1]<=high]
        if len(retained)<25:continue
        bottom=min(y,min(row[0][1] for row in retained));top=max(y,max(row[0][3] for row in retained))
        if top-bottom<=width*.25:continue
        pad=max(width*.015,1e-6)
        bounds=[left+pad,bottom-pad,right-pad,top+pad]
        recovered.append({"bounds":bounds,"width":bounds[2]-bounds[0],"height":bounds[3]-bounds[1],
                          "short":min(bounds[2]-bounds[0],bounds[3]-bounds[1]),
                          "long":max(bounds[2]-bounds[0],bounds[3]-bounds[1]),"layer":"",
                          "handle":"","title_text":[anchor["text"]],"entity_count":len(local),
                          "graphic_entity_count":len(local),"drawing_type":anchor["drawing_type"],
                          "level":anchor["represented_levels"][0] if len(anchor["represented_levels"])==1 else None,
                          "represented_levels":anchor["represented_levels"],
                          "evidence":{"explicit_plan_title":True,"title_cluster_separation":True,
                                      "substantial_local_content":True,"closed_frame":False},
                          "confidence":85,"recovery_method":"title_anchored_content_region",
                          "title_anchor":anchor["point"]})
    return sorted(recovered,key=lambda row:(-row["bounds"][1],row["bounds"][0]))


def _plans_from_authoritative_profiles(profiles, detected_frames=None):
    detected_frames=list(detected_frames or [])
    plans=[]
    for profile in profiles or []:
        bounds=profile.get('region_bounds')
        status=str(profile.get('level_detection_status') or '')
        try:bounds=[float(x) for x in bounds]
        except (TypeError,ValueError):continue
        if len(bounds)!=4 or bounds[2]<=bounds[0] or bounds[3]<=bounds[1]:continue
        if status and not status.startswith('confirmed'):continue
        # Browser analysis owns the level identity, but its region can be a
        # coarse evidence-search window spanning several consultant frames.
        # When its sealed title anchor belongs to exactly one locally detected
        # print frame, that frame is the authoritative geometry boundary. This
        # joins two independent observations instead of fitting the drawing to
        # the coarse browser window and collapsing the plan on the issued sheet.
        title_point=profile.get('title_point')
        try:title_point=(float(title_point[0]),float(title_point[1]))
        except (TypeError,ValueError,IndexError):title_point=None
        matches=[frame for frame in detected_frames if title_point and _inside(title_point,frame.get('bounds') or [])]
        geometry_source='sealed_browser_level_profile'
        if len(matches)==1:
            bounds=[float(x) for x in matches[0]['bounds']]
            geometry_source='sealed_browser_identity_local_print_frame'
        roof=bool(profile.get('roof'))
        plans.append({'plan_id':f"PLAN-AUTH-{len(plans)+1:02d}",'bounds':bounds,
                      'source':geometry_source,'drawing_type':'ROOF_PLAN' if roof else 'ARCH_FLOOR_PLAN',
                      'level':str(profile.get('name') or f"LEVEL-{len(plans)+1:02d}"),
                      'mechanical_role':'ROOF_SUPPORT' if roof else 'PRIMARY_FLOOR',
                      'title_text':[],'entity_count':0})
    # Keep locally classified non-design frames in the ownership inventory.
    # The sealed browser profiles own the designable level identities, but
    # sections, elevations, furniture/lintel sheets and duplicate references
    # still own their source entities.  Dropping those frames makes legitimate
    # source evidence appear unassigned and incorrectly fails the independent
    # level model.  Never restore a locally detected roof here: a rejected roof
    # profile must stay outside the mechanical scope.
    authoritative_bounds = {tuple(round(float(v), 6) for v in plan["bounds"]) for plan in plans}
    has_authoritative_roof = any(plan.get("mechanical_role") == "ROOF_SUPPORT" for plan in plans)
    for frame in detected_frames:
        role = frame.get("mechanical_role")
        if role not in {"EXCLUDE", "DUPLICATE_REFERENCE", "ROOF_SUPPORT"}:
            continue
        if role == "ROOF_SUPPORT" and has_authoritative_roof:
            continue
        bounds = frame.get("bounds") or []
        if len(bounds) != 4:
            continue
        key = tuple(round(float(v), 6) for v in bounds)
        if key in authoritative_bounds:
            continue
        retained = dict(frame)
        if role == "ROOF_SUPPORT":
            retained["mechanical_role"] = "EXCLUDE"
            retained["roof_view_role"] = "REJECTED_LOCAL_ROOF_OWNERSHIP_ONLY"
        retained["source"] = "local_excluded_frame_ownership_evidence"
        plans.append(retained)
    return plans


def _promote_room_evidenced_floor_plans(plans, rooms):
    """Recover untitled floor plans from architectural content, not guesswork.

    Some consultant files use print frames but omit the Persian/English title
    tokens understood by ``_classify``.  A frame is safe to promote only when
    it is otherwise UNKNOWN and contains both wet-room and habitable-room
    evidence.  Explicit elevations, sections, details, roof and furniture
    plans remain excluded.
    """
    by_plan={}
    for room in rooms or []:
        pid=room.get("plan_id")
        if pid:
            by_plan.setdefault(pid,set()).add(room.get("type"))
    promoted=[]
    wet={"bathroom","toilet","kitchen"}
    habitable={"bedroom","living","kitchen"}
    for plan in plans:
        types=by_plan.get(plan.get("plan_id"),set())
        if (plan.get("drawing_type")=="UNKNOWN" and
                types & wet and types & habitable):
            plan["drawing_type"]="ARCH_FLOOR_PLAN"
            plan["mechanical_role"]="PRIMARY_FLOOR"
            plan["source"]="room_evidence_floor_recovery"
            promoted.append(plan.get("plan_id"))
    return promoted


def _segment_overlaps(value, first, second, tolerance=.05):
    low,high=sorted((float(first),float(second)))
    return low-tolerance <= value <= high+tolerance


def _source_geometry_fingerprint(entities, bounds):
    """Fingerprint normalized architectural geometry inside exactly one frame."""
    width=max(float(bounds[2])-float(bounds[0]),1e-9);height=max(float(bounds[3])-float(bounds[1]),1e-9);tokens=[]
    for entity in entities:
        layer=str(getattr(entity.dxf,"layer","") or "")
        if entity.dxftype() in {"TEXT","MTEXT"} or any(token in _norm(layer) for token in PRINT_LAYER_TOKENS):continue
        try:
            extent=bbox.extents([entity],fast=True)
            if not extent.has_data:continue
            box=(float(extent.extmin.x),float(extent.extmin.y),float(extent.extmax.x),float(extent.extmax.y))
        except Exception:continue
        center=((box[0]+box[2])/2,(box[1]+box[3])/2)
        if not _inside(center,bounds):continue
        normalized=tuple(round(value,4) for value in (
            (box[0]-bounds[0])/width,(box[1]-bounds[1])/height,
            (box[2]-bounds[0])/width,(box[3]-bounds[1])/height))
        tokens.append((entity.dxftype(),_norm(layer),normalized))
    return hashlib.sha256(json.dumps(sorted(tokens),separators=(",",":"),ensure_ascii=False).encode()).hexdigest() if tokens else None


def _quantile(values, fraction):
    ordered=sorted(values)
    if not ordered:return None
    position=(len(ordered)-1)*fraction;lower=int(position);upper=min(lower+1,len(ordered)-1)
    weight=position-lower
    return ordered[lower]*(1-weight)+ordered[upper]*weight


def _drawable_content_envelope(entities, frame_bounds):
    """Return an outlier-resistant envelope for the actual plan drawing.

    The print frame owns source entities, but must never be used as the board
    fit envelope: title blocks and remote annotations can make a valid building
    occupy only a few percent of the issued sheet.  Text is deliberately not
    allowed to enlarge the envelope.  The retained graphical centre population
    is trimmed at both tails and the complete extents of those retained entities
    are then restored, so walls/arcs are not cropped merely because they cross a
    quantile line.
    """
    x1,y1,x2,y2=map(float,frame_bounds);fw=x2-x1;fh=y2-y1
    candidates=[]
    for entity in entities:
        if entity.dxftype() in {"TEXT","MTEXT","ATTRIB","ATTDEF","DIMENSION","LEADER"}:continue
        layer=_norm(getattr(entity.dxf,"layer","") or "")
        if any(token in layer for token in PRINT_LAYER_TOKENS):continue
        try:
            extent=bbox.extents([entity],fast=True)
            if not extent.has_data:continue
            box=(float(extent.extmin.x),float(extent.extmin.y),float(extent.extmax.x),float(extent.extmax.y))
        except Exception:continue
        center=((box[0]+box[2])/2,(box[1]+box[3])/2)
        if not _inside(center,frame_bounds):continue
        hugs=(abs(box[0]-x1)<=fw*.015 and abs(box[2]-x2)<=fw*.015 and
              abs(box[1]-y1)<=fh*.015 and abs(box[3]-y2)<=fh*.015)
        if hugs:continue
        candidates.append((entity,box,center))
    if len(candidates)<8:
        return {"status":"FAIL","bounds":None,"reason":"insufficient_drawable_plan_geometry",
                "candidate_count":len(candidates),"retained_count":0}
    xs=[row[2][0] for row in candidates];ys=[row[2][1] for row in candidates]
    qx1,qx2=_quantile(xs,.025),_quantile(xs,.975);qy1,qy2=_quantile(ys,.025),_quantile(ys,.975)
    retained=[row for row in candidates if qx1<=row[2][0]<=qx2 and qy1<=row[2][1]<=qy2]
    if len(retained)<max(8,int(len(candidates)*.60)):
        return {"status":"FAIL","bounds":None,"reason":"outlier_dominated_plan_geometry",
                "candidate_count":len(candidates),"retained_count":len(retained)}
    left=max(x1,min(row[1][0] for row in retained));bottom=max(y1,min(row[1][1] for row in retained))
    right=min(x2,max(row[1][2] for row in retained));top=min(y2,max(row[1][3] for row in retained))
    if right-left<=max(fw*1e-6,1e-9) or top-bottom<=max(fh*1e-6,1e-9):
        return {"status":"FAIL","bounds":None,"reason":"degenerate_drawable_plan_geometry",
                "candidate_count":len(candidates),"retained_count":len(retained)}
    pad_x=(right-left)*.02;pad_y=(top-bottom)*.02
    bounds=[max(x1,left-pad_x),max(y1,bottom-pad_y),min(x2,right+pad_x),min(y2,top+pad_y)]
    return {"status":"PASS","bounds":bounds,"reason":"trimmed_graphical_entity_envelope",
            "candidate_count":len(candidates),"retained_count":len(retained),
            "retained_ratio":round(len(retained)/len(candidates),6)}


def _recover_orthogonal_room_enclosures(architecture, plans):
    """Recover a room boundary only from four bracketing wall faces.

    Consultant DXFs often draw walls as LINE entities and omit a closed room
    polyline.  A text label is sufficient to select a room, but not to invent
    its geometry.  This fallback therefore accepts only an axis-aligned cell
    for which real wall segments bracket the label on every side inside its
    authoritative floor-plan bounds.
    """
    plan_bounds={p.get("plan_id"):p.get("bounds") for p in plans or []}
    walls=architecture.get("walls") or []; recovered=[]
    for room in architecture.get("rooms") or []:
        if room.get("polygon") or not room.get("label_point") or not room.get("plan_id"):
            continue
        bounds=plan_bounds.get(room["plan_id"])
        if not bounds:continue
        x,y=map(float,room["label_point"]); horizontal=[];vertical=[]
        for wall in walls:
            try:(x1,y1),(x2,y2)=wall["start"],wall["end"]
            except (KeyError,TypeError,ValueError):continue
            if max(x1,x2)<bounds[0] or min(x1,x2)>bounds[2] or max(y1,y2)<bounds[1] or min(y1,y2)>bounds[3]:
                continue
            if abs(y1-y2)<=.02 and _segment_overlaps(x,x1,x2):horizontal.append((float((y1+y2)/2),wall))
            if abs(x1-x2)<=.02 and _segment_overlaps(y,y1,y2):vertical.append((float((x1+x2)/2),wall))
        below=[row for row in horizontal if row[0]<y-.05];above=[row for row in horizontal if row[0]>y+.05]
        left=[row for row in vertical if row[0]<x-.05];right=[row for row in vertical if row[0]>x+.05]
        if not (below and above and left and right):continue
        bottom=max(below,key=lambda row:row[0]);top=min(above,key=lambda row:row[0])
        west=max(left,key=lambda row:row[0]);east=min(right,key=lambda row:row[0])
        x1,x2=west[0],east[0];y1,y2=bottom[0],top[0]
        if not (.15 <= x2-x1 <= bounds[2]-bounds[0] and .15 <= y2-y1 <= bounds[3]-bounds[1]):continue
        polygon=[(x1,y1),(x2,y1),(x2,y2),(x1,y2)]
        room["polygon"]=polygon;room["area"]=(x2-x1)*(y2-y1)
        room.setdefault("evidence",[]).append("four_sided_orthogonal_wall_enclosure")
        recovered.append(room.get("id"))
    architecture.setdefault("quality",{})["wall_enclosure_recovered_room_ids"]=recovered
    architecture["quality"]["rooms_with_polygon"]=sum(bool(r.get("polygon")) for r in architecture.get("rooms") or [])
    return recovered


def apply_plan_scopes(src,architecture,recognition,authoritative_profiles=None):
    plans=detect_print_plans(src)
    authoritative=_plans_from_authoritative_profiles(authoritative_profiles,plans)
    if any(p.get('mechanical_role')=='PRIMARY_FLOOR' for p in authoritative):
        # Browser analysis is sealed from this same upload and preserves every
        # confirmed drawing region.  Prefer it even when the local title parser
        # found *some* floors: repeated/consultant-specific titles can otherwise
        # collapse distinct plans into one ``DUPLICATE_REFERENCE`` and make the
        # approved drawing manifest disagree with generated boards/routes.
        plans=authoritative
    # Legacy/single-plan drawings without office print frames remain valid.
    if not plans:
        bounds=architecture.get("bounds") or [0,0,0,0]
        plans=[{"plan_id":"PLAN-01","bounds":list(bounds),"source":"single_plan_fallback",
                "drawing_type":"ARCH_FLOOR_PLAN","level":None,"mechanical_role":"PRIMARY_FLOOR"}]
    doc=ezdxf.readfile(src); source_entities=list(doc.modelspace())
    ownership_ambiguities=[]; ownership_unassigned=[]; ownership_excluded=[]
    # At least two independently confirmed closed frames establish a real
    # drawing-board inventory.  A recovered missing border may coexist with
    # it; isolated unenclosed text far outside every board can then be retained
    # as explicitly excluded source residue.  Title-only files (P2 class) do
    # not receive this exemption.
    closed_frame_inventory=sum(1 for p in plans
        if (p.get("frame_evidence") or {}).get("closed_frame") is True)>=2
    authoritative_widths=[min(p["bounds"][2]-p["bounds"][0],p["bounds"][3]-p["bounds"][1])
                          for p in plans if p.get("mechanical_role") in {"PRIMARY_FLOOR","ROOF_SUPPORT"}]
    isolation_radius=max(authoritative_widths,default=2.0)*.5
    graphical_centers=[]
    for entity in source_entities:
        if entity.dxftype() in {"TEXT","MTEXT","ATTRIB","ATTDEF","DIMENSION","LEADER"}:continue
        try:
            extent=bbox.extents([entity],fast=True)
            if extent.has_data:graphical_centers.append(((extent.extmin.x+extent.extmax.x)/2,
                                                         (extent.extmin.y+extent.extmax.y)/2))
        except Exception:pass
    title_region_inventory=(len([p for p in plans if p.get("mechanical_role") in {"PRIMARY_FLOOR","ROOF_SUPPORT"}])>=2 and
                            all((p.get("frame_evidence") or {}).get("explicit_plan_title") is True
                                for p in plans if p.get("mechanical_role") in {"PRIMARY_FLOOR","ROOF_SUPPORT"}))
    room_points=[room.get("label_point") for room in architecture.get("rooms") or [] if room.get("label_point")]
    def owner(point, entity_type="entity", entity_id=None, *, isolated_unenclosed_room=False):
        matches=[p for p in plans if _inside(point,p["bounds"])] if point else []
        evidence={"entity_type":entity_type,"entity_id":entity_id,"point":point,
                  "candidate_plan_ids":[p["plan_id"] for p in matches]}
        if len(matches)>1:
            ownership_ambiguities.append(evidence); return None
        if not matches and (closed_frame_inventory or title_region_inventory) and isolated_unenclosed_room:
            evidence["exclusion_reason"]="isolated_unenclosed_room_text_outside_confirmed_drawing_frames"
            ownership_excluded.append(evidence); return None
        if not matches:
            ownership_unassigned.append(evidence); return None
        return matches[0]
    for room in architecture.get("rooms") or []:
        point=room.get("label_point")
        other_nearby=sum(1 for other in room_points if point and 1e-9<math.dist(point,other)<=isolation_radius)
        graphical_support=any(math.dist(point,other)<=isolation_radius for other in graphical_centers) if point else False
        isolated=not room.get("polygon") and other_nearby==0 and not graphical_support
        p=owner(point,"room",room.get("id"),isolated_unenclosed_room=isolated)
        room["plan_id"]=p["plan_id"] if p else None
        if not p and isolated and (closed_frame_inventory or title_region_inventory):room["scope_status"]="EXCLUDED_SOURCE_RESIDUE"
    for item in recognition.get("detections") or []:
        p=owner(item.get("point"),"detection",item.get("id")); item["plan_id"]=p["plan_id"] if p else None

    if plans and not any(p.get("mechanical_role")=="PRIMARY_FLOOR" for p in plans):
        promoted=_promote_room_evidenced_floor_plans(plans,architecture.get("rooms") or [])
        architecture.setdefault("quality",{})["room_evidence_promoted_plan_ids"]=promoted

    text_shafts=[]
    for plan in plans:
        envelope=_drawable_content_envelope(source_entities,plan["bounds"])
        plan["content_envelope"]=envelope
        plan["content_bounds"]=envelope.get("bounds") if envelope.get("status")=="PASS" else None
    for e in source_entities:
        if e.dxftype() not in {"TEXT","MTEXT"}: continue
        text=_text(e); point=_point(e)
        if not point or not ("داکت" in text or "شفت" in text): continue
        p=owner(point,"shaft_text",str(getattr(e.dxf,"handle","") or text))
        if p:text_shafts.append({"layer":str(e.dxf.layer),"polygon":None,"point":point,"area":None,
                                 "plan_id":p["plan_id"],"source":"textual_vertical_core"})
    for shaft in architecture.get("shafts") or []:
        point=shaft.get("point")
        if point is None and shaft.get("polygon"):
            poly=shaft["polygon"]; point=(sum(x for x,y in poly)/len(poly),sum(y for x,y in poly)/len(poly))
        p=owner(point,"shaft",shaft.get("id")); shaft["plan_id"]=p["plan_id"] if p else None; shaft["point"]=point
    architecture["shafts"]=(architecture.get("shafts") or [])+text_shafts
    architecture["plans"]=plans
    architecture["mechanical_plan_ids"]=[p["plan_id"] for p in plans if p.get("mechanical_role") in {"PRIMARY_FLOOR","ROOF_SUPPORT"}]
    architecture["primary_floor_plan_ids"]=[p["plan_id"] for p in plans if p.get("mechanical_role")=="PRIMARY_FLOOR"]
    architecture.setdefault("quality",{})["plan_count"]=len(plans)
    architecture["quality"]["primary_floor_count"]=len(architecture["primary_floor_plan_ids"])
    architecture["quality"]["excluded_frame_count"]=sum(1 for p in plans if p.get("mechanical_role") in {"EXCLUDE","DUPLICATE_REFERENCE"})
    ownership=[]
    for plan in plans:
        pid=plan["plan_id"]
        room_ids=sorted(str(r.get("id")) for r in architecture.get("rooms") or [] if r.get("plan_id")==pid)
        detection_ids=sorted(str(x.get("id")) for x in recognition.get("detections") or [] if x.get("plan_id")==pid)
        payload={"plan_id":pid,"bounds":[round(float(v),6) for v in plan["bounds"]],
                 "content_bounds":[round(float(v),6) for v in plan.get("content_bounds") or []],
                 "level":plan.get("level"),"room_ids":room_ids,"detection_ids":detection_ids}
        payload["source_geometry_fingerprint"]=_source_geometry_fingerprint(source_entities,plan["bounds"])
        payload["represented_levels"]=list(plan.get("represented_levels") or [])
        payload["fingerprint"]=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        ownership.append(payload)
    architecture["level_ownership_contract"]={
        "status":"PASS" if (not ownership_ambiguities and not ownership_unassigned and
                              all(p.get("content_bounds") for p in plans if p.get("mechanical_role") in {"PRIMARY_FLOOR","ROOF_SUPPORT"})) else "FAIL",
        "source_unit_code":int(doc.header.get('$INSUNITS',0) or 0),
        "orientation":architecture.get("orientation") or "SOURCE_WCS",
        "plans":ownership,"ambiguities":ownership_ambiguities,"unassigned":ownership_unassigned,
        "excluded_source_evidence":ownership_excluded,
    }
    architecture["quality"]["ambiguous_plan_ownership_count"]=len(ownership_ambiguities)
    architecture["quality"]["unassigned_plan_entity_count"]=len(ownership_unassigned)
    architecture["quality"]["invalid_plan_content_envelope_count"]=sum(
        1 for p in plans if p.get("mechanical_role") in {"PRIMARY_FLOOR","ROOF_SUPPORT"} and not p.get("content_bounds"))

    _recover_orthogonal_room_enclosures(architecture,plans)

    # Only canonical floor plans feed room/fixture driven mechanical design.
    primary=set(architecture["primary_floor_plan_ids"])
    if primary:
        architecture["rooms_all_frames"]=list(architecture.get("rooms") or [])
        recognition["detections_all_frames"]=list(recognition.get("detections") or [])
        architecture["rooms"]=[r for r in architecture.get("rooms") or [] if r.get("plan_id") in primary]
        recognition["detections"]=[x for x in recognition.get("detections") or [] if x.get("plan_id") in primary]
        recognition["fixtures"]=[x for x in recognition.get("detections") or [] if x.get("category")=="fixture"]
        recognition["equipment"]=[x for x in recognition.get("detections") or [] if x.get("category")=="equipment"]
    return architecture,recognition
