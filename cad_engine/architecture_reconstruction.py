"""Routing-grade architectural reconstruction for mechanical design v14.

The output preserves a traceable architectural underlay instead of reducing a
floor to a bounding box.  It is deliberately conservative: geometry that cannot
be classified remains available in underlay_entities but is not promoted to a
room/shaft/obstacle without evidence.
"""
from __future__ import annotations

import math
import re
from collections import Counter
import ezdxf
from ezdxf import bbox

ROOM_ALIASES = {
    'bathroom': ('bathroom','bath','حمام'), 'toilet': ('toilet','wc','سرویس','دستشویی'),
    'kitchen': ('kitchen','آشپزخانه'), 'living': ('living','پذیرایی','نشیمن'),
    'bedroom': ('bedroom','bed','خواب'), 'parking': ('parking','پارکینگ'),
    'mechanical': ('mechanical','motor room','موتورخانه'),
}
LEVEL_TOKENS = ('floor','level','ground','roof','basement','طبقه','همکف','بام','زیرزمین')


def _norm(v):
    v=str(v or '').replace('ي','ی').replace('ك','ک').replace('\u200c',' ').lower()
    v=re.sub(r'[_./\\:;,-]+',' ',v)
    return re.sub(r'\s+',' ',v).strip()


def _classify_room(text):
    s=_norm(text)
    for kind, terms in ROOM_ALIASES.items():
        if any(_norm(t) in s for t in terms): return kind
    return None


def _text(e):
    try:
        return str(e.dxf.text) if e.dxftype()=='TEXT' else str(e.plain_text())
    except Exception: return ''


def _point(e):
    for name in ('insert','location','start'):
        try:
            p=getattr(e.dxf,name); return (float(p.x),float(p.y))
        except Exception: pass
    return None


def _poly(e):
    try:
        if e.dxftype()=='LWPOLYLINE': pts=[(float(x),float(y)) for x,y,*_ in e.get_points()]
        elif e.dxftype()=='POLYLINE': pts=[(float(v.dxf.location.x),float(v.dxf.location.y)) for v in e.vertices]
        else: return None
    except Exception: return None
    if len(pts)<3: return None
    closed=bool(getattr(e,'closed',False)) or pts[0]==pts[-1]
    if not closed: return None
    if pts[0]==pts[-1]: pts=pts[:-1]
    return pts if len(pts)>=3 else None


def _area(poly):
    return abs(sum(poly[i][0]*poly[(i+1)%len(poly)][1]-poly[(i+1)%len(poly)][0]*poly[i][1] for i in range(len(poly)))/2)


def _inside(p, poly):
    x,y=p; hit=False; j=len(poly)-1
    for i,(xi,yi) in enumerate(poly):
        xj,yj=poly[j]
        if ((yi>y)!=(yj>y)) and x < (xj-xi)*(y-yi)/((yj-yi) or 1e-12)+xi: hit=not hit
        j=i
    return hit


def _centroid(poly):
    return (sum(p[0] for p in poly)/len(poly), sum(p[1] for p in poly)/len(poly))



def _nested_inserts(entities,depth=0):
    """Yield transformed nested INSERT evidence without promoting nested geometry."""
    if depth>12:
        return
    for entity in entities:
        if entity.dxftype()!='INSERT':
            continue
        try:
            for child in entity.virtual_entities():
                if child.dxftype()=='INSERT':
                    p=_point(child)
                    if p:
                        yield {'name':str(child.dxf.name or ''),'point':p,
                               'layer':str(getattr(child.dxf,'layer','0') or '0'),
                               'evidence':'nested_block'}
                yield from _nested_inserts([child],depth+1)
        except Exception:
            continue

def _dedupe_inserts(items):
    result=[]; seen=set()
    for item in items:
        key=(_norm(item.get('name')),round(float(item['point'][0]),4),
             round(float(item['point'][1]),4),_norm(item.get('layer')))
        if key in seen:
            continue
        seen.add(key); result.append(item)
    return result


