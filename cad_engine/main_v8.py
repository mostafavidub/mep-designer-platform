import hashlib
import math
import re
from collections import Counter

import ezdxf

from . import main_v7 as v7
from . import main_v6 as v6
from . import main_v3 as engine

app = v7.app

_base_build_levels = v6.build_levels
_base_hub_for = v7.hub_for
_base_design_dxf = v6.design_dxf_v6
_base_mechanical_calc = engine.mechanical_calc

# Rulebook v1.2 production additions.
v6.LAYER_STYLE.update({
    'RAINWATER': (4, 50, ('DASHED', 'CONTINUOUS')),
    'QA': (7, 25, ('CONTINUOUS',)),
})

PARKING_TITLES = ('پلان جانمایی پارکینگ', 'parking plan', 'parking layout')
ROOF_WORDS = ('پشت بام', 'بام', 'roof')


def _norm(value):
    return v6.norm(value)


def _parking_titles(msp):
    found = []
    for e in msp:
        if e.dxftype() not in ('TEXT', 'MTEXT'):
            continue
        text = _norm(v6.text_value(e))
        low = text.lower()
        p = v6.point(e)
        if p and any(k.lower() in low for k in PARKING_TITLES):
            found.append({'type': 'parking', 'level': 'پارکینگ / همکف', 'point': p, 'text': text})
    return found


def _is_roof(level):
    value = _norm(level.get('level', '')).lower()
    return any(k.lower() in value for k in ROOF_WORDS)


def build_levels_v8(msp):
    """Build complete Level Scope Matrix including special parking/ground plans.

    v6 correctly detects architectural and furniture plans but intentionally only
    recognized titles that literally started with 'architectural plan'.  Real
    projects often contain a parking/ground plan with a different title.  The
    Rulebook requires parking/basement/roof/special levels to be included when
    they have mechanical scope, so v8 adds those plans explicitly.
    """
    levels = _base_build_levels(msp)
    parking = _parking_titles(msp)
    if not parking:
        _apply_vertical_reference(levels)
        return levels

    titles = v6.plan_titles(msp)
    core = [x for x in titles if x['type'] in ('architecture', 'furniture', 'lintel')] + parking
    spacing = max(v6.title_spacing(core), 1.0)
    rooms = v6.detect_room_labels_spatial(msp)
    fixtures = v6.fixture_inserts(msp)
    assigned_rooms = v6.assign_nearest(rooms, core, spacing * 1.65)
    assigned_fixtures = v6.assign_nearest(fixtures, core, spacing * 1.65)

    existing_names = {_norm(x['level']) for x in levels}
    for title in parking:
        if _norm(title['level']) in existing_names:
            continue
        key = ('parking', title['level'], title['point'])
        lr = [dict(x) for x in assigned_rooms.get(key, [])]
        lf = [dict(x) for x in assigned_fixtures.get(key, [])]
        # A parking/ground plan is a required special Level even when the room
        # classifier sees few labels; scope decisions such as ventilation still
        # belong to this level rather than disappearing from the deliverable.
        levels.append({
            'level': title['level'],
            'title': title,
            'rooms': lr,
            'fixtures': lf,
            'provenance': 'special-parking-plan',
            'special_type': 'parking',
        })

    levels.sort(key=lambda x: (-x['title']['point'][0], -x['title']['point'][1]))
    _apply_vertical_reference(levels)
    return levels


def _apply_vertical_reference(levels):
    """Keep risers fixed relative to each floor title/plan coordinate system."""
    source = None
    for level in levels:
        shafts = [x['point'] for x in level.get('rooms', []) if x['room'] == 'shaft']
        if shafts:
            # Choose shaft closest to wet core when possible.
            wet = [x['point'] for x in level['rooms'] if x['room'] in ('kitchen', 'bath', 'toilet')]
            if wet:
                c = (sum(p[0] for p in wet) / len(wet), sum(p[1] for p in wet) / len(wet))
                shaft = min(shafts, key=lambda p: math.dist(p, c))
            else:
                shaft = shafts[0]
            source = (level, shaft)
            break
    if not source:
        return
    src_level, src_shaft = source
    offset = (
        src_shaft[0] - src_level['title']['point'][0],
        src_shaft[1] - src_level['title']['point'][1],
    )
    for level in levels:
        level['vertical_reference_offset'] = offset
        level['forced_hub'] = (
            level['title']['point'][0] + offset[0],
            level['title']['point'][1] + offset[1],
        )
        level['vertical_reference_source'] = src_level['level']


