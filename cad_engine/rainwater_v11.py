"""Roof rainwater network and viewport-visibility hardening."""
import math


def _families(calc):
    return {str(x.get('family') or '') for x in (calc.get('_approved_drawing_manifest') or {}).get('sheets') or []}


def _valid_point(value):
    try:
        return float(value[0]), float(value[1])
    except (TypeError, ValueError, IndexError):
        return None


def _proposed_drain_points(level, count, v10_4):
    """Return coordinated proposal points inside the detected roof envelope."""
    count = max(1, int(count or 0))
    evidence = [
        _valid_point(item.get('point'))
        for item in (level.get('rooms') or []) + (level.get('fixtures') or [])
    ]
    evidence = [point for point in evidence if point is not None]
    title = _valid_point((level.get('title') or {}).get('point')) or (0.0, 0.0)
    try:
        xmin, ymin, xmax, ymax = v10_4.v8._level_bounds(level, evidence)
    except Exception:
        xmin, ymin, xmax, ymax = title[0] - 5.0, title[1] - 5.0, title[0] + 5.0, title[1] + 5.0
    width = max(float(xmax) - float(xmin), 1.0)
    height = max(float(ymax) - float(ymin), 1.0)
    inset_x = width * .16
    inset_y = height * .16
    candidates = [
        (xmin + inset_x, ymin + inset_y),
        (xmax - inset_x, ymax - inset_y),
        (xmax - inset_x, ymin + inset_y),
        (xmin + inset_x, ymax - inset_y),
        ((xmin + xmax) / 2, ymin + inset_y),
        ((xmin + xmax) / 2, ymax - inset_y),
        (xmin + inset_x, (ymin + ymax) / 2),
        (xmax - inset_x, (ymin + ymax) / 2),
    ]
    # More than eight drains are uncommon, but keep the proposal deterministic.
    while len(candidates) < count:
        index = len(candidates)
        angle = 2 * math.pi * index / count
        candidates.append((
            (xmin + xmax) / 2 + width * .30 * math.cos(angle),
            (ymin + ymax) / 2 + height * .30 * math.sin(angle),
        ))
    return candidates[:count]


def _prepare_roof_drains(levels, model, v10_4):
    """Preserve detected drains; otherwise add traceable Rulebook proposals."""
    required = int(model.get('roof_drain_count') or 0)
    if required <= 0:
        return 0
    roofs = [level for level in levels if v10_4.v8._is_roof(level)]
    if not roofs:
        return 0
    proposed = 0
    for level in roofs:
        valid = [
            dict(drain, point=_valid_point(drain.get('point')))
            for drain in (level.get('roof_drains') or [])
            if _valid_point(drain.get('point')) is not None
        ]
        if valid:
            level['roof_drains'] = valid
            continue
        points = _proposed_drain_points(level, required, v10_4)
        level['roof_drains'] = [
            {
                'point': point,
                'source': 'rulebook_coordinated_proposal',
                'provenance': 'Rule-based Proposed',
            }
            for point in points
        ]
        proposed += len(points)
    return proposed