def reconstruct_architecture(path):
    doc=ezdxf.readfile(path); msp=doc.modelspace()
    layer_norm={str(l.dxf.name):_norm(l.dxf.name) for l in doc.layers}
    texts=[]; inserts=[]; closed=[]; lines=[]; underlay=[]
    type_counts=Counter()
    for e in msp:
        typ=e.dxftype(); type_counts[typ]+=1; layer=str(getattr(e.dxf,'layer','0') or '0')
        rec={'type':typ,'layer':layer}
        if typ in ('TEXT','MTEXT'):
            p=_point(e); value=_text(e).strip()
            if p and value: texts.append({'text':value,'point':p,'layer':layer}); rec.update(point=p,text=value)
        elif typ=='INSERT':
            p=_point(e)
            if p: inserts.append({'name':str(e.dxf.name or ''),'point':p,'layer':layer}); rec.update(point=p,name=str(e.dxf.name or ''))
        elif typ=='LINE':
            try:
                a=(float(e.dxf.start.x),float(e.dxf.start.y)); b=(float(e.dxf.end.x),float(e.dxf.end.y)); lines.append({'start':a,'end':b,'layer':layer}); rec.update(start=a,end=b)
            except Exception: pass
        elif typ in ('LWPOLYLINE','POLYLINE'):
            poly=_poly(e)
            if poly:
                item={'points':poly,'area':_area(poly),'centroid':_centroid(poly),'layer':layer}; closed.append(item); rec.update(points=poly,closed=True)
        if len(underlay)<50000 and typ in ('LINE','LWPOLYLINE','POLYLINE','ARC','CIRCLE','INSERT','TEXT','MTEXT','HATCH'):
            underlay.append(rec)

    # Nested blocks may contain the real fixture symbols. Only their transformed
    # INSERT evidence is merged; room/wall geometry remains top-level and unchanged.
    inserts=_dedupe_inserts(inserts+list(_nested_inserts(msp)))

    def layer_match(name,*tokens):
        n=layer_norm.get(name,_norm(name)); return any(_norm(t) in n for t in tokens)
    shaft_polys=[p for p in closed if layer_match(p['layer'],'shaft','شفت')]
    column_polys=[p for p in closed if layer_match(p['layer'],'column','ستون')]
    wall_lines=[x for x in lines if layer_match(x['layer'],'wall','دیوار')]
    if not wall_lines:
        wall_lines=list(lines)
    doors=[i for i in inserts if layer_match(i['layer'],'door') or 'door' in _norm(i['name'])]

    rooms=[]
    for t in texts:
        kind=_classify_room(t['text'])
        if not kind: continue
        containers=[p for p in closed if _inside(t['point'],p['points']) and p['area']>1]
        enclosure=min(containers,key=lambda x:x['area']) if containers else None
        room={'id':f"ROOM-{len(rooms)+1:03d}",'type':kind,'label':t['text'],'label_point':t['point'],
              'polygon':enclosure['points'] if enclosure else None,'area':enclosure['area'] if enclosure else None,
              'centroid':enclosure['centroid'] if enclosure else t['point'],'evidence':['room_text']}
        if enclosure: room['evidence'].append('enclosing_closed_polyline')
        rooms.append(room)

    level_labels=[]
    for t in texts:
        n=_norm(t['text'])
        if any(tok in n for tok in LEVEL_TOKENS): level_labels.append({'name':t['text'],'point':t['point']})
    wet_room_ids={r['id'] for r in rooms if r['type'] in ('bathroom','toilet','kitchen')}
    wet_cores=[]
    for r in rooms:
        if r['id'] not in wet_room_ids: continue
        nearest=min((math.dist(r['centroid'],s['centroid']),s) for s in shaft_polys) if shaft_polys else None
        wet_cores.append({'room_id':r['id'],'room_type':r['type'],'centroid':r['centroid'],
                          'nearest_shaft_distance':nearest[0] if nearest else None,
                          'nearest_shaft_centroid':nearest[1]['centroid'] if nearest else None})

    ext=bbox.extents(msp,fast=True); bounds=None
    if ext.has_data: bounds=[float(ext.extmin.x),float(ext.extmin.y),float(ext.extmax.x),float(ext.extmax.y)]
    return {
        'version':'architecture-reconstruction-v14.1','units':int(doc.header.get('$INSUNITS',0) or 0),'bounds':bounds,
        'rooms':rooms,'walls':wall_lines,'doors':doors,'columns':column_polys,
        'shafts':[{'polygon':p['points'],'centroid':p['centroid'],'area':p['area'],'layer':p['layer']} for p in shaft_polys],
        'wet_cores':wet_cores,'level_labels':level_labels,'all_inserts':inserts,'all_texts':texts,
        'underlay_entities':underlay,'obstacles':column_polys,'closed_polygons':closed,
        'quality':{'room_count':len(rooms),'rooms_with_polygon':sum(bool(r['polygon']) for r in rooms),
                   'wall_segments':len(wall_lines),'shaft_count':len(shaft_polys),'wet_core_count':len(wet_cores),
                   'underlay_entities':len(underlay),'entity_types':dict(type_counts)},
    }
