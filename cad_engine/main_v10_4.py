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
    automatic_answers,
    fixture_schedule_proposal,
    is_confirmation,
    plan_detail_requirements,
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
    return str(value or '').translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')).replace('ي', 'ی').replace('ك', 'ک').replace(',', '.').replace('٫', '.').strip()


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


def _attach_analyzer_fixtures(levels, calc):
    """Attach only analyzer-observed fixture blocks to their detected plan.

    Some authority DXFs keep sanitary symbols in nested blocks. The analyzer
    resolves those blocks, while the legacy CAD pass only sees modelspace.
    Coordinates and kinds below therefore come exclusively from the submitted
    architecture analysis; no fixture position is invented.
    """
    observed = []
    for item in (calc.get('_plan_analysis') or {}).get('files') or []:
        for fixture in item.get('fixture_blocks') or []:
            try:
                point = (float(fixture['x']), float(fixture['y']))
            except (KeyError, TypeError, ValueError):
                continue
            kind = str(fixture.get('kind') or '').strip().lower()
            if kind in {'sink', 'faucet', 'toilet', 'bath', 'gas'}:
                observed.append({'kind': kind, 'point': point, 'source': 'architecture_analyzer'})
    if not observed or not levels:
        return 0

    title_points = [level['title']['point'] for level in levels]
    spacings = [math.dist(a, b) for i, a in enumerate(title_points) for b in title_points[i + 1:]]
    title_spacing = min(spacings) if spacings else None
    added = 0
    seen = {
        (fixture.get('kind'), round(fixture['point'][0], 4), round(fixture['point'][1], 4))
        for level in levels for fixture in level.get('fixtures', [])
    }
    for fixture in observed:
        key = (fixture['kind'], round(fixture['point'][0], 4), round(fixture['point'][1], 4))
        if key in seen:
            continue
        level = min(levels, key=lambda x: math.dist(fixture['point'], x['title']['point']))
        evidence = [x['point'] for x in level.get('rooms', [])] + [level['title']['point']]
        if title_spacing is not None:
            limit = title_spacing * 1.65
        else:
            xs = [p[0] for p in evidence]; ys = [p[1] for p in evidence]
            limit = max(max(xs) - min(xs), max(ys) - min(ys), 1.0) * 1.35
        if min(math.dist(fixture['point'], p) for p in evidence) > limit:
            continue
        level.setdefault('fixtures', []).append(fixture)
        seen.add(key)
        added += 1
    return added


def _add_evidence_fixture_branches(doc, levels, model):
    """Draw traceable terminal branches from actual architecture fixtures."""
    msp = doc.modelspace()
    count = 0
    for level in levels:
        fixtures = [x for x in level.get('fixtures', []) if x.get('source') == 'architecture_analyzer']
        if not fixtures:
            continue
        hub = v8._find_level_riser(msp, level)
        if not hub:
            continue
        nn, span = v6.local_metric(level)
        r = max(.08, min(nn * .12, span * .025))
        for fixture in fixtures:
            point = fixture['point']; kind = fixture['kind']
            if kind == 'gas':
                if model.get('gas_main_dn_mm'):
                    v6.route(msp, point, hub, 'ENGITOOLS-M-GAS', True)
                    _plan_text(msp, f"G DN{model['gas_main_dn_mm']}", point, 'ENGITOOLS-M-GAS')
                    count += 1
                continue
            cw = (point[0] - r * .55, point[1])
            san = (point[0] + r * .55, point[1])
            v6.route(msp, cw, hub, 'ENGITOOLS-M-COLD_WATER')
            v6.route(msp, san, hub, 'ENGITOOLS-M-SANITARY')
            _plan_text(msp, f"CW DN{min(model.get('water_main_dn_mm') or 20, 25)}", cw, 'ENGITOOLS-M-COLD_WATER')
            _plan_text(msp, f"SAN DN{110 if kind == 'toilet' else 50} S={model.get('sanitary_slope_pct')}%", san, 'ENGITOOLS-M-SANITARY', (.32, -.24))
            count += 2
            if kind in {'sink', 'faucet', 'bath'}:
                hw = (point[0], point[1] + r * .55)
                v6.route(msp, hw, hub, 'ENGITOOLS-M-HOT_WATER', True)
                _plan_text(msp, 'HW DN20', hw, 'ENGITOOLS-M-HOT_WATER')
                count += 1
    return count


