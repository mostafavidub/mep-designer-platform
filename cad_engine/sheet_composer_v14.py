"""Plan-grade CAD composer v14.

Unlike the earlier schematic-zone output, this composer rebuilds a visible
architectural underlay in project coordinates, places recognized fixtures/
equipment on it, and overlays routed/sized/annotated networks.  Dynamic details
are kept outside the plan extents and only drawn when their required data passes
completeness QA.
"""
from __future__ import annotations
import ezdxf

STYLES={
 'cold_water':('ENGITOOLS-M-COLD_WATER',5,'DASHDOT',30), 'hot_water':('ENGITOOLS-M-HOT_WATER',1,'DIVIDE',30),
 'sanitary':('ENGITOOLS-M-SANITARY',3,'CONTINUOUS',60), 'vent':('ENGITOOLS-M-VENT',4,'HIDDEN',30),
 'heating_supply':('ENGITOOLS-M-HEATING_SUPPLY',1,'CONTINUOUS',30), 'heating_return':('ENGITOOLS-M-HEATING_RETURN',1,'HIDDEN',30),
 'cooling_supply':('ENGITOOLS-M-COOLING_SUPPLY',5,'CONTINUOUS',30), 'cooling_return':('ENGITOOLS-M-COOLING_RETURN',5,'HIDDEN',30),
 'refrigerant_liquid':('ENGITOOLS-M-REFRIG_LIQ',4,'CONTINUOUS',25), 'refrigerant_gas':('ENGITOOLS-M-REFRIG_GAS',4,'HIDDEN',25),
 'condensate':('ENGITOOLS-M-CONDENSATE',4,'HIDDEN',25), 'gas':('ENGITOOLS-M-GAS',2,'DASHED',30),
 'exhaust':('ENGITOOLS-M-EXHAUST',6,'DASHED',30),
}

def _lt(doc,name):
 if name.upper()=='CONTINUOUS': return 'Continuous'
 try: doc.linetypes.get(name); return name
 except Exception: pass
 pattern=[0.6,0.35,-0.25] if name.upper() in ('HIDDEN','DASHED') else [1.0,0.45,-0.2,0.0,-0.2]
 try: doc.linetypes.add(name,pattern=pattern,description=name); return name
 except Exception: return 'Continuous'
def _layer(doc,name,color=7,linetype='Continuous',lineweight=25):
 try: lyr=doc.layers.get(name)
 except Exception: lyr=doc.layers.add(name,color=color,linetype=linetype,lineweight=lineweight)
 try: lyr.dxf.color=color; lyr.dxf.linetype=linetype; lyr.dxf.lineweight=lineweight
 except Exception: pass
 return lyr
def _ensure(doc):
 _layer(doc,'ENGITOOLS-A-UNDERLAY',8,'Continuous',13); _layer(doc,'ENGITOOLS-A-TEXT',8,'Continuous',13)
 _layer(doc,'ENGITOOLS-M-FIXTURE',7,'Continuous',25); _layer(doc,'ENGITOOLS-M-EQUIPMENT',7,'Continuous',30)
 _layer(doc,'ENGITOOLS-M-ANNOTATION',7,'Continuous',25); _layer(doc,'ENGITOOLS-M-DETAIL',7,'Continuous',25)
 for _,(name,color,lt,lw) in STYLES.items(): _layer(doc,name,color,_lt(doc,lt),lw)
def _has_layer_entities(msp,layer): return any(str(getattr(e.dxf,'layer',''))==layer for e in msp)
def _draw_underlay(doc,msp,arch):
 if _has_layer_entities(msp,'ENGITOOLS-A-UNDERLAY'): return 0
 count=0
 for rec in arch.get('underlay_entities') or []:
  typ=rec.get('type')
  try:
   if typ=='LINE' and rec.get('start') and rec.get('end'):
    msp.add_line(rec['start'],rec['end'],dxfattribs={'layer':'ENGITOOLS-A-UNDERLAY'}); count+=1
   elif typ in ('LWPOLYLINE','POLYLINE') and rec.get('points'):
    msp.add_lwpolyline(rec['points'],close=bool(rec.get('closed')),dxfattribs={'layer':'ENGITOOLS-A-UNDERLAY'}); count+=1
   elif typ in ('TEXT','MTEXT') and rec.get('point') and rec.get('text'):
    t=msp.add_mtext(str(rec['text']),dxfattribs={'layer':'ENGITOOLS-A-TEXT','char_height':120}); t.dxf.insert=rec['point']; count+=1
   elif typ=='INSERT' and rec.get('point') and rec.get('name'):
    # Preserve native block reference when destination already has the block definition.
    try: doc.blocks.get(rec['name']); msp.add_blockref(rec['name'],rec['point'],dxfattribs={'layer':'ENGITOOLS-A-UNDERLAY'}); count+=1
    except Exception: pass
  except Exception: pass
 return count