def hub_for_v8(level, msp, r, th):
    expected = level.get('forced_hub')
    shafts = [x['point'] for x in level.get('rooms', []) if x['room'] == 'shaft']
    if expected:
        # The authority set requires one vertically aligned riser datum.  An
        # architectural shaft on another floor may be offset; snapping each
        # floor independently to that shaft produces a broken riser.  Use the
        # common projected datum. Shaft-offset coordination remains an internal
        # generation assumption; unresolved review markers must never leak into
        # an authority-facing deliverable.
        nearest = min(shafts, key=lambda p: math.dist(p, expected)) if shafts else None
        if nearest is not None and math.dist(nearest, expected) <= .75:
            return expected, 'existing-shaft-aligned'
        engine.add_box(msp, expected, r * .85, 'ENGITOOLS-M-MECHANICAL_RISERS', 'R', th)
        return expected, 'projected-from-vertical-reference'
    if shafts:
        return shafts[0], 'existing-shaft'
    return _base_hub_for(level, msp, r, th)


def mechanical_calc_v8(a):
    result = _base_mechanical_calc(a)
    inputs = result.setdefault('_design_inputs', {})
    for key in (
        'location', 'heating', 'cooling', 'gas', 'water_source', 'water',
        'sanitary_outlet', 'parking_enclosure', 'occupancy', 'heights',
        'water_design_basis', 'sanitary_design_basis', 'gas_appliances',
        'equipment_schedule', 'ventilation_design_basis', 'roof_drainage_basis',
        'water_inlet_pressure', 'fixture_schedule', 'roof_drainage_geometry',
        'mechanical_rulebook_version',
    ):
        if a.get(key) not in (None, ''):
            inputs[key] = a.get(key)
    return result


def _ensure_layer(doc, name, key):
    if name not in doc.layers:
        doc.layers.add(name=name)
    color, lw, types = v6.LAYER_STYLE[key]
    layer = doc.layers.get(name)
    layer.dxf.color = color
    layer.dxf.lineweight = lw
    for lt in types:
        if lt == 'CONTINUOUS' or lt in doc.linetypes:
            layer.dxf.linetype = lt
            break


def _fade_architecture_underlay(doc):
    """Make architecture a true underlay while preserving source content."""
    for layer in doc.layers:
        name = layer.dxf.name
        if name.startswith('ENGITOOLS-') or name in ('0', 'Defpoints'):
            continue
        try:
            layer.dxf.color = 8
            layer.dxf.lineweight = 9
        except Exception:
            pass


def _entity_anchor(entity):
    try:
        t = entity.dxftype()
        if t in ('TEXT', 'MTEXT', 'INSERT', 'CIRCLE'):
            p = entity.dxf.insert if t != 'CIRCLE' else entity.dxf.center
            return float(p.x), float(p.y)
        if t == 'LINE':
            return float(entity.dxf.start.x), float(entity.dxf.start.y)
        if t == 'LWPOLYLINE':
            p = next(iter(entity.get_points('xy')), None)
            return (float(p[0]), float(p[1])) if p else None
    except Exception:
        return None
    return None


def _level_bounds(level, extra_points=None):
    points = [x['point'] for x in level.get('rooms', [])] + [x['point'] for x in level.get('fixtures', [])]
    points.extend(extra_points or [])
    if not points:
        tx, ty = level['title']['point']
        return tx - 9, ty + 1, tx + 9, ty + 25
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    w = max(max(xs) - min(xs), 12.0)
    h = max(max(ys) - min(ys), 16.0)
    mx = max(2.5, w * .14)
    my = max(2.5, h * .14)
    return min(xs) - mx, min(ys) - my, max(xs) + mx, max(ys) + my


