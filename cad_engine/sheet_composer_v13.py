"""Stage 10 - compose engineering and project-HVAC content inside owning print plans."""
from __future__ import annotations
import ezdxf
from .output_sanitizer_v13 import sanitize_to_selected_plans, validate_sanitized_output

LAYER_STYLE={
 'cold_water':('ENGITOOLS-M-COLD_WATER',5,'DASHDOT',30),'hot_water':('ENGITOOLS-M-HOT_WATER',1,'DIVIDE',30),
 'sanitary':('ENGITOOLS-M-SANITARY',3,'CONTINUOUS',60),'vent':('ENGITOOLS-M-VENT',4,'HIDDEN',30),
 'heating':('ENGITOOLS-M-HEATING',1,'CONTINUOUS',30),'cooling':('ENGITOOLS-M-COOLING',5,'CONTINUOUS',30),
 'condensate':('ENGITOOLS-M-CONDENSATE',4,'HIDDEN',25),'gas':('ENGITOOLS-M-GAS',2,'DASHED',30),
 'exhaust':('ENGITOOLS-M-EXHAUST',6,'DASHED',30),'ventilation':('ENGITOOLS-M-VENTILATION',6,'DASHED',30),
 'refrigerant':('ENGITOOLS-M-HVAC-REFRIG',6,'CONTINUOUS',35),
 'heating_flow':('ENGITOOLS-M-HEAT-FLOW',1,'CONTINUOUS',35),
 'heating_return':('ENGITOOLS-M-HEAT-RETURN',2,'CONTINUOUS',35),
}

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
    for name in ('ENGITOOLS-M-ANNOTATION','ENGITOOLS-M-DETAIL','ENGITOOLS-M-EQUIPMENT'):
        try:doc.layers.get(name)
        except Exception:doc.layers.add(name,color=7,lineweight=25)
    try:doc.appids.get('ENGITOOLS')
    except Exception:doc.appids.add('ENGITOOLS')

