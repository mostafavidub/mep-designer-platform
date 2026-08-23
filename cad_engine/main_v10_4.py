"""Evidence-gated mechanical technical design engine.

This stage turns the authority sheet package into a measurable engineering
deliverable.  A 10/10 score means every automated technical gate below passed;
it never replaces the statutory review/signature of the engineer of record.
"""

import math
import re
from collections import Counter

import ezdxf
from ezdxf import bbox

from app.mechanical_rulebook import (
    DEFAULT_GAS_PROPOSAL,
    DEFAULT_WATER_INLET_PRESSURE,
    RULEBOOK_VERSION,
    SANITARY,
    WATER,
    fixture_schedule_proposal,
    is_confirmation,
    roof_basis,
    roof_geometry_proposal,
    water_inlet_pressure_basis,
)

from . import main_v10_3 as base
from . import main_v8 as v8
from . import main_v6 as v6
from . import main_v3 as engine

app = base.app
_base_design = base.design_dxf_v10_3
STANDARD_PIPE_MM = (16, 20, 25, 32, 40, 50, 63, 75, 90, 110, 125, 160, 200)


def _norm(value):
    return str(value or '').replace('ي', 'ی').replace('ك', 'ک').replace(',', '.').strip()


def _number(text, unit_pattern=None, default=None):
    value = _norm(text)
    pattern = r'([-+]?\d+(?:\.\d+)?)'
    if unit_pattern:
        pattern += r'\s*(?:' + unit_pattern + r')'
    match = re.search(pattern, value, re.I)
    return float(match.group(1)) if match else default


def _all_numbers(text, unit_pattern):
    pattern = r'([-+]?\d+(?:[\.,]\d+)?)\s*(?:' + unit_pattern + r')'
    return [float(x.replace(',', '.')) for x in re.findall(pattern, str(text or ''), re.I)]


def _next_pipe(value):
    for item in STANDARD_PIPE_MM:
        if value <= item:
            return item
    return STANDARD_PIPE_MM[-1]


def _material(text, choices):
    low = _norm(text).lower()
    for label, aliases in choices:
        if any(x.lower() in low for x in aliases):
            return label
    return None


def _layer_length(msp, layer):
    length = 0.0
    for entity in msp:
        if str(getattr(entity.dxf, 'layer', '')) != layer:
            continue
        try:
            if entity.dxftype() == 'LINE':
                length += math.dist(tuple(entity.dxf.start)[:2], tuple(entity.dxf.end)[:2])
            elif entity.dxftype() == 'LWPOLYLINE':
                points = [(float(x), float(y)) for x, y, *_ in entity.get_points('xy')]
                length += sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        except Exception:
            continue
    return length


def _drawing_unit_to_m(doc):
    return {4: .001, 5: .01, 6: 1.0}.get(int(doc.header.get('$INSUNITS', 0) or 0))


def _fixture_schedule_counts(text):
    """Read explicit fixture quantities; never infer them from room names."""
    value = _norm(text).lower()
    aliases = {
        'sink': ('sink', 'basin', 'سینک', 'روشویی', 'روشويی'),
        'faucet': ('faucet', 'tap', 'شیر آب', 'شير آب'),
        'toilet': ('toilet', 'wc', 'توالت', 'توالت فرنگی'),
        'bath': ('bath', 'shower', 'دوش', 'وان'),
    }
    result = Counter()
    for kind, names in aliases.items():
        for name in names:
            escaped = re.escape(name)
            match = re.search(rf'(?:{escaped})\s*[:=x×-]?\s*(\d+)', value, re.I)
            if not match:
                match = re.search(rf'(\d+)\s*(?:عدد|x|×)?\s*(?:{escaped})', value, re.I)
            if match:
                result[kind] = int(match.group(1))
                break
    return result