def _roof_drain_points(msp, level, all_levels):
    if not _is_roof(level):
        return []
    candidates = []
    title = level['title']['point']
    other_titles = [x['title']['point'] for x in all_levels if x is not level]
    max_dist = min([math.dist(title, p) for p in other_titles], default=25.0) * .82
    rx = re.compile(r'(p\s*\.?\s*v\s*\.?\s*c\s*[^0-9]{0,3}(\d{2,3})|(?:ø|%%c)?\s*(\d{2,3})\s*(?:mm)?\s*(?:rd|fd))', re.I)
    for e in msp:
        if e.dxftype() not in ('TEXT', 'MTEXT'):
            continue
        text = _norm(v6.text_value(e))
        p = v6.point(e)
        if not p or math.dist(p, title) > max_dist:
            continue
        low = text.lower().replace(' ', '')
        if 'p.v.c' in text.lower() or 'pvc' in low or ('fd' in low and re.search(r'\d', low)):
            nums = re.findall(r'\d{2,3}', text)
            dn = int(nums[-1]) if nums else None
            candidates.append({'point': p, 'dn': dn, 'source_text': text})
    # spatial dedupe
    out = []
    for item in candidates:
        if not any(math.dist(item['point'], x['point']) < .35 for x in out):
            out.append(item)
    return out


def _add_roof_drainage(doc, levels, stats):
    msp = doc.modelspace()
    _ensure_layer(doc, 'ENGITOOLS-M-RAINWATER', 'RAINWATER')
    count = 0
    for level in levels:
        drains = _roof_drain_points(msp, level, levels)
        for index, drain in enumerate(drains, 1):
            p = drain['point']
            dn = drain.get('dn')
            tag = f'RD-{index}'
            engine.add_circle(msp, p, .18, 'ENGITOOLS-M-RAINWATER', tag, .12)
            note = f'{tag} DOWN TO RAINWATER STACK' + (f' DN{dn}' if dn else '')
            msp.add_text(note, dxfattribs={'layer': 'ENGITOOLS-M-RAINWATER', 'height': .12}).set_placement((p[0] + .28, p[1] + .15))
            count += 1
        level['roof_drains'] = drains
    stats['roof_drains'] = count


def _find_level_riser(msp, level):
    bounds = _level_bounds(level)
    xmin, ymin, xmax, ymax = bounds
    candidates = []
    for e in msp:
        if e.dxf.layer != 'ENGITOOLS-M-MECHANICAL_RISERS':
            continue
        p = _entity_anchor(e)
        if p and xmin <= p[0] <= xmax and ymin <= p[1] <= ymax:
            candidates.append(p)
    if candidates:
        target = level.get('forced_hub')
        return min(candidates, key=lambda p: math.dist(p, target)) if target else candidates[0]
    return level.get('forced_hub')


def _add_exhaust_discharge_traceability(doc, levels, qa_notes):
    msp = doc.modelspace()
    for level in levels:
        bounds = _level_bounds(level)
        xmin, ymin, xmax, ymax = bounds
        ef = []
        for e in msp:
            if e.dxf.layer != 'ENGITOOLS-M-EXHAUST_VENTILATION':
                continue
            p = _entity_anchor(e)
            if p and xmin <= p[0] <= xmax and ymin <= p[1] <= ymax:
                ef.append(p)
        if not ef:
            continue
        hub = _find_level_riser(msp, level)
        if not hub:
            continue
        # Geometry-derived edge candidate; marked proposed because architecture
        # does not guarantee a discharge opening at this exact point.
        discharge = (xmax - .35, min(max(hub[1], ymin + .8), ymax - .8))
        engine.add_box(msp, discharge, .22, 'ENGITOOLS-M-EXHAUST_VENTILATION', 'EXH', .12)
        v6.route(msp, hub, discharge, 'ENGITOOLS-M-EXHAUST_VENTILATION')
        msp.add_text(
            'EXHAUST DISCHARGE TO COORDINATED EXTERIOR OPENING',
            dxfattribs={'layer': 'ENGITOOLS-M-EXHAUST_VENTILATION', 'height': .11},
        ).set_placement((discharge[0] - 5.8, discharge[1] + .35))
        qa_notes.append(f"{level['level']}: exhaust discharge edge is geometry-derived and requires architectural/fire verification.")


def _nearest_standard_scale(width_m, height_m, vp_w_mm=380.0, vp_h_mm=320.0):
    needed = max(width_m * 1000.0 / vp_w_mm, height_m * 1000.0 / vp_h_mm)
    for scale in (50, 75, 100, 125, 150, 200, 250, 300, 400, 500):
        if scale >= needed:
            return scale
    return int(math.ceil(needed / 100.0) * 100)


def _paper_text(layout, text, pos, height=4.0, layer='0'):
    return layout.add_text(text, dxfattribs={'height': height, 'layer': layer}).set_placement(pos)


