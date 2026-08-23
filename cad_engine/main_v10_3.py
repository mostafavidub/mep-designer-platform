"""Mechanical authority-submission sheet compositor.

The v9 mechanical engine creates engineering geometry first. This final stage
packages that geometry into the system-separated drawing set used by the local
Engineering Organization submission profile.
"""

import ezdxf

from . import main_v10_2 as base
from . import main_v10 as v10
from . import main_v8 as v8
from . import main_v3 as engine

app = base.app
_base_design = v10.design_dxf_v10

AUTHORITY_GROUPS = [
    ('W', 'آب سرد و گرم', {'ENGITOOLS-M-COLD_WATER', 'ENGITOOLS-M-HOT_WATER'}),
    ('S', 'فاضلاب و ونت', {'ENGITOOLS-M-SANITARY', 'ENGITOOLS-M-VENT'}),
    ('H', 'گرمایش', {'ENGITOOLS-M-HEATING_SUPPLY', 'ENGITOOLS-M-HEATING_RETURN'}),
    ('C', 'سرمایش و درین کندانس', {'ENGITOOLS-M-COOLING', 'ENGITOOLS-M-CONDENSATE'}),
    ('G', 'گاز', {'ENGITOOLS-M-GAS'}),
    ('V', 'تهویه و اگزاست', {'ENGITOOLS-M-EXHAUST_VENTILATION'}),
    ('R', 'بام و آب باران', {'ENGITOOLS-M-RAINWATER'}),
]
TEMP_LAYOUT = '__AUTH_TMP__'


def _negative(value):
    s = str(value or '').strip().lower()
    return any(x in s for x in ('ندارد', 'خیر', 'نیست', 'بدون', 'none', 'no '))


def _rooms(level, kinds):
    return [r for r in level.get('rooms', []) if r.get('room') in kinds]


def _effective_for_group(level, group, systems, calc):
    roof = v8._is_roof(level)
    wet = bool(_rooms(level, {'kitchen', 'bath', 'toilet'}))
    hab = bool(_rooms(level, {'bedroom', 'living', 'office', 'shop'}))
    kitchen = bool(_rooms(level, {'kitchen'}))
    parking = bool(_rooms(level, {'parking'})) or level.get('special_type') == 'parking'
    inputs = calc.get('_design_inputs') or {}
    active = set(systems or [])
    if group == 'W':
        return wet and bool(active & {'cold_water', 'hot_water'}) and not roof
    if group == 'S':
        return wet and bool(active & {'sanitary', 'vent'}) and not roof
    if group == 'H':
        return hab and bool(active & {'heating_supply', 'heating_return'}) and not _negative(inputs.get('heating')) and not roof
    if group == 'C':
        return hab and bool(active & {'cooling', 'condensate'}) and not _negative(inputs.get('cooling')) and not roof
    if group == 'G':
        return kitchen and 'gas' in active and not _negative(inputs.get('gas')) and not roof
    if group == 'V':
        return (wet or parking) and 'exhaust_ventilation' in active and not roof
    if group == 'R':
        return roof and 'rainwater' in active
    return False


def _remove_old_issue_layouts(doc):
    # ezdxf cannot delete the active paper-space layout. Create and activate a
    # temporary paper layout, then remove every legacy/helper sheet including
    # M-RISER-CALC. The temporary layout is removed once a new authority sheet
    # can safely become active.
    existing = [x.name for x in doc.layouts]
    if TEMP_LAYOUT in existing:
        try:
            doc.layouts.delete(TEMP_LAYOUT)
        except Exception:
            pass
    doc.layouts.new(TEMP_LAYOUT)
    doc.layouts.set_active_layout(TEMP_LAYOUT)
    for layout in list(doc.layouts):
        if layout.name in ('Model', TEMP_LAYOUT):
            continue
        doc.layouts.delete(layout.name)


def _finish_layout_reset(doc, first_authority_layout):
    if first_authority_layout:
        doc.layouts.set_active_layout(first_authority_layout)
    if TEMP_LAYOUT in [x.name for x in doc.layouts]:
        doc.layouts.delete(TEMP_LAYOUT)