def compose_engineering_content(dst,pipeline):
    doc=ezdxf.readfile(dst);msp=doc.modelspace();_ensure_layers(doc)
    plans=(pipeline.get('architecture') or {}).get('plans') or []
    selected=[p for p in plans if p.get('mechanical_role') in {'PRIMARY_FLOOR','ROOF_SUPPORT'}]
    plan_bounds={p['plan_id']:p['bounds'] for p in plans}
    allowed={p['plan_id'] for p in selected}
    drawn=[];rejected=[]
    for route in (pipeline.get('routing') or {}).get('routes') or []:
        points=route.get('points') or [];pid=route.get('plan_id');style=LAYER_STYLE.get(route.get('system'))
        if len(points)<2 or not style:continue
        if allowed and pid not in allowed:
            rejected.append({'id':route['id'],'reason':'NON_MEP_DRAWING_FRAME'});continue
        if pid and not all(_inside(p,plan_bounds.get(pid)) for p in points):
            rejected.append({'id':route['id'],'reason':'CROSS_PLAN_GEOMETRY'});continue
        ent=msp.add_lwpolyline(points,dxfattribs={'layer':style[0],'lineweight':style[3]});ent.set_xdata('ENGITOOLS',[('1000',pid or ''),('1000',route.get('system') or '')]);drawn.append(route['id'])

    hvac_drawn=[]
    for route in (pipeline.get('hvac') or {}).get('routes') or []:
        points=route.get('points') or [];pid=route.get('plan_id');style=LAYER_STYLE.get(route.get('system'))
        if len(points)<2 or not style:continue
        if allowed and pid not in allowed:
            rejected.append({'id':route['id'],'reason':'HVAC_NON_MEP_DRAWING_FRAME'});continue
        if pid and not all(_inside(p,plan_bounds.get(pid),0.15) for p in points):
            rejected.append({'id':route['id'],'reason':'HVAC_OUTSIDE_OWNING_PLAN'});continue
        ent=msp.add_lwpolyline(points,dxfattribs={'layer':style[0],'lineweight':style[3]});ent.set_xdata('ENGITOOLS',[('1000',pid or ''),('1000',route.get('system') or '')]);hvac_drawn.append(route['id'])
    equipment_drawn=[]
    for item in (pipeline.get('hvac') or {}).get('equipment') or []:
        pid=item.get('plan_id');pt=item.get('point')
        if not pt or (allowed and pid not in allowed) or not _inside(pt,plan_bounds.get(pid),0.15):continue
        x,y=pt;box=msp.add_lwpolyline([(x-.18,y-.09),(x+.18,y-.09),(x+.18,y+.09),(x-.18,y+.09)],close=True,dxfattribs={'layer':'ENGITOOLS-M-EQUIPMENT'})
        box.set_xdata('ENGITOOLS',[('1000',pid or ''),('1000',item.get('kind') or 'equipment')])
        cap=item.get('capacity_btu_h') or item.get('capacity_kw');label=f"{item.get('kind')} {cap or ''}".strip();txt=msp.add_mtext(label,dxfattribs={'layer':'ENGITOOLS-M-ANNOTATION','char_height':0.10});txt.dxf.insert=(x+.22,y);equipment_drawn.append(item.get('id'))

    texts=[];route_plan={r['id']:r.get('plan_id') for r in (pipeline.get('routing') or {}).get('routes') or []}
    for ann in (pipeline.get('annotations') or {}).get('annotations') or []:
        anchor=ann.get('anchor');text=str(ann.get('text') or '').strip();pid=route_plan.get(ann.get('route_id'))
        if not anchor or not text:continue
        if pid and not _inside(anchor,plan_bounds.get(pid),0.5):
            rejected.append({'id':ann.get('id'),'reason':'ANNOTATION_OUTSIDE_PLAN'});continue
        entity=msp.add_mtext(text,dxfattribs={'layer':'ENGITOOLS-M-ANNOTATION','char_height':0.12});entity.dxf.insert=anchor;entity.set_xdata('ENGITOOLS',[('1000',pid or ''),('1000','annotation')]);texts.append(ann['id'])

    sanitization=sanitize_to_selected_plans(doc,selected) if selected else {'version':'output-sanitizer-v13.14','removed_entities':0}
    doc.saveas(dst)
    return {'version':'sheet-composer-v13.14','drawn_routes':drawn,'drawn_hvac_routes':hvac_drawn,'drawn_hvac_equipment':equipment_drawn,
            'drawn_annotations':texts,'drawn_details':[],'incomplete_details':[],'rejected_cross_plan':rejected,
            'sanitization':sanitization}

def validate_composed_dxf(dst,pipeline,composition):
    doc=ezdxf.readfile(dst);msp=doc.modelspace();errors=[]
    if composition.get('rejected_cross_plan'):errors.append('plan_scope_geometry_rejected')
    if (pipeline.get('hvac') or {}).get('status')=='PASS' and len(composition.get('drawn_hvac_routes') or [])!=len((pipeline.get('hvac') or {}).get('routes') or []):errors.append('missing_hvac_route_geometry')
    selected=[p for p in (pipeline.get('architecture') or {}).get('plans') or [] if p.get('mechanical_role') in {'PRIMARY_FLOOR','ROOF_SUPPORT'}]
    sanitizer_qa=validate_sanitized_output(doc,selected) if selected else {'status':'PASS','errors':[],'metrics':{'non_selected_sheet_entities':0}}
    if sanitizer_qa['status']!='PASS':errors.extend(sanitizer_qa['errors'])
    mech=[e for e in msp if str(getattr(e.dxf,'layer','')).startswith('ENGITOOLS-M-')]
    return {'status':'PASS' if not errors else 'FAIL','errors':errors,'metrics':{'mechanical_entities':len(mech),
            'hvac_routes':len(composition.get('drawn_hvac_routes') or []),'hvac_equipment':len(composition.get('drawn_hvac_equipment') or []),
            'scope_rejections':len(composition.get('rejected_cross_plan') or []),
            'non_selected_sheet_entities':sanitizer_qa['metrics']['non_selected_sheet_entities']}}