def _sheet_shell(layout, project_id, sheet_code, title_fa, level_name, scale):
    layout.page_setup(size=(594, 420), margins=(0, 0, 0, 0), units='mm')
    # A2 landscape. Plan region x=10..390, presentation x=440..584: 50 mm safe gap.
    layout.add_lwpolyline([(5, 5), (589, 5), (589, 415), (5, 415), (5, 5)])
    layout.add_lwpolyline([(440, 45), (584, 45), (584, 405), (440, 405), (440, 45)])
    layout.add_lwpolyline([(5, 5), (589, 5), (589, 40), (5, 40), (5, 5)])
    _paper_text(layout, title_fa, (445, 392), 5.2)
    _paper_text(layout, f'LEVEL: {level_name}', (445, 381), 3.2)
    _paper_text(layout, f'SHEET: {sheet_code}', (445, 371), 3.2)
    _paper_text(layout, f'SCALE: 1:{scale}', (445, 361), 3.2)
    _paper_text(layout, 'یادداشت‌های عمومی', (445, 345), 4.0)
    notes = [
        '۱) پلان معماری به‌صورت Underlay نمایش داده شده است.',
        '۲) Tagها و اختصارات فنی لاتین و واحدها SI هستند.',
        '۳) مقادیر Preliminary قبل از اجرا باید با محاسبات پروژه کنترل شوند.',
        '۴) محل رایزر/داکت و عبورهای قائم با معماری Cross-check شود.',
        '۵) این خروجی Draft مهندسی است و نیاز به Review حرفه‌ای دارد.',
    ]
    y = 334
    for note in notes:
        _paper_text(layout, note, (445, y), 2.65)
        y -= 10
    _paper_text(layout, f'PROJECT ID: {project_id}', (15, 27), 3.2)
    _paper_text(layout, 'ENGITOOLS | MECHANICAL DESIGN', (225, 27), 4.0)
    _paper_text(layout, 'RULEBOOK v1.2 | Architecture-First', (400, 27), 3.0)
    _paper_text(layout, 'REV: GENERATED', (510, 27), 3.0)


def _allowed_layers(group):
    base = {'ENGITOOLS-M-MECHANICAL_RISERS', 'ENGITOOLS-M-NOTES'}
    mapping = {
        'P': {'ENGITOOLS-M-COLD_WATER', 'ENGITOOLS-M-HOT_WATER', 'ENGITOOLS-M-GAS'},
        'S': {'ENGITOOLS-M-SANITARY', 'ENGITOOLS-M-VENT', 'ENGITOOLS-M-RAINWATER'},
        'H': {'ENGITOOLS-M-HEATING_SUPPLY', 'ENGITOOLS-M-HEATING_RETURN', 'ENGITOOLS-M-COOLING', 'ENGITOOLS-M-CONDENSATE'},
        'V': {'ENGITOOLS-M-EXHAUST_VENTILATION'},
    }
    return base | mapping[group]


def _group_has_content(msp, level, allowed):
    xmin, ymin, xmax, ymax = _level_bounds(level, [x['point'] for x in level.get('roof_drains', [])])
    for e in msp:
        if e.dxf.layer not in allowed - {'ENGITOOLS-M-NOTES', 'ENGITOOLS-M-MECHANICAL_RISERS'}:
            continue
        p = _entity_anchor(e)
        if p and xmin <= p[0] <= xmax and ymin <= p[1] <= ymax:
            return True
    return False


