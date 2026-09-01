"""Fail-closed release hardening for mechanical authority drawings."""
from __future__ import annotations
from pathlib import Path
import hashlib

import ezdxf
from ezdxf import bbox


def _inside(inner, outer, tol=1e-9):
    return (inner[0] >= outer[0]-tol and inner[1] >= outer[1]-tol and
            inner[2] <= outer[2]+tol and inner[3] <= outer[3]+tol)


def _overlap(a, b, tol=1e-9):
    return not (a[2] <= b[0]+tol or b[2] <= a[0]+tol or
                a[3] <= b[1]+tol or b[3] <= a[1]+tol)


def validate_layout_geometry(composition: dict, minimum_clear_gap: float = 7.5) -> dict:
    """Reject overlapping boards and unsafe internal sheet zones."""
    boards=(composition or {}).get("boards") or {}
    errors=[]; rows=[]
    normalized={}
    for key,board in boards.items():
        try:
            bounds=tuple(map(float,board["bounds"])); plan=tuple(map(float,board["plan_area"]))
            title=tuple(map(float,board["title_area"])); subtitle=tuple(map(float,board["subtitle_area"]))
            if not all(len(x)==4 for x in (bounds,plan,title,subtitle)): raise ValueError
        except Exception:
            errors.append(f"invalid_board_geometry:{key}"); continue
        normalized[key]=(bounds,plan,title,subtitle)
        if not all(_inside(zone,bounds) for zone in (plan,title,subtitle)):
            errors.append(f"zone_outside_board:{key}")
        if _overlap(plan,title) or _overlap(plan,subtitle) or _overlap(title,subtitle):
            errors.append(f"internal_zone_overlap:{key}")
        rows.append({"board_id":key,"bounds":bounds,"plan_area":plan,
                     "title_area":title,"subtitle_area":subtitle})
    keys=list(normalized)
    minimum_gap=None
    for i,left in enumerate(keys):
        a=normalized[left][0]
        for right in keys[i+1:]:
            b=normalized[right][0]
            if _overlap(a,b): errors.append(f"board_overlap:{left}:{right}"); gap=0.0
            else:
                gx=max(b[0]-a[2],a[0]-b[2],0.0); gy=max(b[1]-a[3],a[1]-b[3],0.0)
                gap=max(gx,gy)
            minimum_gap=gap if minimum_gap is None else min(minimum_gap,gap)
            if gap+1e-9 < minimum_clear_gap: errors.append(f"board_clear_gap:{left}:{right}:{gap:.3f}")
    if not boards: errors.append("no_boards")
    return {"version":"layout-geometry-gate-v18.0","status":"PASS" if not errors else "FAIL",
            "errors":sorted(set(errors)),"board_count":len(boards),
            "minimum_clear_gap":minimum_gap,"minimum_required_gap":minimum_clear_gap,"boards":rows}


def _entity_center(entity):
    try:
        ex=bbox.extents([entity],fast=True)
        if ex.has_data: return ((ex.extmin.x+ex.extmax.x)/2,(ex.extmin.y+ex.extmax.y)/2)
    except Exception: pass
    return None


def _plain_text(entity):
    try:
        if entity.dxftype()=="TEXT": return str(entity.dxf.text or "")
        if entity.dxftype()=="MTEXT": return str(entity.plain_text() or "")
    except Exception: pass
    return ""


