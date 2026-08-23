"""Mechanical authority-submission sheet compositor.

The underlying v9 mechanical designer still creates all engineering geometry and
passes its comprehensive QA. This final stage changes only the issued sheet set:
separate approval disciplines are delivered separately, matching the accepted
21-sheet reference convention instead of the earlier four combined families.
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


def _allowed(system_layers):
    return {'ENGITOOLS-M-MECHANICAL_RISERS', 'ENGITOOLS-M-NOTES'} | set(system_layers)


def _has_content(msp, level, system_layers):
    return v8._group_has_content(msp, level, _allowed(system_layers))


def _remove_old_issue_layouts(doc):
    for layout in list(doc.layouts):
        if layout.name == 'Model':
            continue
        try:
            doc.layouts.delete(layout.name)
        except Exception:
            pass


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
    allowed = _allowed(system_layers)
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


def _compose_authority_layouts(doc, levels, project_id):
    _remove_old_issue_layouts(doc)
    msp = doc.modelspace()
    created = []
    counts = {key: 0 for key, _, _ in AUTHORITY_GROUPS}

    for group, title, layers in AUTHORITY_GROUPS:
        index = 0
        for level in levels:
            if not _has_content(msp, level, layers):
                continue
            index += 1
            code = f'M-{group}-{index:02d}'
            row = _plan_view(doc, level, project_id, code, title, layers)
            row['group'] = group
            created.append(row)
        counts[group] = index

    if counts['W'] >= 2:
        created.append(_water_special(doc, levels, project_id)); counts['W'] += 1

    roofs = [x for x in levels if v8._is_roof(x)]
    if counts['C'] >= 1 and roofs:
        created.append(_cooling_special(doc, roofs[0], project_id)); counts['C'] += 1

    return created, counts


def design_dxf_v10_3(src, dst, discipline, systems, revision, calc):
    meta = _base_design(src, dst, discipline, systems, revision, calc)
    if discipline != 'mechanical':
        return meta

    doc = ezdxf.readfile(dst)
    levels = v8.build_levels_v8(doc.modelspace())
    project_id = meta.get('v8_project_id') or 'ET-AUTHORITY'
    created, counts = _compose_authority_layouts(doc, levels, project_id)

    audit = doc.audit()
    if audit.errors:
        raise RuntimeError(f'Authority sheet DXF audit failed with {len(audit.errors)} error(s).')
    if not created:
        raise RuntimeError('Authority sheet compositor produced no mechanical deliverables.')

    issued_names = [x.name for x in doc.layouts if x.name.startswith('M-')]
    if len(issued_names) != len(created):
        expected_names = [x['layout'] for x in created]
        raise RuntimeError(
            'Authority deliverable count does not match issued CAD layout count: '
            f'created={len(created)} {expected_names}; issued={len(issued_names)} {issued_names}; counts={counts}'
        )

    doc.saveas(dst)
    meta['authority_submission'] = {
        'profile': 'local_engineering_organization',
        'system_separated': True,
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
        'water_system_special_sheet': True,
        'cooling_roof_equipment_sheet': True,
        'dedicated_roof_rainwater_sheet': True,
        'generic_combined_riser_sheet': False,
        'construction_ready': False,
        'professional_verification_required': True,
    }
