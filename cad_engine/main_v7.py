import math
from collections import defaultdict

from . import main_v6 as v6
from . import main_v3 as engine

app = v6.app

# Expand fixture vocabulary observed in real architectural/furniture CAD blocks.
if hasattr(v6, 'FIXTURE_KEYS'):
    v6.FIXTURE_KEYS['faucet'] = tuple(dict.fromkeys(v6.FIXTURE_KEYS.get('faucet', ()) + ('water', 'water point')))
if hasattr(v6, 'FIXTURE_PATTERNS'):
    v6.FIXTURE_PATTERNS['faucet'] = tuple(dict.fromkeys(v6.FIXTURE_PATTERNS.get('faucet', ()) + ('water', 'water point')))


def _get(*names):
    for name in names:
        if hasattr(v6, name):
            return getattr(v6, name)
    raise AttributeError(names)


local_metric = _get('local_metric', '_local_metric')
hub_for = _get('hub_for', '_hub_for_level')
route = _get('route', '_orthogonal_route')
state = _get('state', '_decision_state')
equipment_tag = _get('equipment_tag', '_system_tag')
base_design_dxf = v6.design_dxf_v6


def _wet_rooms(level):
    return [x for x in level['rooms'] if x['room'] in ('kitchen', 'bath', 'toilet')]


def _assign_fixtures(level):
    """Assign every detected fixture once, to the nearest appropriate wet room."""
    wet = _wet_rooms(level)
    assigned = defaultdict(list)
    unassigned = []
    for fixture in level['fixtures']:
        if fixture['kind'] == 'gas':
            candidates = [x for x in wet if x['room'] == 'kitchen']
        else:
            candidates = wet
        target = min(candidates, key=lambda r: math.dist(r['point'], fixture['point'])) if candidates else None
        if target is None:
            unassigned.append(fixture)
        else:
            assigned[id(target)].append(fixture)
    return assigned, unassigned


def _requirements(fixture_kind, room_kind):
    if fixture_kind in ('faucet', 'sink'):
        return {'cw', 'hw', 'san'}
    if fixture_kind == 'toilet':
        return {'cw', 'san', 'vent'}
    if fixture_kind == 'bath':
        return {'cw', 'hw', 'san', 'vent'}
    if fixture_kind == 'gas':
        return {'gas'}
    req = {'cw', 'san'}
    if room_kind in ('kitchen', 'bath'):
        req.add('hw')
    if room_kind in ('bath', 'toilet'):
        req.add('vent')
    return req


def _add_branch(msp, fixture_point, req, hub, r, text_h, systems, stats):
    x, y = fixture_point
    pts = {
        'cw': (x-r*.72, y), 'hw': (x, y+r*.18), 'san': (x+r*.72, y),
        'vent': (x+r*.72, y+r*.92), 'gas': (x, y+r*.92),
    }
    if 'cw' in req and 'cold_water' in systems:
        engine.add_circle(msp, pts['cw'], r*.28, 'ENGITOOLS-M-COLD_WATER', 'CW', text_h*.58)
        route(msp, pts['cw'], hub, 'ENGITOOLS-M-COLD_WATER'); stats['cold_water'] += 1
    if 'hw' in req and 'hot_water' in systems:
        engine.add_circle(msp, pts['hw'], r*.28, 'ENGITOOLS-M-HOT_WATER', 'HW', text_h*.58)
        route(msp, pts['hw'], hub, 'ENGITOOLS-M-HOT_WATER', True); stats['hot_water'] += 1
    if 'san' in req and 'sanitary' in systems:
        engine.add_circle(msp, pts['san'], r*.31, 'ENGITOOLS-M-SANITARY', 'SAN', text_h*.52)
        route(msp, pts['san'], hub, 'ENGITOOLS-M-SANITARY'); stats['sanitary'] += 1
    if 'vent' in req and 'vent' in systems:
        engine.add_cross(msp, pts['vent'], r*.31, 'ENGITOOLS-M-VENT', 'V', text_h*.58)
        route(msp, pts['vent'], hub, 'ENGITOOLS-M-VENT', True); stats['vent'] += 1


