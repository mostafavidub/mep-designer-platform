"""Traceable fixture/equipment recognition v14.

Recognizes installed mechanical consumers from block/layer/text evidence and assigns
connection-port requirements.  Objects outside reconstructed rooms are retained as
candidates, not silently treated as installed equipment (protects legends/details).
"""
from __future__ import annotations
import math, re

FIXTURES={
 'wc':('wc','toilet','water closet','closet','توالت','فرنگی'),
 'basin':('basin','lavatory','rooshooee','روشویی'),
 'sink':('sink','kitchen sink','سینک'),
 'shower':('shower','دوش'),
 'floor_drain':('floor drain','floordrain',' fd ','کفشور'),
}
EQUIPMENT={
 'radiator':('radiator',' rad ','رادیاتور'), 'fan_coil':('fancoil','fan coil','fcu'),
 'split_indoor':('indoor split','split indoor','indoor unit'), 'split_outdoor':('outdoor split','outdoor unit'),
 'exhaust_fan':('exh fan','exhaust fan'), 'hood':('hood','هود'), 'pump':('pump','پمپ'),
 'tank':('tank','مخزن'), 'water_heater':('water heater','boiler','آبگرمکن'), 'stove':('stove','range','اجاق'),
}
PORTS={
 'wc':['cold_water','sanitary','vent'], 'basin':['cold_water','hot_water','sanitary','vent'],
 'sink':['cold_water','hot_water','sanitary','vent'], 'shower':['cold_water','hot_water','sanitary','vent'],
 'floor_drain':['sanitary'], 'radiator':['heating_supply','heating_return'],
 'fan_coil':['cooling_supply','cooling_return','condensate'], 'split_indoor':['refrigerant_liquid','refrigerant_gas','condensate'],
 'split_outdoor':['refrigerant_liquid','refrigerant_gas'], 'exhaust_fan':['exhaust'], 'hood':['exhaust'],
 'pump':['cold_water'], 'tank':['cold_water'], 'water_heater':['cold_water','hot_water'], 'stove':['gas'],
}

def _norm(v):
 v=' '+str(v or '').replace('_',' ').replace('-',' ').replace('.',' ').lower()+' '
 return re.sub(r'\s+',' ',v)

def _match(v,mapping):
 s=_norm(v); best=None; n=0
 for kind,terms in mapping.items():
  for term in terms:
   t=_norm(term).strip()
   if t and t in s and len(t)>n: best=kind; n=len(t)
 return best

def _inside(p,poly):
 x,y=p; hit=False; j=len(poly)-1
 for i,(xi,yi) in enumerate(poly):
  xj,yj=poly[j]
  if ((yi>y)!=(yj>y)) and x < (xj-xi)*(y-yi)/((yj-yi) or 1e-12)+xi: hit=not hit
  j=i
 return hit

def _nearest_text(point,texts,limit=1500):
 rows=sorted(((math.dist(point,t['point']),t) for t in texts if t.get('point')),key=lambda x:x[0])
 return [(d,t) for d,t in rows[:5] if d<=limit]

def recognize_fixtures_equipment(architecture):
 rooms=[r for r in architecture.get('rooms') or [] if r.get('polygon')]
 texts=architecture.get('all_texts') or []; detections=[]; candidates=[]
 for item in architecture.get('all_inserts') or []:
  signals=[]; kind=_match(item.get('name'),FIXTURES); category='fixture' if kind else None
  if not kind:
   kind=_match(item.get('name'),EQUIPMENT); category='equipment' if kind else None
  if kind: signals.append('block_name')
  if not kind:
   kind=_match(item.get('layer'),FIXTURES); category='fixture' if kind else None
   if not kind: kind=_match(item.get('layer'),EQUIPMENT); category='equipment' if kind else None
   if kind: signals.append('layer_name')
  nearby=[]
  if not kind:
   nearby=_nearest_text(item['point'],texts)
   for distance,t in nearby:
    kind=_match(t.get('text'),FIXTURES); category='fixture' if kind else None
    if not kind: kind=_match(t.get('text'),EQUIPMENT); category='equipment' if kind else None
    if kind: signals.append('nearby_text'); break
  if not kind: continue
  room=next((r for r in rooms if _inside(item['point'],r['polygon'])),None)
  confidence=0.95 if 'block_name' in signals else (0.84 if 'layer_name' in signals else 0.70)
  row={'id':f"MEP-{len(detections)+len(candidates)+1:04d}",'category':category,'type':kind,'point':item['point'],
       'block':item.get('name'),'layer':item.get('layer'),'room_id':room.get('id') if room else None,
       'room_type':room.get('type') if room else None,'ports':list(PORTS.get(kind,[])),
       'confidence':confidence,'evidence':signals,'installed':bool(room)}
  (detections if room else candidates).append(row)
 return {'version':'fixture-equipment-recognition-v14.2','detections':detections,'candidates':candidates,
         'fixtures':[x for x in detections if x['category']=='fixture'],
         'equipment':[x for x in detections if x['category']=='equipment'],
         'quality':{'installed_detected':len(detections),'unassigned_candidates':len(candidates),
                    'with_ports':sum(bool(x['ports']) for x in detections),
                    'high_confidence':sum(x['confidence']>=0.84 for x in detections)}}