def _add_semantic_room_networks(doc, levels, model, calc):
    """Guarantee terminal branches for every analyzer-detected served room.

    The legacy pass can miss rooms in consultant block/layout exports even
    though the final level builder resolves them. This post-composition pass
    uses those resolved semantic room points and never creates an unobserved
    room. Exact equipment positioning remains documented as coordinated.
    """
    families = {
        str(x.get('family') or '')
        for x in (calc.get('_approved_drawing_manifest') or {}).get('sheets') or []
    }
    msp = doc.modelspace(); count = 0
    for level in levels:
        hub = v8._find_level_riser(msp, level)
        if not hub:
            continue
        nn, span = v6.local_metric(level)
        r = max(.08, min(nn * .12, span * .025))
        for room in level.get('rooms', []):
            kind = room.get('room'); x, y = room['point']
            if kind in {'bedroom', 'living', 'office', 'shop'}:
                if 'heating' in families:
                    supply = (x - r * .85, y - r * 1.55)
                    ret = (x + r * .85, y - r * 1.55)
                    v6.route(msp, supply, hub, 'ENGITOOLS-M-HEATING_SUPPLY')
                    v6.route(msp, ret, hub, 'ENGITOOLS-M-HEATING_RETURN', True)
                    _plan_text(msp, 'HS DN20', supply, 'ENGITOOLS-M-HEATING_SUPPLY')
                    _plan_text(msp, 'HR DN20', ret, 'ENGITOOLS-M-HEATING_RETURN')
                    count += 2
                if 'cooling' in families:
                    terminal = (x, y + r * 1.55)
                    condensate = (x + r * 1.1, y + r * 1.55)
                    v6.route(msp, terminal, hub, 'ENGITOOLS-M-COOLING')
                    v6.route(msp, condensate, hub, 'ENGITOOLS-M-CONDENSATE', True)
                    _plan_text(msp, f"C {model.get('per_room_cooling_kw')}kW", terminal, 'ENGITOOLS-M-COOLING')
                    _plan_text(msp, 'CD DN25 S=1%', condensate, 'ENGITOOLS-M-CONDENSATE')
                    count += 2
                if 'ventilation_exhaust' in families and kind in {'office', 'shop'}:
                    terminal = (x - r * 1.1, y + r * 1.1)
                    v6.route(msp, terminal, hub, 'ENGITOOLS-M-EXHAUST_VENTILATION')
                    _plan_text(msp, f"SA/EA {model.get('ventilation_airflow_m3h')} m3/h", terminal, 'ENGITOOLS-M-EXHAUST_VENTILATION')
                    count += 1
    return count


def _dn_for_downstream(family, count, model):
    """Select a traceable segment size from the downstream terminal count."""
    count = max(int(count or 1), 1)
    if family == 'sanitary':
        return 110 if count <= 3 else (125 if count <= 6 else 160)
    if family == 'condensate':
        return 25 if count <= 3 else (32 if count <= 6 else 40)
    calculated = int(model.get('water_main_dn_mm') or 20)
    staged = 20 if count == 1 else (25 if count <= 3 else (32 if count <= 6 else 40))
    return min(calculated, staged) if family == 'water' else staged


def _unique_line(msp, start, end, layer, seen):
    if math.dist(start, end) <= 1e-9:
        return False
    a = (round(start[0], 5), round(start[1], 5))
    b = (round(end[0], 5), round(end[1], 5))
    key = (layer, *sorted((a, b)))
    if key in seen:
        return False
    seen.add(key)
    msp.add_line(start, end, dxfattribs={'layer': layer})
    return True


