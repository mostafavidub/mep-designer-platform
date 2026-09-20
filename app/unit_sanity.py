import re
import statistics

from ezdxf import bbox

from . import main_auto

_original_analyze_dxf_enhanced = main_auto.analyze_dxf_enhanced
_original_infer_architecture_facts = main_auto.infer_architecture_facts


def _dimension_measurements(doc):
    values = []
    for entity in doc.modelspace().query('DIMENSION'):
        try:
            value = abs(float(entity.get_measurement()))
        except Exception:
            continue
        if 0.001 <= value <= 100000:
            values.append(value)
    return values


def _text_value(entity):
    try:
        return str(entity.dxf.text if entity.dxftype() == 'TEXT' else entity.text or '')
    except Exception:
        return ''


def _paper_space_metre_evidence(doc):
    """Detect a metre-authored plan plotted in centimetre-sized paper frames.

    This is intentionally conjunctive.  A scale label, an A-series frame and
    repeated architectural opening/height dimensions must all agree; none of
    them alone is allowed to turn an unknown DXF unit into an engineering unit.
    """
    texts = [_text_value(entity) for entity in doc.modelspace().query('TEXT MTEXT')]
    has_scale_100 = any(re.search(r'(?i)(?:sc(?:ale)?\s*[:=]?\s*)?1\s*[/ :]\s*100', text) for text in texts)
    metric_tokens = []
    canonical = (0.75, 0.8, 0.9, 1.0, 1.1, 1.2, 2.0, 2.1, 2.2, 2.3)
    for text in texts:
        normalized = text.replace('/', '.').replace(',', '.')
        for raw in re.findall(r'(?<!\d)(\d+(?:\.\d+)?)(?!\d)', normalized):
            try:
                value = float(raw)
            except ValueError:
                continue
            if any(abs(value - candidate) <= 0.015 for candidate in canonical):
                metric_tokens.append(value)
    a_series_frames = 0
    for entity in doc.modelspace().query('LWPOLYLINE POLYLINE'):
        try:
            extent = bbox.extents([entity], fast=True)
            if not extent.has_data:
                continue
            width = abs(float(extent.extmax.x - extent.extmin.x))
            height = abs(float(extent.extmax.y - extent.extmin.y))
        except Exception:
            continue
        short, long = sorted((width, height))
        if ((20.5 <= short <= 21.5 and 29.0 <= long <= 30.5) or
                (29.0 <= short <= 30.5 and 41.0 <= long <= 43.0)):
            a_series_frames += 1
    passed = bool(has_scale_100 and a_series_frames >= 1 and len(metric_tokens) >= 4)
    return {
        'status': 'PASS' if passed else 'INSUFFICIENT_EVIDENCE',
        'scale_1_100_label': has_scale_100,
        'a_series_frame_count': a_series_frames,
        'canonical_metric_dimension_token_count': len(metric_tokens),
    }


def _infer_scale(doc):
    insunits = int(doc.header.get('$INSUNITS', 0) or 0)
    header_scale = main_auto.INSUNITS_TO_M.get(insunits)
    values = _dimension_measurements(doc)
    median_dim = statistics.median(values) if values else None

    paper_evidence = _paper_space_metre_evidence(doc) if not header_scale else None
    scale = header_scale
    source = 'header' if header_scale else 'unknown'
    confidence = 'medium' if header_scale else 'low'

    # Architectural drawings are frequently authored in metres while the DXF
    # header still says millimetres. A typical dimension measurement of 0.2..50
    # drawing units cannot represent 0.2..50 mm room/building dimensions.
    if insunits == 4 and median_dim is not None and 0.20 <= median_dim <= 50.0:
        scale = 1.0
        source = 'dimension-measurement-override-mm-header-to-m'
        confidence = 'high'
    elif insunits == 6 and median_dim is not None and 200.0 <= median_dim <= 50000.0:
        scale = 0.001
        source = 'dimension-measurement-override-m-header-to-mm'
        confidence = 'high'
    elif not header_scale and paper_evidence and paper_evidence['status'] == 'PASS':
        scale = 1.0
        source = 'multi-evidence-paper-frame-scale-and-architectural-dimensions'
        confidence = 'high'

    return {
        'header_insunits': insunits,
        'header_scale_to_m': header_scale,
        'effective_scale_to_m': scale,
        'dimension_count': len(values),
        'median_dimension_drawing_units': round(median_dim, 6) if median_dim is not None else None,
        'source': source,
        'confidence': confidence,
        'paper_space_metre_evidence': paper_evidence,
    }


def analyze_dxf_enhanced(path):
    result = _original_analyze_dxf_enhanced(path)
    doc, _recovery = main_auto.legacy.read_input_dxf(path)
    unit = _infer_scale(doc)
    result['unit_inference'] = unit
    result['effective_unit_to_m'] = unit['effective_scale_to_m']

    bounds = result.get('geometry_bounds')
    scale = unit.get('effective_scale_to_m')
    if bounds and scale:
        minx, miny, maxx, maxy = bounds
        width = abs(maxx - minx) * scale
        height = abs(maxy - miny) * scale
        # Global modelspace often contains many separated plans. Never convert
        # that global extent into a fake building area. Keep geometry-derived
        # area only when the extent itself is a plausible single building plan.
        aspect = max(width, height) / max(min(width, height), 1e-9)
        plausible_single_plan = 2 <= width <= 500 and 2 <= height <= 500 and aspect <= 12
        if plausible_single_plan:
            result['geometry_width_m'] = round(width, 3)
            result['geometry_height_m'] = round(height, 3)
            result['geometry_area_m2'] = round(width * height, 2)
            result['geometry_scope'] = 'single-plan-plausible'
        else:
            result['geometry_width_m'] = None
            result['geometry_height_m'] = None
            result['geometry_area_m2'] = None
            result['geometry_scope'] = 'multi-plan-or-presentation-extents-rejected'
    return result


def _aggregate_unit_inference(analysis):
    rows=[]
    for item in (analysis or {}).get('files') or []:
        scale=item.get('effective_unit_to_m')
        evidence=item.get('unit_inference') or {}
        try: scale=float(scale)
        except (TypeError,ValueError): continue
        if scale <= 0 or evidence.get('confidence') not in {'high','medium'}:
            continue
        rows.append({'file':item.get('file'),'scale_to_m':scale,'evidence':evidence})
    file_count=len((analysis or {}).get('files') or [])
    if not rows or len(rows) != file_count:
        return {'status':'INPUT_REQUIRED','effective_scale_to_m':None,
                'errors':['CALIBRATED_ARCHITECTURAL_UNIT_REQUIRED'],'files':rows}
    scales={round(row['scale_to_m'],12) for row in rows}
    if len(scales) != 1:
        return {'status':'INPUT_REQUIRED','effective_scale_to_m':None,
                'errors':['CONFLICTING_ARCHITECTURAL_FILE_UNITS'],'files':rows}
    return {'status':'PASS','effective_scale_to_m':rows[0]['scale_to_m'],
            'errors':[],'files':rows,'provenance':'per-file-converging-unit-evidence'}


def infer_architecture_facts(analysis, discipline):
    result=_original_infer_architecture_facts(analysis,discipline)
    project_unit=_aggregate_unit_inference(analysis)
    result['unit_inference']=project_unit
    result['effective_unit_to_m']=project_unit['effective_scale_to_m']
    return result


# Patch module globals used by analyze_project_job and legacy workflow.
main_auto.analyze_dxf_enhanced = analyze_dxf_enhanced
main_auto.legacy.analyze_dxf = analyze_dxf_enhanced
main_auto.infer_architecture_facts = infer_architecture_facts