def _fixture_summary(levels, fixture_schedule=''):
    detected = Counter()
    rooms = Counter()
    for level in levels:
        for room in level.get('rooms', []):
            rooms[room.get('room')] += 1
        for fixture in level.get('fixtures', []):
            detected[fixture.get('kind')] += 1
    # Room proxies may keep a preliminary drawing legible, but can never satisfy
    # the traceability gate. Only architecture blocks or an explicit quantified
    # fixture schedule are accepted as final-design evidence.
    effective = Counter(detected)
    scheduled = _fixture_schedule_counts(fixture_schedule)
    proxy_count = 0
    if not sum(detected.values()):
        if sum(scheduled.values()):
            effective.update(scheduled)
        else:
            effective['sink'] = rooms['kitchen'] + rooms['bath']
            effective['toilet'] = rooms['toilet']
            effective['bath'] = rooms['bath']
            proxy_count = sum(effective.values())
    return detected, scheduled, effective, rooms, proxy_count


def _technical_model(doc, levels, calc):
    inputs = calc.get('_design_inputs') or {}
    fixture_schedule = _norm(inputs.get('fixture_schedule'))
    if is_confirmation(fixture_schedule):
        fixture_schedule = fixture_schedule_proposal(levels)
    detected, scheduled, fixtures, rooms, proxies = _fixture_summary(levels, fixture_schedule)
    unit_to_m = _drawing_unit_to_m(doc)
    water_basis = _norm(inputs.get('water_design_basis')) or (
        f"{WATER['material']}; Hazen-Williams C={WATER['hazen_williams_c']}; "
        f"maximum loss {WATER['maximum_friction_loss_kpa_per_100m']} kPa/100 m"
    )
    sanitary_basis = _norm(inputs.get('sanitary_design_basis')) or (
        f"{SANITARY['material']}; {SANITARY['branch_slope_pct']} percent branches; "
        f"{SANITARY['main_slope_pct']} percent mains"
    )
    gas_basis = _norm(inputs.get('gas_appliances') or inputs.get('gas'))
    if is_confirmation(gas_basis):
        gas_basis = DEFAULT_GAS_PROPOSAL
    equipment = _norm(inputs.get('equipment_schedule'))
    ventilation = _norm(inputs.get('ventilation_design_basis'))
    roof_design_basis = _norm(inputs.get('roof_drainage_basis'))
    roof_geometry = _norm(inputs.get('roof_drainage_geometry'))
    if is_confirmation(roof_geometry):
        roof_geometry = roof_geometry_proposal(levels)
    roof_design_basis = roof_basis(inputs.get('location'), roof_design_basis or roof_geometry)

    water_fu = (
        fixtures['sink'] * 1.5 + fixtures['faucet'] * 1.0
        + fixtures['toilet'] * 2.5 + fixtures['bath'] * 2.0
    )
    flow_lps = calc.get('design_water_flow_lps') or calc.get('estimated_water_flow_lps')
    if flow_lps is None and water_fu:
        flow_lps = max(.2, .16 * math.sqrt(water_fu))
    flow_lps = float(flow_lps) if flow_lps is not None else None
    velocity = float(calc.get('target_water_velocity_mps') or 1.5)
    hydraulic_d = None
    water_dn = None
    if flow_lps:
        hydraulic_d = math.sqrt(4.0 * flow_lps / 1000.0 / (math.pi * max(velocity, .1))) * 1000.0
        water_dn = _next_pipe(hydraulic_d)
    pressure_input = _norm(inputs.get('water_inlet_pressure'))
    inlet_bar = _number(pressure_input, r'bar|بار') or _number(water_basis, r'bar|بار')
    match = re.search(r'c\s*=\s*(\d+(?:\.\d+)?)', water_basis, re.I)
    hazen_c = float(match.group(1)) if match else None
    water_material = _material(water_basis, (
        ('PPR', ('ppr',)), ('PEX', ('pex',)), ('Copper', ('copper', 'مس')),
        ('Galvanized steel', ('galvanized', 'گالوانیزه')),
    ))
    water_length_m = _layer_length(doc.modelspace(), 'ENGITOOLS-M-COLD_WATER')
    water_length_m = water_length_m * unit_to_m if unit_to_m else None
    head_loss_m = None
    if flow_lps and water_dn and hazen_c and water_length_m:
        q = flow_lps / 1000.0
        d = water_dn / 1000.0
        head_loss_m = 10.67 * water_length_m * (q ** 1.852) / ((hazen_c ** 1.852) * (d ** 4.871))

    drainage_fu = fixtures['sink'] * 2 + fixtures['faucet'] + fixtures['toilet'] * 6 + fixtures['bath'] * 2
    sanitary_dn = 110 if fixtures['toilet'] else (75 if drainage_fu > 6 else 50)
    sanitary_slope = _number(sanitary_basis, r'%|percent|درصد')
    sanitary_material = _material(sanitary_basis, (
        ('uPVC', ('upvc', 'u-pvc', 'pvc', 'پی وی سی')), ('PP', ('polypropylene', 'پلی پروپیلن', ' pp')),
        ('Cast iron', ('cast iron', 'چدن')),
    ))
    sanitary_outlet = _norm(inputs.get('sanitary_outlet'))
    if is_confirmation(sanitary_outlet):
        sanitary_outlet = 'municipal sewer at project boundary - user confirmed Rulebook proposal'

    gas_values_kw = _all_numbers(gas_basis, r'kw|کیلووات|كيلووات')
    gas_load_kw = sum(gas_values_kw) if gas_values_kw else None
    gas_flow_m3h = gas_load_kw / 9.5 if gas_load_kw else None
    gas_pressure_mbar = _number(gas_basis, r'mbar|میلی\s*بار|ميلي\s*بار')
    gas_dn = None
    if gas_flow_m3h is not None:
        gas_dn = 20 if gas_flow_m3h <= 2.5 else 25 if gas_flow_m3h <= 6 else 32 if gas_flow_m3h <= 10 else 40
    gas_meter = bool(re.search(r'meter|regulator|کنتور|رگلاتور', gas_basis, re.I))

    cooling_kw = calc.get('cooling_load_kw')
    heating_kw = calc.get('heating_load_kw')
    capacities_btuh = _all_numbers(equipment, r'btu(?:/h|hr)?')
    capacities_kw = _all_numbers(equipment, r'kw|کیلووات|كيلووات')
    equipment_resolved = bool(equipment and (capacities_btuh or capacities_kw or re.search(r'per\s+room\s+load|بار\s+هر\s+فضا', equipment, re.I)))
    habitable = max(1, rooms['bedroom'] + rooms['living'] + rooms['office'] + rooms['shop'])
    per_room_cooling_kw = round(float(cooling_kw) / habitable, 2) if cooling_kw else None
    per_room_heating_kw = round(float(heating_kw) / habitable, 2) if heating_kw else None

    airflow_m3h = sum(_all_numbers(ventilation, r'm3/h|m³/h|متر\s*مکعب\s*بر\s*ساعت')) or None
    ach_values = _all_numbers(ventilation, r'ach|تعویض\s*هوا|تعويض\s*هوا')
    discharge_resolved = bool(re.search(r'discharge|تخلیه|تخليه|بام|roof|exterior|خارج', ventilation, re.I))
    makeup_resolved = bool(re.search(r'make.?up|جبرانی|جبراني', ventilation, re.I))

    roof_area = _number(roof_design_basis, r'm2|m²|متر\s*مربع')
    rainfall = _number(roof_design_basis, r'mm/h|میلی.?متر\s*بر\s*ساعت|ميلي.?متر\s*بر\s*ساعت')
    drain_match = re.search(r'(\d+)\s*(?:drain|rd|کف.?خواب|ناودان)', roof_design_basis, re.I)
    drain_count = int(drain_match.group(1)) if drain_match else None
    roof_flow_lps = roof_area * rainfall / 3600.0 if roof_area and rainfall else None
    roof_flow_each = roof_flow_lps / drain_count if roof_flow_lps and drain_count else None
    roof_dn = _next_pipe(max(75.0, 45.0 * math.sqrt(roof_flow_each))) if roof_flow_each else None

    model = {
        'fixture_blocks_detected': sum(detected.values()),
        'fixture_schedule_count': sum(scheduled.values()),
        'fixture_traceability_basis': (
            'architecture_blocks' if sum(detected.values()) else
            'explicit_fixture_schedule' if sum(scheduled.values()) else
            'room_proxy_preliminary_only'
        ),
        'fixture_proxies': proxies,
        'water_fixture_units': round(water_fu, 2), 'design_water_flow_lps': round(flow_lps, 3) if flow_lps else None,
        'water_velocity_mps': velocity, 'water_hydraulic_diameter_mm': round(hydraulic_d, 1) if hydraulic_d else None,
        'water_main_dn_mm': water_dn, 'water_material': water_material, 'water_inlet_pressure_bar': inlet_bar,
        'water_design_basis_source': f'Rulebook v{RULEBOOK_VERSION}',
        'hazen_williams_c': hazen_c, 'water_route_length_m': round(water_length_m, 2) if water_length_m else None,
        'water_head_loss_m': round(head_loss_m, 2) if head_loss_m is not None else None,
        'drainage_fixture_units': drainage_fu, 'sanitary_main_dn_mm': sanitary_dn,
        'sanitary_slope_pct': sanitary_slope, 'sanitary_material': sanitary_material, 'sanitary_outlet': sanitary_outlet or None,
        'gas_load_kw': round(gas_load_kw, 2) if gas_load_kw else None,
        'gas_flow_m3h': round(gas_flow_m3h, 2) if gas_flow_m3h else None, 'gas_pressure_mbar': gas_pressure_mbar,
        'gas_main_dn_mm': gas_dn, 'gas_meter_regulator_defined': gas_meter,
        'cooling_load_kw': cooling_kw, 'heating_load_kw': heating_kw,
        'equipment_schedule_resolved': equipment_resolved, 'equipment_schedule': equipment or None,
        'per_room_cooling_kw': per_room_cooling_kw, 'per_room_heating_kw': per_room_heating_kw,
        'ventilation_airflow_m3h': airflow_m3h, 'ventilation_ach_values': ach_values,
        'ventilation_discharge_resolved': discharge_resolved, 'makeup_air_resolved': makeup_resolved,
        'roof_area_m2': roof_area, 'rainfall_mm_h': rainfall, 'roof_drain_count': drain_count,
        'roof_flow_lps': round(roof_flow_lps, 2) if roof_flow_lps else None,
        'roof_flow_per_drain_lps': round(roof_flow_each, 2) if roof_flow_each else None,
        'roof_drain_dn_mm': roof_dn,
        'mechanical_rulebook_version': RULEBOOK_VERSION,
    }
    return model