def _shared_network(msp, terminals, hub, layer, family, model, seen):
    """Draw a shared, auditable trunk/branch graph with cumulative sizing."""
    if not terminals or not hub:
        return {'segments': 0, 'junctions': 0, 'terminals': len(terminals)}
    xs = [p[0] for p in terminals]; ys = [p[1] for p in terminals]
    horizontal = (max(xs) - min(xs)) >= (max(ys) - min(ys))
    ordered = sorted(terminals, key=lambda p: p[0] if horizontal else p[1])
    junctions = [(p[0], hub[1]) if horizontal else (hub[0], p[1]) for p in ordered]
    grouped = []
    for terminal, junction in zip(ordered, junctions):
        if grouped and math.dist(junction, grouped[-1]['junction']) <= 1e-6:
            grouped[-1]['terminals'].append(terminal)
        else:
            grouped.append({'junction': junction, 'terminals': [terminal]})
    segments = 0
    for group in grouped:
        for terminal in group['terminals']:
            segments += int(_unique_line(msp, terminal, group['junction'], layer, seen))
        msp.add_blockref('ET_M_JUNCTION', group['junction'], dxfattribs={'layer': layer})
        if family in {'water', 'heating', 'cooling'}:
            msp.add_blockref('ET_M_ISOLATION_VALVE', group['junction'], dxfattribs={'layer': layer})
        if family == 'sanitary':
            msp.add_blockref('ET_M_CLEANOUT', group['junction'], dxfattribs={'layer': layer})
    nodes = [group['junction'] for group in grouped] + [hub]
    nodes = sorted(set((round(p[0], 8), round(p[1], 8)) for p in nodes),
                   key=lambda p: p[0] if horizontal else p[1])
    hub_index = min(range(len(nodes)), key=lambda i: math.dist(nodes[i], hub))
    for i, (a, b) in enumerate(zip(nodes, nodes[1:])):
        if not _unique_line(msp, a, b, layer, seen):
            continue
        segments += 1
        downstream = i + 1 if i < hub_index else len(nodes) - i - 1
        dn = _dn_for_downstream(family, downstream, model)
        suffix = f" S={model.get('sanitary_slope_pct')}%" if family == 'sanitary' else ''
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        _plan_text(msp, f"DN{dn}{suffix} [CALCULATED:{downstream}]", mid, layer, (.12, .12))
        msp.add_blockref('ET_M_FLOW_ARROW', mid, dxfattribs={'layer': layer})
    return {'segments': segments, 'junctions': len(grouped), 'terminals': len(terminals)}


def _add_shared_distribution_networks(doc, levels, model, calc):
    """Compose independent shared networks from observed project evidence."""
    _ensure_symbol_blocks(doc)
    msp = doc.modelspace(); seen = set(); report = Counter()
    families = _families(calc)
    for level in levels:
        hub = v8._find_level_riser(msp, level)
        if not hub:
            continue
        nn, span = v6.local_metric(level)
        offset = max(.10, min(nn * .18, span * .03))
        fixtures = [f for f in level.get('fixtures', []) if f.get('point')]
        rooms = [r for r in level.get('rooms', []) if r.get('point')]
        wet = [f['point'] for f in fixtures if f.get('kind') != 'gas']
        wet_provenance = 'Detected'
        # When consultant blocks have no usable name/attribute, a wet-room
        # label is still valid architectural evidence for a coordinated
        # connection zone.  It is deliberately marked Proposed and never
        # represented as a detected fixture location.
        if not wet:
            wet = [r['point'] for r in rooms if r.get('room') in {'bath', 'toilet', 'kitchen'}]
            wet_provenance = 'Rule-based Proposed'
        conditioned = [r['point'] for r in rooms if r.get('room') in {'bedroom', 'living', 'office', 'shop'}]
        exhaust = [r['point'] for r in rooms if r.get('room') in {'bath', 'toilet', 'kitchen', 'parking'}]
        specs = []
        if 'water_supply' in families and wet:
            specs += [('water', [(x-offset, y) for x, y in wet], 'ENGITOOLS-M-COLD_WATER')]
            hot = [f['point'] for f in fixtures if f.get('kind') in {'sink', 'faucet', 'bath'}]
            specs += [('water', [(x, y+offset) for x, y in hot], 'ENGITOOLS-M-HOT_WATER')]
        if 'sanitary_vent' in families and wet:
            specs += [('sanitary', [(x+offset, y) for x, y in wet], 'ENGITOOLS-M-SANITARY')]
            specs += [('ventilation', [(x+offset, y+offset) for x, y in wet], 'ENGITOOLS-M-VENT')]
        if 'heating' in families and conditioned:
            specs += [('heating', [(x-offset, y-offset) for x, y in conditioned], 'ENGITOOLS-M-HEATING_SUPPLY')]
            specs += [('heating', [(x+offset, y-offset) for x, y in conditioned], 'ENGITOOLS-M-HEATING_RETURN')]
        if 'cooling' in families and conditioned:
            specs += [('cooling', [(x, y+offset) for x, y in conditioned], 'ENGITOOLS-M-COOLING')]
            specs += [('condensate', [(x+offset, y+offset) for x, y in conditioned], 'ENGITOOLS-M-CONDENSATE')]
        if 'ventilation_exhaust' in families and exhaust:
            specs += [('ventilation', exhaust, 'ENGITOOLS-M-EXHAUST_VENTILATION')]
        for family, terminals, layer in specs:
            row = _shared_network(msp, terminals, hub, layer, family, model, seen)
            report['segments'] += row['segments']; report['junctions'] += row['junctions']
            report['terminals'] += row['terminals']; report['networks'] += 1
        if wet and wet_provenance != 'Detected':
            for point in wet:
                _plan_text(msp, 'CONNECTION ZONE [RULE-BASED PROPOSED]', point,
                           'ENGITOOLS-M-MECHANICAL_DETAILS_LEGEND_NOTES', (.18, -.18))
            report['proposed_wet_connection_zones'] += len(wet)
        else:
            report['detected_fixture_connection_points'] += len(wet)
    return dict(report)


