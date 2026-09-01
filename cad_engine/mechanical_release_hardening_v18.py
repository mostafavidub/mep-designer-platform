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
    return {"version":"split-ac-visuao¾vòÚ$z{-®éÜj×^LŽˆÛÝ[
ÏLBˆÝ]\ÏIÔTÔÉÈYˆÛÝ[Œ[ÙH	ÑRS	ÂˆYˆÝ]\ÏOIÑRS	Îˆ\œ›ÜœË˜\[™
	Ù[\WÜ[—ÛYXÚ[šXØ[Ø›Ø\™‰ÊÜÝŠ›ÝÖÉØÛÙI×HÜˆ›ÝÖÉÛÛÜÚY]	×JJBˆ™\Ý[Ë˜\[™
ÉØÛÙIÎœ›ÝÖÉØÛÙI×K	Ø›Ø\™ÚY	Îœ›ÝÖÉÛÛÜÚY]	×K	ÛYXÚ[šXØ[Ù[]WØÛÝ[	Î˜ÛÝ[	ÜÝ]\ÉÎœÝ]\ßJBˆ™]\›ˆÉÝ™\œÚ[Û‰Î‰Ü[‹X›Ø\™\Ü[][Û‹]ŒMË‰Ë	ÜÝ]\ÉÎ‰ÔTÔÉÈYˆ›Ý\œ›ÜœÈ[ÙH	ÑRS	Ë	Ù\œ›ÜœÉÎ™\œ›ÜœË	Ø›Ø\™ÉÎœ™\Ý[Ë	Ù^XÝÙš[WÜ™[Ü[™Y	Î•Y_B‚‚™Yˆ\ÚYÛ—ÛYXÚ[šXØ[Ø]]Üš]WÜÚ]JÜ˜Î”]Ý”][œÝÙ\œÎ™XÝ›Û™OS›Û™K[—Ø[˜[\Ú\Î™XÝ›Û™OS›Û™JKO™XÝ‚ˆÜ˜ÏT]
Ü˜ÊNÙÝT]
Ý
NØ[œÝÙ\œÏWÛ›Ü›X[^™WÜ›Ú™XÝØ[œÝÙ\œÊ[œÝÙ\œÊNØ˜XÚÝ\S›Û™BˆYˆÝ™^\ÝÊ
N‚ˆ™˜[YO][\š[K›ZÜÝ[\
™Yš^IÙ[™Ú]ÛÛË]ŒMËX˜XÚÝ\IËÝY™š^IË™‰ÊNÔ]
˜[YJK[›[šÊZ\ÜÚ[™×ÛÚÏUYJNØ˜XÚÝ\T]
˜[YJNÜÚ][˜ÛÜLŠÝ˜XÚÝ\
Bˆ™\ÜWÙ\ÚYÛ—ÝŒMŠÜ˜ËÝ[œÝÙ\œÏX[œÝÙ\œË[—Ø[˜[\Ú\Ï\[—Ø[˜[\Ú\ÊBˆYˆ™\Ü™Ù]
	ÜÝ]\ÉÊHOIÔTÔÉÎ‚ˆYˆ˜XÚÝ\[™˜XÚÝ\™^\ÝÊ
NœÚ][˜ÛÜLŠ˜XÚÝ\Ý
NØ˜XÚÝ\[›[šÊZ\ÜÚ[™×ÛÚÏUYJBˆ™]\›ˆ™\Üˆ[œ™\ÛÛ™YWÜ™[X\ÙWÚ[œ]Ù\œ›ÜœÊ™\Ü
NÜ™\ÜÉÜ™[X\ÙWÚ[œ]ÜXI×O^ÉÝ™\œÚ[Û‰Î‰Ü™[X\ÙKZ[œ]YØ]K]ŒMË‰Ë	ÜÝ]\ÉÎ‰ÔTÔÉÈYˆ›Ý[œ™\ÛÛ™Y[ÙH	ÑRS	Ë	Ù\œ›ÜœÉÎ[œ™\ÛÛ™YBˆYˆ[œ™\ÛÛ™Y‚ˆ™\ÜÉÜÝ]\É×OIÑRS	ÎÜ™\ÜÉÜÝYÙI×OIÜ™[X\ÙWÚ[œ]ÙØ]IÎ×Ü™\ÝÜ™WÛÜ—Ü™[[Ý™JÝ˜XÚÝ\
BˆYˆ˜XÚÝ\˜˜XÚÝ\[›[šÊZ\ÜÚ[™×ÛÚÏUYJBˆ™]\›ˆ™\ÜˆX[šY™\ÝÜXO]˜[Y]WØ\›Ý™YÛX[šY™\Ý
™\Ü[œÝÙ\œÊNÜ™\ÜÉØ\›Ý™YÛX[šY™\ÝÜXI×O[X[šY™\ÝÜXBˆYˆX[šY™\ÝÜXK™Ù]
	ÜÝ]\ÉÊOOIÑRS	Î‚ˆ™\ÜÉÜÝ]\É×OIÑRS	ÎÜ™\ÜÉÜÝYÙI×OIØ\›Ý™YÛX[šY™\ÝÙØ]IÎ×Ü™\ÝÜ™WÛÜ—Ü™[[Ý™JÝ˜XÚÝ\
BˆYˆ˜XÚÝ\˜˜XÚÝ\[›[šÊZ\ÜÚ[™×ÛÚÏUYJBˆ™]\›ˆ™\ÜˆÙ[ÛY]žO]˜[Y]WÛ^[Ý]ÙÙ[ÛY]žJ™\Ü™Ù]
	ØÛÛ\ÜÚ][Û‰ÊHÜˆßJNÜ™\ÜÉÛ^[Ý]ÙÙ[ÛY]žWÜXI×OYÙ[ÛY]žBˆYˆÙ[ÛY]žK™Ù]
	ÜÝ]\ÉÊHOIÔTÔÉÎ‚ˆ™\ÜÉÜÝ]\É×OIÑRS	ÎÜ™\ÜÉÜÝYÙI×OIÛ^[Ý]ÙÙ[ÛY]žWÙØ]IÎ×Ü™\ÝÜ™WÛÜ—Ü™[[Ý™JÝ˜XÚÝ\
BˆYˆ˜XÚÝ\˜˜XÚÝ\[›[šÊZ\ÜÚ[™×ÛÚÏUYJBˆ™]\›ˆ™\ÜˆÛÛ^\›Ú™XÝØÛÛ^Ùœ›ÛWÜ™\Ü
™\Ü[œÝÙ\œÏX[œÝÙ\œË›Ú™XÝÚY\Ü˜ËœÝ[JNÜXÚØYÙOXZ[ÙØÝ[Y[][Û—ÜXÚØYÙJÛÛ^
NÜ™\ÜÉÜ™Y™\™[˜ÙWÜ\š]WÙØÝ[Y[][Û‰×O\XÚØYÙBˆYˆXÚØYÙK™Ù]
	ÜÝ]\ÉÊHOIÔTÔÉÎ‚ˆ™\ÜÉÜÝ]\É×OIÑRS	ÎÜ™\ÜÉÜÝYÙI×OIÜ™Y™\™[˜ÙWÜ\š]WÙØÝ[Y[][Û—ÙØ]IÎ×Ü™\ÝÜ™WÛÜ—Ü™[[Ý™JÝ˜XÚÝ\
BˆYˆ˜XÚÝ\˜˜XÚÝ\[›[šÊZ\ÜÚ[™×ÛÚÏUYJBˆ™]\›ˆ™\Üˆ[š[˜Ù[Y[X\WÙØÝ[Y[][Û—Ù[š[˜Ù[Y[ÊÝ™\ÜÛÛ^
NÜ™\ÜÉÙØÝ[Y[][Û—Ù[š[˜Ù[Y[ÜXI×OY[š[˜Ù[Y[ˆYˆ[š[˜Ù[Y[™Ù]
	ÜÝ]\ÉÊHOIÔTÔÉÎ‚ˆ™\ÜÉÜÝ]\É×OIÑRS	ÎÜ™\ÜÉÜÝYÙI×OIÙØÝ[Y[][Û—Ù[š[˜Ù[Y[ÙØ]IÎ×Ü™\ÝÜ™WÛÜ—Ü™[[Ý™JÝ˜XÚÝ\
BˆYˆ˜XÚÝ\˜˜XÚÝ\[›[šÊZ\ÜÚ[™×ÛÚÏUYJBˆ™]\›ˆ™\Üˆ\ÛÛ][Û\Ø[š]^™WÝ×Ø\›Ý™YØ›Ø\™ÊÝ™\Ü
NÜ™\ÜÉÙš[˜[Ù[]™\žWÚ\ÛÛ][Û—ÜXI×OZ\ÛÛ][Û‚ˆYˆ\ÛÛ][Û‹™Ù]
	ÜÝ]\ÉÊHOIÔTÔÉÎ‚ˆ™\ÜÉÜÝ]\É×OIÑRS	ÎÜ™\ÜÉÜÝYÙI×OIÙš[˜[Ù[]™\žWÚ\ÛÛ][Û—ÙØ]IÎ×Ü™\ÝÜ™WÛÜ—Ü™[[Ý™JÝ˜XÚÝ\
BˆYˆ˜XÚÝ\˜˜XÚÝ\[›[šÊZ\ÜÚ[™×ÛÚÏUYJBˆ™]\›ˆ™\Üˆ\™[š[™×ÙØ]\ÏJˆ
	Ý]X›ØÚ×ÜXIË˜[Y]WÝ]X›ØÚÜÊÝ™\Ü™Ù]
	ØÛÛ\ÜÚ][Û‰ÊHÜˆßJK	Ý]X›ØÚ×ÙØ]IÊKˆ
	ÜØY™WÞ›Û™WÜXIË˜[Y]WÜØY™WÞ›Û™\ÊÝ™\Ü™Ù]
	ØÛÛ\ÜÚ][Û‰ÊHÜˆßJK	ÜØY™WÞ›Û™WÙØ]IÊKˆ
	Ø\˜Ú]XÝ\˜[Ü™\Ù[][Û—ÜXIË˜[Y]WØ\˜Ú]XÝ\˜[Ü™\Ù[][ÛŠÝ™\Ü™Ù]
	ØÛÛ\ÜÚ][Û‰ÊHÜˆßJK	Ø\˜Ú]XÝ\˜[Ü™\Ù[][Û—ÙØ]IÊKˆ
	Ù\]Z\Y[Û[šØYÙWÜXIË˜[Y]WÙ\]Z\Y[Û[šØYÙJÝ™\Ü™Ù]
	ØÛÛ\ÜÚ][Û‰ÊHÜˆßJK	Ù\]Z\Y[Û[šØYÙWÙØ]IÊKˆ
	ÜÜ]ØX×Ýš\ÝX[ÜXIË˜[Y]WÜÜ]ØX×Ýš\ÝX[ÛYÚXš[]JÝ™\Ü™Ù]
	ØÛÛ\ÜÚ][Û‰ÊHÜˆßKÝÚ]Û˜[YJÝœÝ[JÉË\Ü]\™]šY]ÜÉÊJK	ÜÜ]ØX×Ýš\ÝX[ÙØ]IÊKˆ
	Ù]Z[ÛXœ˜\žWÜXIË˜[Y]WÙ]Z[ÛXœ˜\žJÝ™\Ü™Ù]
	ØÛÛ\ÜÚ][Û‰ÊHÜˆßJK	Ù]Z[ÛXœ˜\žWÙØ]IÊKˆ
	ØÛÛ[ØÛÛ\][™\Ü×ÜXIË˜[Y]WØÛÛ[ØÛÛ\][™\ÜÊÝ™\Ü™Ù]
	ØÛÛ\ÜÚ][Û‰ÊHÜˆßJK	ØÛÛ[ØÛÛ\][™\Ü×ÙØ]IÊKˆ
Bˆ›ÜˆÙ^KØ]KÝYÙH[ˆ\™[š[™×ÙØ]\Î‚ˆ™\ÜÚÙ^WOYØ]BˆYˆØ]K™Ù]
	ÜÝ]\ÉÊHOIÔTÔÉÎ‚ˆ™\ÜÉÜÝ]\É×OIÑRS	ÎÜ™\ÜÉÜÝYÙI×O\ÝYÙN×Ü™\ÝÜ™WÛÜ—Ü™[[Ý™JÝ˜XÚÝ\
BˆYˆ˜XÚÝ\˜˜XÚÝ\[›[šÊZ\ÜÚ[™×ÛÚÏUYJBˆ™]\›ˆ™\ÜˆÜ[][Û]˜[Y]WÜ[—Ø›Ø\™ÜÜ[][ÛŠÝ™\Ü[œÝÙ\œÊNÜ™\ÜÉÜ[—Ø›Ø\™ÜÜ[][Û—ÜXI×O\Ü[][Û‚ˆYˆÜ[][Û‹™Ù]
	ÜÝ]\ÉÊOOIÑRS	Î‚ˆ™\ÜÉÜÝ]\É×OIÑRS	ÎÜ™\ÜÉÜÝYÙI×OIÜ[—Ø›Ø\™ÜÜ[][Û—ÙØ]IÎ×Ü™\ÝÜ™WÛÜ—Ü™[[Ý™JÝ˜XÚÝ\
BˆYˆ˜XÚÝ\˜˜XÚÝ\[›[šÊZ\ÜÚ[™×ÛÚÏUYJBˆ™]\›ˆ™\Üˆ™\Ù\˜][ÛY]˜[X]WØ\˜Ú]XÝ\™WÜ™\Ù\˜][ÛŠÜ˜ËÝ™\Ü[œÝÙ\œÏX[œÝÙ\œÊNÜ™\ÜÉØ\˜Ú]XÝ\™WÜ™\Ù\˜][Û—ÜXWØY\—ÝŒMÉ×O\™\Ù\˜][Û‚ˆYˆ™\Ù\˜][Û‹™Ù]
	ÜÝ]\ÉÊHOIÔTÔÉÎ‚ˆ™\ÜÉÜÝ]\É×OIÑRS	ÎÜ™\ÜÉÜÝYÙI×OIØ\˜Ú]XÝ\™WÜ™\Ù\˜][Û—ØY\—ÜØ[š]^˜][Û‰Î×Ü™\ÝÜ™WÛÜ—Ü™[[Ý™JÝ˜XÚÝ\
BˆYˆ˜XÚÝ\˜˜XÚÝ\[›[šÊZ\ÜÚ[™×ÛÚÏUYJBˆ™]\›ˆ™\Üˆ^XÝ]˜[Y]WÙš[˜[Ù[]™\žJÝ™\Ü
NÜ™\ÜÉÙ^XÝÙš[WÙš[˜[Ù[]™\žWÜXI×OY^XÝˆYˆ^XÝ™Ù]
	ÜÝ]\ÉÊHOIÔTÔÉÎ‚ˆ™\ÜÉÜÝ]\É×OIÑRS	ÎÜ™\ÜÉÜÝYÙI×OIÙ^XÝÙš[WÙš[˜[Ù[]™\žWÙØ]IÎ×Ü™\ÝÜ™WÛÜ—Ü™[[Ý™JÝ˜XÚÝ\
BˆYˆ˜XÚÝ\˜˜XÚÝ\[›[šÊZ\ÜÚ[™×ÛÚÏUYJBˆ™]\›ˆ™\Üˆ[ÛYÙOXÜ™X]WÛ[ÛYÙWØ[™Ý˜[Y]JÝÝÚ]Û˜[YJÝœÝ[JÉË[[ÛYÙKœ™ÉÊJNÜ™\ÜÉÛ[ÛYÙWÙ^XÝÜ™[Ü[—ÜXI×O[[ÛYÙBˆYˆ[ÛYÙK™Ù]
	ÜÝ]\ÉÊHOIÔTÔÉÎ‚ˆ™\ÜÉÜÝ]\É×OIÑRS	ÎÜ™\ÜÉÜÝYÙI×OIÛ[ÛYÙWÙ^XÝÜ™[Ü[—ÙØ]IÎ×Ü™\ÝÜ™WÛÜ—Ü™[[Ý™JÝ˜XÚÝ\
BˆYˆ˜XÚÝ\˜˜XÚÝ\[›[šÊZ\ÜÚ[™×ÛÚÏUYJBˆ™]\›ˆ™\Üˆ™\ÜÉÝ™\œÚ[Û‰×OSQPÒS’PÐSÔTSS‘WÕ‘T”ÒSÓŽÜ™\ÜÉÜÝ]\É×OIÔTÔÉÂˆYˆ˜XÚÝ\˜˜XÚÝ\[›[šÊZ\ÜÚ[™×ÛÚÏUYJBˆ™]\›ˆ™\Ü