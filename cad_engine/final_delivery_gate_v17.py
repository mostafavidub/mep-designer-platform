"""Final issued-DXF gate for the mechanical authority pipeline."""
from __future__ import annotations
from pathlib import Path
import ezdxf
from ezdxf import bbox


def _bounds_from_report(report):
    boards=((report or {}).get('composition') or {}).get('boards') or {}
    out=[]
    for board in boards.values():
        try: b=tuple(float(x) for x in board.get('bounds'))
        except Exception: continue
        if len(b)==4 and b[0] <= b[2] and b[1] <= b[3]: out.append(b)
    return out


def _contains_ext(ex,b,tol=0.03):
    return (ex.extmin.x >= b[0]-tol and ex.extmax.x <= b[2]+tol and ex.extmin.y >= b[1]-tol and ex.extmax.y <= b[3]+tol)


def _point(e):
    for attr in ('insert','location','start','center'):
        try:
            p=getattr(e.dxf,attr); return float(p.x),float(p.y)
        except Exception: pass
    if e.dxftype()=='LWPOLYLINE':
        try:
            pts=[(float(x),float(y)) for x,y,*_ in e.get_points()]
            if pts:return pts[0]
        except Exception: pass
    return None


def _contained(e,boards):
    try:
        ex=bbox.extents([e],fast=True)
        if ex.has_data:return any(_contains_ext(ex,b) for b in boards)
    except Exception: pass
    p=_point(e)
    if p:return any(b[0]-0.03 <= p[0] <= b[2]+0.03 and b[1]-0.03 <= p[1] <= b[3]+0.03 for b in boards)
    return False


def _paperspace_layouts(doc):
    return [x for x in doc.layouts if x.name!='Model']


def _remove_empty_paperspace_layouts(doc):
    removed=[]
    papers=_paperspace_layouts(doc)
    empties=[]
    for layout in papers:
        try: count=sum(1 for _ in layout)
        except Exception: count=0
        if count==0: empties.append(layout.name)
    # DXF requires at least one paperspace layout. Keep one empty fallback only
    # when every paperspace layout is empty; remove all other empty layouts.
    keep=None
    if papers and len(empties)==len(papers):
        keep='Layout1' if 'Layout1' in empties else empties[0]
    for name in empties:
        if name==keep: continue
        try:
            doc.layouts.delete(name); removed.append(name)
        except Exception: pass
    return removed


def sanitize_to_approved_boards(path:Path,report:dict)->dict:
    path=Path(path); boards=_bounds_from_report(report)
    if not boards:return {'version':'final-delivery-gate-v17.2','status':'FAIL','errors':['no_approved_board_bounds']}
    try:
        doc=ezdxf.readfile(path); msp=doc.modelspace()
    except Exception as exc:
        return {'version':'final-delivery-gate-v17.2','status':'FAIL','errors':['cannot_open_output_dxf'],'detail':str(exc)}
    before=len(msp); removed=0
    for e in list(msp):
        if not _contained(e,boards):
            try:msp.delete_entity(e); removed+=1
            except Exception:pass
    empty_layouts_removed=_remove_empty_paperspace_layouts(doc)
    try:
        ex=bbox.extents(msp,fast=True)
        if ex.has_data:
            doc.header['$EXTMIN']=tuple(map(float,ex.extmin)); doc.header['$EXTMAX']=tuple(map(float,ex.extmax))
        doc.saveas(path)
    except Exception as exc:
        return {'version':'final-delivery-gate-v17.2','status':'FAIL','errors':['cannot_save_sanitized_output'],'detail':str(exc)}
    qa=validate_final_delivery(path,report)
    qa.update({'entities_before':before,'entities_after':before-removed,'entities_removed':removed,'empty_layouts_removed':empty_layouts_removed})
    return qa


def validate_final_delivery(path:Path,report:dict)->dict:
    boards=_bounds_from_report(report); errors=[]; outside=[]; empty_layouts=[]
    if not boards:return {'version':'final-delivery-gate-v17.2','status':'FAIL','errors':['no_approved_board_bounds']}
    try:
        doc=ezdxf.readfile(Path(path)); msp=doc.modelspace()
    except Exception as exc:
        return {'version':'final-delivery-gate-v17.2','status':'FAIL','errors':['cannot_reopen_exact_output'],'detail':str(exc)}
    for e in msp:
        if not _contained(e,boards):
            outside.append({'type':e.dxftype(),'layer':str(getattr(e.dxf,'layer',''))})
            if len(outside)>=25:break
    papers=_paperspace_layouts(doc)
    for layout in papers:
        try:
            if sum(1 for _ in layout)==0: empty_layouts.append(layout.name)
        except Exception:empty_layouts.append(layout.name)
    # One empty paperspace is a mandatory DXF fallback and is not a release defect.
    actionable_empty=empty_layouts if len(papers)>1 else []
    if outside:errors.append('visible_modelspace_entities_outside_approved_boards')
    if actionable_empty:errors.append('empty_paperspace_layouts')
    return {'version':'final-delivery-gate-v17.2','status':'PASS' if not errors else 'FAIL','errors':errors,
            'approved_board_count':len(boards),'outside_entity_count':len(outside),'outside_samples':outside,
            'empty_layouts':actionable_empty,'mandatory_empty_layouts_ignored':empty_layouts if len(papers)==1 else [],
            'modelspace_entity_count':len(msp)}
