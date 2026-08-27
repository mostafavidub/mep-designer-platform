"""Stage 5 — build mechanical network topology before geometric routing."""
from __future__ import annotations

import math

SYSTEM_TARGETS = {
    'cold_water': {'wc','basin','sink','shower'},
    'hot_water': {'basin','sink','shower'},
    'sanitary': {'wc','basin','sink','shower','floor_drain'},
    'vent': {'wc','basin','sink','shower','floor_drain'},
    'heating': {'radiator','fan_coil'},
    'cooling': {'fan_coil','split_indoor'},
    'condensate': {'fan_coil','split_indoor'},
    'exhaust': {'exhaust_fan','hood'},
    'gas': {'stove','water_heater'},
}


def _centroid(poly):
    if not poly: return None
    return (sum(p[0] for p in poly)/len(poly), sum(p[1] for p in poly)/len(poly))


def build_system_topology(architecture, recognition, requirements, calculations):
    nodes = []
    for item in recognition.get('detections') or []:
        nodes.append({'id':item['id'],'kind':item.get('type'),'category':item.get('category'),'point':item.get('point'),'room_id':item.get('room_id')})
    shafts = []
    for index, shaft in enumerate(architecture.get('shafts') or [],1):
        point = _centroid(shaft.get('polygon'))
        if point:
            sid = f'SHAFT-{index:02d}'; shafts.append({'id':sid,'kind':'shaft','category':'vertical','point':point}); nodes.append(shafts[-1])
    if not shafts:
        # Fail-safe topology anchor is explicit and flagged; it may not be silently issued as a real shaft.
        bounds = architecture.get('bounds') or [0,0,0,0]
        point = ((bounds[0]+bounds[2])/2.0,(bounds[1]+bounds[3])/2.0)
        shafts.append({'id':'SHAFT-PROVISIONAL','kind':'shaft','category':'vertical','point':point,'provisional':True}); nodes.append(shafts[-1])

    project_systems = set(requirements.get('project_systems') or [])
    edges = []
    system_graphs = {}
    for system in sorted(project_systems):
        allowed = SYSTEM_TARGETS.get(system,set())
        endpoints = [n for n in nodes if n.get('kind') in allowed]
        graph_nodes = [n['id'] for n in endpoints]
        if endpoints:
            shaft = min(shafts, key=lambda s: sum(math.dist(e['point'],s['point']) for e in endpoints))
            graph_nodes.append(shaft['id'])
            for endpoint in endpoints:
                edge = {'id':f'{system.upper()}-E{len(edges)+1:03d}','system':system,'from':endpoint['id'],'to':shaft['id'],
                        'load_source':endpoint['id'],'topology':'endpoint_to_vertical_core'}
                edges.append(edge)
        system_graphs[system] = {'nodes':graph_nodes,'edges':[e['id'] for e in edges if e['system']==system]}

    return {'version':'mechanical-topology-v13.5','nodes':nodes,'edges':edges,'systems':system_graphs,
            'quality':{'systems':len(system_graphs),'edges':len(edges),'provisional_shaft':any(s.get('provisional') for s in shafts)}}