def _ensure_symbol_blocks(doc):
    defs = {
        'ET_M_WATER_POINT': ('circle', 'WP'), 'ET_M_SAN_POINT': ('circle', 'S'),
        'ET_M_GAS_POINT': ('box', 'G'), 'ET_M_EQUIPMENT': ('box', 'EQ'),
        'ET_M_EXHAUST': ('box', 'EF'), 'ET_M_RISER': ('diamond', 'R'),
    }
    for name, (kind, tag) in defs.items():
        if name in doc.blocks:
            continue
        block = doc.blocks.new(name=name)
        if kind == 'circle':
            block.add_circle((0, 0), .12)
        elif kind == 'diamond':
            block.add_lwpolyline([(0, .16), (.16, 0), (0, -.16), (-.16, 0), (0, .16)])
        else:
            block.add_lwpolyline([(-.14, -.14), (.14, -.14), (.14, .14), (-.14, .14), (-.14, -.14)])
        block.add_text(tag, dxfattribs={'height': .08}).set_placement((-.08, -.03))


def _add_standard_symbols(doc, levels, model):
    _ensure_symbol_blocks(doc)
    msp = doc.modelspace()
    count = 0
    for level in levels:
        fixtures = level.get('fixtures') or []
        wet_points = [x['point'] for x in fixtures if x.get('kind') != 'gas']
        if not wet_points:
            wet_points = [x['point'] for x in level.get('rooms', []) if x.get('room') in ('kitchen', 'bath', 'toilet')]
        for point in wet_points:
            msp.add_blockref('ET_M_WATER_POINT', point, dxfattribs={'layer': 'ENGITOOLS-M-COLD_WATER'})
            msp.add_blockref('ET_M_SAN_POINT', (point[0] + .22, point[1]), dxfattribs={'layer': 'ENGITOOLS-M-SANITARY'})
            count += 2
        for room in level.get('rooms', []):
            point = room['point']
            if room.get('room') == 'kitchen' and model.get('gas_main_dn_mm'):
                msp.add_blockref('ET_M_GAS_POINT', point, dxfattribs={'layer': 'ENGITOOLS-M-GAS'}); count += 1
            if room.get('room') in ('bedroom', 'living') and model.get('equipment_schedule_resolved'):
                msp.add_blockref('ET_M_EQUIPMENT', point, dxfattribs={'layer': 'ENGITOOLS-M-COOLING'}); count += 1
            if room.get('room') in ('bath', 'toilet') and model.get('ventilation_airflow_m3h'):
                msp.add_blockref('ET_M_EXHAUST', point, dxfattribs={'layer': 'ENGITOOLS-M-EXHAUST_VENTILATION'}); count += 1
        hub = v8._find_level_riser(msp, level)
        if hub:
            msp.add_blockref('ET_M_RISER', hub, dxfattribs={'layer': 'ENGITOOLS-M-MECHANICAL_RISERS'}); count += 1
    return count