def validate_titleblocks(path: Path, composition: dict) -> dict:
    """Require one readable sheet code and complete title-block geometry per board."""
    boards=(composition or {}).get("boards") or {}; rows=(composition or {}).get("manifest") or []
    errors=[]; results=[]
    try: doc=ezdxf.readfile(Path(path)); entities=list(doc.modelspace())
    except Exception as exc:
        return {"version":"titleblock-gate-v18.0","status":"FAIL","errors":["exact_dxf_reopen_failed"],"detail":str(exc)}
    by_old={str(r.get("old_sheet")):r for r in rows}
    for key,board in boards.items():
        title=tuple(map(float,board.get("title_area") or ())); code=str((by_old.get(str(key)) or {}).get("code") or board.get("code") or "").strip()
        if len(title)!=4 or not code:
            errors.append(f"titleblock_contract_missing:{key}"); continue
        inside=[]
        for entity in entities:
            p=_entity_center(entity)
            if p and title[0]-.02<=p[0]<=title[2]+.02 and title[1]-.02<=p[1]<=title[3]+.02:
                inside.append(entity)
        grid=sum(1 for e in inside if str(getattr(e.dxf,"layer","")).upper()=="ENGITOOLS-SHEET-GRID")
        code_hits=sum(1 for e in inside if code in _plain_text(e))
        status="PASS" if grid>=10 and code_hits==1 else "FAIL"
        if grid<10: errors.append(f"titleblock_grid_incomplete:{code}:{grid}")
        if code_hits!=1: errors.append(f"titleblock_code_count:{code}:{code_hits}")
        results.append({"board_id":key,"code":code,"grid_entity_count":grid,"code_count":code_hits,"status":status})
    if len(results)!=len(boards): errors.append(f"titleblock_count_mismatch:{len(results)}:{len(boards)}")
    return {"version":"titleblock-gate-v18.0","status":"PASS" if not errors else "FAIL","errors":sorted(set(errors)),
            "expected_titleblocks":len(boards),"validated_titleblocks":sum(r["status"]=="PASS" for r in results),
            "boards":results,"exact_file_reopened":True}


def validate_safe_zones(path: Path, composition: dict) -> dict:
    """Reject drawing entities intruding into reserved title/subtitle zones."""
    boards=(composition or {}).get("boards") or {}; errors=[]; results=[]
    try: doc=ezdxf.readfile(Path(path)); entities=list(doc.modelspace())
    except Exception as exc:
        return {"version":"safe-zone-gate-v18.0","status":"FAIL","errors":["exact_dxf_reopen_failed"],"detail":str(exc)}
    for key,board in boards.items():
        title=tuple(map(float,board.get("title_area") or ())); subtitle=tuple(map(float,board.get("subtitle_area") or ()))
        intrusions=[]
        for entity in entities:
            layer=str(getattr(entity.dxf,"layer","") or "").upper()
            if layer.startswith("ENGITOOLS-SHEET-") or layer.startswith("ENGITOOLS-V17-DOCUMENTATION"): continue
            p=_entity_center(entity)
            if not p: continue
            if ((len(title)==4 and title[0]<=p[0]<=title[2] and title[1]<=p[1]<=title[3]) or
                (len(subtitle)==4 and subtitle[0]<=p[0]<=subtitle[2] and subtitle[1]<=p[1]<=subtitle[3])):
                intrusions.append(str(getattr(entity.dxf,"handle","") or entity.dxftype()))
        if intrusions: errors.append(f"reserved_zone_intrusion:{key}:{len(intrusions)}")
        results.append({"board_id":key,"intrusion_count":len(intrusions),"status":"PASS" if not intrusions else "FAIL"})
    return {"version":"safe-zone-gate-v18.0","status":"PASS" if not errors else "FAIL","errors":errors,
            "boards":results,"exact_file_reopened":True}


