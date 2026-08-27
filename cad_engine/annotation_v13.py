"""Stage 8 — generate drawing annotation intents from engineering data."""
from __future__ import annotations


def _midpoint(points):
    if not points:
        return (0.0, 0.0)
    a = points[len(points) // 2 - 1] if len(points) > 1 else points[0]
    b = points[len(points) // 2] if len(points) > 1 else points[0]
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)


def _shaft_anchor(topology):
    """Return a real vertical-core point for riser/cleanout annotations."""
    for node in topology.get('nodes') or []:
        if node.get('kind') == 'shaft' and node.get('point') and not node.get('provisional'):
            return tuple(node['point'][:2])
    return None


def build_annotations(routing, sizing, recognition, calculations, topology):
    size_by_route = {x['route_id']: x for x in sizing.get('segments') or []}
    item_by_id = {x['id']: x for x in recognition.get('detections') or []}
    edge_by_id = {x['id']: x for x in topology.get('edges') or []}
    room_calc = {x['room_id']: x for x in calculations.get('rooms') or []}
    annotations = []

    for route in routing.get('routes') or []:
        sz = size_by_route.get(route['id'], {})
        text = []
        if sz.get('size_mm') is not None:
            text.append(f"DN{int(sz['size_mm'])}")
        if sz.get('slope_percent') is not None:
            text.append(f"SLOPE {sz['slope_percent']:.1f}%")
        edge = edge_by_id.get(route.get('edge_id'), {})
        item = item_by_id.get(edge.get('from'), {})
        if item.get('type') == 'floor_drain':
            text.append('FD')
        if route.get('system') == 'sanitary' and item.get('type') in {'wc', 'sink', 'basin', 'shower', 'floor_drain'}:
            text.append('TO SOIL STACK')
        if route.get('system') == 'vent':
            text.append('VENT / UP TO ROOF')
        rc = room_calc.get(item.get('room_id'), {})
        if route.get('system') == 'cooling' and rc.get('cooling_w'):
            text.append(f"ROOM COOLING {rc['cooling_w'] / 1000:.1f} kW")
        if route.get('system') == 'exhaust' and rc.get('exhaust_cfm'):
            text.append(f"EXH {rc['exhaust_cfm']:.0f} CFM")
        if not text:
            text = [route.get('system', '').upper()]
        annotations.append({
            'id': f"ANN-{len(annotations) + 1:03d}",
            'route_id': route['id'],
            'system': route.get('system'),
            'text': ' | '.join(text),
            'anchor': _midpoint(route.get('points')),
            'leader': True,
            'source': 'calculated_route',
        })

    shaft = _shaft_anchor(topology)
    main_rows = [x for x in sizing.get('vertical_mains') or [] if x.get('size_mm') is not None]
    tag_by_system = {
        'sanitary': 'S1', 'vent': 'V1', 'cold_water': 'CW1', 'hot_water': 'HW1',
        'heating': 'H1', 'cooling': 'C1', 'condensate': 'CD1', 'gas': 'G1',
        'exhaust': 'EX1', 'ventilation': 'VN1',
    }
    for index, main in enumerate(main_rows):
        system = main['system']
        tag = tag_by_system.get(system, 'R1')
        anchor = None
        if shaft:
            anchor = (shaft[0] + 300.0, shaft[1] + index * 260.0)
        annotations.append({
            'id': f"ANN-{len(annotations) + 1:03d}",
            'route_id': None,
            'system': system,
            'text': f"{system.upper()} RISER {tag} DN{int(main['size_mm'])}",
            'anchor': anchor,
            'leader': bool(anchor),
            'source': 'vertical_main',
        })

    sanitary_main = next((x for x in main_rows if x.get('system') == 'sanitary'), None)
    if shaft and sanitary_main:
        annotations.append({
            'id': f"ANN-{len(annotations) + 1:03d}",
            'route_id': None,
            'system': 'sanitary',
            'text': f"C.O. AT BASE OF SANITARY RISER S1 DN{int(sanitary_main['size_mm'])}",
            'anchor': (shaft[0] + 600.0, shaft[1] - 500.0),
            'leader': True,
            'source': 'cleanout',
        })

    return {
        'version': 'annotation-engine-v13.8.1',
        'annotations': annotations,
        'quality': {
            'annotations': len(annotations),
            'leaders': sum(1 for x in annotations if x['leader']),
            'sized_route_labels': sum(1 for x in annotations if 'DN' in x['text']),
            'anchored_vertical_labels': sum(1 for x in annotations if x.get('source') == 'vertical_main' and x.get('anchor')),
            'cleanout_labels': sum(1 for x in annotations if x.get('source') == 'cleanout'),
        },
    }
