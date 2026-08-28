from __future__ import annotations

import hashlib
import html
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from ezdxf import bbox

from .design import FAMILY_RULES, REFERENCE_TAXONOMY


def content_signature_qa(manifest, signatures):
    errors=[]; per_sheet={}
    for sheet in manifest:
        actual=(signatures.get(sheet.sheet_id) or {}).get("signature") or {}; missing=[]
        for key,minimum in sheet.minimum_content_signature.items():
            if int(actual.get(key,0) or 0) < int(minimum): missing.append(f"{key}:{actual.get(key,0)}<{minimum}")
        if sheet.family in {"LIGHTING","POWER","FIRE_ALARM","LOW_CURRENT","GROUNDING"} and actual.get("architectural_underlay",0)<=0:
            missing.append("architectural_underlay:0")
        if missing: errors.append(f"FAIL_EMPTY_ELECTRICAL_CONTENT:{sheet.sheet_id}:{','.join(missing)}")
        per_sheet[sheet.sheet_id]={"status":"PASS" if not missing else "FAIL","actual":actual,"missing":missing}
    return {"status":"PASS" if not errors else "FAIL","errors":errors,"sheets":per_sheet}


def family_purity_qa(path: str|Path, manifest):
    doc=ezdxf.readfile(str(path)); errors=[]; report={}
    for sheet in manifest:
        if sheet.sheet_id not in doc.layouts: errors.append(f"layout_missing:{sheet.sheet_id}"); continue
        layout=doc.layouts.get(sheet.sheet_id); layers={str(getattr(e.dxf,"layer","0")) for e in layout}
        forbidden=sorted(set(sheet.forbidden_layers)&layers)
        if forbidden: errors.append(f"forbidden_layers:{sheet.sheet_id}:{forbidden}")
        report[sheet.sheet_id]={"layers":sorted(layers),"forbidden_present":forbidden}
    return {"status":"PASS" if not errors else "FAIL","errors":errors,"sheets":report}


def _entity_point(entity):
    for attr in ("insert","center","start"):
        try:
            p=getattr(entity.dxf,attr); return round(float(p.x),2),round(float(p.y),2)
        except Exception: pass
    return None


def _fingerprint(layout):
    rows=[]
    for e in layout:
        layer=str(getattr(e.dxf,"layer","0"))
        if layer in {"ENGITOOLS-E-ARCH-UNDERLAY","ENGITOOLS-E-DOC"}: continue
        text=""
        try:
            if e.dxftype()=="TEXT": text=str(e.dxf.text or "")
            elif e.dxftype()=="MTEXT": text=str(e.plain_text() or "")
        except Exception: pass
        name=str(getattr(e.dxf,"name","") or "")
        rows.append((e.dxftype(),layer,name,text[:80],_entity_point(e)))
    rows.sort(key=str)
    return hashlib.sha256(repr(rows).encode()).hexdigest(),len(rows)


def semantic_duplicate_qa(path: str|Path, manifest):
    doc=ezdxf.readfile(str(path)); seen={}; errors=[]; fingerprints={}
    for sheet in manifest:
        if sheet.sheet_id not in doc.layouts: continue
        fp,count=_fingerprint(doc.layouts.get(sheet.sheet_id)); fingerprints[sheet.sheet_id]={"hash":fp,"electrical_entity_count":count,"family":sheet.family}
        if count>0 and fp in seen and seen[fp]["family"]!=sheet.family:
            errors.append(f"FAIL_DUPLICATE_SHEET:{seen[fp]['sheet']}:{sheet.sheet_id}")
        else: seen[fp]={"sheet":sheet.sheet_id,"family":sheet.family}
    return {"status":"PASS" if not errors else "FAIL","errors":errors,"fingerprints":fingerprints}