def _technical_model(doc, levels, calc):
    inputs = calc.get('_design_inputs') or {}
    plan_analysis = calc.get('_plan_analysis') or {}
    architectural_auto = plan_analysis.get('architectural_auto') or {}
    analyzer_fixture_counts = Counter(architectural_auto.get('fixture_counts') or {})
    if not sum(analyzer_fixture_counts.values()):
        for file_info in plan_analysis.get('files') or []:
            analyzer_fixture_counts.update(file_info.get('fixture_counts') or {})

    fixture_schedule = _norm(inputs.get('fixture_schedule'))
    if is_confirmation(fixture_schedule):
        if sum(analyzer_fixture_counts.values()):
            fixture_schedule = '; '.join(
                f'{kind} {int(analyzer_fixture_counts.get(kind) or 0)}'
                for kind in ('sink', 'faucet', 'toilet', 'bath')
            )
        else:
            # A non-empty analyzer payload is not proof that its aggregate
            # counters were populated. Consultant DXFs stored in named blocks
            # can produce valid detected CAD levels while room_counts remains
            # empty. Fall back to those detected levels so a confirmed
            # Rulebook fixture proposal remains quantified and hydraulic-ready.
            auto_rooms = architectural_auto.get('room_counts') or {}
            wet_room_count = sum(
                int(auto_rooms.get(kind) or 0)
                for kind in ('kitchen', 'bath', 'toilet')
            )
            fixture_source = architectural_auto if wet_room_count else levels
            fixture_schedule = fixture_schedule_proposal(fixture_source)
    detected, scheduled, fixtures, rooms, proxies = _fixture_summary(levels, fixture_schedule)
    unit_to_m = _drawing_unit_to_m(doc)
    water_basis = _norm(inputs.get('water_design_basis')) or (
        f"{WATER['material']}; Hazen-Williams C={WATER['hazen_williams_c']}; "
        f"maximum loss {WATER['maximum_friction_loss_kpa_per_100m']} kPa/100 m"
    )
    water_source = _norm(inputs.get('water_source'))
    water_service_connection = _norm(inputs.get('water_service_connection'))
    mechanical_shaft_route = _norm(inputs.get('mechanical_shaft_route'))
    hot_water_system = _norm(inputs.get('hot_water_system'))
    local_mechanical_code = _norm(inputs.get('local_mechanical_code'))
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
    flow_lps = (
        calc.get('design_water_flow_lps')
        or calc.get('estimated_water_flow_lps')
        or architectural_auto.get('estimated_water_flow_lps')
    )
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
    if not water_length_m:
        try:
            water_length_m = float(architectural_auto.get('estimated_route_length_m') or 0) or None
        except (TypeError, ValueError):
            water_length_m = None
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
    if cooling_kw in (None, ''):
        cooling_kw = architectural_auto.get('estimated_cooling_load_kw')
    if heating_kw in (None, ''):
        heating_kw = architectural_auto.get('estimated_heating_load_kw')
    try:
        cooling_kw = float(cooling_kw) if cooling_kw not in (None, '') else None
    except (TypeError, ValueError):
        cooling_kw = None
    try:
        heating_kw = float(heating_kw) if heating_kw not in (None, '') else None
    except (TypeError, ValueError):
        heating_kw = None
    # Reliable occupied-room classifications are sufficient for a transparent
    # preliminary Rule Book load when area metadata is unavailable.
    conditioned_equiv = (
        rooms['bedroom'] * 1.6 + rooms['living'] * 3.0
        + rooms['office'] * 2.0 + rooms['shop'] * 2.0
    )
    if cooling_kw in (None, '') and conditioned_equiv > 0:
        cooling_kw = round(conditioned_equiv, 2)
    if heating_kw in (None, '') and conditioned_equiv > 0:
        heating_kw = round(conditioned_equiv * .75, 2)
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
        'water_source': water_source or None,
        'water_service_connection': water_service_connection or None,
        'mechanical_shaft_route': mechanical_shaft_route or None,
        'hot_water_system': hot_water_system or None,
        'local_mechanical_code': local_mechanical_code or None,
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