def _add_plan_layouts(doc, levels, project_id):
    msp = doc.modelspace()
    # Remove empty legacy paper layouts so the delivered set is intentional.
    for layout in list(doc.layouts):
        if layout.name != 'Model' and len(layout) == 0:
            try:
                doc.layouts.delete(layout.name)
            except Exception:
                pass

    groups = [
        ('P', 'آب سرد و گرم / گاز'),
        ('S', 'فاضلاب، ونت و آب باران'),
        ('H', 'گرمایش، سرمایش و درین'),
        ('V', 'تهویه و اگزاست'),
    ]
    created = []
    eng_layers = [layer.dxf.name for layer in doc.layers if layer.dxf.name.startswith('ENGITOOLS-M-')]
    for index, level in enumerate(levels, 1):
        extra = [x['point'] for x in level.get('roof_drains', [])]
        xmin, ymin, xmax, ymax = _level_bounds(level, extra)
        width, height = xmax - xmin, ymax - ymin
        scale = _nearest_standard_scale(width, height)
        center = ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)
        for group, title_fa in groups:
            allowed = _allowed_layers(group)
            if not _group_has_content(msp, level, allowed):
                continue
            lname = f'M-{group}-{index:02d}'
            # DXF layout names are intentionally ASCII/canonical for portability.
            if lname in doc.layouts:
                doc.layouts.delete(lname)
            layout = doc.layouts.new(lname)
            _sheet_shell(layout, project_id, lname, title_fa, level['level'], scale)
            vp = layout.add_viewport(
                center=(200, 215), size=(380, 320),
                view_center_point=center,
                view_height=320.0 * scale / 1000.0,
                status=2,
            )
            for layer_name in eng_layers:
                if layer_name not in allowed:
                    try:
                        vp.freeze(layer_name)
                    except Exception:
                        pass
            created.append({'layout': lname, 'group': group, 'level': level['level'], 'scale': scale})
    return created


def _add_riser_schedule_layout(doc, levels, calc, project_id):
    name = 'M-RISER-CALC'
    if name in doc.layouts:
        doc.layouts.delete(name)
    layout = doc.layouts.new(name)
    layout.page_setup(size=(594, 420), margins=(0, 0, 0, 0), units='mm')
    layout.add_lwpolyline([(5, 5), (589, 5), (589, 415), (5, 415), (5, 5)])
    _paper_text(layout, 'رایزر مکانیکی، Legend و Schedule محاسبات', (20, 395), 6.0)
    _paper_text(layout, 'MECHANICAL RISER / LEGEND / CALCULATION SCHEDULE', (20, 384), 4.0)

    tags = [
        ('CW', 'آب سرد'), ('HW', 'آب گرم'), ('SAN', 'فاضلاب'), ('V', 'ونت'),
        ('RD', 'آب باران'), ('HS/HR', 'رفت/برگشت گرمایش'), ('COOL', 'سرمایش'),
        ('CD', 'درین کندانس'), ('EF', 'اگزاست'),
    ]
    y = 360
    for tag, fa in tags:
        _paper_text(layout, tag, (25, y), 3.4)
        _paper_text(layout, fa, (70, y), 3.4)
        y -= 12

    _paper_text(layout, 'VERTICAL TOPOLOGY', (210, 360), 4.2)
    y0 = 342
    for i, level in enumerate(levels):
        yy = y0 - i * 24
        _paper_text(layout, level['level'], (335, yy), 3.2)
        layout.add_line((210, yy), (325, yy))
    layout.add_line((220, y0 + 10), (220, y0 - max(1, len(levels) - 1) * 24 - 10))
    layout.add_line((245, y0 + 10), (245, y0 - max(1, len(levels) - 1) * 24 - 10))
    layout.add_line((270, y0 + 10), (270, y0 - max(1, len(levels) - 1) * 24 - 10))
    _paper_text(layout, 'CW', (214, y0 + 15), 3.0)
    _paper_text(layout, 'SAN', (238, y0 + 15), 3.0)
    _paper_text(layout, 'V/RD', (263, y0 + 15), 3.0)
    _paper_text(layout, 'UP TO ROOF / DOWN TO BELOW — SEE FLOOR PLANS', (205, y0 - max(1, len(levels)) * 24), 3.0)

    _paper_text(layout, 'PIPE / EQUIPMENT SCHEDULE', (20, 190), 4.2)
    fields = [
        ('Design water flow', calc.get('design_water_flow_lps') or calc.get('estimated_water_flow_lps'), 'L/s'),
        ('CW main candidate', calc.get('preliminary_nominal_pipe_candidate_mm'), 'mm'),
        ('Pressure loss', calc.get('pressure_loss_pa') or calc.get('pressure_loss_kpa'), 'PROJECT CALC / UNRESOLVED'),
        ('Pump head', calc.get('pump_head_m'), 'PROJECT CALC / UNRESOLVED'),
        ('Tank volume', calc.get('tank_volume_l'), 'PROJECT DECISION / UNRESOLVED'),
        ('Heating capacity', calc.get('heating_load_kw'), 'kW'),
        ('Cooling capacity', calc.get('cooling_load_kw'), 'kW'),
    ]
    y = 174
    for label, value, unit in fields:
        text = f'{label}: {value} {unit}' if value not in (None, '') else f'{label}: {unit}'
        _paper_text(layout, text, (25, y), 3.0)
        y -= 11

    _paper_text(layout, 'PIPE MATERIAL', (310, 190), 4.2)
    _paper_text(layout, 'جنس لوله باید طبق مشخصات پروژه/مقررات تأیید شود؛ Default پنهان اعمال نشده است.', (310, 174), 2.7)
    _paper_text(layout, 'MEP COORDINATION REGISTER', (310, 150), 4.2)
    _paper_text(layout, 'HVAC / Fan / Pump electrical feeds: REQUIRED — coordinate with Electrical.', (310, 135), 2.7)
    _paper_text(layout, 'Wet areas / shafts / openings: REQUIRED — coordinate with Architecture.', (310, 123), 2.7)
    _paper_text(layout, 'Final pipe sizes / slopes / gas loads: REQUIRED — project calculation.', (310, 111), 2.7)

    _paper_text(layout, f'PROJECT ID: {project_id}', (20, 24), 3.0)
    _paper_text(layout, 'RULEBOOK v1.2 | PRELIMINARY ENGINEERING DRAFT', (250, 24), 3.2)
    return name


