"""Water + sanitary network hardening for mechanical v11.

The existing v10.4 hydraulic calculations remain authoritative. This module
ensures the plan geometry is a real connected network: every applicable level
gets branches, trunks, valves/cleanouts, flow tags, and hot-water service where
architecture provides hot-water consumers.
"""
from collections import Counter


def _line_count(msp, layer):
    return sum(1 for e in msp if e.dxftype() in {'LINE', 'LWPOLYLINE'} and str(getattr(e.dxf, 'layer', '')) == layer)


def _text_count(msp, layer, token=None):
    count = 0
    for e in msp:
        if e.dxftype() not in {'TEXT', 'MTEXT'} or str(getattr(e.dxf, 'layer', '')) != layer:
            continue
        value = str(getattr(e.dxf, 'text', '') or '') if e.dxftype() == 'TEXT' else str(e.plain_text() or '')
        if token is None or token in value:
            count += 1
    return count


def _insert_count(msp, name, layer=None):
    count = 0
    for e in msp.query('INSERT'):
        if str(e.dxf.name) != name:
            continue
        if layer and str(e.dxf.layer) != layer:
            continue
        count += 1
    return count


def _families(calc):
    return {str(x.get('family') or '') for x in (calc.get('_approved_drawing_manifest') or {}).get('sheets') or []}


def install(v10_4):
    if getattr(v10_4, '_water_sanitary_v11_installed', False):
        return
    original = v10_4._add_shared_distribution_networks

    def hardened(doc, levels, model, calc):
        report = dict(original(doc, levels, model, calc) or {})
        families = _families(calc)
        msp = doc.modelspace()

        # The base engine routes hot water only to detected sink/faucet/bath
        # fixtures. Consultant drawings can identify a wet consumer by room
        # geometry while the symbol itself is exploded. Add a traceable
        # rule-based hot-water connection zone in that case; never invent a
        # fixture type or quantity.
        if 'water_supply' in families and _line_count(msp, 'ENGITOOLS-M-HOT_WATER') == 0:
            seen = set()
            for level in levels:
                hub = v10_4.v8._find_level_riser(msp, level)
                if not hub:
                    continue
                rooms = [r for r in level.get('rooms', []) if r.get('room') in {'kitchen', 'bath'} and r.get('point')]
                if not rooms:
                    continue
                terminals = [(r['point'][0], r['point'][1] + 0.18) for r in rooms]
                row = v10_4._shared_network(
                    msp, terminals, hub, 'ENGITOOLS-M-HOT_WATER', 'water', model, seen,
                )
                report['hot_water_rule_based_terminals'] = report.get('hot_water_rule_based_terminals', 0) + row['terminals']
                for r in rooms:
                    v10_4._plan_text(
                        msp, 'HW CONNECTION ZONE [RULE-BASED PROPOSED]', r['point'],
                        'ENGITOOLS-M-HOT_WATER', (.22, .28),
                    )

        checks = {}
        if 'water_supply' in families and levels:
            checks['cold_water_network'] = _line_count(msp, 'ENGITOOLS-M-COLD_WATER') >= 2
            checks['hot_water_network'] = _line_count(msp, 'ENGITOOLS-M-HOT_WATER') >= 1
            checks['water_sizing_tags'] = _text_count(msp, 'ENGITOOLS-M-COLD_WATER', 'DN') >= 1
            checks['water_isolation'] = _insert_count(msp, 'ET_M_ISOLATION_VALVE') >= 1
        if 'sanitary_vent' in families and levels:
            checks['sanitary_network'] = _line_count(msp, 'ENGITOOLS-M-SANITARY') >= 2
            checks['vent_network'] = _line_count(msp, 'ENGITOOLS-M-VENT') >= 1
            checks['sanitary_slope_tags'] = _text_count(msp, 'ENGITOOLS-M-SANITARY', 'S=') >= 1
            checks['sanitary_cleanout'] = _insert_count(msp, 'ET_M_CLEANOUT') >= 1

        failed = [name for name, passed in checks.items() if not passed]
        report['water_sanitary_checks'] = checks
        report['water_sanitary_status'] = 'PASS' if not failed else 'FAIL'
        if failed:
            raise RuntimeError('Water/Sanitary network QA failed: ' + ', '.join(failed))
        return report

    v10_4._add_shared_distribution_networks = hardened
    v10_4._water_sanitary_v11_installed = True