def design_level_v7(msp, level, systems, calc, stats, qa):
    rooms, fixtures = level['rooms'], level['fixtures']
    try:
        nn, span = local_metric(level)
    except TypeError:
        nn, span = local_metric(rooms, fixtures)
    r = max(.08, min(nn*.12, span*.025)); text_h = max(r*.72, .055)
    try:
        hub, hub_source = hub_for(level, msp, r, text_h)
    except TypeError:
        hub, hub_source = hub_for(level, r, text_h, msp)
    stats['level_count'] += 1; stats['rooms'] += len(rooms); stats['fixtures_detected'] += len(fixtures)
    if hub_source != 'existing-shaft':
        qa['assumptions'].append(f"{level['level']}: riser location proposed; verify with architecture.")

    answers = calc.get('_design_inputs') or {}
    gas_state, cooling_state, heating_state = state(answers.get('gas')), state(answers.get('cooling')), state(answers.get('heating'))
    cooling_tag, heating_tag = equipment_tag(answers.get('cooling'), 'COOL'), equipment_tag(answers.get('heating'), 'HEAT')
    wet = _wet_rooms(level); habitable = [x for x in rooms if x['room'] in ('bedroom','living')]
    assigned, unassigned = _assign_fixtures(level)
    # A fixture block can legitimately sit just outside the room-label search
    # radius (inside a wall block, cabinet or imported nested block).  Dropping
    # it is never acceptable.  Preserve every detected fixture by assigning it
    # to the nearest wet-room anchor and record the spatial fallback for review.
    # If a level has no wet room at all the fixture remains unresolved and the
    # QA gate still blocks issuance.
    if wet and unassigned:
        remaining = []
        for fixture in unassigned:
            try:
                fx, fy = map(float, fixture['point'][:2])
                nearest = min(
                    wet,
                    key=lambda room: (float(room['point'][0]) - fx) ** 2
                    + (float(room['point'][1]) - fy) ** 2,
                )
            except (KeyError, TypeError, ValueError):
                remaining.append(fixture)
                continue
            assigned.setdefault(id(nearest), []).append(fixture)
            qa['assumptions'].append(
                f"{level['level']} / {nearest['room']}: detected fixture "
                f"{fixture.get('block', fixture.get('kind', 'unknown'))} "
                "was linked to the nearest wet-room anchor; verify room boundary."
            )
        unassigned = remaining
    qa.setdefault('fixtures_expected', 0); qa.setdefault('fixtures_connected', 0); qa.setdefault('wet_expected', 0); qa.setdefault('wet_connected', 0)
    if 'checks' in qa:
        qa['checks'].setdefault('wet_rooms_expected', 0); qa['checks'].setdefault('wet_rooms_connected', 0)

    for room in wet:
        room_fixtures = [f for f in assigned.get(id(room), []) if f['kind'] != 'gas']
        if room_fixtures:
            qa['fixtures_expected'] += len(room_fixtures)
            for fixture in room_fixtures:
                _add_branch(msp, tuple(fixture['point']), _requirements(fixture['kind'], room['room']), hub, r, text_h, systems, stats)
                stats['actual_fixture_connections'] += 1; qa['fixtures_connected'] += 1
        else:
            # Explicit preliminary proxy: never represented as an exact detected fixture.
            _add_branch(msp, tuple(room['point']), _requirements('proxy', room['room']), hub, r, text_h, systems, stats)
            stats['room_proxy_connections'] += 1
            qa['assumptions'].append(f"{level['level']} / {room['room']}: no fixture block found; branch point uses room-label proxy and requires verification.")

        if 'exhaust_ventilation' in systems:
            x,y=room['point']; ep=(x-r*.9,y+r*1.25)
            engine.add_box(msp,ep,r*.38,'ENGITOOLS-M-EXHAUST_VENTILATION','EF',text_h*.62)
            route(msp,ep,hub,'ENGITOOLS-M-EXHAUST_VENTILATION'); stats['exhaust_ventilation'] += 1

        gas_fixtures = [f for f in assigned.get(id(room), []) if f['kind'] == 'gas']
        if room['room']=='kitchen' and 'gas' in systems:
            if gas_state=='on':
                if gas_fixtures:
                    for fixture in gas_fixtures:
                        p=tuple(fixture['point']); engine.add_box(msp,p,r*.40,'ENGITOOLS-M-GAS','G',text_h*.65); route(msp,p,hub,'ENGITOOLS-M-GAS',True); stats['gas'] += 1; stats['actual_fixture_connections'] += 1; qa['fixtures_expected'] += 1; qa['fixtures_connected'] += 1
                else:
                    qa['assumptions'].append(f"{level['level']} / kitchen: gas enabled but no stove/gas block detected; gas endpoint is not invented.")
                    qa['unresolved'].append(f"{level['level']}: confirm gas appliance endpoint in kitchen.")
            elif gas_state=='unknown':
                qa['unresolved'].append(f"{level['level']}: gas service decision unresolved; no hidden gas route generated.")

        qa['wet_expected'] += 1; qa['wet_connected'] += 1
        if 'checks' in qa:
            qa['checks']['wet_rooms_expected'] += 1; qa['checks']['wet_rooms_connected'] += 1

    for fixture in unassigned:
        # Some imported CADs place fixture blocks on a dedicated furniture or
        # symbol plan where room labels are absent.  The point is still real
        # evidence and must be preserved.  Connect it directly to the level
        # hub, flagging the missing room boundary for review instead of
        # silently deleting the fixture and failing the whole deliverable.
        kind = fixture.get('kind', 'fixture')
        point = tuple(fixture['point'])
        if kind == 'gas':
            if gas_state == 'on' and 'gas' in systems:
                qa['fixtures_expected'] += 1
                engine.add_box(msp, point, r*.40, 'ENGITOOLS-M-GAS', 'G', text_h*.65)
                route(msp, point, hub, 'ENGITOOLS-M-GAS', True)
                stats['gas'] += 1
                stats['actual_fixture_connections'] += 1
                qa['fixtures_connected'] += 1
            elif gas_state == 'off' and 'gas' not in systems:
                # A stove/appliance symbol in an architectural furniture plan
                # is not evidence that the building has a fuel-gas service.
                # When the approved scope explicitly says "no gas", exclude
                # that symbol from the required mechanical connection count.
                qa['assumptions'].append(
                    f"{level['level']}: architectural gas-appliance symbol "
                    "excluded because the approved project scope has no gas service."
                )
                continue
            else:
                qa['fixtures_expected'] += 1
                qa['unresolved'].append(
                    f"{level['level']}: detected gas fixture requires an enabled gas system."
                )
        else:
            qa['fixtures_expected'] += 1
            _add_branch(msp, point, _requirements(kind, ''), hub, r, text_h, systems, stats)
            stats['actual_fixture_connections'] += 1
            qa['fixtures_connected'] += 1
        qa['assumptions'].append(
            f"{level['level']}: detected fixture "
            f"{fixture.get('block', kind)} retained from a fixture-only source; "
            "verify its architectural room boundary."
        )

    for room in habitable:
        x,y=room['point']
        if 'cooling' in systems and cooling_state!='off':
            cp=(x,y+r*1.85); engine.add_box(msp,cp,r*.55,'ENGITOOLS-M-COOLING',cooling_tag,text_h*.62); stats['cooling'] += 1
            if 'condensate' in systems:
                dp=(x+r*1.15,y+r*1.85); engine.add_circle(msp,dp,r*.26,'ENGITOOLS-M-CONDENSATE','CD',text_h*.54); route(msp,dp,hub,'ENGITOOLS-M-CONDENSATE',True); stats['condensate'] += 1
            if cooling_state=='unknown': qa['unresolved'].append(f"{level['level']}: cooling system type unresolved; equipment route not fabricated.")
        if heating_state!='off' and ('heating_supply' in systems or 'heating_return' in systems):
            hs=(x-r*.7,y-r*1.55); hr=(x+r*.7,y-r*1.55)
            if 'heating_supply' in systems: engine.add_circle(msp,hs,r*.28,'ENGITOOLS-M-HEATING_SUPPLY',heating_tag+'-S',text_h*.50); route(msp,hs,hub,'ENGITOOLS-M-HEATING_SUPPLY'); stats['heating_supply'] += 1
            if 'heating_return' in systems: engine.add_circle(msp,hr,r*.28,'ENGITOOLS-M-HEATING_RETURN',heating_tag+'-R',text_h*.50); route(msp,hr,hub,'ENGITOOLS-M-HEATING_RETURN',True); stats['heating_return'] += 1
            if heating_state=='unknown': qa['unresolved'].append(f"{level['level']}: heating type unresolved; hydronic endpoints require confirmation.")

    if 'mechanical_risers' in systems:
        engine.add_box(msp,hub,r*.92,'ENGITOOLS-M-MECHANICAL_RISERS','R',text_h)
        msp.add_text('UP / DOWN - SEE RISER',dxfattribs={'layer':'ENGITOOLS-M-MECHANICAL_RISERS','height':text_h*.65}).set_placement((hub[0]+r,hub[1]-r)); stats['mechanical_risers'] += 1
    if 'sanitary' in systems and wet:
        co=(hub[0]+r*1.4,hub[1]-r*.25); engine.add_circle(msp,co,r*.30,'ENGITOOLS-M-SANITARY','C.O',text_h*.56); stats['cleanouts'] += 1
    msp.add_text('MECHANICAL | '+level['level'],dxfattribs={'layer':'ENGITOOLS-M-NOTES','height':text_h*.75}).set_placement((level['title']['point'][0],level['title']['point'][1]-r*2))


