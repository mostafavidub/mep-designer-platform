"""Stage 7 — size routed networks from downstream design loads.

Sizing tables are explicit project/office defaults and are overrideable. They are
not silently represented as universal code minima.
"""
from __future__ import annotations

DEFAULT_TABLES = {
    'cold_water': [(1,16),(3,20),(6,25),(12,32),(999,40)],
    'hot_water': [(1,16),(3,20),(6,25),(12,32),(999,40)],
    'sanitary': [(1,50),(2,63),(6,75),(12,90),(999,110)],
    'vent': [(2,50),(8,63),(20,75),(999,90)],
    'heating': [(1500,16),(3500,20),(7000,25),(14000,32),(999999,40)],
    'condensate': [(5000,25),(12000,32),(999999,40)],
    'gas': [(12,20),(30,25),(60,32),(9999,40)],
    'exhaust': [(150,100),(300,125),(600,160),(1200,200),(999999,250)],
}

FIXTURE_LOAD = {
    'wc': {'cold_water':2.5,'sanitary':4,'vent':4},
    'basin': {'cold_water':1,'hot_water':1,'sanitary':1,'vent':1},
    'sink': {'cold_water':1.5,'hot_water':1.5,'sanitary':2,'vent':2},
    'shower': {'cold_water':2,'hot_water':2,'sanitary':2,'vent':2},
    'floor_drain': {'sanitary':2,'vent':2},
}


def _size(system, load, tables):
    for threshold, size in tables.get(system, []):
        if load <= threshold: return size
    return None


def size_networks(topology, routing, recognition, calculations, tables=None):
    tables = {k:list(v) for k,v in DEFAULT_TABLES.items()}
    for key,value in (tables or {}).items():
        tables[key] = list(value)
    item_by_id={x['id']:x for x in recognition.get('detections') or []}
    edge_by_id={x['id']:x for x in topology.get('edges') or []}
    room_calc={x['room_id']:x for x in calculations.get('rooms') or []}
    sized=[]
    totals={}
    for route in routing.get('routes') or []:
        edge=edge_by_id.get(route.get('edge_id'),{})
        system=route.get('system')
        item=item_by_id.get(edge.get('from'),{})
        load=0.0
        if item.get('category')=='fixture':
            load=FIXTURE_LOAD.get(item.get('type'),{}).get(system,0.0)
        elif system in {'heating','cooling','condensate','gas'}:
            rc=room_calc.get(item.get('room_id'),{})
            load={'heating':rc.get('heating_w',0),'cooling':rc.get('cooling_w',0),'condensate':rc.get('cooling_w',0),'gas':rc.get('gas_kw',0)}[system]
        if item.get('design_load') is not None:
            load=float(item.get('design_load'))
        if system=='exhaust' and not load:
            load=150.0
        totals[system]=totals.get(system,0.0)+float(load or 0)
        size=_size(system,float(load or 0),tables)
        sized.append({'route_id':route['id'],'system':system,'downstream_load':round(float(load or 0),2),'size_mm':size,
                      'slope_percent':2.0 if system=='sanitary' else None})
    mains=[]
    for system,total in totals.items():
        mains.append({'system':system,'downstream_load':round(total,2),'size_mm':_size(system,total,tables),'role':'vertical_main'})
    return {'version':'network-sizing-v13.7','segments':sized,'vertical_mains':mains,'tables':tables,
            'quality':{'segments_sized':sum(1 for x in sized if x['size_mm'] is not None),
                       'sanitary_slopes_assigned':all(x['slope_percent'] is not None for x in sized if x['system']=='sanitary')}}
