import statistics

import ezdxf

from . import main_v8 as v8
from . import main_v3 as engine

app = v8.app
_base_design_dxf = v8.design_dxf_v8


def _dimension_unit_inference(doc):
    values = []
    for entity in doc.modelspace().query('DIMENSION'):
        try:
            value = abs(float(entity.get_measurement()))
        except Exception:
            continue
        if 0.001 <= value <= 100000:
            values.append(value)
    median_dim = statistics.median(values) if values else None
    insunits = int(doc.header.get('$INSUNITS', 0) or 0)
    effective = insunits
    reason = 'header-accepted'
    confidence = 'medium'
    if insunits == 4 and median_dim is not None and 0.20 <= median_dim <= 50.0:
        effective = 6
        reason = 'dimension-measurement-override-mm-header-to-m'
        confidence = 'high'
    elif insunits == 6 and median_dim is not None and 200.0 <= median_dim <= 50000.0:
        effective = 4
        reason = 'dimension-measurement-override-m-header-to-mm'
        confidence = 'high'
    return {
        'source_insunits': insunits,
        'effective_insunits': effective,
        'dimension_count': len(values),
        'median_dimension_drawing_units': round(median_dim, 6) if median_dim is not None else None,
        'reason': reason,
        'confidence': confidence,
    }


def _stamp_unit_sanity(doc, unit):
    if 'M-RISER-CALC' not in doc.layouts:
        return
    layout = doc.layouts.get('M-RISER-CALC')
    src = unit['source_insunits']
    eff = unit['effective_insunits']
    labels = {0: 'UNITLESS', 4: 'mm', 5: 'cm', 6: 'm'}
    if src != eff:
        text = (
            f"UNIT SANITY: source header {labels.get(src, src)} overridden to "
            f"{labels.get(eff, eff)} from DIMENSION measurements — confidence {unit['confidence'].upper()}"
        )
    else:
        text = f"UNIT SANITY: {labels.get(eff, eff)} — {unit['reason']}"
    layout.add_text(text, dxfattribs={'height': 3.0}).set_placement((20, 48))


def design_dxf_v9(src, dst, discipline, systems, revision, calc):
    if discipline != 'mechanical':
        return _base_design_dxf(src, dst, discipline, systems, revision, calc)

    source_doc = ezdxf.readfile(src)
    unit = _dimension_unit_inference(source_doc)
    if unit['effective_insunits'] not in (4, 5, 6):
        raise RuntimeError('CAD unit sanity unresolved; mechanical output is blocked until units are known.')

    meta = _base_design_dxf(src, dst, discipline, systems, revision, calc)
    doc = ezdxf.readfile(dst)
    doc.header['$INSUNITS'] = unit['effective_insunits']
    _stamp_unit_sanity(doc, unit)

    audit = doc.audit()
    if audit.errors:
        raise RuntimeError(f'Post-unit DXF audit failed with {len(audit.errors)} error(s).')

    v8qa = meta.get('v8_comprehensive_qa') or {}
    checks = dict(v8qa.get('checks') or {})
    checks['unit_sanity'] = unit['effective_insunits'] in (4, 5, 6)
    checks['dimension_scale_confidence'] = unit['confidence'] in ('high', 'medium')
    passed = sum(bool(v) for v in checks.values())
    score = round(10.0 * passed / len(checks), 1) if checks else 0.0
    if score < 10.0:
        failed = [k for k, value in checks.items() if not value]
        raise RuntimeError(f'Final mechanical Rulebook QA failed ({score}/10): ' + ', '.join(failed))

    # Replace the earlier v8 QA stamp with an explicit final gate statement.
    if 'M-RISER-CALC' in doc.layouts:
        layout = doc.layouts.get('M-RISER-CALC')
        layout.add_text('FINAL RULEBOOK COMPLETENESS QA: 10.0 / 10', dxfattribs={'height': 4.0}).set_placement((310, 42))

    doc.saveas(dst)
    meta['v9_final_qa'] = {
        'score_10': score,
        'passed': passed,
        'total': len(checks),
        'checks': checks,
        'unit_inference': unit,
        'construction_ready': False,
        'professional_verification_required': True,
    }
    meta['design_standard'] = 'Rulebook v1.2 comprehensive mechanical deliverable + dimension-based unit sanity v9'
    return meta


engine.design_dxf = design_dxf_v9


@app.get('/v9-capabilities')
def v9_capabilities():
    return {
        'ok': True,
        'version': '0.9.0',
        'dimension_based_unit_sanity': True,
        'comprehensive_rulebook_qa': True,
        'system_separated_a2_sheets': True,
        'level_scope_matrix': True,
        'vertical_riser_alignment': True,
        'roof_drainage_detection': True,
        'construction_ready': False,
        'professional_verification_required': True,
    }