def _text(layout, value, x, y, height=2.55, layer='ENGITOOLS-M-NOTES'):
    return layout.add_text(str(value), dxfattribs={'height': height, 'layer': layer}).set_placement((x, y))


def _schedule_lines(code, model):
    group = code[2:3]
    if group == 'W':
        return [
            f"Q={model.get('design_water_flow_lps')} L/s | FU={model.get('water_fixture_units')}",
            f"MAIN DN{model.get('water_main_dn_mm')} | v={model.get('water_velocity_mps')} m/s",
            f"MATERIAL={model.get('water_material')} | C={model.get('hazen_williams_c')}",
            f"ROUTE={model.get('water_route_length_m')} m | hf={model.get('water_head_loss_m')} m",
            f"INLET={model.get('water_inlet_pressure_bar')} bar",
        ]
    if group == 'S':
        return [
            f"DFU={model.get('drainage_fixture_units')} | MAIN DN{model.get('sanitary_main_dn_mm')}",
            f"SLOPE={model.get('sanitary_slope_pct')}% | MATERIAL={model.get('sanitary_material')}",
            f"OUTLET={model.get('sanitary_outlet')}",
            'BRANCH: WC DN110 | BASIN/BATH DN50 | VENT DN50',
        ]
    if group in ('H', 'C'):
        return [
            f"COOLING={model.get('cooling_load_kw')} kW | HEATING={model.get('heating_load_kw')} kW",
            f"PER CONDITIONED ROOM: C={model.get('per_room_cooling_kw')} kW | H={model.get('per_room_heating_kw')} kW",
            f"EQUIPMENT={model.get('equipment_schedule')}",
            'CONDENSATE: DN25 MIN, CONTINUOUS FALL TO APPROVED DISCHARGE',
        ]
    if group == 'G':
        return [
            f"CONNECTED LOAD={model.get('gas_load_kw')} kW | FLOW={model.get('gas_flow_m3h')} m3/h",
            f"INLET={model.get('gas_pressure_mbar')} mbar | MAIN DN{model.get('gas_main_dn_mm')}",
            'METER / REGULATOR LOCATION DEFINED IN PROJECT INPUT',
        ]
    if group == 'V':
        return [
            f"DESIGN AIRFLOW={model.get('ventilation_airflow_m3h')} m3/h",
            f"ACH VALUES={model.get('ventilation_ach_values')}",
            'DISCHARGE AND MAKE-UP AIR PATHS DEFINED IN PROJECT INPUT',
        ]
    if group == 'R':
        return [
            f"ROOF AREA={model.get('roof_area_m2')} m2 | i={model.get('rainfall_mm_h')} mm/h",
            f"Q={model.get('roof_flow_lps')} L/s | DRAINS={model.get('roof_drain_count')}",
            f"EACH={model.get('roof_flow_per_drain_lps')} L/s | RD DN{model.get('roof_drain_dn_mm')}",
        ]
    return []


