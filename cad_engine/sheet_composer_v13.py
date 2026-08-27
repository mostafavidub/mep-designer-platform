"""Stage 10 — compose engineering routes, annotations and details into DXF.

This module does not fabricate a plan from empty space. It expects a drawing
whose modelspace already contains the project architecture/underlay and adds
mechanical content in the same coordinate system.
"""
from __future__ import annotations

import os
import ezdxf

LAYER_STYLE = {
    'cold_water': ('ENGITOOLS-M-COLD_WATER', 5, 'DASHDOT', 30),
    'hot_water': ('ENGITOOLS-M-HOT_WATER', 1, 'DIVIDE', 30),
    'sanitary': ('ENGITOOLS-M-SANITARY', 3, 'CONTINUOUS', 60),
    'vent': ('ENGITOOLS-M-VENT', 4, 'HIDDEN', 30),
    'heating': ('ENGITOOLS-M-HEATING', 1, 'CONTINUOUS', 30),
    'cooling': ('ENGITOOLS-M-COOLING', 5, 'CONTINUOUS', 30),
    'condensate': ('ENGITOOLS-M-CONDENSATE', 4, 'HIDDEN', 25),
    'gas': ('ENGITOOLS-M-GAS', 2, 'DASHED', 30),
    'exhaust': ('ENGITOOLS-M-EXHAUST', 6, 'DASHED', 30),
    'ventilation': ('ENGITOOLS-M-VENTILATION', 6, 'DASHED', 30),
}


def _ensure_linetype(doc, name):
    if name.upper() == 'CONTINUOUS': return 'Continuous'
    try:
        doc.linetypes.get(name)
        return name
    except Exception:
        pass
    # Portable fallbacks; pattern description stays explicit even when client CAD
    # does not ship the original office SHX linetype definition.
    try:
        if name.upper() in {'HIDDEN','DASHED'}:
            doc.linetypes.add(name, pattern=[0.6,0.35,-0.25], description=name)
        elif name.upper() in {'DASHDOT','DIVIDE'}:
            doc.linetypes.add(name, pattern=[1.0,0.45,-0.2,0.0,-0.2], description=name)
        else:
            doc.linetypes.add(name, pattern=[0.6,0.35,-0.25], description=name)
    except Exception:
        return 'Continuous'
    return name


def _ensure_layers(doc):
    for system,(name,color,linetype,lineweight) in LAYER_STYLE.items():
        lt=_ensure_linetype(doc,linetype)
        try:
            layer=doc.layers.get(name)
        except Exception:
            layer=doc.layers.add(name,color=color,linetype=lt,lineweight=lineweight)
        try:
            layer.dxf.color=color; layer.dxf.linetype=lt; layer.dxf.lineweight=lineweight
        except Exception:
            pass
    for name in ('ENGITOOLS-M-ANNOTATION','ENGITOOLS-M-DETAIL'):
        try: doc.layers.get(name)
        except Exception: doc.layers.add(name,color=7,lineweight=25)


def compose_engineering_content(dst, pipeline):
    doc=ezdxf.readfile(dst); msp=doc.modelspace(); _ensure_layers(doc)
    route_by_id={r['id']:r for r in pipeline.get('routing',{}).get('routes') or []}
    drawn=[]
    for route in route_by_id.values():
        points=route.get('points') or []
        if len(points)<2: continue
        style=LAYER_STYLE.get(route.get('system'))
        if not style: continue
        msp.add_lwpolyline(points,dxfattribs={'layer':style[0],'lineweight':style[3]})
        drawn.append(route['id'])

    texts=[]
    for ann in pipeline.get('annotations',{}).get('annotations') or []:
        anchor=ann.get('anchor')
        if not anchor: continue
        text=str(ann.get('text') or '').strip()
        if not text: continue
        entity=msp.add_mtext(text,dxfattribs={'layer':'ENGITOOLS-M-ANNOTATION','char_height':180})
        entity.dxf.insert=anchor
        texts.append(ann['id'])

    # Dynamic details are composed outside the architecture extents and only when
    # every required parameter has a value. Incomplete engineering data is not
    # disguised as a complete authority detail.
    bounds=(pipeline.get('architecture') or {}).get('bounds') or [0,0,10000,10000]
    x0=bounds[2]+2000; y0=bounds[3]
    details_drawn=[]; incomplete=[]
    items=(pipeline.get('details') or {}).get('details',[])+(pipeline.get('details') or {}).get('schedules',[])
    for idx,item in enumerate(items):
        params=item.get('parameters') or {}; required=item.get('required_fields') or []
        missing=[key for key in required if params.get(key) in (None,'',[])]
        if missing:
            incomplete.append({'id':item.get('id'),'missing':missing}); continue
        bx=x0+(idx%4)*4200; by=y0-(idx//4)*5200
        msp.add_lwpolyline([(bx,by),(bx+3800,by),(bx+3800,by-4600),(bx,by-4600)],close=True,dxfattribs={'layer':'ENGITOOLS-M-DETAIL'})
        title=msp.add_mtext(str(item.get('title') or item.get('kind')),dxfattribs={'layer':'ENGITOOLS-M-DETAIL','char_height':220}); title.dxf.insert=(bx+200,by-300)
        yy=by-800
        for key in required:
            row=msp.add_mtext(f"{key.upper()}: {params.get(key)}",dxfattribs={'layer':'ENGITOOLS-M-DETAIL','char_height':150}); row.dxf.insert=(bx+200,yy); yy-=320
        details_drawn.append(item.get('id'))

    doc.saveas(dst)
    return {'version':'sheet-composer-v13.10','drawn_routes':drawn,'drawn_annotations':texts,'drawn_details':details_drawn,'incomplete_details':incomplete}


def validate_composed_dxf(dst,pipeline,composition):
    doc=ezdxf.readfile(dst); msp=doc.modelspace()
    expected_routes={r['id'] for r in pipeline.get('routing',{}).get('routes') or []}
    errors=[]
    if expected_routes-set(composition.get('drawn_routes') or []): errors.append('missing_route_geometry')
    if any(x.get('missing') for x in composition.get('incomplete_details') or []): errors.append('incomplete_dynamic_details')
    mech_entities=[e for e in msp if str(getattr(e.dxf,'layer','')).startswith('ENGITOOLS-M-')]
    if expected_routes and not mech_entities: errors.append('no_mechanical_entities_in_modelspace')
    annotation_count=sum(1 for e in msp if str(getattr(e.dxf,'layer',''))=='ENGITOOLS-M-ANNOTATION' and e.dxftype() in {'TEXT','MTEXT'})
    if expected_routes and annotation_count < len(expected_routes): errors.append('insufficient_route_annotations')
    return {'status':'PASS' if not errors else 'FAIL','errors':errors,
            'metrics':{'mechanical_entities':len(mech_entities),'expected_routes':len(expected_routes),'annotations':annotation_count,
                       'details':len(composition.get('drawn_details') or [])}}
