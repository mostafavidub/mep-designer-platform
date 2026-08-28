"""Downstream-load network sizing v14.

Each route is sized from the endpoint set carried by topology, so branch, floor
main and riser loads increase naturally. Tables/slopes are project-overridable
engineering bases, never hidden statutory claims.
"""
from __future__ import annotations

DEFAULT_TABLES={
 'cold_water':[(1.5,16),(4,20),(8,25),(16,32),(999,40)],
 'hot_water':[(1.5,16),(4,20),(8,25),(16,32),(999,40)],
 'sanitary':[(1,50),(3,63),(8,75),(16,90),(999,110)],
 'vent':[(2,50),(8,63),(20,75),(999,90)],
 'heating_supply':[(1500,16),(3500,20),(7000,25),(14000,32),(999999,40)],
 'heating_return':[(1500,16),(3500,20),(7000,25),(14000,32),(999999,40)],
 'cooling_supply':[(2500,16),(6000,20),(12000,25),(24000,32),(999999,40)],
 'cooling_return':[(2500,16),(6000,20),(12000,25),(24000,32),(999999,40)],
 'condensate':[(5000,25),(12000,32),(30000,40),(999999,50)],
 'gas':[(12,20),(30,25),(60,32),(9999,40)],
 'refrigerant_liquid':[(9000,6),(18000,9),(30000,12),(999999,16)],
 'refrigerant_gas':[(9000,10),(18000,12),(30000,16),(999999,19)],
}
FIXTURE_LOAD={
 'wc':{'cold_water':2.5,'sanitary':4,'vent':4},'basin':{'cold_water':1,'hot_water':1,'sanitary':1,'vent':1},
 'sink':{'cold_water':1.5,'hot_water':1.5,'sanitary':2,'vent':2},'shower':{'cold_water':2,'hot_water':2,'sanitary':2,'vent':2},
 'floor_drain':{'sanitary':2},
}

def _pick(system,load,tables):
 for threshold,size in tables.get(system,[]):
  if load<=threshold:return size
 return None

def _endpoint_load(item,system,room_calc):
 if not item:return 0.0
 if item.get('category')=='fixture': return float(FIXTURE_LOAD.get(item.get('type'),{}).get(system,0) or 0)
 rc=room_calc.get(item.get('room_id'),{})
 if system in ('heating_supply','heating_return'): return float(rc.get('heating_w',0) or 0)
 if system in ('cooling_supply','cooling_return','condensate'): return float(rc.get('cooling_w',0) or 0)
 if system=='gas': return float(rc.get('gas_kw',0) or 0)
 if system in ('refrigerant_liquid','refrigerant_gas'):
  cand=rc.get('split_candidate') or {}; return float(cand.get('selected_btu_h',0) or 0)
 return 0.0

def size_networks(topology,routing,recognition,calculations,tables=None,design_basis=None):
 tbl={k:list(v) for k,v in DEFAULT_TABLES.items()}
 for k,v in (tables or {}).items(): tbl[k]=list(v)
 basis={'sanitary_slope_percent':2.0}; basis.update(design_basis or {})
 item_by_id={x['id']:x for x in recognition.get('detections') or []}; room_calc={x['room_id']:x for x in calculations.get('rooms') or []}
 edge_by_id={x['id']:x for x in topology.get('edges') or []}; segments=[]
 for route in routing.get('routes') or []:
  edge=edge_by_id.get(route.get('edge_id'),{}); system=route.get('system'); endpoint_ids=list(route.get('endpoint_ids') or edge.get('endpoint_ids') or [])
  if not endpoint_ids and edge.get('from') in item_by_id: endpoint_ids=[edge['from']]
  loads=[_endpoint_load(item_by_id.get(eid),system,room_calc) for eid in endpoint_ids]
  load=sum(loads); size=_pick(system,load,tbl)
  segments.append({'route_id':route['id'],'edge_id':route.get('edge_id'),'system':system,'role':route.get('role'),
                   'endpoint_ids':endpoint_ids,'downstream_load':round(load,2),'size_mm':size,
                   'slope_percent':float(basis['sanitary_slope_percent']) if system=='sanitary' else None,
                   'sizing_basis':'accumulated_downstream_endpoint_load'})
 # system mains are the maximum accumulated-load routes, not a second independent sum.
 mains=[]
 for system in sorted({x['system'] for x in segments}):
  ss=[x for x in segments if x['system']==system]
  if ss:
   maxseg=max(ss,key=lambda x:x['downstream_load']); mains.append({'system':system,'downstream_load':maxseg['downstream_load'],'size_mm':maxseg['size_mm'],'role':'largest_accumulated_route','route_id':maxseg['route_id']})
 unsized=[x['route_id'] for x in segments if x['size_mm'] is None]
 return {'version':'network-sizing-v14.7','segments':segments,'system_mains':mains,'tables':tbl,'design_basis':basis,
         'quality':{'segments':len(segments),'segments_sized':len(segments)-len(unsized),'unsized_routes':unsized,
                    'sanitary_slopes_assigned':all(x['slope_percent'] is not None for x in segments if x['system']=='sanitary'),
                    'downstream_accumulation':True}}
