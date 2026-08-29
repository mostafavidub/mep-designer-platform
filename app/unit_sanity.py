import statistics

from ezdxf import bbox

from . import main_auto

_original_analyze_dxf_enhanced = main_auto.analyze_dxf_enhanced


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


def _infer_scale(doc):
    insunits = int(doc.header.get('$INSUNITS', 0) or 0)
    header_scale = main_auto.INSUNITS_TO_M.get(insunits)
    values = _dimension_measurements(doc)
    median_dim = statistics.median(values) if values else None

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

    return {
        'header_insunits': insunits,
        'header_scale_to_m': header_scale,
        'effective_scale_to_m': scale,
        'dimension_count': len(values),
        'median_dimension_drawing_units': round(median_dim, 6) if median_dim is not None else None,
        'source': source,
        'confidence': confidence,
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


# Patch module globals used by analyze_project_job and legacy workflow.
main_auto.analyze_dxf_enhanced = analyze_dxf_enhanced
main_auto.legacy.analyze_dxf = analyze_dxf_enhanced
