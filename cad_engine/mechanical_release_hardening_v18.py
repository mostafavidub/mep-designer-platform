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
        if missing:errors.append(f"equipment_or_route_missing:{key}:"+",".join(missing))
        results.append({"board_id":key,"family":family,"counts":counts,"status":"PASS" if not missing else "FAIL"})
    return {"version":"equipment-linkage-gate-v18.0","status":"PASS" if not errors else "FAIL","errors":errors,"boards":results,"exact_file_reopened":True}


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