def validate_architectural_presentation(path: Path, composition: dict) -> dict:
    """Forbid duplicate north graphics, source print frames and subtitle bands."""
    boards=(composition or {}).get("boards") or {};errors=[];results=[]
    try:doc=ezdxf.readfile(Path(path));entities=list(doc.modelspace())
    except Exception as exc:return {"version":"architectural-presentation-gate-v18.2","status":"FAIL","errors":["exact_dxf_reopen_failed"],"detail":str(exc)}
    generated_north=[e for e in entities if str(getattr(e.dxf,"layer","") or "").upper()=="ENGITOOLS-SHEET-NORTH"]
    if generated_north:errors.append(f"duplicate_generated_north:{len(generated_north)}")
    subtitle_entities=[e for e in entities if str(getattr(e.dxf,"layer","") or "").upper()=="ENGITOOLS-SHEET-SUBTITLE"]
    if subtitle_entities:errors.append(f"forbidden_subtitle_band:{len(subtitle_entities)}")
    for key,board in boards.items():
        area=tuple(map(float,board.get("plan_area") or ()));frames=[]
        if len(area)==4:
            aw=max(area[2]-area[0],1e-9);ah=max(area[3]-area[1],1e-9)
            for e in entities:
                if e.dxftype() not in {"LWPOLYLINE","POLYLINE"}:continue
                try:
                    if not e.closed:continue
                    ex=bbox.extents([e],fast=True)
                    if not ex.has_data:continue
                    x1,y1,x2,y2=map(float,(ex.extmin.x,ex.extmin.y,ex.extmax.x,ex.extmax.y))
                    if (x2-x1)>=aw*.88 and (y2-y1)>=ah*.88 and _inside((x1,y1,x2,y2),area,.08):frames.append(str(getattr(e.dxf,"handle","") or "POLYLINE"))
                except Exception:continue
        if frames:errors.append(f"source_print_frame_present:{key}:{len(frames)}")
        results.append({"board_id":key,"source_frame_count":len(frames),"status":"PASS" if not frames else "FAIL"})
    return {"version":"architectural-presentation-gate-v18.2","status":"PASS" if not errors else "FAIL","errors":errors,"boards":results,"generated_north_count":len(generated_north),"subtitle_entity_count":len(subtitle_entities),"exact_file_reopened":True}


