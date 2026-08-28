"""Fixture/Equipment Context v1.

Associates detected fixtures/equipment with the reconstructed architectural
model. Polygon containment is preferred; bounded nearest-room association is a
fallback. The output is the first room-aware equipment schedule that later MEP
system and routing engines can consume directly.
"""
from collections import Counter
import math

CONTEXT_VERSION = "fixture-equipment-context-v1"


def _contains(poly, point):
    if not poly or len(poly) < 3:
        return False
    x, y = point; inside = False; j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]; xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and x < (xj-xi)*(y-yi)/((yj-yi) or 1e-12)+xi:
            inside = not inside
        j = i
    return inside


def _center(room):
    if room.get('center'):
        return [float(room['center'][0]), float(room['center'][1])]
    if room.get('label_point'):
        return [float(room['label_point'][0]), float(room['label_point'][1])]
    b = room.get('bounds') or [0, 0, 0, 0]
    return [(b[0]+b[2])/2.0, (b[1]+b[3])/2.0]


def _region_diag(level):
    b = level.get('region_bounds') or [0, 0, 1, 1]
    return max(math.hypot(b[2]-b[0], b[3]-b[1]), 1.0)


def _room_for(point, level):
    rooms = level.get('rooms') or []
    contained = [r for r in rooms if r.get('polygon') and _contains(r['polygon'], point)]
    if contained:
        # If nested polygons exist, the smaller one is the more specific room.
        def area(room):
            b = room.get('bounds') or [0, 0, 1e9, 1e9]
            return abs((b[2]-b[0])*(b[3]-b[1]))
        return min(contained, key=area), 'polygon', 0.99
    if not rooms:
        return None, None, 0.0
    room, dist = min(((r, math.dist(point, _center(r))) for r in rooms), key=lambda x: x[1])
    limit = max(_region_diag(level) * 0.18, 1.0)
    if dist <= limit:
        return room, 'nearest_room', round(max(0.60, 0.90 - 0.30*(dist/limit)), 3)
    return None, None, 0.0


def _level_for(point, levels, hinted_name=None):
    if hinted_name:
        named = [x for x in levels if str(x.get('name')) == str(hinted_name)]
        if named:
            return named[0]
    # Prefer region containment, then closest title point.
    contained = []
    for level in levels:
        b = level.get('region_bounds')
        if b and b[0] <= point[0] <= b[2] and b[1] <= point[1] <= b[3]:
            contained.append(level)
    if contained:
        return min(contained, key=lambda x: _region_diag(x))
    titled = [x for x in levels if x.get('title_point')]
    if titled:
        return min(titled, key=lambda x: math.dist(point, x['title_point']))
    return None


def enrich_fixture_context(auto):
    auto = dict(auto or {})
    model = auto.get('architecture_model') or {}
    levels = model.get('levels') or []
    rows = []
    for category, source in (
        ('fixture', auto.get('fixture_detections') or []),
        ('equipment', auto.get('equipment_detections') or []),
    ):
        for raw in source:
            row = dict(raw)
            try:
                point = [float(row.get('x')), float(row.get('y'))]
            except Exception:
                rows.append(row); continue
            level = _level_for(point, levels, row.get('level'))
            if level:
                row['level'] = level.get('name')
                room, method, confidence = _room_for(point, level)
                if room:
                    row['room_id'] = room.get('id')
                    row['room_type'] = room.get('type')
                    row['room_association_method'] = method
                    row['room_association_confidence'] = confidence
                    wet_core = next((w for w in level.get('wet_cores') or [] if room.get('id') in (w.get('room_ids') or [])), None)
                    row['wet_core_id'] = wet_core.get('id') if wet_core else None
                else:
                    row['room_id'] = None; row['room_type'] = None
                    row['room_association_method'] = None; row['room_association_confidence'] = 0.0
                    row['wet_core_id'] = None
            rows.append(row)

    fixtures = [x for x in rows if x.get('category') == 'fixture']
    equipment = [x for x in rows if x.get('category') == 'equipment']
    auto['fixture_detections'] = fixtures
    auto['equipment_detections'] = equipment

    level_schedules = []
    for level in levels:
        name = level.get('name')
        f = [x for x in fixtures if x.get('level') == name and x.get('status') == 'detected']
        e = [x for x in equipment if x.get('level') == name and x.get('status') == 'detected']
        room_schedules = []
        for room in level.get('rooms') or []:
            rid = room.get('id')
            rf = [x for x in f if x.get('room_id') == rid]
            re = [x for x in e if x.get('room_id') == rid]
            room_schedules.append({
                'room_id': rid, 'room_type': room.get('type'),
                'fixture_counts': dict(Counter(x.get('type') for x in rf)),
                'equipment_counts': dict(Counter(x.get('type') for x in re)),
                'fixture_ids': [f"F-{i+1:04d}" for i, _ in enumerate(rf)],
                'detected_fixture_count': len(rf), 'detected_equipment_count': len(re),
            })
        level_schedules.append({
            'level': name,
            'fixture_counts': dict(Counter(x.get('type') for x in f)),
            'equipment_counts': dict(Counter(x.get('type') for x in e)),
            'rooms': room_schedules,
            'unassigned_detected_count': sum(1 for x in f+e if not x.get('room_id')),
        })

    auto['fixture_equipment_model'] = {
        'version': CONTEXT_VERSION,
        'levels': level_schedules,
        'detected_fixture_count': sum(1 for x in fixtures if x.get('status') == 'detected'),
        'detected_equipment_count': sum(1 for x in equipment if x.get('status') == 'detected'),
        'room_assigned_detected_count': sum(1 for x in fixtures+equipment if x.get('status') == 'detected' and x.get('room_id')),
    }
    return auto


def install(main_auto_module):
    if getattr(main_auto_module, '_fixture_context_v1_installed', False):
        return
    base_infer = main_auto_module.infer_architecture_facts

    def infer(analysis, discipline):
        return enrich_fixture_context(base_infer(analysis, discipline))

    main_auto_module.infer_architecture_facts = infer
    main_auto_module._fixture_context_v1_installed = True