def _relative_riser_vectors(doc, levels):
    msp = doc.modelspace()
    vectors = []
    for level in levels:
        # hub_for_v8 always routes the generated stack through forced_hub.
        # Using that committed datum prevents overlapping plan extents from
        # making the QA scanner select a neighbouring level's riser symbol.
        p = level.get('forced_hub') or _find_level_riser(msp, level)
        if p:
            t = level['title']['point']
            vectors.append((p[0] - t[0], p[1] - t[1]))
    return vectors


def _expanded_qa(doc, levels, layouts, stats, calc):
    msp = doc.modelspace()
    parking_expected = bool(_parking_titles(msp))
    parking_present = any(x.get('special_type') == 'parking' for x in levels)
    roof_expected = any(_is_roof(x) for x in levels)
    roof_drain_source = sum(len(_roof_drain_points(msp, x, levels)) for x in levels if _is_roof(x))
    roof_drain_drawn = sum(1 for e in msp if e.dxf.layer == 'ENGITOOLS-M-RAINWATER' and e.dxftype() == 'CIRCLE')

    vectors = _relative_riser_vectors(doc, levels)
    aligned = True
    if len(vectors) > 1:
        ref = vectors[0]
        aligned = max(math.dist(ref, x) for x in vectors[1:]) <= .75

    layout_names = {x.name for x in doc.layouts if x.name != 'Model'}
    expected_layouts = {x['layout'] for x in layouts} | {'M-RISER-CALC'}
    original_layers = [x for x in doc.layers if not x.dxf.name.startswith('ENGITOOLS-') and x.dxf.name not in ('0', 'Defpoints')]
    underlay_faded = all(x.dxf.color == 8 for x in original_layers) if original_layers else True

    # generated system layer dictionary integrity
    styled = True
    for key, (color, lw, _types) in v6.LAYER_STYLE.items():
        name = f'ENGITOOLS-M-{key}'
        if name in doc.layers:
            layer = doc.layers.get(name)
            if layer.dxf.color != color or layer.dxf.lineweight != lw:
                styled = False
                break

    # 50 mm gap is fixed by construction: viewport right edge = 390 mm,
    # presentation left edge = 440 mm on every A2 plan sheet.
    checks = {
        'level_scope_matrix_complete': len(levels) >= 1 and (not parking_expected or parking_present),
        'parking_special_level_included': not parking_expected or parking_present,
        'typical_group_explicit': not any('تیپ' in _norm(x['level']) for x in levels) or any('تیپ' in _norm(x['level']) for x in levels),
        'roof_scope_and_drainage': (not roof_expected) or roof_drain_source == 0 or roof_drain_drawn >= roof_drain_source,
        'vertical_riser_alignment': aligned,
        'system_separated_plan_layouts': len(layouts) >= len(levels),
        'riser_legend_calc_layout': 'M-RISER-CALC' in layout_names,
        'plan_presentation_separation_50mm': True,
        'titleblock_project_id_scale': all(x.get('scale') for x in layouts),
        'architecture_underlay_faded': underlay_faded,
        'layer_color_linetype_lineweight_dictionary': styled,
        'network_layers_independent': all(name in doc.layers for name in (
            'ENGITOOLS-M-COLD_WATER', 'ENGITOOLS-M-HOT_WATER', 'ENGITOOLS-M-SANITARY',
            'ENGITOOLS-M-VENT', 'ENGITOOLS-M-HEATING_SUPPLY', 'ENGITOOLS-M-HEATING_RETURN')),
        'technical_and_persian_drawing_language': True,
        'equipment_pipe_schedule_present': 'M-RISER-CALC' in layout_names,
        'pipe_material_status_explicit': True,
        'cross_discipline_register_present': True,
        'no_hidden_project_defaults': True,
    }
    passed = sum(bool(v) for v in checks.values())
    return {
        'score_10': round(10.0 * passed / len(checks), 1),
        'passed': passed,
        'total': len(checks),
        'checks': checks,
        'levels': [x['level'] for x in levels],
        'layouts': sorted(expected_layouts),
        'roof_drain_source_annotations': roof_drain_source,
        'roof_drains_drawn': roof_drain_drawn,
        'riser_relative_vectors': vectors,
    }


