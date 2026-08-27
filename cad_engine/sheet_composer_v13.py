"""Stage 10 — compose engineering content without crossing independent print plans."""
from __future__ import annotations
import ezdxf
LAYER_STYLE={'cold_water':('ENGITOOLS-M-COLD_WATER',5,'DASHDOT',30),'hot_water':('ENGITOOLS-M-HOT_WATER',1,'DIVIDE',30),
 'sanitary':('ENGITOOLS-M-SANITARY',3,'CONTINUOUS',60),'vent':('ENGITOOLS-M-VENT',4,'HIDDEN',30),'heating':('ENGITOOLS-M-HEATING',1,'CONTINUOUS',30),
 'cooling':('ENGITOOLS-M-COOLING',5,'CONTINUOUS',30),'condensate':('ENGITOOLS-M-CONDENSATE',4,'HIDDEN',25),'gas':('ENGITOOLS-M-GAS',2,'DASHED',30),
 'exhaust':('ENGITOOLS-M-EXHAUST',6,'DASHED',30),'ventilation':('ENGITOOLS-M-VENTILATION',6,'DASHED',30)}

def _inside(p,b,tol=1e-6): return not b or (b[0]-tol<=p[0]<=b[2]+tol and b[1]-tol<=p[1]<=b[3]+tol)
def _ensure_linetype(doc,name):
    if name.upper()=='CONTINUOUS':return 'Continuous'
    try:doc.linetypes.get(name);return name
    except Exception:pass
    try:doc.linetypes.add(name,pattern=[0.6,0.35,-0.25],description=name);return name
    except Exception:return 'Continuous'
def _ensure_layers(doc):
    for _,(name,color,linetype,lineweight) in LAYER_STYLE.items():
        lt=_ensure_linetype(doc,linetype)
        try:layer=doc.layers.get(name)
        except Exception:layer=doc.layers.add(name,color=color,linetype=lt,lineweight=lineweight)
        layer.dxf.color=color;layer.dxf.linetype=lt;layer.dxf.lineweight=lineweight
    for name in ('ENGITOOLS-M-ANNOTATION','ENGITOOLS-M-DETAIL'):
        try:doc.layers.get(name)
        except Exception:doc.layers.add(name,color=7,lineweight=25)
    try:doc.appids.get('ENGITOOLS')
    except Exception:doc.appids.add('ENGITOOLS')

def compose_engineering_content(dst,pipeline):
    doc=ezdxf.readfile(dst);msp=doc.modelspace();_ensure_layers(doc)
    plan_bounds={p['plan_id']:p['bounds'] for p in (pipeline.get('architecture') or {}).get('plans') or []}
    drawn=[];rejected=[]
    for route in (pipeline.get('routing') or {}).get('routes') or []:
        points=route.get('points') or [];pid=route.get('plan_id');style=LAYER_STYLE.get(route.get('system'))
        if len(points)<2 or not style:continue
        if pid and not all(_inside(p,plan_bounds.get(pid)) for p in points):
            rejected.append({'id':route['id'],'reason':'CROSS_PLAN_GEOMETRY'});continue
        ent=msp.add_lwpolyline(points,dxfattribs={'layer':style[0],'lineweight':style[3]})
        ent.set_xdata('ENGITOOLS',[('1000',pid or ''),('1000',route.get('system') or '')]);drawn.append(route['id'])
    texts=[]
    route_plan={r['id']:r.get('plan_id') for r in (pipeline.get('routing') or {}).get('routes') or []}
    for ann in (pipeline.get('annotations') or {}).get('annotations') or []:
        anchor=ann.get('anchor');text=str(ann.get('text') or '').strip();pid=route_plan.get(ann.get('route_id'))
        if not anchor or not text:continue
        if pid and not _inside(anchor,plan_bounds.get(pid),0.5):
            rejected.append({'id':ann.get('id'),'reason':'ANNOTATION_OUTSIDE_PLAN'});continue
        entity=msp.add_mtext(text,dxfattribs={'layer':'ENGITOOLS-M-ANNOTATION','char_height':180});entity.dxf.insert=anchor
        entity.set_xdata('ENGITOOLS',[('1000',pid or ''),('1000','annotation')]);texts.append(ann['id'])
    bounds=(pipeline.get('architecture') or {}).get('bounds') or [0,0,10000,10000];x0=bounds[2]+2000;y0=bounds[3]
    details_drawn=[];incomplete=[];items=(pipeline.get('details') or {}).get('details',[])+(pipeline.get('details') or {}).get('schedules',[])
    for idx,item in enumerate(items):
        params=item.get('parameters') or {};required=item.get('required_fields') or [];missing=[k for k in required if params.get(k) in (None,'',[])]
        if missing:incomplete.append({'id':item.get('id'),'missing':missing});continue
        bx=x0+(idx%4)*4200;by=y0-(idx//4)*5200;msp.add_lwpolyline([(bx,by),(bx+3800,by),(bx+3800,by-4600),(bx,by-4600)],close=True,dxfattribs={'layer':'ENGITOOLS-M-DETAIL'})
        title=msp.add_mtext(str(item.get('title') or item.get('kind')),dxfattribs={'layer':'ENGITOOLS-M-DETAIL','char_height':220});title.dxf.insert=(bx+200,by-300);details_drawn.append(item.get('id'))
    doc.saveas(dst)
    return {'version':'sheet-composer-v13.12','drawn_routes':drawn,'drawn_annotations':texts,'drawn_details':details_drawn,
            'incomplete_details':incomplete,'rejected_cross_plan':rejected}

def validate_composed_dxf(dst,pipeline,composition):
    doc=ezdxf.readfile(dst);msp=doc.modelspace();expected={r['id'] for r in (pipeline.get('routing') or {}).get('routes') or []};errors=[]
    if expected-set(composition.get('drawn_routes') or []):errors.append('missing_route_geometry')
    if composition.get('rejected_cross_plan'):errors.append('cross_plan_geometry_rejected')
    if any(x.get('missing') for x in composition.get('incomplete_details') or []):errors.append('incomplete_dynamic_details')
    mech=[e for e in msp if str(getattr(e.dxf,'layer','')).startswith('ENGITOOLS-M-')]
    annotation_count=sum(1 for e in msp if str(getattr(e.dxf,'layer',''))=='ENGITOOLS-M-ANNOTATION' and e.dxftype() in {'TEXT','MTEXT'})
    return {'status':'PASS' if not errors else 'FAIL','errors':errors,'metrics':{'mechanical_entities':len(mech),'expected_routes':len(expected),
            'annotations':annotation_count,'details':len(composition.get('drawn_details') or []),'cross_plan_rejections':len(composition.get('rejected_cross_plan') or [])}}