def validate_equipment_linkage(path: Path, composition: dict) -> dict:
    """Require equipment symbols and their service routes for active families."""
    family_contract={
        "SPLIT_AC":["ENGITOOLS-M-HVAC-EQUIP","ENGITOOLS-M-HVAC-REFRIG","ENGITOOLS-M-HVAC-COND"],
        "HEATING":["ENGITOOLS-M-PACKAGE","ENGITOOLS-M-RADIATOR","ENGITOOLS-M-HEAT-FLOW","ENGITOOLS-M-HEAT-RETURN"],
        "GAS":["ENGITOOLS-M-GAS"],
        "ROOF":["ENGITOOLS-M-HVAC-EQUIP"],
    }
    try: doc=ezdxf.readfile(Path(path)); entities=list(doc.modelspace())
    except Exception as exc:return {"version":"equipment-linkage-gate-v18.0","status":"FAIL","errors":["exact_dxf_reopen_failed"],"detail":str(exc)}
    errors=[];results=[]
    all_families={str(b.get("family") or "").upper() for b in ((composition or {}).get("boards") or {}).values()}
    for key,board in ((composition or {}).get("boards") or {}).items():
        family=str(board.get("family") or "").upper(); required=family_contract.get(family)
        if family=="SPLIT_AC" and str(board.get("level") or "").upper()=="ROOF":required=["ENGITOOLS-M-HVAC-EQUIP"]
        if family=="ROOF" and "SPLIT_AC" not in all_families: required=None
        if not required:continue
        area=tuple(map(float,board.get("plan_area") or ())); counts={layer:0 for layer in required}
        for e in entities:
            layer=str(getattr(e.dxf,"layer","") or "").upper();p=_entity_center(e)
            if layer in counts and p and len(area)==4 and area[0]<=p[0]<=area[2] and area[1]<=p[1]<=area[3]:counts[layer]+=1
        missing=[layer for layer,count in counts.items() if count<1]
        semantic={}
        if family=="SPLIT_AC":
            roof=str(board.get("level") or "").upper()=="ROOF";expected_name="ENGI_AC_OUTDOOR" if roof else "ENGI_AC_INDOOR";expected_label="ODU" if roof else "IDU"
            local=[e for e in entities if (p:=_entity_center(e)) and len(area)==4 and area[0]<=p[0]<=area[2] and area[1]<=p[1]<=area[3]]
            equipment=[e for e in local if e.dxftype()=="INSERT" and str(getattr(e.dxf,"name","")).upper()==expected_name]
            callouts=[e for e in local if str(getattr(e.dxf,"layer","")).upper()=="ENGITOOLS-M-HVAC-CALLOUT" and expected_label in _plain_text(e).upper()]
            leaders=[e for e in local if str(getattr(e.dxf,"layer","")).upper()=="ENGITOOLS-M-HVAC-CALLOUT" and e.dxftype() in {"LINE","LWPOLYLINE"}]
            airflow=[e for e in local if str(getattr(e.dxf,"layer","")).upper()=="ENGITOOLS-M-HVAC-AIRFLOW"]
            definition=doc.blocks.get(expected_name) if expected_name in doc.blocks else []
            definition_text=" ".join(_plain_text(e) for e in definition).upper()
            semantic={"expected_block":expected_name,"equipment_count":len(equipment),"callout_count":len(callouts),"leader_count":len(leaders),"airflow_entity_count":len(airflow),"definition_label":expected_label in definition_text}
            if not equipment:missing.append("standard_equipment_block=0")
            if len(callouts)<len(equipment):missing.append(f"readable_callouts={len(callouts)}<{len(equipment)}")
            if len(leaders)<len(equipment):missing.append(f"callout_leaders={len(leaders)}<{len(equipment)}")
            if not roof and len(airflow)<len(equipment):missing.append(f"airflow_geometry={len(airflow)}<{len(equipment)}")
            if not semantic["definition_label"]:missing.append(f"block_label_missing:{expected_label}")
            for layer in (["ENGITOOLS-M-HVAC-REFRIG","ENGITOOLS-M-HVAC-COND"] if not roof else []):
                if counts.get(layer,0)<len(equipment):missing.append(f"linked_{layer}={counts.get(layer,0)}<{len(equipment)}")
        if missing:errors.append(f"equipment_or_route_missing:{key}:"+",".join(missing))
        results.append({"board_id":key,"family":family,"counts":counts,"semantic":semantic,"status":"PASS" if not missing else "FAIL"})
    return {"version":"equipment-linkage-gate-v18.0","status":"PASS" if not errors else "FAIL","errors":errors,"boards":results,"exact_file_reopened":True}