def reference_similarity_qa(manifest, signatures, threshold: float=.6):
    reference=REFERENCE_TAXONOMY["observed"]["families"]; family_scores={}; errors=[]
    mapping={"LIGHTING":"LIGHTING","POWER":"POWER","FIRE_ALARM":"FIRE_ALARM","LOW_CURRENT":"LOW_CURRENT","GROUNDING":"GROUNDING_BONDING"}
    for family,ref_family in mapping.items():
        sheets=[s for s in manifest if s.family==family]
        if not sheets: continue
        behavior=set(reference.get(ref_family,{}).get("behavior") or []); dimensions=[]
        for sheet in sheets:
            sig=(signatures.get(sheet.sheet_id) or {}).get("signature") or {}
            if family=="LIGHTING": present={"symbols" if sig.get("lighting_fixtures",0)>0 else "", "circuit_graphics" if sig.get("lighting_circuits",0)>0 else "", "annotations" if sig.get("lighting_circuits",0)>0 else "", "control_routes" if sig.get("switches",0)>0 else ""}
            elif family=="POWER": present={"receptacles" if sig.get("power_loads",0)>0 else "", "routes" if sig.get("power_circuits",0)>0 else "", "annotations" if sig.get("power_circuits",0)>0 else ""}
            elif family=="FIRE_ALARM": present={"devices" if sig.get("fire_devices",0)>0 else ""}
            elif family=="LOW_CURRENT": present={"independent_system_graphics" if sig.get("low_current_devices",0)>0 else ""}
            else: present={"bonding_graphics" if sig.get("grounding_elements",0)>0 else ""}
            present.discard(""); score=len(behavior&present)/len(behavior) if behavior else 1.0; dimensions.append(score)
        score=sum(dimensions)/len(dimensions); family_scores[family]=score
        if score<threshold: errors.append(f"reference_similarity:{family}:{score:.3f}<{threshold}")
    return {"status":"PASS" if not errors else "FAIL","errors":errors,"family_scores":family_scores,"threshold":threshold,
            "goal":"engineering_behavior_and_drawing_structure_not_pixel_match"}


def _layout_extents(layout):
    ext=bbox.extents(layout,fast=True)
    if not ext.has_data: return None
    return (float(ext.extmin.x),float(ext.extmin.y),float(ext.extmax.x),float(ext.extmax.y))


def _text_box(e):
    try:
        if e.dxftype()!="TEXT": return None
        p=e.dxf.insert; h=float(e.dxf.height or 0); text=str(e.dxf.text or ""); w=max(h*.55*len(text),h)
        return float(p.x),float(p.y),float(p.x)+w,float(p.y)+h
    except Exception: return None


def _overlap(a,b):
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))


