"""Stage 4 — calculation engine with explicit, overrideable project design bases.

Defaults are internal preliminary engineering assumptions, not code-prescribed
constants. Every result carries its design-basis provenance so professional
review can replace project values without changing routing logic.
"""
from __future__ import annotations

import math

DEFAULTS = {
    'water_fixture_units': {'wc':2.5,'basin':1.0,'sink':1.5,'shower':2.0,'floor_drain':0.0},
    'sanitary_dfu': {'wc':4.0,'basin':1.0,'sink':2.0,'shower':2.0,'floor_drain':2.0},
    'room_heating_w_m2': {'bathroom':90,'toilet':65,'kitchen':70,'living':80,'bedroom':75,'parking':0,'mechanical':45},
    'room_cooling_w_m2': {'bathroom':0,'toilet':0,'kitchen':110,'living':120,'bedroom':105,'parking':0,'mechanical':0},
    'room_exhaust_cfm': {'bathroom':80,'toilet':70,'kitchen':180,'parking':0},
    'gas_kw': {'stove':12.0,'water_heater':24.0},
}


def _area_m2(room, units):
    area = room.get('area')
    if not area:
        return None
    # DXF INSUNITS=4 is millimetres. Otherwise caller may supply normalized area_m2.
    if room.get('area_m2') is not None:
        return float(room['area_m2'])
    return float(area) / 1_000_000.0 if units == 4 else float(area)


def calculate_mechanical_loads(architecture, recognition, requirements, design_basis=None):
    basis = {k:(dict(v) if isinstance(v,dict) else v) for k,v in DEFAULTS.items()}
    for key, value in (design_basis or {}).items():
        if isinstance(value, dict) and isinstance(basis.get(key), dict): basis[key].update(value)
        else: basis[key] = value

    room_by_id = {r['id']:r for r in architecture.get('rooms') or []}
    req_by_id = {r['room_id']:set(r.get('systems') or []) for r in requirements.get('rooms') or []}
    detections = recognition.get('detections') or []
    results = []
    totals = {'water_fu':0.0,'sanitary_dfu':0.0,'heating_w':0.0,'cooling_w':0.0,'exhaust_cfm':0.0,'gas_kw':0.0}

    for rid, room in room_by_id.items():
        items = [x for x in detections if x.get('room_id') == rid]
        area = _area_m2(room, architecture.get('units'))
        water_fu = sum(basis['water_fixture_units'].get(x.get('type'),0) for x in items if x.get('category')=='fixture')
        sanitary_dfu = sum(basis['sanitary_dfu'].get(x.get('type'),0) for x in items if x.get('category')=='fixture')
        heat = (area or 0) * basis['room_heating_w_m2'].get(room.get('type'),0) if 'heating' in req_by_id.get(rid,set()) else 0
        cool = (area or 0) * basis['room_cooling_w_m2'].get(room.get('type'),0) if 'cooling' in req_by_id.get(rid,set()) else 0
        exhaust = basis['room_exhaust_cfm'].get(room.get('type'),0) if ('exhaust' in req_by_id.get(rid,set()) or 'ventilation' in req_by_id.get(rid,set())) else 0
        gas = sum(basis['gas_kw'].get(x.get('type'),0) for x in items if x.get('category')=='equipment')
        row = {'room_id':rid,'area_m2':area,'water_fu':round(water_fu,2),'sanitary_dfu':round(sanitary_dfu,2),
               'heating_w':round(heat,1),'cooling_w':round(cool,1),'exhaust_cfm':round(exhaust,1),'gas_kw':round(gas,2)}
        results.append(row)
        for key in totals: totals[key] += row[key]

    # Preliminary diversified water flow used only as a sizing input. The formula
    # is explicit and overrideable by replacing this stage/project basis.
    totals = {k:round(v,2) for k,v in totals.items()}
    totals['preliminary_water_lps'] = round(0.12 * math.sqrt(max(totals['water_fu'],0.0)), 3)
    return {'version':'mechanical-calculations-v13.4','rooms':results,'totals':totals,
            'design_basis':basis,'basis_status':'PRELIMINARY_OVERRIDEABLE',
            'quality':{'rooms_calculated':len(results),'traceable_basis':True}}