def validate_split_ac_visual_legibility(path: Path, composition: dict, preview_dir: Path | None=None,
                                        minimum_symbol_pixels: tuple[int,int]=(28,14), minimum_ink_pixels: int=20) -> dict:
    """Render every Split-AC sheet and reject symbols that are not visibly legible."""
    path=Path(path);preview_dir=Path(preview_dir) if preview_dir else None;errors=[];results=[]
    try:
        doc=ezdxf.readfile(path);entities=list(doc.modelspace())
        from ezdxf.addons.drawing import RenderContext,Frontend
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        import matplotlib;matplotlib.use("Agg")
        from matplotlib import pyplot as plt
        fig=plt.figure(figsize=(8.27,11.69),dpi=120,facecolor="#101820");ax=fig.add_axes([.02,.02,.96,.96],facecolor="#101820");ax.set_axis_off();Frontend(RenderContext(doc),MatplotlibBackend(ax)).draw_layout(doc.modelspace(),finalize=True)
        if preview_dir:preview_dir.mkdir(parents=True,exist_ok=True)
        for key,board in ((composition or {}).get("boards") or {}).items():
            if str(board.get("family") or "").upper()!="SPLIT_AC":continue
            bounds=tuple(map(float,board.get("bounds") or ()));area=tuple(map(float,board.get("plan_area") or ()));roof=str(board.get("level") or "").upper()=="ROOF";name="ENGI_AC_OUTDOOR" if roof else "ENGI_AC_INDOOR"
            ax.set_xlim(bounds[0],bounds[2]);ax.set_ylim(bounds[1],bounds[3]);fig.canvas.draw();np=__import__("numpy");rgba=np.asarray(fig.canvas.buffer_rgba());board_ink=int((np.abs(rgba[:,:,:3].astype(int)-np.array([16,24,32]))>18).any(axis=2).sum())
            units=[]
            for e in entities:
                p=_entity_center(e)
                if e.dxftype()!="INSERT" or str(getattr(e.dxf,"name","")).upper()!=name or not p or not(area[0]<=p[0]<=area[2] and area[1]<=p[1]<=area[3]):continue
                ex=bbox.extents([e],fast=True);a=ax.transData.transform((ex.extmin.x,ex.extmin.y));b=ax.transData.transform((ex.extmax.x,ex.extmax.y));w=abs(int(b[0]-a[0]));h=abs(int(b[1]-a[1]));long_px=max(w,h);short_px=min(w,h);ink=board_ink;units.append({"handle":str(e.dxf.handle),"pixel_width":w,"pixel_height":h,"pixel_long_side":long_px,"pixel_short_side":short_px,"rendered_board_ink_pixels":ink});
                if long_px<minimum_symbol_pixels[0] or short_px<minimum_symbol_pixels[1]:errors.append(f"split_symbol_too_small:{key}:{w}x{h}")
            if not units:errors.append(f"split_visual_no_equipment:{key}")
            preview=None
            if preview_dir:
                preview=preview_dir/f"{board.get('code') or key}-{board.get('level') or ''}.png";fig.savefig(preview,dpi=120,facecolor="#101820")
                if not preview.exists() or preview.stat().st_size<1500:errors.append(f"split_preview_empty:{key}")
            results.append({"board_id":key,"code":board.get("code"),"unit_count":len(units),"units":units,"preview":str(preview) if preview else None,"status":"PASS" if units and not any(f":{key}:" in x for x in errors) else "FAIL"})
        plt.close(fig)
    except Exception as exc:return {"version":"split-ac-visual-legibility-v18.1","status":"FAIL","errors":["split_visual_render_failed"],"detail":str(exc)}
    if not results:errors.append("no_split_ac_boards")
    return {"version":"split-ac-visual-legibility-v18.1","status":"PASS" if not errors else "FAIL","errors":errors,"boards":results,"exact_file_reopened":True}


def validate_detail_library(path: Path, composition: dict, minimum_geometry: int = 12) -> dict:
    """Reject register-only detail sheets; tags and executable geometry are required."""
    try:doc=ezdxf.readfile(Path(path));entities=list(doc.modelspace())
    except Exception as exc:return {"version":"detail-library-gate-v18.0","status":"FAIL","errors":["exact_dxf_reopen_failed"],"detail":str(exc)}
    errors=[];results=[]
    for key,board in ((composition or {}).get("boards") or {}).items():
        if str(board.get("family") or "").upper()!="GENERAL_DETAIL":continue
        area=tuple(map(float,board.get("plan_area") or ()));geometry=tags=0
        for e in entities:
            p=_entity_center(e);layer=str(getattr(e.dxf,"layer","") or "").upper()
            if not p or len(area)!=4 or not(area[0]<=p[0]<=area[2] and area[1]<=p[1]<=area[3]):continue
            if layer=="ENGITOOLS-M-DETAIL" and e.dxftype() not in {"TEXT","MTEXT"}:geometry+=1
            if layer=="ENGITOOLS-M-DETAIL" and "D-" in _plain_text(e).upper():tags+=1
        missing=[]
        if geometry<minimum_geometry:missing.append(f"geometry={geometry}")
        if tags<2:missing.append(f"tags={tags}")
        if missing:errors.append(f"detail_sheet_incomplete:{key}:"+",".join(missing))
        results.append({"board_id":key,"geometry_count":geometry,"detail_tag_count":tags,"status":"PASS" if not missing else "FAIL"})
    if not results:errors.append("no_detail_sheets")
    return {"version":"detail-library-gate-v18.0","status":"PASS" if not errors else "FAIL","errors":errors,"boards":results,"exact_file_reopened":True}


