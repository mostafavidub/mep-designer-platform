"""Final fail-closed engineering QA for the guarded mechanical v11 pipeline.

This module does not design anything.  It validates the already-generated DXF
against the frozen approved manifest and the per-system QA reports produced by
the narrow v11 engines.  A failed invariant blocks issuance.
"""
from __future__ import annotations

import ezdxf

from .rainwater_v11 import validate_rainwater


FAMILY_LAYERS = {
    'water_supply': {'ENGITOOLS-M-COLD_WATER', 'ENGITOOLS-M-HOT_WATER'},
    'sanitary_vent': {'ENGITOOLS-M-SANITARY', 'ENGITOOLS-M-VENT'},
    'heating': {'ENGITOOLS-M-HEATING_SUPPLY', 'ENGITOOLS-M-HEATING_RETURN'},
    'cooling': {'ENGITOOLS-M-COOLING', 'ENGITOOLS-M-CONDENSATE'},
    'gas': {'ENGITOOLS-M-GAS'},
    'ventilation_exhaust': {'ENGITOOLS-M-EXHAUST_VENTILATION'},
    'roof_rainwater': {'ENGITOOLS-M-ROOF_RAINWATER'},
}


def _families(manifest):
    return {str(x.get('family') or '') for x in (manifest or {}).get('sheets') or []}


def _layer_has_engineering_content(msp, layer):
    for entity in msp:
        if str(getattr(entity.dxf, 'layer', '') or '') != layer:
            continue
        if entity.dxftype() in {'LINE', 'LWPOLYLINE', 'POLYLINE', 'INSERT', 'TEXT', 'MTEXT', 'CIRCLE', 'ARC'}:
            return True
    return False


def _special_sheet_content(doc, manifest):
    checks = {}
    for sheet in (manifest or {}).get('sheets') or []:
        if not sheet.get('special'):
            continue
        code = str(sheet.get('code') or '')
        try:
            layout = doc.layouts.get(code)
        except Exception:
            checks[f'special:{code}'] = False
            continue
        # Special sheets must contain role-specific paper-space information.
        # A bare renamed layout/viewport is not an acceptable deliverable.
        substantive = [e for e in layout if e.dxftype() != 'VIEWPORT']
        checks[f'special:{code}'] = len(substantive) >= 3
    return checks


def validate_generated_mechanical_output(path, calc, meta):
    manifest = (calc or {}).get('_approved_drawing_manifest') or {}
    expected = [str(x.get('code') or '') for x in manifest.get('sheets') or []]
    if not expected or int(manifest.get('total_sheets') or -1) != len(expected):
        raise RuntimeError('Engineering QA blocked: approved drawing manifest is missing or invalid.')

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    actual = [layout.name for layout in doc.layouts if layout.name.startswith('M-')]
    families = _families(manifest)
    technical = (meta or {}).get('technical_design') or {}
    network = technical.get('shared_distribution_network') or {}
    quality = (meta or {}).get('technical_quality') or {}
    compact = (meta or {}).get('compact_output') or {}

    checks = {
        'approved_manifest_exact_order': actual == expected,
        'approved_manifest_exact_count': len(actual) == len(expected),
        'base_technical_quality_10_of_10': quality.get('score_10') == 10.0 and not quality.get('failed'),
        'compact_output_pass': compact.get('status') == 'PASS',
        'dxf_audit_clean': len(doc.audit().errors) == 0,
    }

    for family in sorted(families):
        required = FAMILY_LAYERS.get(family) or set()
        for layer in sorted(required):
            checks[f'{family}:{layer}'] = _layer_has_engineering_content(msp, layer)

    if {'water_supply', 'sanitary_vent'} & families:
        checks['water_sanitary_engine_pass'] = network.get('water_sanitary_status') == 'PASS'
    if 'gas' in families:
        checks['gas_engine_pass'] = network.get('gas_network_status') in {'PASS', 'NOT_APPLICABLE'}
    if {'heating', 'cooling', 'ventilation_exhaust'} & families:
        checks['hvac_ventilation_engine_pass'] = network.get('hvac_ventilation_status') == 'PASS'

    rain = validate_rainwater(doc, manifest, technical)
    checks['rainwater_engine_pass'] = rain.get('status') in {'PASS', 'NOT_APPLICABLE'}
    checks.update(_special_sheet_content(doc, manifest))

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        'status': 'PASS' if not failed else 'FAIL',
        'checks': checks,
        'failed': failed,
        'expected_layouts': expected,
        'generated_layouts': actual,
        'rainwater': rain,
        'professional_review_required': True,
        'statutory_approval_claimed': False,
    }
    if failed:
        raise RuntimeError('Mechanical final engineering QA failed: ' + ', '.join(failed))
    return report
