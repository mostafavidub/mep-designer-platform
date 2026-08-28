"""Engineering annotation engine v14.

Produces route labels, equipment/fixture tags, flow/slope callouts and riser notes
with traceable sources.  Label anchors are offset deterministically to reduce
collisions; final CAD composition still performs spatial overlap QA.
"""
from __future__ import annotations
import math

SYSTEM_LABELS={
 'cold_water':'CW','hot_water':'HW','sanitary':'SAN','vent':'V','heating_supply':'H-S','heating_return':'H-R',
 'cooling_supply':'C-S','cooling_return':'C-R','refrigerant_liquid':'LIQ','refrigerant_gas':'GAS-REF',
 'condensate':'CD','exhaust':'EXH','gas':'GAS',
}
EQUIP_TAGS={'radiator':'RAD','fan_coil':'FCU','split_indoor':'IDU','split_outdoor':'ODU','exhaust_fan':'EF','hood':'HOOD','pump':'P','tank':'TK','water_heater':'WH','stove':'GS'}
FIXTURE_TAGS={'wc':'WC','basin':'LAV','sink':'KS','shower':'SH','floor_drain':'FD'}

def _longest_segment(points):
 best=None; best_len=-1
 for a,b in zip(points or [],(points or [])[1:]):
  l=abs(b[0]-a[0])+abs(b[1]-a[1])
  if l>best_len: best_len=l; best=(a,b)
 return best

def _anchor(points,index=0):
 seg=_longest_segment(points)
 if not seg: return (0.0,0.0)
 a,b=seg; x=(a[0]+b[0])/2; y=(a[1]+b[1])/2
 # Alternate side of pipe in a stable way, similar to drafting leader staggering.
 off=120.0*(1 if index%2==0 else -1)
 if a[0]==b[0]: x+=off
 else: y+=off
 return (round(x,3),round(y,3))
def _equipment_text(item,room_calc):
 tag=EQUIP_TAGS.get(item.get('type'),item.get('type','EQ').upper()); rc=room_calc.get(item.get('room_id'),{})
 if item.get('type')=='split_indoor':
  cand=rc.get('split_candidate') or {}; cap=cand.get('selected_btu_h'); return f"{tag} {int(cap)} BTU/H" if cap else tag
 if item.get('type')=='radiator':
  cand=rc.get('radiator_candidate') or {}; sec=cand.get('sections'); return f"{tag} {int(sec)} SEC" if sec else tag
 if item.get('type')=='exhaust_fan' and rc.get('exhaust_cfm'): return f"{tag} {rc['exhaust_cfm']:.0f} CFM"
 return tag

def build_annotations(routing,sizing,recognition,calculations,topology):
 size_by_route={x['route_id']:x for x in sizing.get('segments') or []}; room_calc={x['room_id']:x for x in calculations.get('rooms') or []}
 edge_by_id={x['id']:x for x in topology.get('edges') or []}; annotations=[]
 for i,route in enumerate(routing.get('routes') or []):
  sz=size_by_route.get(route['id'],{}); system=route.get('system'); parts=[SYSTEM_LABELS.get(system,system.upper())]
  if sz.get('size_mm') is not None: parts.append(f"DN{int(sz['size_mm'])}")
  if sz.get('slope_percent') is not None: parts.append(f"SLOPE {float(sz['slope_percent']):g}%")
  if system=='vent' and route.get('role') in ('floor_main','riser_connection'): parts.append('UP TO ROOF')
  if system=='sanitary' and route.get('role')=='floor_main': parts.append('TO STACK')
  if system=='condensate': parts.append('DRAIN')
  annotations.append({'id':f"ANN-R-{len(annotations)+1:04d}",'kind':'route_label','route_id':route['id'],'edge_id':route.get('edge_id'),
                      'system':system,'text':' | '.join(parts),'anchor':_anchor(route.get('points'),i),'leader':True,
                      'source':{'sizing_route_id':route['id'],'topology_edge_id':route.get('edge_id')}})
 # Object tags are separate from route labels, as in approved plans.
 for item in recognition.get('detections') or []:
  rc=room_calc.get(item.get('room_id'),{}); text=FIXTURE_TAGS.get(item.get('type')) if item.get('category')=='fixture' else _equipment_text(item,room_calc)
  if not text: continue
  p=item.get('point') or (0,0); annotations.append({'id':f"ANN-O-{len(annotations)+1:04d}",'kind':'object_tag','object_id':item['id'],
          'system':None,'text':text,'anchor':(p[0]+150,p[1]+150),'leader':True,'source':{'object_id':item['id'],'room_id':item.get('room_id')}})
 # Riser callouts use the heaviest accumulated route for each system.
 for main in sizing.get('system_mains') or sizing.get('vertical_mains') or []:
  if main.get('size_mm') is None: continue
  annotations.append({'id':f"ANN-M-{len(annotations)+1:04d}",'kind':'riser_note','route_id':main.get('route_id'),'system':main['system'],
                      'text':f"{SYSTEM_LABELS.get(main['system'],main['system'].upper())} RISER DN{int(main['size_mm'])}",
                      'anchor':None,'leader':False,'source':{'route_id':main.get('route_id'),'downstream_load':main.get('downstream_load')}})
 return {'version':'annotation-engine-v14.8','annotations':annotations,
         'quality':{'annotations':len(annotations),'route_labels':sum(x['kind']=='route_label' for x in annotations),
                    'object_tags':sum(x['kind']=='object_tag' for x in annotations),'riser_notes':sum(x['kind']=='riser_note' for x in annotations),
                    'leaders':sum(bool(x['leader']) for x in annotations),'traceable':all(bool(x.get('source')) for x in annotations)}}