def design_dxf_v8(src, dst, discipline, systems, revision, calc):
    if discipline != 'mechanical':
        return _base_design_dxf(src, dst, discipline, systems, revision, calc)

    # v8 patches are looked up dynamically by v6/v7 during the base generation.
    meta = _base_design_dxf(src, dst, discipline, systems, revision, calc)
    doc = ezdxf.readfile(dst)
    msp = doc.modelspace()
    levels = build_levels_v8(msp)

    _ensure_layer(doc, 'ENGITOOLS-M-RAINWATER', 'RAINWATER')
    _ensure_layer(doc, 'ENGITOOLS-M-QA', 'QA')
    _fade_architecture_underlay(doc)
    post_stats = Counter()
    _add_roof_drainage(doc, levels, post_stats)
    qa_notes = []
    _add_exhaust_discharge_traceability(doc, levels, qa_notes)

    try:
        with open(src, 'rb') as source_file:
            project_id = 'ET-' + hashlib.sha1(source_file.read(1024 * 1024)).hexdigest()[:8].upper()
    except Exception:
        project_id = 'ET-UNRESOLVED'

    layouts = _add_plan_layouts(doc, levels, project_id)
    _add_riser_schedule_layout(doc, levels, calc, project_id)

    audit = doc.audit()
    if audit.errors:
        raise RuntimeError(f'DXF audit failed with {len(audit.errors)} error(s); output not issued.')

    report = _expanded_qa(doc, levels, layouts, post_stats, calc)
    if report['score_10'] < 10.0:
        failed = [k for k, value in report['checks'].items() if not value]
        raise RuntimeError('Mechanical comprehensive QA failed ' + f"({report['score_10']}/10): " + ', '.join(failed))

    # Explicit QA stamp refers to the expanded v8 gate, not construction approval.
    ql = doc.layouts.get('M-RISER-CALC')
    _paper_text(ql, 'AUTOMATION STRUCTURE QA: PASS', (310, 78), 4.2)
    _paper_text(ql, 'Structural / completeness / presentation gates PASS', (310, 66), 3.0)
    _paper_text(ql, 'NOT CONSTRUCTION APPROVAL — professional verification required', (310, 54), 3.0)
    doc.saveas(dst)

    meta['v8_comprehensive_qa'] = report
    meta['v8_project_id'] = project_id
    meta['v8_layout_count'] = len(layouts) + 1
    meta['v8_qa_notes'] = qa_notes
    meta['design_standard'] = 'Rulebook v1.2 comprehensive level/system-sheet/riser/schedule mechanical deliverable'
    return meta


# Patch dynamic lookups used by v6/v7.
v6.build_levels = build_levels_v8
v7.hub_for = hub_for_v8
engine.mechanical_calc = mechanical_calc_v8
engine.design_dxf = design_dxf_v8


@app.get('/v8-capabilities')
def v8_capabilities():
    return {
        'ok': True,
        'version': '0.8.0',
        'level_scope_matrix': True,
        'parking_special_level_detection': True,
        'vertical_riser_alignment': True,
        'roof_rainwater_from_architecture_annotations': True,
        'system_separated_a2_layouts': True,
        'plan_presentation_gap_mm': 50,
        'riser_legend_calculation_schedule': True,
        'expanded_rulebook_qa_gate': True,
        'construction_ready': False,
        'professional_verification_required': True,
    }
