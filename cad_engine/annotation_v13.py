"""Stage 8 — generate drawing annotation intents from engineering data."""
from __future__ import annotations


def _midpoint(points):
    if not points: return (0.0,0.0)
    a=points[len(points)//2-1] if len(points)>1 else points[0]
    b=points[len(points)//2] if len(points)>1 else points[0]
    return ((a[0]+b[0])/2.0,(a[1]+b[1])/2.0)


def build_annotations(routing, sizing, recognition, calculations, topology):
    size_by_route={x['route_id']:x for x in sizing.get('segments') or []}
    item_by_id={x['id']:x for x in recognition.get('detections') or []}
    edge_by_id={x['id']:x for x in topology.get('edges') or []}
    room_calc={x['room_id']:x for x in calculations.get('rooms') or []}
    annotations=[]
    for route in routing.get('routes') or []:
        sz=size_by_route.get(route['id'],{})
        text=[]
        if sz.get('size_mm') is not None: text.append(f"DN{int(sz['size_mm'])}")
        if sz.get('slope_percent') is not None: text.append(f"SLOPE {sz['slope_percent']:.1f}%")
        edge=edge_by_id.get(route.get('edge_id'),{})
        item=item_by_id.get(edge.get('from'),{})
        if item.get('type')=='floor_drain': text.append('FD')
        if route.get('system')=='sanitary' and item.get('type') in {'wc','sink','basin','shower','floor_drain'}: text.append('TO SOIL STACK')
        if route.get('system')=='vent': text.append('VENT / UP TO ROOF')
        rc=room_calc.get(item.get('room_id'),{})
        if route.get('system')=='cooling' and rc.get('cooling_w'):
            text.append(f"ROOM COOLING {rc['cooling_w']/1000:.1f} kW")
        if route.get('system')=='exhaust' and rc.get('exhaust_cfm'):
            text.append(f"EXH {rc['exhaust_cfm']:.0f} CFM")
        if not text: text=[route.get('system','').upper()]
        annotations.append({'id':f"ANN-{len(annotations)+1:03d}",'route_id':route['id'],'system':route.get('system'),
                            'text':' | '.join(text),'anchor':_midpoint(route.get('points')),'leader':True,'source':'calculated_route'})
    for main in sizing.get('vertical_mains') or []:
        if main.get('size_mm') is not None:
            annotations.append({'id':f"ANN-{len(annotations)+1:03d}",'route_id':None,'system':main['system'],
                                'text':f"{main['system'].upper()} RISER DN{int(main['size_mm'])}",'anchor':None,'leader':False,'source':'vertical_main'})
    return {'version':'annotation-engine-v13.8','annotations':annotations,
            'quality':{'annotations':len(annotations),'leaders':sum(1 for x in annotations if x['leader']),
                       'sized_route_labels':sum(1 for x in annotations if 'DN' in x['text'])}}
