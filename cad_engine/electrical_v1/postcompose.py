from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import ezdxf

from .models import EngineeringStatus, EvidenceValue, SheetManifestItem


def append_detail_sheet(manifest: List[SheetManifestItem], details) -> None:
    if not details or any(s.family=="DETAILS" for s in manifest): return
    nums=[]
    for s in manifest:
        try: nums.append(int(s.sheet_id.split("-")[-1]))
        except Exception: pass
    sid=f"E-{(max(nums) if nums else 0)+1:02d}"
    manifest.append(SheetManifestItem(sid,"DETAILS",None,"Project-specific electrical details",
                                      ["parametric_details"],["ENGITOOLS-E-DETAIL","ENGITOOLS-E-DOC"],[],{"parametric_details":1},[]))


def _fit_transform(bounds, paper, margins=(12,18,12,12)):
    pw,ph=paper; left,bottom,right,top=margins; x1,y1,x2,y2=bounds
    aw=max(pw-left-right,1e-6); ah=max(ph-bottom-top,1e-6); w=max(x2-x1,1e-9); h=max(y2-y1,1e-9)
    scale=min(aw/w,ah/h); ox=left+(aw-w*scale)/2-x1*scale; oy=bottom+(ah-h*scale)/2-y1*scale
    return lambda p:(float(p[0])*scale+ox,float(p[1])*scale+oy)


def _frame(architecture, frame_id):
    return next((f for f in architecture.frames if f.id==frame_id),None)


def _draw_cover(doc, manifest, signatures, paper):
    covers=[s for s in manifest if s.family=="COVER"]
    for sheet in covers:
        if sheet.sheet_id not in doc.layouts: continue
        layout=doc.layouts.get(sheet.sheet_id); y=paper[1]-28
        layout.add_text("ELECTRICAL DRAWING INDEX",dxfattribs={"layer":"ENGITOOLS-E-DOC","height":2.5}).set_placement((18,y)); y-=7
        for item in manifest:
            layout.add_text(f"{item.sheet_id}  {item.purpose}",dxfattribs={"layer":"ENGITOOLS-E-DOC","height":1.2}).set_placement((18,y)); y-=4
        signatures.setdefault(sheet.sheet_id,{}).setdefault("signature",{})["sheet_index"]=len(manifest)


def _draw_panels(doc, manifest, topology, architecture, paper):
    if not topology: return
    for panel in topology.get("panels") or []:
        location=panel.location.value if isinstance(panel.location,EvidenceValue) and panel.location.status==EngineeringStatus.FINAL else None
        if not isinstance(location,dict) or not location.get("point"): continue
        frame_id=location.get("frame_id")
        if not frame_id:
            frame=next((f for f in architecture.frames if f.level_id==panel.level_id and f.eligible_for_electrical),None); frame_id=frame.id if frame else None
        frame=_frame(architecture,frame_id) if frame_id else None
        if not frame: continue
        transform=_fit_transform(frame.bounds,paper); point=transform(location["point"])
        for sheet in manifest:
            if sheet.family!="POWER" or sheet.level_id!=panel.level_id or sheet.sheet_id not in doc.layouts: continue
            layout=doc.layouts.get(sheet.sheet_id)
            if "ET_EL_PNL_01" in doc.blocks:
                layout.add_blockref("ET_EL_PNL_01",point,dxfattribs={"layer":"ENGITOOLS-E-POWER"})
            else:
                layout.add_lwpolyline([(point[0]-2,point[1]-3),(point[0]+2,point[1]-3),(point[0]+2,point[1]+3),(point[0]-2,point[1]+3),(point[0]-2,point[1]-3)],dxfattribs={"layer":"ENGITOOLS-E-POWER"})
            layout.add_text(panel.id,dxfattribs={"layer":"ENGITOOLS-E-ANNOTATION","height":1.3}).set_placement((point[0]+3,point[1]+2))


def _draw_grounding(doc, manifest, grounding, signatures, paper, architecture):
    elements=grounding.get("elements") or []
    for sheet in [s for s in manifest if s.family=="GROUNDING"]:
        if sheet.sheet_id not in doc.layouts: continue
        layout=doc.layouts.get(sheet.sheet_id); count=0; y=paper[1]-35
        for element in elements:
            data=element.get("data"); status=element.get("status")
            text=f"{element['kind']}: {data if data is not None else status}"
            layout.add_text(text,dxfattribs={"layer":"ENGITOOLS-E-GROUNDING","height":1.3}).set_placement((18,y)); y-=5; count+=1
            if element["kind"]=="earth_electrode" and isinstance(data,dict) and data.get("point"):
                frame_id=data.get("frame_id") or (sheet.source_frame_ids[0] if sheet.source_frame_ids else None)
                frame=_frame(architecture,frame_id) if frame_id else None
                if frame:
                    q=_fit_transform(frame.bounds,paper)(data["point"])
                    if "ET_EL_GND_01" in doc.blocks:
                        layout.add_blockref("ET_EL_GND_01",q,dxfattribs={"layer":"ENGITOOLS-E-GROUNDING"})
                    else:
                        layout.add_circle(q,2.0,dxfattribs={"layer":"ENGITOOLS-E-GROUNDING"})
                    layout.add_text("EARTH ELECTRODE",dxfattribs={"layer":"ENGITOOLS-E-ANNOTATION","height":1.1}).set_placement((q[0]+3,q[1]+1)); count+=1
        signatures.setdefault(sheet.sheet_id,{}).setdefault("signature",{})["grounding_elements"]=count