def validate_content_completeness(path: Path, composition: dict) -> dict:
    """Per-board semantic content gate; global entity totals cannot mask blanks."""
    try:doc=ezdxf.readfile(Path(path));entities=list(doc.modelspace())
    except Exception as exc:return {"version":"content-completeness-gate-v18.0","status":"FAIL","errors":["exact_dxf_reopen_failed"],"detail":str(exc)}
    plan_families={"ROOF","SANITARY_VENT","WATER","HEATING","GAS","SPLIT_AC","EXHAUST"};errors=[];results=[]
    for key,board in ((composition or {}).get("boards") or {}).items():
        family=str(board.get("family") or "").upper();area=tuple(map(float,board.get("plan_area") or ()));mechanical=annotations=0
        for e in entities:
            p=_entity_center(e);layer=str(getattr(e.dxf,"layer","") or "").upper()
            if not p or len(area)!=4 or not(area[0]<=p[0]<=area[2] and area[1]<=p[1]<=area[3]):continue
            if layer.startswith("ENGITOOLS-M-") or layer.startswith("ENGITOOLS-V17-DOCUMENTATION"):mechanical+=1
            if e.dxftype() in {"TEXT","MTEXT"} and (layer.startswith("ENGITOOLS-M-") or layer.startswith("ENGITOOLS-V17-")):annotations+=1
        minimum=2 if family in plan_families else 1
        missing=[]
        if mechanical<minimum:missing.append(f"mechanical={mechanical}<{minimum}")
        if family in plan_families and annotations<1:missing.append("annotation=0")
        if missing:errors.append(f"board_content_incomplete:{key}:"+",".join(missing))
        results.append({"board_id":key,"family":family,"mechanical_entity_count":mechanical,"annotation_count":annotations,"status":"PASS" if not missing else "FAIL"})
    return {"version":"content-completeness-gate-v18.0","status":"PASS" if not errors else "FAIL","errors":errors,"boards":results,"exact_file_reopened":True}


def create_montage_and_validate(path: Path, montage_path: Path) -> dict:
    """Render the exact issued DXF and prove that reopen is non-mutating."""
    path=Path(path);montage_path=Path(montage_path);before=path.read_bytes();digest=hashlib.sha256(before).hexdigest()
    try:
        doc=ezdxf.readfile(path);entity_count=len(doc.modelspace())
        from ezdxf.addons.drawing import RenderContext, Frontend
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import pyplot as plt
        fig=plt.figure(figsize=(18,12),dpi=110);ax=fig.add_axes([.01,.01,.98,.98]);ax.set_axis_off()
        Frontend(RenderContext(doc),MatplotlibBackend(ax)).draw_layout(doc.modelspace(),finalize=True)
        montage_path.parent.mkdir(parents=True,exist_ok=True);fig.savefig(montage_path,dpi=110,bbox_inches="tight",facecolor="white");plt.close(fig)
    except Exception as exc:
        return {"version":"montage-exact-reopen-gate-v18.0","status":"FAIL","errors":["montage_render_or_reopen_failed"],"detail":str(exc)}
    after=path.read_bytes();errors=[]
    if hashlib.sha256(after).hexdigest()!=digest:errors.append("exact_file_changed_during_qa")
    if entity_count<1:errors.append("exact_file_empty")
    if not montage_path.exists() or montage_path.stat().st_size<1500:errors.append("montage_empty_or_too_small")
    return {"version":"montage-exact-reopen-gate-v18.0","status":"PASS" if not errors else "FAIL","errors":errors,
            "exact_file_reopened":True,"sha256":digest,"entity_count":entity_count,"montage_path":str(montage_path),
            "montage_size_bytes":montage_path.stat().st_size if montage_path.exists() else 0}
