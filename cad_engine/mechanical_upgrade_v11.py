"""Mechanical v11 guarded upgrades.

This layer is deliberately installed on top of v10.4.  Each upgrade keeps the
proven design engine and replaces only the narrow helper responsible for the
new invariant, so existing electrical/site behaviour is untouched.
"""
from collections import Counter
import math
import re

import ezdxf


SPECIAL_SUFFIXES = {"RISER", "EQUIP", "RETURN", "DETAIL", "RAIN", "PARK", "SPECIAL"}


def _paper_text(v8, layout, value, x, y, h=3.2):
    v8._paper_text(layout, str(value), (x, y), h)


def _new_special_layout(doc, v8, project_id, code, title, subtitle):
    layout = doc.layouts.new(code)
    layout.page_setup(size=(594, 420), margins=(0, 0, 0, 0), units='mm')
    _paper_text(v8, layout, title, 20, 395, 6.0)
    _paper_text(v8, layout, subtitle, 20, 384, 4.0)
    _paper_text(v8, layout, f'PROJECT ID: {project_id}', 20, 24, 3.0)
    return layout


def _system_special_sheet(doc, v10_3, level_rows, project_id, sheet, group, layers):
    """Create a genuinely independent special sheet, never a renamed base plan."""
    v8 = v10_3.v8
    code = str(sheet.get('code') or '')
    suffix = code.rsplit('-', 1)[-1].upper()
    levels = [str(x) for x in (sheet.get('levels') or [])]
    label = str(sheet.get('label') or code)

    # A cooling equipment sheet on an explicitly detected roof is a legitimate
    # equipment plan.  It still uses different geometry from the occupied-floor
    # cooling plan and therefore is not a duplicated viewport.
    if group == 'C' and suffix == 'EQUIP':
        roofs = [x for x in level_rows if v8._is_roof(x)]
        if roofs:
            return v10_3._plan_view(
                doc, roofs[0], project_id, code, label,
                set(layers) | {'ENGITOOLS-M-ROOF_RAINWATER', 'ENGITOOLS-M-RAINWATER'},
            ) | {'group': group, 'special': True, 'drawing_role': 'equipment_roof_plan'}

    # A rainwater role with a detected roof is a dedicated roof drainage plan,
    # not a sanitary viewport of the occupied floor.
    if suffix == 'RAIN':
        roofs = [x for x in level_rows if v8._is_roof(x)]
        if roofs:
            return v10_3._plan_view(
                doc, roofs[0], project_id, code, label,
                {'ENGITOOLS-M-ROOF_RAINWATER', 'ENGITOOLS-M-RAINWATER', 'ENGITOOLS-M-MECHANICAL_RISERS'},
            ) | {'group': group, 'special': True, 'drawing_role': 'rainwater_roof_plan'}

    titles = {
        ('W', 'RISER'): ('رایزر آبرسانی', 'WATER SUPPLY RISER SCHEMATIC'),
        ('W', 'EQUIP'): ('تجهیزات آبرسانی', 'WATER METER / TANK / PUMP ARRANGEMENT'),
        ('W', 'RETURN'): ('برگشت آب گرم', 'DOMESTIC HOT WATER RETURN / BALANCING'),
        ('S', 'RISER'): ('رایزر فاضلاب و ونت', 'SANITARY / VENT STACK SCHEMATIC'),
        ('S', 'RAIN'): ('آب باران و ونت', 'RAINWATER / VENT DETAIL SCHEMATIC'),
        ('S', 'DETAIL'): ('جزئیات فاضلاب و ونت', 'SANITARY CLEANOUT / TRAP / VENT DETAILS'),
        ('H', 'EQUIP'): ('تجهیزات گرمایش', 'HEATING EQUIPMENT / TERMINAL DETAILS'),
        ('C', 'EQUIP'): ('تجهیزات سرمایش', 'COOLING EQUIPMENT / CONDENSATE DETAILS'),
        ('V', 'DETAIL'): ('جزئیات تهویه', 'EXHAUST / MAKE-UP AIR DETAILS'),
        ('V', 'PARK'): ('تهویه پارکینگ', 'PARKING EXHAUST / MAKE-UP AIR SCHEMATIC'),
    }
    title, subtitle = titles.get((group, suffix), (label, f'{group} SYSTEM SPECIAL DRAWING'))
    layout = _new_special_layout(doc, v8, project_id, code, title, subtitle)

    # Draw role-specific diagrams directly in Paper Space.  Special sheets have
    # no occupied-floor viewport, preventing the old duplicate-layout failure.
    y0 = 345.0
    if suffix == 'RISER':
        used_levels = levels or [str(x.get('level') or '') for x in level_rows if not v8._is_roof(x)]
        left = 165.0; right = 225.0
        layout.add_line((left, y0 + 12), (left, y0 - max(1, len(used_levels)-1) * 30 - 12))
        layout.add_line((right, y0 + 12), (right, y0 - max(1, len(used_levels)-1) * 30 - 12))
        _paper_text(v8, layout, 'MAIN / SUPPLY', left - 18, y0 + 20, 2.8)
        _paper_text(v8, layout, 'RETURN / VENT', right - 18, y0 + 20, 2.8)
        for i, name in enumerate(used_levels):
            y = y0 - i * 30
            layout.add_line((115, y), (275, y))
            _paper_text(v8, layout, name, 290, y - 2, 3.0)
            _paper_text(v8, layout, 'BRANCH + ISOLATION / CLEANOUT', 320, y - 2, 2.5)
    elif suffix in {'EQUIP', 'RETURN'}:
        boxes = [
            ('SERVICE / SOURCE', 70), ('METER / CONTROL', 190),
            ('PRIMARY EQUIPMENT', 310), ('DISTRIBUTION', 430),
        ]
        for text, x in boxes:
            layout.add_lwpolyline([(x, 290), (x+90, 290), (x+90, 335), (x, 335), (x, 290)])
            _paper_text(v8, layout, text, x+7, 310, 2.7)
        for x in (160, 280, 400):
            layout.add_line((x, 312), (x+30, 312))
        _paper_text(v8, layout, 'Sizing / capacities are taken from the resolved technical schedule.', 30, 245, 3.0)
        _paper_text(v8, layout, 'Valves, balancing and service isolation are mandatory at equipment connections.', 30, 228, 3.0)
    elif suffix == 'PARK':
        layout.add_lwpolyline([(80, 260), (500, 260), (500, 335), (80, 335), (80, 260)])
        _paper_text(v8, layout, 'PARKING ZONE', 240, 300, 4.0)
        _paper_text(v8, layout, 'MAKE-UP AIR ->', 95, 350, 3.0)
        _paper_text(v8, layout, '-> EXHAUST FAN -> SAFE DISCHARGE', 330, 350, 3.0)
        layout.add_line((110, 335), (110, 365)); layout.add_line((465, 335), (465, 365))
    else:
        rows = [
            '1. CONNECTION / TERMINATION DETAIL',
            '2. ACCESS, CLEANOUT OR SERVICE CLEARANCE',
            '3. SLOPE / FLOW DIRECTION / DISCHARGE REQUIREMENT',
            '4. SUPPORT / ISOLATION / COORDINATION REQUIREMENT',
            '5. ALL VALUES SHALL MATCH THE TECHNICAL DESIGN SCHEDULE',
        ]
        for i, text in enumerate(rows):
            y = 335 - i * 38
            layout.add_lwpolyline([(45, y-12), (545, y-12), (545, y+12), (45, y+12), (45, y-12)])
            _paper_text(v8, layout, text, 60, y-3, 3.0)

    return {
        'layout': code, 'group': group, 'special': True,
        'drawing_role': suffix.lower(), 'manifest_levels': levels,
    }