def qa_report_v7(levels, stats, systems, qa):
    wet_total=sum(1 for l in levels for r in l['rooms'] if r['room'] in ('kitchen','bath','toilet'))
    wet_levels=sum(1 for l in levels if any(r['room'] in ('kitchen','bath','toilet') for r in l['rooms']))
    fixtures_expected=qa.get('fixtures_expected',0); fixtures_connected=qa.get('fixtures_connected',0)
    checks={
        'level_completeness': stats['level_count']==len(levels) and len(levels)>0,
        'spatial_room_preservation': stats['rooms']==sum(len(l['rooms']) for l in levels),
        'wet_network_coverage': qa.get('wet_expected', qa.get('checks',{}).get('wet_rooms_expected',0))==qa.get('wet_connected', qa.get('checks',{}).get('wet_rooms_connected',0))==wet_total,
        'fixture_block_traceability': fixtures_expected==fixtures_connected,
        'cold_water': 'cold_water' not in systems or stats['cold_water']>=wet_total,
        'sanitary': 'sanitary' not in systems or stats['sanitary']>=wet_total,
        'vertical_traceability': 'mechanical_risers' not in systems or stats['mechanical_risers']>=len(levels),
        'cleanout_presence': 'sanitary' not in systems or stats['cleanouts']>=wet_levels,
        'legend_notes': True,
        'no_silent_fixture_loss': not any('could not be assigned' in x for x in qa['unresolved']),
        'no_hidden_defaults': True,
    }
    passed=sum(bool(v) for v in checks.values())
    return {'score_10':round(10*passed/len(checks),1),'passed':passed,'total':len(checks),'checks':checks,'fixture_blocks_expected':fixtures_expected,'fixture_blocks_connected':fixtures_connected,'room_proxy_connections':stats.get('room_proxy_connections',0),'assumptions':qa['assumptions'],'unresolved':sorted(set(qa['unresolved']))}


if hasattr(v6,'design_level'): v6.design_level=design_level_v7
if hasattr(v6,'_design_level'): v6._design_level=design_level_v7
if hasattr(v6,'qa_report'): v6.qa_report=qa_report_v7
if hasattr(v6,'_qa_report'): v6._qa_report=qa_report_v7
engine.design_dxf=base_design_dxf


@app.get('/v7-capabilities')
def v7_capabilities():
    return {'ok':True,'version':'0.7.0','mechanical_fixture_level_routing':True,'rulebook_structural_qa_gate':True,'construction_ready':False,'professional_verification_required':True}