def _plan_view(doc, level, project_id, code, title, system_layers):
    extra = [x['point'] for x in level.get('roof_drains', [])]
    xmin, ymin, xmax, ymax = v8._level_bounds(level, extra)
    width, height = xmax - xmin, ymax - ymin
    scale = v8._nearest_standard_scale(width, height)
    center = ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0)
    layout = doc.layouts.new(code)
    v8._sheet_shell(layout, project_id, code, title, level['level'], scale)
    vp = layout.add_viewport(
        center=(200, 215), size=(380, 320), view_center_point=center,
        view_height=320.0 * scale / 1000.0, status=2,
    )
    allowed = {'ENGITOOLS-M-MECHANICAL_RISERS', 'ENGITOOLS-M-NOTES'} | set(system_layers)
    for layer in doc.layers:
        name = layer.dxf.name
        if name.startswith('ENGITOOLS-M-') and name not in allowed:
            try:
                vp.freeze(name)
            except Exception:
                pass
    return {'layout': code, 'level': level['level'], 'scale': scale}


def _water_special(doc, levels, project_id):
    name = 'M-W-SPECIAL'
    layout = doc.layouts.new(name)
    layout.page_setup(size=(594, 420), margins=(0, 0, 0, 0), units='mm')
    v8._paper_text(layout, 'رایزر / تجهیزات / شماتیک آبرسانی', (20, 395), 6.0)
    v8._paper_text(layout, 'WATER SUPPLY RISER / EQUIPMENT SCHEMATIC', (20, 384), 4.0)
    y0 = 350
    for i, level in enumerate(levels):
        y = y0 - i * 28
        v8._paper_text(layout, level['level'], (310, y), 3.2)
        layout.add_line((140, y), (295, y))
    if levels:
        layout.add_line((165, y0 + 10), (165, y0 - max(1, len(levels) - 1) * 28 - 10))
        layout.add_line((205, y0 + 10), (205, y0 - max(1, len(levels) - 1) * 28 - 10))
    v8._paper_text(layout, 'CW', (158, y0 + 18), 3.0)
    v8._paper_text(layout, 'HW', (198, y0 + 18), 3.0)
    v8._paper_text(layout, 'Pump / tank / meter arrangement follows resolved project inputs.', (20, 90), 3.0)
    v8._paper_text(layout, f'PROJECT ID: {project_id}', (20, 24), 3.0)
    return {'layout': name, 'group': 'W', 'special': True}


def _cooling_special(doc, roof, project_id):
    name = 'M-C-EQUIP'
    if roof is not None:
        return _plan_view(doc, roof, project_id, name, 'سرمایش — تجهیزات / بام', {'ENGITOOLS-M-COOLING', 'ENGITOOLS-M-CONDENSATE'}) | {'group': 'C', 'special': True}
    layout = doc.layouts.new(name)
    layout.page_setup(size=(594, 420), margins=(0, 0, 0, 0), units='mm')
    v8._paper_text(layout, 'سرمایش — تجهیزات / بام', (20, 395), 6.0)
    v8._paper_text(layout, 'COOLING EQUIPMENT / ROOF PLAN', (20, 384), 4.0)
    v8._paper_text(layout, 'Equipment arrangement requires final architectural roof coordination.', (20, 350), 3.0)
    v8._paper_text(layout, f'PROJECT ID: {project_id}', (20, 24), 3.0)
    return {'layout': name, 'group': 'C', 'special': True}


def _norm_level(value):
    return ''.join(str(value or '').strip().lower().replace('ي', 'ی').replace('ك', 'ک').split())


def _manifest_level(sheet, levels):
    wanted = [_norm_level(x) for x in (sheet.get('levels') or [])]
    for level in levels:
        actual = _norm_level(level.get('level'))
        if actual in wanted:
            return level
    for level in levels:
        actual = _norm_level(level.get('level'))
        if any(actual and (actual in x or x in actual) for x in wanted):
            return level
    raise RuntimeError(
        f"Approved sheet {sheet.get('code')} references levels not found in CAD: "
        f"{sheet.get('levels')}; detected={[x.get('level') for x in levels]}"
    )