def _compose_authority_layouts_v2(doc, levels, project_id, systems, calc, v10_3):
    manifest = calc.get('_approved_drawing_manifest') or {}
    sheets = manifest.get('sheets') or []
    expected = int(manifest.get('total_sheets') or -1)
    if expected < 1 or expected != len(sheets):
        raise RuntimeError('Approved mechanical drawing manifest is missing or invalid.')
    expected_codes = [str(x.get('code') or '') for x in sheets]
    if any(not x for x in expected_codes) or len(expected_codes) != len(set(expected_codes)):
        raise RuntimeError('Approved mechanical drawing manifest has missing or duplicate sheet codes.')

    v10_3._remove_old_issue_layouts(doc)
    msp = doc.modelspace()
    for level in levels:
        if v10_3.v8._is_roof(level):
            level['roof_drains'] = v10_3.v8._roof_drain_points(msp, level, levels)

    group_defs = {key: (title, set(layers)) for key, title, layers in v10_3.AUTHORITY_GROUPS}
    # Canonical rainwater layer in v10.4 plus legacy v8 layer are both visible.
    if 'R' in group_defs:
        title, layers = group_defs['R']
        layers |= {'ENGITOOLS-M-ROOF_RAINWATER', 'ENGITOOLS-M-RAINWATER'}
        group_defs['R'] = title, layers
    family_groups = {
        'water_supply': 'W', 'sanitary_vent': 'S', 'heating': 'H',
        'cooling': 'C', 'gas': 'G', 'ventilation_exhaust': 'V',
        'roof_rainwater': 'R',
    }

    created = []
    counts = {key: 0 for key, _, _ in v10_3.AUTHORITY_GROUPS}
    for sheet in sheets:
        code = str(sheet['code']); family = str(sheet.get('family') or '')
        group = family_groups.get(family)
        if not group:
            raise RuntimeError(f'Unsupported approved mechanical sheet family: {family}')
        title, layers = group_defs[group]
        suffix = code.rsplit('-', 1)[-1].upper()
        special = bool(sheet.get('special')) or suffix in SPECIAL_SUFFIXES
        if special:
            row = _system_special_sheet(doc, v10_3, levels, project_id, sheet, group, layers)
        else:
            level = v10_3._manifest_level(sheet, levels)
            row = v10_3._plan_view(
                doc, level, project_id, code, str(sheet.get('label') or title), layers,
            )
            row['special'] = False
            row['drawing_role'] = 'system_plan'
        row['layout'] = code
        row['group'] = group
        row['manifest_pattern'] = sheet.get('pattern')
        row['manifest_levels'] = list(sheet.get('levels') or [])
        created.append(row); counts[group] += 1

    v10_3._finish_layout_reset(doc, created[0]['layout'] if created else None)
    actual = [row['layout'] for row in created]
    if actual != expected_codes:
        raise RuntimeError(f'Generated sheet manifest mismatch: expected={expected_codes}; generated={actual}')
    return created, counts


def install(v10_3, v10_4):
    if getattr(v10_4, '_mechanical_upgrade_v11_installed', False):
        return
    v10_3._compose_authority_layouts = lambda doc, levels, project_id, systems, calc: _compose_authority_layouts_v2(
        doc, levels, project_id, systems, calc, v10_3,
    )
    # The original v10.4 design function calls v10.3 by reference and therefore
    # picks up the upgraded compositor without duplicating the rest of the engine.
    v10_4._mechanical_upgrade_v11_installed = True