def _annotate_sheets(doc, model):
    count = 0
    for layout in doc.layouts:
        if not re.match(r'^M-[WSHCGVR]-', layout.name):
            continue
        _text(layout, 'TECHNICAL DESIGN SCHEDULE', 445, 275, 3.2)
        y = 263
        for line in _schedule_lines(layout.name, model):
            _text(layout, line, 445, y)
            y -= 9
            count += 1
    return count


def _families(calc):
    manifest = calc.get('_approved_drawing_manifest') or {}
    return {str(x.get('family') or '') for x in manifest.get('sheets') or []}


def _quality_report(doc, levels, calc, model, symbol_count, schedule_count):
    manifest = calc.get('_approved_drawing_manifest') or {}
    expected = int(manifest.get('total_sheets') or 0)
    issued = [x.name for x in doc.layouts if x.name.startswith('M-')]
    families = _families(calc)
    gas_required = 'gas' in families and not base._negative((calc.get('_design_inputs') or {}).get('gas'))
    roof_required = 'roof_rainwater' in families
    ventilation_required = 'ventilation_exhaust' in families
    fixture_traceable = model['fixture_blocks_detected'] > 0 or model['fixture_schedule_count'] > 0
    checks = {
        'approved_manifest_exact': expected > 0 and expected == len(issued),
        'exact_level_geometry': bool(levels) and not any(x.get('manifest_geometry_fallback') for x in levels),
        'fixture_and_symbol_traceability': fixture_traceable and symbol_count >= len(levels),
        'water_hydraulic_design': all(model.get(k) not in (None, '') for k in (
            'design_water_flow_lps', 'water_main_dn_mm', 'water_material',
            'water_inlet_pressure_bar', 'hazen_williams_c', 'water_route_length_m', 'water_head_loss_m')),
        'sanitary_vent_design': all(model.get(k) not in (None, '') for k in (
            'drainage_fixture_units', 'sanitary_main_dn_mm', 'sanitary_slope_pct',
            'sanitary_material', 'sanitary_outlet')),
        'gas_design': (not gas_required) or all(model.get(k) not in (None, '', False) for k in (
            'gas_load_kw', 'gas_flow_m3h', 'gas_pressure_mbar', 'gas_main_dn_mm', 'gas_meter_regulator_defined')),
        'heating_cooling_equipment_design': all(model.get(k) not in (None, '', False) for k in (
            'cooling_load_kw', 'heating_load_kw', 'equipment_schedule_resolved',
            'per_room_cooling_kw', 'per_room_heating_kw')),
        'ventilation_design': (not ventilation_required) or all(model.get(k) not in (None, '', False) for k in (
            'ventilation_airflow_m3h', 'ventilation_discharge_resolved', 'makeup_air_resolved')),
        'roof_drainage_design': (not roof_required) or all(model.get(k) not in (None, '', False) for k in (
            'roof_area_m2', 'rainfall_mm_h', 'roof_drain_count', 'roof_flow_lps', 'roof_drain_dn_mm')),
        'technical_documentation': schedule_count >= max(1, len(issued) * 3) and not base._technical_issue_gaps(doc, manifest, {}),
    }
    passed = sum(bool(x) for x in checks.values())
    return {
        'score_10': round(passed, 1), 'passed': passed, 'total': 10,
        'checks': checks, 'failed': [key for key, value in checks.items() if not value],
        'professional_review_required': True,
        'statutory_approval_claimed': False,
    }


