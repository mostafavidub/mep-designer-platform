import math

from . import main_v10_fix as fix
from . import main_v10 as v10
from . import main_v6 as v6
from . import main_v3 as engine

app = fix.app
_base_levels = v10._electrical_levels


def electrical_levels_with_elevator(msp):
    levels = _base_levels(msp)
    # Elevator is an explicit Rulebook special load. The legacy room classifier
    # intentionally did not include it, so extract it directly from architecture
    # text and assign it to the nearest non-parking architectural level.
    elevators = []
    for entity in msp:
        if entity.dxftype() not in ('TEXT', 'MTEXT'):
            continue
        text = v6.norm(v6.text_value(entity)).lower()
        p = v6.point(entity)
        if p and ('آسانسور' in text or 'elevator' in text or 'lift' in text):
            elevators.append({'room': 'elevator', 'point': p, 'text': text})
    candidates = [x for x in levels if x.get('special_type') != 'parking' and not v10.v8._is_roof(x)]
    for item in elevators:
        if not candidates:
            break
        level = min(candidates, key=lambda x: math.dist(item['point'], x['title']['point']))
        # Only transfer labels spatially belonging to the selected plan cluster.
        other_titles = [x['title']['point'] for x in candidates if x is not level]
        limit = min([math.dist(level['title']['point'], p) for p in other_titles], default=25.0) * 1.25
        if math.dist(item['point'], level['title']['point']) <= max(limit, 8.0):
            if not any(r.get('room') == 'elevator' and math.dist(r['point'], item['point']) < .5 for r in level.get('rooms', [])):
                level.setdefault('rooms', []).append(item)
    return levels


v10._electrical_levels = electrical_levels_with_elevator
engine.design_dxf = v10.design_dxf_v10
engine.electrical_calc = v10.electrical_calc_v10


@app.get('/v10-2-capabilities')
def capabilities():
    return {
        'ok': True,
        'version': '1.0.2-electrical-v10',
        'elevator_architecture_extraction': True,
        'elevator_dedicated_panel_feeder': True,
        'legal_dxf_lineweights': True,
        'comprehensive_electrical_rulebook_gate': True,
        'construction_ready': False,
        'professional_verification_required': True,
    }
