import math

from . import main_v10_fix as fix
from . import main_v10 as v10
from . import main_v6 as v6
from . import main_v3 as engine

app = fix.app
_base_levels = v10._electrical_levels


def electrical_levels_with_elevator(msp):
    levels = _base_levels(msp)
    elevators = []
    for entity in msp:
        if entity.dxftype() not in ('TEXT', 'MTEXT'):
            continue
        text = v6.norm(v6.text_value(entity)).lower()
        p = v6.point(entity)
        if p and ('آسانسور' in text or 'elevator' in text or 'lift' in text):
            elevators.append({'room': 'elevator', 'point': p, 'text': text})
    candidates = [x for x in levels if x.get('special_type') != 'parking' and not v10.v8._is_roof(x)]
    for level in candidates:
        # Architecture/furniture sheets in real projects can repeat elevator text.
        # Keep only the elevator annotation spatially belonging to this primary
        # architecture plan; do not copy elevator labels from adjacent furniture
        # or lintel plans into the electrical level.
        nearby = [x for x in elevators if math.dist(x['point'], level['title']['point']) <= 12.0]
        if nearby and not any(r.get('room') == 'elevator' for r in level.get('rooms', [])):
            level.setdefault('rooms', []).append(min(nearby, key=lambda x: math.dist(x['point'], level['title']['point'])))
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