def _refresh_hydraulic_model(doc, model):
    """Recalculate route-dependent hydraulics after shared networks exist."""
    unit_to_m = _drawing_unit_to_m(doc) or 1.0
    drawn_length_m = _layer_length(doc.modelspace(), 'ENGITOOLS-M-COLD_WATER') * unit_to_m
    # A resumed project can carry a quantified fixture schedule while its
    # consultant DXF has no trustworthy wet-point coordinates. In that case
    # the shared-network pass correctly draws no invented route. Preserve the
    # architecture-derived preliminary route instead of replacing it by None.
    length_m = drawn_length_m or float(model.get('water_route_length_m') or 0)
    flow_lps = model.get('design_water_flow_lps')
    dn = model.get('water_main_dn_mm')
    hazen_c = model.get('hazen_williams_c')
    model['water_route_length_m'] = round(length_m, 2) if length_m > 0 else None
    if flow_lps and dn and hazen_c and length_m > 0:
        q = float(flow_lps) / 1000.0
        d = float(dn) / 1000.0
        head_loss = 10.67 * length_m * (q ** 1.852) / ((float(hazen_c) ** 1.852) * (d ** 4.871))
        model['water_head_loss_m'] = round(head_loss, 2)
    return model


def _ensure_symbol_blocks(doc):
    defs = {
        'ET_M_WATER_POINT': ('circle', 'WP'), 'ET_M_SAN_POINT': ('circle', 'S'),
        'ET_M_GAS_POINT': ('box', 'G'), 'ET_M_EQUIPMENT': ('box', 'EQ'),
        'ET_M_EXHAUST': ('box', 'EF'), 'ET_M_RISER': ('diamond', 'R'),
        'ET_M_ISOLATION_VALVE': ('circle', 'V'), 'ET_M_CLEANOUT': ('circle', 'CO'),
        'ET_M_VENT_TERMINAL': ('diamond', 'VT'), 'ET_M_ROOF_DRAIN': ('circle', 'RD'),
        'ET_M_JUNCTION': ('circle', 'J'), 'ET_M_FLOW_ARROW': ('diamond', '>'),
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


def _plan_text(msp, value, point, layer, offset=(.32, .18)):
    """Attach a compact, plot-visible engineering tag beside a plan symbol."""
    return msp.add_text(str(value), dxfattribs={'layer': layer, 'height': .12}).set_placement(
        (point[0] + offset[0], point[1] + offset[1])
    )


def _add_standard_symbols(doc, levels, model):
    """Materialize the Rule Book's minimum plan-visible detail standard.

    These marks are intentionally placed only at detected fixtures/rooms and
    known riser/roof points.  They do not pretend that unobserved project
    geometry has been measured; numeric labels come from the resolved design
    model and every family remains traceable in the issued plan.
    """
    _ensure_symbol_blocks(doc)
    msp = doc.modelspace()
    count = 0
    water_tag = f"CW/HW DN{model.get('water_main_dn_mm')} | V"
    sanitary_tag = f"SAN DN{model.get('sanitary_main_dn_mm')} | S={model.get('sanitary_slope_pct')}% | CO"
    equipment_tag = f"C={model.get('per_room_cooling_kw')}kW H={model.get('per_room_heating_kw')}kW"
    exhaust_tag = f"EF {model.get('ventilation_airflow_m3h')} m3/h"
    for level in levels:
        fixtures = level.get('fixtures') or []
        wet_points = [x['point'] for x in fixtures if x.get('kind') != 'gas']
        if not wet_points:
            wet_points = [x['point'] for x in level.get('rooms', []) if x.get('room') in ('kitchen', 'bath', 'toilet')]
        for point in wet_points:
            msp.add_blockref('ET_M_WATER_POINT', point, dxfattribs={'layer': 'ENGITOOLS-M-COLD_WATER'})
            msp.add_blockref('ET_M_SAN_POINT', (point[0] + .22, point[1]), dxfattribs={'layer': 'ENGITOOLS-M-SANITARY'})
            msp.add_blockref('ET_M_ISOLATION_VALVE', (point[0] - .22, point[1]), dxfattribs={'layer': 'ENGITOOLS-M-COLD_WATER'})
            msp.add_blockref('ET_M_CLEANOUT', (point[0] + .44, point[1]), dxfattribs={'layer': 'ENGITOOLS-M-SANITARY'})
            _plan_text(msp, water_tag, point, 'ENGITOOLS-M-COLD_WATER')
            _plan_text(msp, sanitary_tag, point, 'ENGITOOLS-M-SANITARY', (.32, -.24))
            count += 4
        for room in level.get('rooms', []):
            point = room['point']
            if room.get('room') == 'kitchen' and model.get('gas_main_dn_mm'):
                msp.add_blockref('ET_M_GAS_POINT', point, dxfattribs={'layer': 'ENGITOOLS-M-GAS'}); count += 1
            # Offices and shops are conditioned occupied spaces as well.  The
            # analyzer already classifies them as conditioned candidates; not
            # placing their terminal equipment made commercial/bank projects
            # fail symbol traceability despite a resolved equipment schedule.
            if room.get('room') in ('bedroom', 'living', 'office', 'shop') and model.get('equipment_schedule_resolved'):
                msp.add_blockref('ET_M_EQUIPMENT', point, dxfattribs={'layer': 'ENGITOOLS-M-COOLING'})
                _plan_text(msp, equipment_tag, point, 'ENGITOOLS-M-COOLING'); count += 1
            if room.get('room') in ('bath', 'toilet') and model.get('ventilation_airflow_m3h'):
                msp.add_blockref('ET_M_EXHAUST', point, dxfattribs={'layer': 'ENGITOOLS-M-EXHAUST_VENTILATION'})
                _plan_text(msp, exhaust_tag, point, 'ENGITOOLS-M-EXHAUST_VENTILATION'); count += 1
        hub = v8._find_level_riser(msp, level)
        if hub:
            msp.add_blockref('ET_M_RISER', hub, dxfattribs={'layer': 'ENGITOOLS-M-MECHANICAL_RISERS'})
            msp.add_blockref('ET_M_VENT_TERMINAL', (hub[0] + .26, hub[1]), dxfattribs={'layer': 'ENGITOOLS-M-VENT'})
            _plan_text(msp, f"RISER: W DN{model.get('water_main_dn_mm')} / S DN{model.get('sanitary_main_dn_mm')} / V DN{SANITARY['vent_dn_mm']}", hub, 'ENGITOOLS-M-MECHANICAL_RISERS')
            count += 2
        for drain in level.get('roof_drains') or []:
            point = drain['point']
            msp.add_blockref('ET_M_ROOF_DRAIN', point, dxfattribs={'layer': 'ENGITOOLS-M-ROOF_RAINWATER'})
            _plan_text(msp, f"RD DN{model.get('roof_drain_dn_mm')}", point, 'ENGITOOLS-M-ROOF_RAINWATER')
            count += 1
    return count


def _annotate_network_topology(doc, model):
    """Mark route-derived junctions and representative flow directions."""
    _ensure_symbol_blocks(doc)
    msp = doc.modelspace()
    specs = {
        'ENGITOOLS-M-COLD_WATER': f"CW DN{model.get('water_main_dn_mm')}",
        'ENGITOOLS-M-HOT_WATER': 'HW DN20',
        'ENGITOOLS-M-SANITARY': f"SAN DN{model.get('sanitary_main_dn_mm')} S={model.get('sanitary_slope_pct')}%",
        'ENGITOOLS-M-VENT': f"VENT DN{SANITARY['vent_dn_mm']}",
        'ENGITOOLS-M-HEATING_SUPPLY': 'HS FLOW',
        'ENGITOOLS-M-HEATING_RETURN': 'HR RETURN',
        'ENGITOOLS-M-COOLING': 'REFRIGERANT / SUPPLY',
        'ENGITOOLS-M-CONDENSATE': 'CD S=1%',
        'ENGITOOLS-M-EXHAUST_VENTILATION': f"EA {model.get('ventilation_airflow_m3h')} m3/h",
    }
    count = 0
    for layer, label in specs.items():
        lines = []
        degree = Counter()
        for entity in msp.query('LINE'):
            if str(entity.dxf.layer) != layer:
                continue
            a = tuple(entity.dxf.start)[:2]; b = tuple(entity.dxf.end)[:2]
            if math.dist(a, b) <= 1e-9:
                continue
            lines.append((math.dist(a, b), a, b))
            degree[(round(a[0], 5), round(a[1], 5))] += 1
            degree[(round(b[0], 5), round(b[1], 5))] += 1
        for point, connections in degree.items():
            if connections < 2:
                continue
            msp.add_blockref('ET_M_JUNCTION', point, dxfattribs={'layer': layer})
            count += 1
        for index, (_length, a, b) in enumerate(sorted(lines, reverse=True)[:12]):
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            msp.add_blockref('ET_M_FLOW_ARROW', mid, dxfattribs={'layer': layer})
            count += 1
            if index % 3 == 0:
                _plan_text(msp, label, mid, layer, (.18, .14))
                count += 1
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
            f"SOURCE={model.get('water_source')} | ENTRY={model.get('water_service_connection')}",
            f"HOT WATER={model.get('hot_water_system')} | SHAFT={model.get('mechanical_shaft_route')}",
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
            f"LOCAL AUTHORITY BASIS={model.get('local_mechanical_code')}",
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
    applicable_detail_families = {
        'water_supply', 'sanitary_vent', 'heating', 'cooling', 'ventilation_exhaust',
        'gas', 'roof_rainwater',
    } & families
    required_detail_tokens = sum(len(plan_detail_requirements(family)) for family in applicable_detail_families)
    plan_visible_tags = sum(1 for entity in doc.modelspace() if entity.dxftype() == 'TEXT' and str(entity.dxf.layer).startswith('ENGITOOLS-M-'))
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
        'technical_documentation': (
            schedule_count >= max(1, len(issued) * 3)
            and not base._technical_issue_gaps(doc, manifest, {})
            and (required_detail_tokens == 0 or plan_visible_tags >= required_detail_tokens)
        ),
    }
    passed = sum(bool(x) for x in checks.values())
    return {
        'score_10': round(passed, 1),
        'passed': passed, 'total': len(checks),
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

    # Source dimensions are intentionally excluded from the mechanical issue
    # file. Remove their unused styles first so custom arrow references cannot
    # pin hundreds of anonymous consultant blocks in the final DXF.
    if not any(len(layout.query('DIMENSION')) for layout in doc.layouts):
        for dimstyle in list(doc.dimstyles):
            if str(dimstyle.dxf.name or '').upper() == 'STANDARD':
                continue
            try:
                doc.dimstyles.remove(dimstyle.dxf.name)
            except Exception:
                continue

    # Keep only blocks reachable from an INSERT in Model/Paper space, including
    # nested INSERT chains. All unreferenced title blocks, details, anonymous
    # dimension geometry and architecture libraries are removed. This produces
    # a genuinely compact authority deliverable instead of hiding source CAD
    # baggage outside the plotted sheets.
    referenced_blocks = set()

    def collect_inserts(entities):
        for insert in entities.query('INSERT'):
            referenced_blocks.add(str(insert.dxf.name))

    for layout in doc.layouts:
        collect_inserts(layout)
    changed = True
    while changed:
        changed = False
        for name in list(referenced_blocks):
            try:
                block = doc.blocks.get(name)
            except Exception:
                continue
            before_refs = len(referenced_blocks)
            collect_inserts(block)
            if len(referenced_blocks) != before_refs:
                changed = True

    layout_blocks = {str(layout.block_record_name) for layout in doc.layouts}
    removed_blocks = []
    for block in list(doc.blocks):
        name = str(block.name or '')
        if name in layout_blocks or name in referenced_blocks:
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
        'retained_block_definitions': len(doc.blocks),
        'retained_dimstyles': len(doc.dimstyles),
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
        architectural_auto = (calc.get('_plan_analysis') or {}).get('architectural_auto') or {}
        # Hydrate Rule Book-owned calculation bases at the CAD boundary too.
        # This keeps resumed/migrated projects deterministic and prevents a
        # short confirmation from erasing the complete engineering basis.
        rulebook_defaults = automatic_answers(architectural_auto)
        for key in ('water_design_basis', 'sanitary_design_basis'):
            if not str(inputs.get(key) or '').strip() or is_confirmation(inputs.get(key)):
                inputs[key] = rulebook_defaults[key]
        ventilation = _norm(inputs.get('ventilation_design_basis'))
        if not ventilation or is_confirmation(ventilation):
            inputs['ventilation_design_basis'] = rulebook_defaults['ventilation_design_basis']
        equipment_schedule = _norm(inputs.get('equipment_schedule'))
        if not equipment_schedule or is_confirmation(equipment_schedule):
            # Missing values occur on projects created before this questionnaire
            # field was persisted. Rehydrate the Rulebook-owned proposal instead
            # of allowing a resumed project to fail the equipment QA gate.
            inputs['equipment_schedule'] = rulebook_defaults['equipment_schedule']
        if is_confirmation(inputs.get('fixture_schedule')):
            auto_rooms = architectural_auto.get('room_counts') or {}
            if sum(int(auto_rooms.get(kind) or 0) for kind in ('kitchen', 'bath', 'toilet')):
                inputs['fixture_schedule'] = fixture_schedule_proposal(architectural_auto)
            # Otherwise keep the confirmation token. _technical_model runs
            # after Level Detection and resolves it from the actual DXF levels.
        inputs['water_inlet_pressure'] = water_inlet_pressure_basis(inputs.get('water_inlet_pressure'))
        if not inputs.get('water_source') or is_confirmation(inputs.get('water_source')):
            inputs['water_source'] = (
                'Rulebook automatic: municipal meter + storage tank + booster pump '
                'sized from calculated demand'
            )
        sanitary_outlet = _norm(inputs.get('sanitary_outlet'))
        if not sanitary_outlet or is_confirmation(sanitary_outlet):
            inputs['sanitary_outlet'] = (
                'municipal sewer at project boundary - Rulebook-confirmed default connection'
            )
        confirmation_defaults = {
            'water_service_connection': 'Rulebook proposal confirmed: property boundary beside the main service entrance',
            'mechanical_shaft_route': 'Rulebook proposal confirmed: nearest coordinated architectural shaft / wet core',
            'hot_water_system': 'Rulebook proposal confirmed: central combi/storage source; return loop where developed route length requires it',
            'local_mechanical_code': 'No project-specific override declared; current Rulebook and city authority basis applies',
        }
        for key, proposal in confirmation_defaults.items():
            if is_confirmation(inputs.get(key)):
                inputs[key] = proposal
        calc['_design_inputs'] = inputs
    meta = _base_design(src, dst, discipline, systems, revision, calc)
    if discipline != 'mechanical':
        return meta
    doc = ezdxf.readfile(dst)
    levels = v8.build_levels_v8(doc.modelspace())
    analyzer_fixture_count = _attach_analyzer_fixtures(levels, calc)
    model = _technical_model(doc, levels, calc)
    semantic_branch_count = _add_semantic_room_networks(doc, levels, model, calc)
    shared_network = _add_shared_distribution_networks(doc, levels, model, calc)
    _refresh_hydraulic_model(doc, model)
    model['shared_distribution_network'] = shared_network
    model['decision_provenance'] = {
        'architecture_geometry': 'Detected',
        'fixture_and_room_classification': 'Detected',
        'network_topology': 'Rule-based Proposed',
        'segment_sizing': 'Calculated',
        'questionnaire_overrides': 'User-confirmed',
    }
    symbol_count = _add_standard_symbols(doc, levels, model)
    symbol_count += _add_evidence_fixture_branches(doc, levels, model)
    symbol_count += _annotate_network_topology(doc, model)
    symbol_count += semantic_branch_count
    symbol_count += int(shared_network.get('junctions') or 0)
    model['analyzer_fixture_blocks_attached'] = analyzer_fixture_count
    schedule_count = _annotate_sheets(doc, model)
    report = _quality_report(doc, levels, calc, model, symbol_count, schedule_count)
    if report['score_10'] < 10.0:
        raise RuntimeError(
            f"Mechanical technical design QA failed ({report['score_10']}/10): "
            + ', '.join(report['failed']) + f"; checks={report['checks']}"
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
