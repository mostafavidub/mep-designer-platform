"""Stage 13 — remove non-selected architectural sheets from issued mechanical DXF."""
from __future__ import annotations

from ezdxf import bbox


def _inside(point, bounds, tol=0.02):
    x, y = point
    x1, y1, x2, y2 = bounds
    return x1 - tol <= x <= x2 + tol and y1 - tol <= y <= y2 + tol


def _entity_bounds(entity):
    try:
        ext = bbox.extents([entity], fast=True)
        if ext.has_data:
            return [float(ext.extmin.x), float(ext.extmin.y), float(ext.extmax.x), float(ext.extmax.y)]
    except Exception:
        pass
    for attr in ('insert', 'location', 'start', 'center'):
        try:
            p = getattr(entity.dxf, attr)
            x, y = float(p.x), float(p.y)
            return [x, y, x, y]
        except Exception:
            continue
    return None


def _center(bounds):
    return ((bounds[0] + bounds[2]) / 2.0, (bounds[1] + bounds[3]) / 2.0)


def sanitize_to_selected_plans(doc, selected_plans):
    """Delete visible modelspace entities not owned by a selected sheet.

    This runs after the design manifest is fixed. It intentionally keeps only
    architectural underlay + MEP content whose geometric centre lies inside one
    selected plan frame. Block/layer definitions may remain in the DXF database,
    but no non-selected drawing geometry remains visible in modelspace.
    """
    msp = doc.modelspace()
    bounds = [list(p['bounds']) for p in selected_plans]
    removed = 0
    for entity in list(msp):
        eb = _entity_bounds(entity)
        if eb is None or not any(_inside(_center(eb), b) for b in bounds):
            try:
                msp.delete_entity(entity)
                removed += 1
            except Exception:
                pass
    return {'version': 'output-sanitizer-v13.14', 'removed_entities': removed}


def validate_sanitized_output(doc, selected_plans):
    msp = doc.modelspace()
    bounds = [list(p['bounds']) for p in selected_plans]
    outside = []
    for entity in msp:
        eb = _entity_bounds(entity)
        if eb is None:
            continue
        if not any(_inside(_center(eb), b) for b in bounds):
            outside.append({'type': entity.dxftype(), 'layer': str(getattr(entity.dxf, 'layer', '') or '')})
    return {
        'status': 'PASS' if not outside else 'FAIL',
        'errors': [] if not outside else ['non_selected_sheet_entities'],
        'metrics': {'non_selected_sheet_entities': len(outside)},
    }