def install(v10_4):
    if getattr(v10_4, '_rainwater_v11_installed', False):
        return
    original_symbols = v10_4._add_standard_symbols

    def symbols_with_rain(doc, levels, model):
        proposed = _prepare_roof_drains(levels, model, v10_4)
        count = original_symbols(doc, levels, model)
        msp = doc.modelspace()
        routes = 0
        drains = 0
        for level in levels:
            roof_drains = [d for d in (level.get('roof_drains') or []) if _valid_point(d.get('point'))]
            if not roof_drains:
                continue
            hub = v10_4.v8._find_level_riser(msp, level)
            if not hub:
                xs = [d['point'][0] for d in roof_drains]
                ys = [d['point'][1] for d in roof_drains]
                hub = (sum(xs) / len(xs), sum(ys) / len(ys))
                v10_4._plan_text(
                    msp,
                    'RAINWATER STACK LOCATION [RULE-BASED PROPOSED - COORDINATE]',
                    hub, 'ENGITOOLS-M-ROOF_RAINWATER', (.3, .3),
                )
            for drain in roof_drains:
                point = drain['point']
                drains += 1
                if drain.get('source') == 'rulebook_coordinated_proposal':
                    v10_4._plan_text(
                        msp,
                        'RD LOCATION [RULE-BASED PROPOSED - ENGINEER COORDINATION REQUIRED]',
                        point, 'ENGITOOLS-M-ROOF_RAINWATER', (.18, -.24),
                    )
                elbow = (hub[0], point[1])
                if math.dist(point, elbow) <= 1e-9:
                    elbow = (point[0], hub[1])
                if math.dist(point, elbow) > 1e-9:
                    msp.add_line(point, elbow, dxfattribs={'layer': 'ENGITOOLS-M-ROOF_RAINWATER'})
                    routes += 1
                if math.dist(elbow, hub) > 1e-9:
                    msp.add_line(elbow, hub, dxfattribs={'layer': 'ENGITOOLS-M-ROOF_RAINWATER'})
                    routes += 1
                mid = ((point[0] + elbow[0]) / 2, (point[1] + elbow[1]) / 2)
                v10_4._plan_text(
                    msp,
                    f"RW DN{model.get('roof_drain_dn_mm')} | FLOW TO STACK | SLOPE TO RD",
                    mid, 'ENGITOOLS-M-ROOF_RAINWATER', (.18, .14),
                )
            v10_4._plan_text(
                msp,
                f"RAINWATER STACK DN{model.get('roof_drain_dn_mm')} | Q={model.get('roof_flow_lps')} L/s [CALCULATED]",
                hub, 'ENGITOOLS-M-ROOF_RAINWATER', (.35, -.28),
            )
        model['rainwater_network_drains'] = drains
        model['rainwater_network_segments'] = routes
        model['rainwater_proposed_drain_locations'] = proposed
        model['rainwater_location_provenance'] = (
            'Rule-based Proposed - engineer roof coordination required' if proposed else 'Detected/Provided'
        )
        return count + routes

    v10_4._add_standard_symbols = symbols_with_rain
    v10_4._rainwater_v11_installed = True


def validate_rainwater(doc, manifest, model):
    families = {str(x.get('family') or '') for x in (manifest or {}).get('sheets') or []}
    if 'roof_rainwater' not in families and not any(str(x.get('code') or '').endswith('-RAIN') for x in (manifest or {}).get('sheets') or []):
        return {'status': 'NOT_APPLICABLE'}
    msp = doc.modelspace()
    canonical = 'ENGITOOLS-M-ROOF_RAINWATER'
    line_count = sum(
        1 for e in msp
        if e.dxftype() in {'LINE', 'LWPOLYLINE'}
        and str(getattr(e.dxf, 'layer', '')) == canonical
    )
    drain_count = sum(
        1 for e in msp.query('INSERT')
        if str(e.dxf.name) == 'ET_M_ROOF_DRAIN' and str(e.dxf.layer) == canonical
    )
    required = int(model.get('roof_drain_count') or drain_count or 0)
    checks = {
        'roof_drains_present': drain_count > 0,
        'drain_count_matches_basis': required == 0 or drain_count >= required,
        'rainwater_route_present': line_count >= max(1, drain_count),
        'rainwater_dn_resolved': model.get('roof_drain_dn_mm') not in (None, '', False),
    }
    failed = [k for k, v in checks.items() if not v]
    if failed:
        raise RuntimeError('Rainwater QA failed: ' + ', '.join(failed))
    return {
        'status': 'PASS', 'checks': checks, 'drains': drain_count,
        'segments': line_count,
        'proposed_drain_locations': int(model.get('rainwater_proposed_drain_locations') or 0),
        'location_provenance': model.get('rainwater_location_provenance'),
    }
