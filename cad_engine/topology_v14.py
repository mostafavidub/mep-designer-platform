"""Mechanical topology engine v14.

Builds logical trunk/branch/riser graphs before geometry.  Endpoints in a room
first aggregate to a room branch node, branches aggregate to a vertical core,
and sources/equipment connect to that core.  This prevents decorative radial
endpoint-to-shaft linework and makes downstream-load sizing deterministic.
"""
from __future__ import annotations
import math

PORT_TO_SYSTEM={
 'cold_water':'cold_water','hot_water':'hot_water','sanitary':'sanitary','vent':'vent',
 'heating_supply':'heating_supply','heating_return':'heating_return',
 'cooling_supply':'cooling_supply','cooling_return':'cooling_return',
 'refrigerant_liquid':'refrigerant_liquid','refrigerant_gas':'refrigerant_gas',
 'condensate':'condensate','exhaust':'exhaust','gas':'gas',
}
SOURCE_TYPES={
 'cold_water':{'tank','pump'},'hot_water':{'water_heater'},'gas':set(),
 'heating_supply':set(),'heating_return':set(),'cooling_supply':set(),'cooling_return':set(),
 'refrigerant_liquid':{'split_outdoor'},'refrigerant_gas':{'split_outdoor'},
}

def _centroid(poly):
 if not poly:return None
 return (sum(p[0] for p in poly)/len(poly),sum(p[1] for p in poly)/len(poly))

def _nearest(point,nodes):
 return min(nodes,key=lambda n:math.dist(point,n['point'])) if nodes else None

def build_system_topology(architecture,recognition,requirements,calculations):
 detected=recognition.get('detections') or []
 nodes=[]; node_by_id={}
 for item in detected:
  n={'id':item['id'],'kind':item.get('type'),'category':item.get('category'),'point':tuple(item.get('point')),
     'room_id':item.get('room_id'),'ports':list(item.get('ports') or [])}
  nodes.append(n); node_by_id[n['id']]=n
 shafts=[]
 for i,s in enumerate(architecture.get('shafts') or [],1):
  p=s.get('centroid') or _centroid(s.get('polygon'))
  if p:
   n={'id':f'SHAFT-{i:02d}','kind':'shaft','category':'vertical_core','point':tuple(p)}; shafts.append(n); nodes.append(n); node_by_id[n['id']]=n
 wetcores=[]
 for i,w in enumerate(architecture.get('wet_cores') or [],1):
  p=w.get('nearest_shaft_centroid') or w.get('centroid')
  if p:
   n={'id':f'WETCORE-{i:02d}','kind':'wet_core','category':'aggregation','point':tuple(p),'room_id':w.get('room_id')}; wetcores.append(n); nodes.append(n); node_by_id[n['id']]=n
 if not shafts:
  # A provisional vertical core is permitted for computation but marks QA as unresolved.
  b=architecture.get('bounds') or [0,0,0,0]; p=((b[0]+b[2])/2,(b[1]+b[3])/2)
  n={'id':'SHAFT-PROVISIONAL','kind':'shaft','category':'vertical_core','point':p,'provisional':True}; shafts=[n]; nodes.append(n); node_by_id[n['id']]=n

 calc_by_room={x['room_id']:x for x in calculations.get('rooms') or []}
 system_endpoints={}
 for item in detected:
  for port in item.get('ports') or []:
   system=PORT_TO_SYSTEM.get(port)
   if system: system_endpoints.setdefault(system,[]).append(item)
 edges=[]; graphs={}
 for system,endpoints in sorted(system_endpoints.items()):
  if not endpoints: continue
  graph_node_ids=set(); graph_edge_ids=[]
  by_room={}
  for ep in endpoints: by_room.setdefault(ep.get('room_id') or 'UNASSIGNED',[]).append(ep)
  branch_nodes=[]
  for room_id,eps in sorted(by_room.items()):
   p=(sum(e['point'][0] for e in eps)/len(eps),sum(e['point'][1] for e in eps)/len(eps))
   bid=f'{system.upper()}-BR-{len(branch_nodes)+1:02d}'
   branch={'id':bid,'kind':'branch_header','category':'aggregation','system':system,'point':p,'room_id':None if room_id=='UNASSIGNED' else room_id}
   nodes.append(branch); node_by_id[bid]=branch; branch_nodes.append(branch); graph_node_ids.add(bid)
   for ep in eps:
    eid=f'{system.upper()}-E{len(edges)+1:04d}'
    edge={'id':eid,'system':system,'from':ep['id'],'to':bid,'role':'fixture_branch','endpoint_ids':[ep['id']],
          'room_id':ep.get('room_id'),'calculation':calc_by_room.get(ep.get('room_id'))}
    edges.append(edge); graph_edge_ids.append(eid); graph_node_ids.add(ep['id'])
  for branch in branch_nodes:
   target=_nearest(branch['point'],wetcores) or _nearest(branch['point'],shafts)
   if target and branch['id']!=target['id']:
    eid=f'{system.upper()}-E{len(edges)+1:04d}'
    eps=[e['id'] for e in endpoints if e.get('room_id')==branch.get('room_id')]
    edge={'id':eid,'system':system,'from':branch['id'],'to':target['id'],'role':'floor_main','endpoint_ids':eps,'room_id':branch.get('room_id')}
    edges.append(edge); graph_edge_ids.append(eid); graph_node_ids.add(target['id'])
  # Wet cores connect onward to the nearest true/provisional shaft once per system.
  used_wet={node_by_id[e['to']]['id'] for e in edges if e['system']==system and e.get('to') in node_by_id and node_by_id[e['to']].get('kind')=='wet_core'}
  for wid in sorted(used_wet):
   wet=node_by_id[wid]; shaft=_nearest(wet['point'],shafts)
   if shaft and shaft['id']!=wet['id']:
    descendant=[]
    for e in edges:
     if e['system']==system and e.get('to')==wid: descendant.extend(e.get('endpoint_ids') or [])
    eid=f'{system.upper()}-E{len(edges)+1:04d}'
    edges.append({'id':eid,'system':system,'from':wid,'to':shaft['id'],'role':'riser_connection','endpoint_ids':sorted(set(descendant))})
    graph_edge_ids.append(eid); graph_node_ids.update((wid,shaft['id']))
  graphs[system]={'nodes':sorted(graph_node_ids),'edges':graph_edge_ids,'endpoint_count':len(endpoints),'branch_count':len(branch_nodes)}
 return {'version':'mechanical-topology-v14.5','nodes':nodes,'edges':edges,'systems':graphs,
         'quality':{'systems':len(graphs),'edges':len(edges),'branches':sum(g['branch_count'] for g in graphs.values()),
                    'provisional_shaft':any(s.get('provisional') for s in shafts),
                    'direct_endpoint_to_shaft_edges':sum(1 for e in edges if node_by_id.get(e['from'],{}).get('category') in ('fixture','equipment') and node_by_id.get(e['to'],{}).get('kind')=='shaft')}}
