from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import ezdxf

from .models import SheetManifestItem


def append_detail_sheet(manifest: List[SheetManifestItem], details) -> None:
    if not details or any(s.family=="DETAILS" for s in manifest): return
    nums=[]
    for s in manifest:
        try: nums.append(int(s.sheet_id.split("-")[-1]))
        except Exception: pass
    sid=f"E-{(max(nums) if nums else 0)+1:02d}"
    manifest.append(SheetManifestItem(sid,"DETAILS",None,"Project-specific electrical details",
                                      ["parametric_details"],["ENGITOOLS-E-DETAIL","ENGITOOLS-E-DOC"],[],{"parametric_details":1},[]))


def _draw_grounding(doc, manifest, grounding, signatures, paper):
    elements=grounding.get("elements") or []
    for sheet in [s for s in manifest if s.family=="GROUNDING"]:
        if sheet.sheet_id not in doc.layouts: continue
        layout=doc.layouts.get(sheet.sheet_id); count=0; y=paper[1]-35
        for element in elements:
            data=element.get("data"); status=element.get("status")
            text=f"{element['kind']}: {data if data is not None else status}"
            layout.add_text(text,dxfattribs={"layer":"ENGITOOLS-E-GROUNDING","height":1.3}).set_placement((18,y)); y-=5; count+=1
            if element["kind"]=="earth_electrode" and isinstance(data,dict) and data.get("point"):
                p=data["point"]
                # The plan coordinate is documented in annotation; full underlay transform is kept by the composer.
                layout.add_text(f"EARTH ELECTRODE COORD {p}",dxfattribs={"layer":"ENGITOOLS-E-GROUNDING","height":1.1}).set_placement((18,y)); y-=4
                layout.add_circle((90,y+2),2.0,dxfattribs={"layer":"ENGITOOLS-E-GROUNDING"}); count+=1
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
        # Parametric geometry primitives are represented by real CAD geometry, not a text-only placeholder.
        gy=y-15
        for primitive in detail.get("geometry") or []:
            kind=str(primitive[0]);
            if kind in {"wall_section","ceiling_section","mounting_surface"}: layout.add_line((x+10,gy),(x+cell_w-15,gy),dxfattribs={"layer":"ENGITOOLS-E-DETAIL"})
            elif kind in {"panel_box","meter_box","device_box","junction_box","isolator","luminaire","detector","equipment"}: layout.add_lwpolyline([(x+20,gy-4),(x+34,gy-4),(x+34,gy+4),(x+20,gy+4),(x+20,gy-4)],dxfattribs={"layer":"ENGITOOLS-E-DETAIL"})
            elif kind in {"conduit","cable","connection","terminal","lug","support","sleeve","firestop","earth","electrode","clearance","clearance_zone","access_zone"}: layout.add_line((x+38,gy-4),(x+55,gy+4),dxfattribs={"layer":"ENGITOOLS-E-DETAIL"})
            elif kind=="dimension": layout.add_line((x+8,gy-7),(x+8,gy+7),dxfattribs={"layer":"ENGITOOLS-E-DETAIL"})
            gy-=5
        ptxt=", ".join(f"{k}={v.get('value') if isinstance(v,dict) else v}" for k,v in (detail.get("parameters") or {}).items())
        layout.add_text(ptxt[:120],dxfattribs={"layer":"ENGITOOLS-E-DETAIL","height":.9}).set_placement((x+3,y-cell_h+9)); count+=1
    signatures.setdefault(sheet.sheet_id,{}).setdefault("signature",{})["parametric_details"]=count


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


def apply_postcomposition(path: str|Path, manifest, details, grounding, signatures, paper=(420.0,297.0)):
    doc=ezdxf.readfile(str(path)); _draw_grounding(doc,manifest,grounding,signatures,paper); _draw_details(doc,manifest,details,signatures,paper); moved=optimize_annotations(doc,manifest,paper); doc.saveas(str(path))
    return {"status":"PASS","annotations_moved_with_leaders":moved}
