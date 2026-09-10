"""Detect, classify, deduplicate and safely scope architectural drawings.

Frame detection is deliberately evidence based.  A rectangle is not a plan by
itself: repeated sheet geometry, a print-layer name, drawing titles and useful
content all contribute independently to an explainable confidence score.
Uncertain rectangles are reported but never promoted to mechanical authority.
"""
from __future__ import annotations
from collections import Counter
import re
import ezdxf


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
        evidence={"print_layer":layer_hit,"repeated_geometry":family_count>=2,
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
    for p in plans:
        if p["drawing_type"]=="ROOF_PLAN": p["mechanical_role"]="ROOF_SUPPORT"
        elif p["drawing_type"]=="ARCH_FLOOR_PLAN" and p["mechanical_role"]!="PRIMARY_FLOOR":
            p["mechanical_role"]="DUPLICATE_REFERENCE"
    return plans


def _plans_from_authoritative_profiles(profiles):
    plans=[]
    for profile in profiles or []:
        bounds=profile.get('region_bounds')
        status=str(profile.get('level_detection_status') or '')
        try:bounds=[float(x) for x in bounds]
        except (TypeError,ValueError):continue
        if len(bounds)!=4 or bounds[2]<=bounds[0] or bounds[3]<=bounds[1]:continue
        if status and not status.startswith('confirmed'):continue
        roof=bool(profile.get('roof'))
        plans.append({'plan_id':f"PLAN-AUTH-{len(plans)+1:02d}",'bounds':bounds,
                      'source':'sealed_browser_level_profile','drawing_type':'ROOF_PLAN' if roof else 'ARCH_FLOOR_PLAN',
                      'level':str(profile.get('name') or f"LEVEL-{len(plans)+1:02d}"),
                      'mechanical_role':'ROOF_SUPPORT' if roof else 'PRIMARY_FLOOR',
                      'title_text':[],'entity_count':0})
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
    authoritative=_plans_from_authoritative_profiles(authoritative_profiles)
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
    def owner(point):
        return next((p for p in plans if _inside(point,p["bounds"])),None)
    for room in architecture.get("rooms") or []:
        p=owner(room.get("label_point")); room["plan_id"]=p["plan_id"] if p else None
    for item in recognition.get("detections") or []:
        p=owner(item.get("point")); item["plan_id"]=p["plan_id"] if p else None

    if plans and not any(p.get("mechanical_role")=="PRIMARY_FLOOR" for p in plans):
        promoted=_promote_room_evidenced_floor_plans(plans,architecture.get("rooms") or [])
        architecture.setdefault("quality",{})["room_evidence_promoted_plan_ids"]=promoted

    doc=ezdxf.readfile(src); text_shafts=[]
    for e in doc.modelspace():
        if e.dxftype() not in {"TEXT","MTEXT"}: continue
        text=_text(e); point=_point(e)
        if not point or not ("داکت" in text or "شفت" in text): continue
        p=owner(point)
        if p:text_shafts.append({"layer":str(e.dxf.layer),"polygon":None,"point":point,"area":None,
                                 "plan_id":p["plan_id"],"source":"textual_vertical_core"})
    for shaft in architecture.get("shafts") or []:
        point=shaft.get("point")
        if point is None and shaft.get("polygon"):
            poly=shaft["polygon"]; point=(sum(x for x,y in poly)/len(poly),sum(y for x,y in poly)/len(poly))
        p=owner(point); shaft["plan_id"]=p["plan_id"] if p else None; shaft["point"]=point
    architecture["shafts"]=(architecture.get("shafts") or [])+text_shafts
    architecture["plans"]=plans
    architecture["mechanical_plan_ids"]=[p["plan_id"] for p in plans if p.get("mechanical_role") in {"PRIMARY_FLOOR","ROOF_SUPPORT"}]
    architecture["primary_floor_plan_ids"]=[p["plan_id"] for p in plans if p.get("mechanical_role")=="PRIMARY_FLOOR"]
    architecture.setdefault("quality",{})["plan_count"]=len(plans)
    architecture["quality"]["primary_floor_count"]=len(architecture["primary_floor_plan_ids"])
    architecture["quality"]["excluded_frame_count"]=sum(1 for p in plans if p.get("mechanical_role") in {"EXCLUDE","DUPLICATE_REFERENCE"})

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
