import re
from . import main_v3 as engine


def _extract(pattern: str, text: str):
    m = re.search(pattern, str(text or ''), re.I)
    if not m:
        return None
    return m.group(1).replace(',', '.')


def _normalized_answers(a: dict, discipline: str) -> dict:
    out = dict(a or {})
    if discipline == 'electrical':
        loads = str(out.get('loads') or '')
        pf = _extract(r'\bPF\s*=\s*([0-9]+(?:[\.,][0-9]+)?)', loads)
        vd = _extract(r'\bVD\s*=\s*([0-9]+(?:[\.,][0-9]+)?)\s*%?', loads)
        if pf is not None:
            out['power_factor'] = pf
        if vd is not None:
            out['max_voltage_drop_pct'] = vd
        # Preserve exact numeric inputs under canonical keys as well as the human-readable answer.
        load = _extract(r'([0-9]+(?:[\.,][0-9]+)?)\s*kW\b', loads)
        length = _extract(r'([0-9]+(?:[\.,][0-9]+)?)\s*m\b', loads)
        if load is not None:
            out['design_load_kw'] = load
        if length is not None:
            out['cable_length_m'] = length
        supply = str(out.get('supply') or '')
        voltage = _extract(r'([0-9]+(?:[\.,][0-9]+)?)\s*V\b', supply)
        if voltage is not None:
            out['supply_voltage'] = voltage
    else:
        water = str(out.get('water') or '')
        flow = _extract(r'([0-9]+(?:[\.,][0-9]+)?)\s*L/s\b', water)
        vel = _extract(r'\bVEL\s*=\s*([0-9]+(?:[\.,][0-9]+)?)\s*m/s\b', water)
        if flow is not None:
            out['design_water_flow_lps'] = flow
        if vel is not None:
            out['target_water_velocity_mps'] = vel
        cooling = str(out.get('cooling') or '')
        cooling_kw = _extract(r'([0-9]+(?:[\.,][0-9]+)?)\s*kW\b', cooling)
        if cooling_kw is not None:
            out['cooling_load_kw'] = cooling_kw
        heating = str(out.get('heating') or '')
        heating_kw = _extract(r'([0-9]+(?:[\.,][0-9]+)?)\s*kW\b', heating)
        if heating_kw is not None:
            out['heating_load_kw'] = heating_kw
    return out


_original_electrical_calc = engine.electrical_calc
_original_mechanical_calc = engine.mechanical_calc


def electrical_calc(a):
    return _original_electrical_calc(_normalized_answers(a, 'electrical'))


def mechanical_calc(a):
    return _original_mechanical_calc(_normalized_answers(a, 'mechanical'))


engine.electrical_calc = electrical_calc
engine.mechanical_calc = mechanical_calc
engine.app.version = '0.4.0'
app = engine.app


@app.get('/engine-capabilities')
def engine_capabilities():
    return {
        'version': '0.4.0',
        'questionnaire': 'structured-numeric',
        'electrical_numeric_inputs': ['phase', 'voltage_v', 'design_load_kw', 'cable_length_m', 'power_factor', 'max_voltage_drop_pct'],
        'mechanical_numeric_inputs': ['design_water_flow_lps', 'target_water_velocity_mps', 'cooling_load_kw', 'heating_load_kw'],
        'note': 'Calculation outputs remain preliminary and require professional engineering verification.'
    }