def _boxes_intersect(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _entity_box(entity):
    try:
        extents = bbox.extents([entity], fast=True)
        if extents.has_data:
            return (
                float(extents.extmin.x), float(extents.extmin.y),
                float(extents.extmax.x), float(extents.extmax.y),
            )
    except Exception:
        pass
    point = v8._entity_anchor(entity)
    if point:
        return point[0], point[1], point[0], point[1]
    return None


def _issued_level_bounds(levels, calc):
    """Return only architecture envelopes actually used by approved sheets.

    Typical-floor sheets use one representative geometry; repeated copies and
    unrelated architecture plans must not remain in the issued mechanical DXF.
    """
    manifest = calc.get('_approved_drawing_manifest') or {}
    selected = []
    seen = set()
    roofs = [level for level in levels if v8._is_roof(level)]
    for sheet in manifest.get('sheets') or []:
        code = str(sheet.get('code') or '')
        if code == 'M-W-SPECIAL':
            continue
        if code == 'M-C-EQUIP':
            level = roofs[0] if roofs else None
        else:
            try:
                level = base._manifest_level(sheet, levels)
            except RuntimeError:
                level = None
        if not level:
            continue
        key = (str(level.get('level') or ''), tuple(level.get('title', {}).get('point') or ()))
        if key in seen:
            continue
        seen.add(key)
        selected.append(level)
    return [v8._level_bounds(level, [x['point'] for x in level.get('roof_drains', [])]) for level in selected]


def _prune_mechanical_deliverable(doc, levels, calc):
    """Strip raw architecture baggage from the authority issue file.

    The approved layouts remain intact. Modelspace keeps mechanical entities
    and only a faded architecture underlay inside the representative plan
    envelopes referenced by those layouts. Source title sheets, duplicate
    typical floors, remote details, images, leaders and unrelated blocks are
    removed, then unreferenced block definitions are purged.
    """
    msp = doc.modelspace()
    bounds = _issued_level_bounds(levels, calc)
    if not bounds:
        raise RuntimeError('Compact mechanical output blocked: approved sheet view bounds are unavailable.')

    forbidden_source_types = {
        'IMAGE', 'PDFUNDERLAY', 'DGNUNDERLAY', 'DWFUNDERLAY',
        'LEADER', 'MLEADER', 'TABLE', 'ACAD_PROXY_ENTITY',
    }
    max_w = max(box[2] - box[0] for box in bounds)
    max_h = max(box[3] - box[1] for box in bounds)
    before = len(msp)
    mechanical = architecture = removed = 0
    removed_by_type = Counter()

    for entity in list(msp):
        layer = str(getattr(entity.dxf, 'layer', '') or '')
        if layer.startswith('ENGITOOLS-M-'):
            mechanical += 1
            continue
        entity_type = entity.dxftype()
        box = _entity_box(entity)
        keep = bool(box and any(_boxes_intersect(box, allowed) for allowed in bounds))
        if box and ((box[2] - box[0]) > max_w * 5 or (box[3] - box[1]) > max_h * 5):
            keep = False
        if entity_type in forbidden_source_types or entity_type == 'DIMENSION':
            keep = False
        if keep:
            architecture += 1
            continue
        msp.delete_entity(entity)
        removed += 1
        removed_by_type[entity_type] += 1

    # Remove only demonstrably unused, substantial source blocks.  A blanket
    # block purge can invalidate custom DIMSTYLE arrow references in consultant
    # DXFs, so referenced INSERT/DIMSTYLE blocks and small CAD support blocks
    # are preserved deliberately.
    referenced_blocks = set()
    for layout in doc.layouts:
        for insert in layout.query('INSERT'):
            referenced_blocks.add(str(insert.dxf.name).lower())
        for dimension in layout.query('DIMENSION'):
            name = str(getattr(dimension.dxf, 'geometry', '') or '')
            if name:
                referenced_blocks.add(name.lower())
    for dimstyle in doc.dimstyles:
        for value in dimstyle.dxfattribs().values():
            if isinstance(value, str) and value in doc.blocks:
                referenced_blocks.add(value.lower())
    analyzer_blocks = {
        str(profile.get('source_name') or '').lower()
        for profile in ((calc.get('_plan_analysis') or {}).get('architectural_auto') or {}).get('level_profiles') or []
        if profile.get('source_type') == 'block'
    }
    removed_blocks = []
    for block in list(doc.blocks):
        name = str(block.name or '')
        low = name.lower()
        if low.startswith('*') or low in referenced_blocks:
            continue
        if low not in analyzer_blocks and len(block) < 50:
            continue
        try:
            doc.blocks.delete_block(name, safe=False)
            removed_blocks.append(name)
        except Exception:
            continue
    issued = [layout.name for layout in doc.layouts if layout.name.startswith('M-')]
    expected = [str(sheet.get('code') or '') for sheet in (calc.get('_approved_drawing_manifest') or {}).get('sheets') or []]
    report = {
        'status': 'PASS' if issued == expected and mechanical > 0 and architecture > 0 else 'FAIL',
        'raw_modelspace_entities': before,
        'retained_mechanical_entities': mechanical,
        'retained_architecture_underlay_entities': architecture,
        'removed_unneeded_entities': removed,
        'removed_by_type': dict(removed_by_type),
        'removed_unused_block_definitions': len(removed_blocks),
        'retained_plan_envelopes': len(bounds),
        'only_approved_mechanical_layouts': issued == expected,
        'architecture_source_files_packaged': 0,
        'issued_layouts': issued,
    }
    if report['status'] != 'PASS':
        raise RuntimeError('Compact mechanical output QA failed: ' + str(report))
    return report


def design_dxf_v10_4(src, dst, discipline, systems, revision, calc):
    if discipline == 'mechanical':
        inputs = dict(calc.get('_design_inputs') or {})
        inputs['water_inlet_pressure'] = water_inlet_pressure_basis(inputs.get('water_inlet_pressure'))
        if not inputs.get('water_source'):
            inputs['water_source'] = (
                'Rulebook automatic: municipal meter + storage tank + booster pump '
                'sized from calculated demand'
            )
        calc['_design_inputs'] = inputs
    meta = _base_design(src, dst, discipline, systems, revision, calc)
    if discipline != 'mechanical':
        return meta
    doc = ezdxf.readfile(dst)
    levels = v8.build_levels_v8(doc.modelspace())
    model = _technical_model(doc, levels, calc)
    symbol_count = _add_standard_symbols(doc, levels, model)
    schedule_count = _annotate_sheets(doc, model)
    report = _quality_report(doc, levels, calc, model, symbol_count, schedule_count)
    if report['score_10'] < 10.0:
        raise RuntimeError(
            f"Mechanical technical design QA failed ({report['score_10']}/10): "
            + ', '.join(report['failed'])
        )
    cleanup = _prune_mechanical_deliverable(doc, levels, calc)
    audit = doc.audit()
    if audit.errors:
        raise RuntimeError(f'Mechanical v10.4 DXF audit failed with {len(audit.errors)} error(s).')
    doc.saveas(dst)
    cleanup['output_bytes'] = dst.stat().st_size
    meta['technical_design'] = model
    meta['technical_quality'] = report
    meta['technical_symbol_blocks'] = symbol_count
    meta['technical_schedule_annotations'] = schedule_count
    meta['compact_output'] = cleanup
    meta['design_standard'] = f'Rulebook v{RULEBOOK_VERSION} short-answer evidence-gated mechanical technical design v10.7'
    return meta


engine.design_dxf = design_dxf_v10_4


@app.get('/v10-4-capabilities')
def capabilities():
    return {
        'ok': True, 'version': '1.0.7-technical-mechanical',
        'evidence_gated_score_10': True,
        'water_hydraulic_calculation': True, 'sanitary_fixture_unit_schedule': True,
        'gas_load_and_flow_schedule': True, 'room_load_distribution': True,
        'ventilation_airflow_gate': True, 'roof_rainfall_calculation': True,
        'standard_mechanical_symbol_blocks': True, 'per_sheet_technical_schedules': True,
        'rulebook_owned_defaults_not_customer_questions': True,
        'short_answer_rulebook_confirmation': True,
        'unknown_pressure_rulebook_fallback': DEFAULT_WATER_INLET_PRESSURE,
        'compact_mechanical_output': True,
        'raw_architecture_files_packaged': False,
        'construction_ready': False, 'professional_verification_required': True,
    }
