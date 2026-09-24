from ezdxf import bbox

from . import main_auto
from .drawing_unit_sanity import dimension_measurements as _dimension_measurements, infer_drawing_unit_scale as _infer_scale

_original_analyze_dxf_enhanced = main_auto.analyze_dxf_enhanced


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