def _draw_details(doc, manifest, details, signatures, paper):
    sheets=[s for s in manifest if s.family=="DETAILS"]
    if not sheets: return
    sheet=sheets[0]
    if sheet.sheet_id not in doc.layouts: return
    layout=doc.layouts.get(sheet.sheet_id); cols=3; cell_w=(paper[0]-30)/cols; cell_h=58; count=0
    for i,detail in enumerate(details):
        col=i%cols; row=i//cols; x=12+col*cell_w; y=paper[1]-25-row*cell_h
        if y-cell_h<15: break
        layout.add_lwpolyline([(x,y),(x+cell_w-5,y),(x+cell_w-5,y-cell_h+5),(x,y-cell_h+5),(x,y)],dxfattribs={"layer":"ENGITOOLS-E-DETAIL"})
        layout.add_text(detail["detail_id"],dxfattribs={"layer":"ENGITOOLS-E-DETAIL","height":1.8}).set_placement((x+3,y-5))
        gy=y-15
        for primitive in detail.get("geometry") or []:
            kind=str(primitive[0])
            if kind in {"wall_section","ceiling_section","mounting_surface"}: layout.add_line((x+10,gy),(x+cell_w-15,gy),dxfattribs={"layer":"ENGITOOLS-E-DETAIL"})
            elif kind in {"panel_box","meter_box","device_box","junction_box","isolator","luminaire","detector","equipment"}: layout.add_lwpolyline([(x+20,gy-4),(x+34,gy-4),(x+34,gy+4),(x+20,gy+4),(x+20,gy-4)],dxfattribs={"layer":"ENGITOOLS-E-DETAIL"})
            elif kind in {"conduit","cable","connection","terminal","lug","support","sleeve","firestop","earth","electrode","clearance","clearance_zone","access_zone"}: layout.add_line((x+38,gy-4),(x+55,gy+4),dxfattribs={"layer":"ENGITOOLS-E-DETAIL"})
            elif kind=="dimension": layout.add_line((x+8,gy-7),(x+8,gy+7),dxfattribs={"layer":"ENGITOOLS-E-DETAIL"})
            gy-=5
        ptxt=", ".join(f"{k}={v.get('value') if isinstance(v,dict) else v}" for k,v in (detail.get("parameters") or {}).items())
        layout.add_text(ptxt[:120],dxfattribs={"layer":"ENGITOOLS-E-DETAIL","height":.9}).set_placement((x+3,y-cell_h+9)); count+=1
    signatures.setdefault(sheet.sheet_id,{}).setdefault("signature",{})["parametric_details"]=count


def _draw_detail_links(doc, manifest, links, paper):
    detail_sheet=next((s.sheet_id for s in manifest if s.family=="DETAILS"),None)
    if not detail_sheet: return
    grouped={}
    for link in links or []: grouped.setdefault(link["sheet_id"],[]).append(link["detail_id"])
    for sheet_id, detail_ids in grouped.items():
        if sheet_id not in doc.layouts: continue
        layout=doc.layouts.get(sheet_id); y=paper[1]-22
        for did in sorted(set(detail_ids)):
            layout.add_text(f"SEE DETAIL {detail_sheet} / {did}",dxfattribs={"layer":"ENGITOOLS-E-ANNOTATION","height":1.0}).set_placement((paper[0]-92,y)); y-=3.2


def optimize_annotations(doc, manifest, paper):
    """Resolve obvious annotation collisions and add leaders to moved labels."""
    moved=0
    for sheet in manifest:
        if sheet.sheet_id not in doc.layouts: continue
        layout=doc.layouts.get(sheet.sheet_id); texts=[e for e in layout if e.dxftype()=="TEXT" and str(getattr(e.dxf,"layer",""))=="ENGITOOLS-E-ANNOTATION"]
        occupied=[]
        for e in texts:
            p=e.dxf.insert; h=max(float(e.dxf.height or 1),.8); text=str(e.dxf.text or ""); w=max(h*.55*len(text),h); box=[float(p.x),float(p.y),float(p.x)+w,float(p.y)+h]; original=(float(p.x),float(p.y))
            attempts=0
            while any(max(0,min(box[2],b[2])-max(box[0],b[0]))*max(0,min(box[3],b[3])-max(box[1],b[1]))>.2 for b in occupied) and attempts<8:
                box=[box[0],box[1]+3,box[2],box[3]+3]; attempts+=1
            if attempts:
                e.dxf.insert=(box[0],box[1]); layout.add_line(original,(box[0],box[1]),dxfattribs={"layer":"ENGITOOLS-E-ANNOTATION"}); moved+=1
            occupied.append(box)
    return moved


def apply_postcomposition(path: str|Path, manifest, details, grounding, signatures, paper=(420.0,297.0), *, architecture=None, topology=None, links=None):
    doc=ezdxf.readfile(str(path))
    _draw_cover(doc,manifest,signatures,paper)
    if architecture is not None:
        _draw_panels(doc,manifest,topology or {},architecture,paper)
        _draw_grounding(doc,manifest,grounding,signatures,paper,architecture)
    _draw_details(doc,manifest,details,signatures,paper)
    _draw_detail_links(doc,manifest,links or [],paper)
    moved=optimize_annotations(doc,manifest,paper)
    doc.saveas(str(path))
    return {"status":"PASS","annotations_moved_with_leaders":moved}
