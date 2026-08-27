"""Stage 11 fail-closed QA for real issued mechanical drawing content.

The approved manifest is the source of truth.  Layout count alone is not proof
that the promised deliverables exist.  Every approved sheet must have its own
issued drawing role: a system plan with an actual viewport plus EngiTools-owned
annotations, or a special drawing with role-specific paper-space geometry.
"""
from __future__ import annotations

import ezdxf


SPECIAL_GEOMETRY = {'LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC', 'INSERT'}


def _base_architectural_view_count(calc, manifest):
    auto = ((calc or {}).get('_plan_analysis') or {}).get('architectural_auto') or {}
    profiles = auto.get('level_profiles') or []
    names = [str(x.get('name') or '') for x in profiles if isinstance(x, dict) and x.get('name')]
    if names:
        return len(dict.fromkeys(names))
    names = []
    for sheet in (manifest or {}).get('sheets') or []:
        for level in sheet.get('levels') or []:
            if str(level) not in names:
                names.append(str(level))
    return len(names)


def validate_independent_drawing_content(path, calc):
    manifest = (calc or {}).get('_approved_drawing_manifest') or {}
    sheets = manifest.get('sheets') or []
    expected = [str(x.get('code') or '') for x in sheets]
    if not expected or int(manifest.get('total_sheets') or -1) != len(expected):
        raise RuntimeError('CAD output does not match approved drawing manifest: invalid approved manifest')

    doc = ezdxf.readfile(path)
    actual = [x.name for x in doc.layouts if x.name.startswith('M-')]
    per_sheet = {}
    content_count = 0

    for sheet in sheets:
        code = str(sheet.get('code') or '')
        special = bool(sheet.get('special'))
        try:
            layout = doc.layouts.get(code)
        except Exception:
            per_sheet[code] = {'status': 'FAIL', 'reason': 'missing_layout'}
            continue

        viewports = len(layout.query('VIEWPORT'))
        dimensions = len(layout.query('DIMENSION'))
        leaders = len(layout.query('LEADER'))
        geometry = sum(1 for entity in layout if entity.dxftype() in SPECIAL_GEOMETRY)
        annotations_ok = dimensions >= 1 and leaders >= 1

        if special:
            # Equipment/roof specials may legitimately be viewport-based; riser,
            # detail, return and parking sheets must contain their own diagram
            # geometry.  Either path is acceptable, but a renamed empty layout is not.
            role_content = geometry >= 1 or viewports >= 1
        else:
            role_content = viewports >= 1 and bool(sheet.get('levels'))

        ok = role_content and annotations_ok
        per_sheet[code] = {
            'status': 'PASS' if ok else 'FAIL',
            'special': special,
            'viewports': viewports,
            'role_geometry_entities': geometry,
            'dimensions': dimensions,
            'leaders': leaders,
            'levels': list(sheet.get('levels') or []),
        }
        if ok:
            content_count += 1

    base_views = _base_architectural_view_count(calc, manifest)
    report = {
        'base_architectural_view_count': base_views,
        'approved_deliverable_count': len(expected),
        'independent_issued_drawing_content_count': content_count,
        'issued_layout_count': len(actual),
        'expected_layouts': expected,
        'actual_layouts': actual,
        'per_sheet': per_sheet,
    }
    report['status'] = 'PASS' if (
        actual == expected
        and len(expected) == len(actual) == content_count
        and all(x.get('status') == 'PASS' for x in per_sheet.values())
    ) else 'FAIL'
    if report['status'] != 'PASS':
        raise RuntimeError('CAD output does not match approved drawing manifest: ' + str(report))
    return report