def visual_qa(path: str|Path, manifest, paper=(420.0,297.0)):
    doc=ezdxf.readfile(str(path)); errors=[]; warnings=[]; sheets={}
    for sheet in manifest:
        if sheet.sheet_id not in doc.layouts: errors.append(f"visual_layout_missing:{sheet.sheet_id}"); continue
        layout=doc.layouts.get(sheet.sheet_id); entities=list(layout); ext=_layout_extents(layout)
        if not ext: errors.append(f"blank_layout:{sheet.sheet_id}"); continue
        if ext[0]<-1 or ext[1]<-1 or ext[2]>paper[0]+1 or ext[3]>paper[1]+1: errors.append(f"print_extents_outside_paper:{sheet.sheet_id}:{ext}")
        inserts=[e for e in entities if e.dxftype()=="INSERT"]; texts=[e for e in entities if e.dxftype()=="TEXT"]
        if sheet.family in {"LIGHTING","POWER","FIRE_ALARM","LOW_CURRENT","GROUNDING"} and not inserts:
            errors.append(f"equipment_not_visually_present:{sheet.sheet_id}")
        small=[]
        for e in texts:
            try:
                if float(e.dxf.height or 0)<.8: small.append(str(e.dxf.text or "")[:30])
            except Exception: pass
        if small: warnings.append(f"small_text:{sheet.sheet_id}:{len(small)}")
        boxes=[x for x in (_text_box(e) for e in texts) if x]; overlaps=0
        for i,a in enumerate(boxes):
            for b in boxes[i+1:]:
                if _overlap(a,b)>.5: overlaps+=1
        if overlaps>max(3,len(boxes)//4): errors.append(f"annotation_overlap:{sheet.sheet_id}:{overlaps}")
        sheets[sheet.sheet_id]={"entity_count":len(entities),"insert_count":len(inserts),"text_count":len(texts),"extents":ext,"text_overlaps":overlaps}
    return {"status":"FAIL" if errors else ("PRELIMINARY" if warnings else "PASS"),"errors":errors,"warnings":warnings,"sheets":sheets}


def render_layout_svg(layout, output_path: str|Path, paper=(420.0,297.0)):
    """Produce a deterministic lightweight visual preview from the re-opened DXF layout."""
    lines=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{paper[0]}mm" height="{paper[1]}mm" viewBox="0 0 {paper[0]} {paper[1]}">',f'<rect x="0" y="0" width="{paper[0]}" height="{paper[1]}" fill="white"/>']
    def sy(y): return paper[1]-y
    count=0
    for e in layout:
        try:
            if e.dxftype()=="LINE":
                a=e.dxf.start;b=e.dxf.end;lines.append(f'<line x1="{a.x}" y1="{sy(a.y)}" x2="{b.x}" y2="{sy(b.y)}" stroke="black" stroke-width="0.25"/>');count+=1
            elif e.dxftype()=="CIRCLE":
                c=e.dxf.center;r=e.dxf.radius;lines.append(f'<circle cx="{c.x}" cy="{sy(c.y)}" r="{r}" fill="none" stroke="black" stroke-width="0.25"/>');count+=1
            elif e.dxftype()=="LWPOLYLINE":
                pts=" ".join(f"{x},{sy(y)}" for x,y,*_ in e.get_points("xy"));lines.append(f'<polyline points="{pts}" fill="none" stroke="black" stroke-width="0.25"/>');count+=1
            elif e.dxftype()=="TEXT":
                p=e.dxf.insert;t=html.escape(str(e.dxf.text or ""));h=max(float(e.dxf.height or 1),.7);lines.append(f'<text x="{p.x}" y="{sy(p.y)}" font-size="{h}">{t}</text>');count+=1
            elif e.dxftype()=="INSERT":
                p=e.dxf.insert;lines.append(f'<circle cx="{p.x}" cy="{sy(p.y)}" r="1.4" fill="none" stroke="black" stroke-width="0.35"/>');count+=1
        except Exception: continue
    lines.append('</svg>'); Path(output_path).write_text("\n".join(lines),encoding="utf-8"); return count


def final_reopen_qa(path: str|Path, manifest, expected_signatures, render_dir: Optional[str|Path]=None, paper=(420.0,297.0)):
    """SAVE -> CLOSE -> REOPEN SAME FILE -> VALIDATE -> RENDER SAME FILE."""
    path=Path(path); errors=[]; renders=[]
    if not path.exists() or path.stat().st_size<=0: return {"status":"FAIL","errors":["file_missing_or_empty"]}
    doc=ezdxf.readfile(str(path)); audit=doc.audit()
    if audit.errors: errors.append(f"dxf_audit_errors:{len(audit.errors)}")
    if len(doc.modelspace())<=0: errors.append("modelspace_empty")
    actual_layouts={x.name for x in doc.layouts if x.name!="Model"}; expected={s.sheet_id for s in manifest}
    if actual_layouts!=expected: errors.append(f"layout_manifest_mismatch:actual={sorted(actual_layouts)} expected={sorted(expected)}")
    for name in expected:
        if name not in doc.layouts: continue
        layout=doc.layouts.get(name)
        if len(layout)<=0: errors.append(f"blank_layout:{name}")
        ext=_layout_extents(layout)
        if not ext: errors.append(f"no_extents:{name}")
    if render_dir:
        rd=Path(render_dir);rd.mkdir(parents=True,exist_ok=True)
        for name in sorted(expected&actual_layouts):
            target=rd/f"{name}.svg"; count=render_layout_svg(doc.layouts.get(name),target,paper); renders.append(str(target))
            if count<=0 or target.stat().st_size<100: errors.append(f"render_empty:{name}")
    return {"status":"PASS" if not errors else "FAIL","errors":errors,"file_size_bytes":path.stat().st_size,"layout_count":len(actual_layouts),"renders":renders}