def _compose_authority_layouts(doc, levels, project_id, systems, calc):
    manifest = calc.get('_approved_drawing_manifest') or {}
    sheets = manifest.get('sheets') or []
    expected = int(manifest.get('total_sheets') or -1)
    if expected < 1 or expected != len(sheets):
        raise RuntimeError('Approved mechanical drawing manifest is missing or invalid.')

    expected_codes = [str(x.get('code') or '') for x in sheets]
    if any(not x for x in expected_codes) or len(expected_codes) != len(set(expected_codes)):
        raise RuntimeError('Approved mechanical drawing manifest has missing or duplicate sheet codes.')

    _remove_old_issue_layouts(doc)
    created = []
    counts = {key: 0 for key, _, _ in AUTHORITY_GROUPS}
    msp = doc.modelspace()
    for level in levels:
        if v8._is_roof(level):
            level['roof_drains'] = v8._roof_drain_points(msp, level, levels)

    group_defs = {key: (title, layers) for key, title, layers in AUTHORITY_GROUPS}
    family_groups = {
        'water_supply': 'W', 'sanitary_vent': 'S', 'heating': 'H',
        'cooling': 'C', 'gas': 'G', 'ventilation_exhaust': 'V',
        'roof_rainwater': 'R',
    }
    roofs = [x for x in levels if v8._is_roof(x)]

    for sheet in sheets:
        code = str(sheet['code'])
        family = str(sheet.get('family') or '')
        group = family_groups.get(family)
        if not group:
            raise RuntimeError(f'Unsupported approved mechanical sheet family: {family}')
        title, layers = group_defs[group]
        special = bool(sheet.get('special'))

        if code == 'M-W-SPECIAL':
            water_levels = [
                x for x in levels
                if _effective_for_group(x, 'W', systems, calc)
            ]
            row = _water_special(doc, water_levels, project_id)
        elif code == 'M-C-EQUIP':
            row = _cooling_special(doc, roofs[0] if roofs else None, project_id)
        else:
            level = _manifest_level(sheet, levels)
            row = _plan_view(
                doc, level, project_id, code,
                str(sheet.get('label') or title), layers,
            )
            row['special'] = special
        row['layout'] = code
        row['group'] = group
        row['manifest_pattern'] = sheet.get('pattern')
        row['manifest_levels'] = list(sheet.get('levels') or [])
        created.append(row)
        counts[group] += 1

    _finish_layout_reset(doc, created[0]['layout'] if created else None)
    actual_codes = [x['layout'] for x in created]
    if actual_codes != expected_codes:
        raise RuntimeError(
            f'Generated sheet manifest mismatch: expected={expected_codes}; generated={actual_codes}'
        )
    return created, counts


def design_dxf_v10_3(src, dst, discipline, systems, revision, calc):
    effective_systems = list(systems or [])
    if discipline == 'mechanical' and 'rainwater' not in effective_systems:
        effective_systems.append('rainwater')
    meta = _base_design(src, dst, discipline, effective_systems, revision, calc)
    if discipline != 'mechanical':
        return meta

    doc = ezdxf.readfile(dst)
    levels = v8.build_levels_v8(doc.modelspace())
    project_id = meta.get('v8_project_id') or 'ET-AUTHORITY'
    created, counts = _compose_authority_layouts(doc, levels, project_id, effective_systems, calc)

    audit = doc.audit()
    if audit.errors:
        raise RuntimeError(f'Authority sheet DXF audit failed with {len(audit.errors)} error(s).')
    if not created:
        raise RuntimeError('Authority sheet compositor produced no mechanical deliverables.')

    manifest = calc.get('_approved_drawing_manifest') or {}
    expected_names = [str(x.get('code') or '') for x in (manifest.get('sheets') or [])]
    issued_names = [x.name for x in doc.layouts if x.name.startswith('M-')]
    if issued_names != expected_names:
        raise RuntimeError(
            'Approved manifest does not match issued CAD layouts: '
            f'expected={expected_names}; issued={issued_names}; counts={counts}'
        )

    doc.saveas(dst)
    meta['authority_submission'] = {
        'profile': 'local_engineering_organization',
        'system_separated': True,
        'expected_sheet_count': len(expected_names),
        'generated_sheet_count': len(issued_names),
        'validation_status': 'PASS',
        'manifest_id': manifest.get('manifest_id'),
        'layout_count': len(created),
        'counts': counts,
        'layouts': [x['layout'] for x in created],
        'combined_approval_families': False,
        'generic_riser_calc_extra_sheet': False,
    }
    meta['design_standard'] = 'Rulebook authority-separated mechanical submission'
    return meta


engine.design_dxf = design_dxf_v10_3


@app.get('/v10-3-capabilities')
def capabilities():
    return {
        'ok': True,
        'version': '1.0.3-authority-mechanical',
        'authority_submission_profile': True,
        'system_separated_mechanical_sheets': True,
        'effective_level_sheet_scope': True,
        'water_system_special_sheet': True,
        'cooling_roof_equipment_sheet': True,
        'dedicated_roof_rainwater_sheet': True,
        'generic_combined_riser_sheet': False,
        'construction_ready': False,
        'professional_verification_required': True,
    }