def _symbol(msp,item):
 p=item.get('point'); typ=item.get('type');
 if not p:return 0
 layer='ENGITOOLS-M-FIXTURE' if item.get('category')=='fixture' else 'ENGITOOLS-M-EQUIPMENT'
 x,y=p; s=120
 try:
  if typ in ('floor_drain','basin','wc','sink','shower'):
   msp.add_circle((x,y),s,dxfattribs={'layer':layer}); msp.add_line((x-s,y),(x+s,y),dxfattribs={'layer':layer}); msp.add_line((x,y-s),(x,y+s),dxfattribs={'layer':layer})
  else:
   msp.add_lwpolyline([(x-s,y-s),(x+s,y-s),(x+s,y+s),(x-s,y+s)],close=True,dxfattribs={'layer':layer})
  return 1
 except Exception:return 0

def compose_engineering_content(dst,pipeline):
 doc=ezdxf.readfile(dst); msp=doc.modelspace(); _ensure(doc); arch=pipeline.get('architecture') or {}
 underlay=_draw_underlay(doc,msp,arch); symbols=sum(_symbol(msp,x) for x in (pipeline.get('recognition') or {}).get('detections') or [])
 routes=[]
 for route in (pipeline.get('routing') or {}).get('routes') or []:
  pts=route.get('points') or []; style=STYLES.get(route.get('system'))
  if len(pts)<2 or not style: continue
  msp.add_lwpolyline(pts,dxfattribs={'layer':style[0],'lineweight':style[3]}); routes.append(route['id'])
 anns=[]
 for ann in (pipeline.get('annotations') or {}).get('annotations') or []:
  anchor=ann.get('anchor'); text=str(ann.get('text') or '').strip()
  if not anchor or not text: continue
  t=msp.add_mtext(text,dxfattribs={'layer':'ENGITOOLS-M-ANNOTATION','char_height':140}); t.dxf.insert=anchor; anns.append(ann['id'])
 bounds=arch.get('bounds') or [0,0,10000,10000]; x0=bounds[2]+2000; y0=bounds[3]; details=[]; incomplete=[]
 all_items=((pipeline.get('details') or {}).get('details') or [])+((pipeline.get('details') or {}).get('schedules') or [])
 for idx,item in enumerate(all_items):
  qa=item.get('qa') or {}; missing=qa.get('missing') or []
  if missing: incomplete.append({'id':item.get('id'),'missing':missing}); continue
  bx=x0+(idx%3)*5200; by=y0-(idx//3)*5600
  msp.add_lwpolyline([(bx,by),(bx+4700,by),(bx+4700,by-5000),(bx,by-5000)],close=True,dxfattribs={'layer':'ENGITOOLS-M-DETAIL'})
  title=msp.add_mtext(str(item.get('title') or item.get('kind')),dxfattribs={'layer':'ENGITOOLS-M-DETAIL','char_height':210}); title.dxf.insert=(bx+180,by-300)
  yy=by-750
  for key in item.get('required_fields') or []:
   val=(item.get('parameters') or {}).get(key); row=msp.add_mtext(f"{key.upper()}: {val}",dxfattribs={'layer':'ENGITOOLS-M-DETAIL','char_height':135}); row.dxf.insert=(bx+180,yy); yy-=300
  details.append(item.get('id'))
 doc.saveas(dst)
 return {'version':'sheet-composer-v14.10','underlay_drawn':underlay,'symbols_drawn':symbols,'drawn_routes':routes,'drawn_annotations':anns,'drawn_details':details,'incomplete_details':incomplete}

def validate_composed_dxf(dst,pipeline,composition):
 doc=ezdxf.readfile(dst); msp=doc.modelspace(); errors=[]; warnings=[]
 expected={x['id'] for x in (pipeline.get('routing') or {}).get('routes') or []}; drawn=set(composition.get('drawn_routes') or [])
 if expected-drawn: errors.append('missing_route_geometry')
 underlay_count=sum(1 for e in msp if str(getattr(e.dxf,'layer','')).startswith('ENGITOOLS-A-'))
 if underlay_count==0: errors.append('missing_architectural_underlay')
 symbols=sum(1 for e in msp if str(getattr(e.dxf,'layer','')) in ('ENGITOOLS-M-FIXTURE','ENGITOOLS-M-EQUIPMENT'))
 if (pipeline.get('recognition') or {}).get('detections') and symbols==0: errors.append('missing_fixture_equipment_symbols')
 ann_count=sum(1 for e in msp if str(getattr(e.dxf,'layer',''))=='ENGITOOLS-M-ANNOTATION' and e.dxftype() in ('TEXT','MTEXT'))
 if expected and ann_count<len(expected): errors.append('insufficient_route_annotations')
 if composition.get('incomplete_details'): warnings.append('incomplete_dynamic_details_not_drawn')
 mech=sum(1 for e in msp if str(getattr(e.dxf,'layer','')).startswith('ENGITOOLS-M-'))
 return {'status':'PASS' if not errors else 'FAIL','errors':errors,'warnings':warnings,
         'metrics':{'architectural_underlay_entities':underlay_count,'mechanical_entities':mech,'expected_routes':len(expected),'drawn_routes':len(drawn),'annotations':ann_count,'fixture_equipment_entities':symbols,'details':len(composition.get('drawn_details') or [])}}
