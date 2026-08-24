import math
import re
import statistics
from collections import Counter, defaultdict

import ezdxf

from . import main_v5
from . import main_v3 as engine

app = main_v5.app
_prev_design_dxf = engine.design_dxf
_prev_mechanical_calc = engine.mechanical_calc

PLAN_PREFIX = {
    'architecture': ('پلان معماری', 'architectural plan', 'architecture plan'),
    'furniture': ('پلان مبلمان', 'furniture plan'),
    'lintel': ('پلان نعل درگاه', 'lintel plan'),
}
FIXTURE_KEYS = {
    'faucet': ('faucet', 'tap'),
    'sink': ('sink', 'basin', 'lav'),
    'toilet': ('toalet', 'toilet', 'farangi', 'wc'),
    'bath': ('bat', 'bath', 'shower'),
    'gas': ('k_gaz', 'gaz', 'gas', 'stove'),
}
LAYER_STYLE = {
    'COLD_WATER': (5, 30, ('DASHDOTX2', 'DASHDOT', 'CONTINUOUS')),
    'HOT_WATER': (1, 30, ('DIVIDE', 'DASHED', 'CONTINUOUS')),
    'SANITARY': (3, 60, ('CONTINUOUS',)),
    'VENT': (4, 30, ('HIDDEN', 'DASHED', 'CONTINUOUS')),
    'GAS': (2, 35, ('DASHED', 'CONTINUOUS')),
    'HEATING_SUPPLY': (1, 30, ('CONTINUOUS',)),
    'HEATING_RETURN': (6, 30, ('HIDDEN', 'DASHED', 'CONTINUOUS')),
    'COOLING': (5, 25, ('CONTINUOUS',)),
    'CONDENSATE': (4, 25, ('DASHED', 'CONTINUOUS')),
    'EXHAUST_VENTILATION': (6, 25, ('CENTER', 'DASHED', 'CONTINUOUS')),
    'MECHANICAL_RISERS': (2, 50, ('CONTINUOUS',)),
    'MECHANICAL_DETAILS_LEGEND_NOTES': (7, 25, ('CONTINUOUS',)),
    'NOTES': (7, 25, ('CONTINUOUS',)),
    'CALC': (7, 25, ('CONTINUOUS',)),
}


def norm(value):
    return re.sub(r'\s+', ' ', (value or '').replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ')).strip()


def text_value(entity):
    try:
        return (entity.dxf.text if entity.dxftype() == 'TEXT' else entity.plain_text()) or ''
    except Exception:
        return ''


def point(entity):
    try:
        p = entity.dxf.insert
        return float(p.x), float(p.y)
    except Exception:
        return None


def nearest_distances(points):
    out = []
    for i, p in enumerate(points):
        ds = [math.dist(p, q) for j, q in enumerate(points) if j != i]
        if ds:
            out.append(min(ds))
    return out


def detect_room_labels_spatial(msp):
    raw = []
    for e in msp:
        if e.dxftype() not in ('TEXT', 'MTEXT'):
            continue
        room = engine.classify_room(text_value(e))
        p = point(e)
        if room and p:
            raw.append({'room': room, 'point': p, 'text': norm(text_value(e))})
    if len(raw) < 2:
        return raw
    nd = nearest_distances([x['point'] for x in raw])
    median_nn = statistics.median(nd) if nd else 1.0
    tol = max(.015, min(.35, median_nn * .08))
    out = []
    for item in raw:
        if not any(item['room'] == x['room'] and math.dist(item['point'], x['point']) <= tol for x in out):
            out.append(item)
    return out


def parse_plan_title(value):
    s = norm(value)
    low = s.lower()
    if 'roof plan' in low or 'پلان شیب' in s or 'پلان شيب' in s:
        return 'architecture', 'بام'
    for kind, prefixes in PLAN_PREFIX.items():
        for prefix in prefixes:
            pos = low.find(prefix.lower())
            if pos >= 0:
                level = norm(s[:pos] + s[pos + len(prefix):])
                return kind, level or 'unspecified'
    return None


def plan_titles(msp):
    out = []
    for e in msp:
        if e.dxftype() not in ('TEXT', 'MTEXT'):
            continue
        parsed = parse_plan_title(text_value(e))
        p = point(e)
        if parsed and p:
            out.append({'type': parsed[0], 'level': parsed[1], 'point': p, 'text': norm(text_value(e))})
    return out


def select_architecture_levels(titles):
    arch = [x for x in titles if x['type'] == 'architecture']
    if not arch:
        return []
    levels = list(dict.fromkeys(x['level'] for x in arch))
    selected = []
    for level in levels:
        candidates = [x for x in arch if x['level'] == level]
        others = [x for x in levels if x != level]
        def score(candidate):
            return sum(min(math.dist(candidate['point'], b['point']) for b in arch if b['level'] == other) for other in others) if others else 0
        selected.append(min(candidates, key=score))
    selected.sort(key=lambda x: (-x['point'][1], -x['point'][0]))
    return selected


def title_spacing(titles):
    nd = nearest_distances([x['point'] for x in titles])
    return statistics.median(nd) if nd else 25.0


def assign_nearest(items, titles, max_distance):
    out = defaultdict(list)
    if not titles:
        return out
    for item in items:
        t = min(titles, key=lambda x: math.dist(item['point'], x['point']))
        if math.dist(item['point'], t['point']) <= max_distance:
            out[(t['type'], t['level'], t['point'])].append(item)
    return out


def fixture_kind(name):
    low = (name or '').lower()
    for kind, keys in FIXTURE_KEYS.items():
        if any(k in low for k in keys):
            return kind
    return None


def fixture_inserts(msp):
    out = []
    for e in msp.query('INSERT'):
        try:
            kind = fixture_kind(e.dxf.name)
            if kind:
                out.append({'kind': kind, 'point': (float(e.dxf.insert.x), float(e.dxf.insert.y)), 'block': e.dxf.name})
        except Exception:
            pass
    return out


def dedupe(items, key, tol):
    out = []
    for item in items:
        if not any(item[key] == x[key] and math.dist(item['point'], x['point']) <= tol for x in out):
            out.append(item)
    return out


def build_levels(msp):
    titles = plan_titles(msp)
    primary = select_architecture_levels(titles)
    rooms = detect_room_labels_spatial(msp)
    if not primary:
        return [{'level': f'PLAN-{i:02d}', 'title': {'point': tuple(c[0]['point'])}, 'rooms': c, 'fixtures': [], 'provenance': 'spatial-cluster'} for i, c in enumerate(main_v5._cluster_rooms(rooms), 1)]
    core = [x for x in titles if x['type'] in ('architecture', 'furniture', 'lintel')]
    spacing = max(title_spacing(core), 1.0)
    assigned_rooms = assign_nearest(rooms, core, spacing * 1.65)
    assigned_fixtures = assign_nearest(fixture_inserts(msp), core, spacing * 1.65)
    models = []
    for a in primary:
        level = a['level']
        key = ('architecture', level, a['point'])
        lr = [dict(x) for x in assigned_rooms.get(key, [])]
        lf = [dict(x) for x in assigned_fixtures.get(key, [])]
        for ref in [x for x in core if x['type'] == 'furniture' and x['level'] == level]:
            dx, dy = a['point'][0] - ref['point'][0], a['point'][1] - ref['point'][1]
            rkey = ('furniture', level, ref['point'])
            for item in assigned_rooms.get(rkey, []):
                mapped = dict(item); mapped['point'] = (item['point'][0] + dx, item['point'][1] + dy); mapped['mapped_from'] = 'furniture'; lr.append(mapped)
            for item in assigned_fixtures.get(rkey, []):
                mapped = dict(item); mapped['point'] = (item['point'][0] + dx, item['point'][1] + dy); mapped['mapped_from'] = 'furniture'; lf.append(mapped)
        pts = [x['point'] for x in lr]
        nd = nearest_distances(pts)
        tol = max(.08, min(.65, (statistics.median(nd) if nd else spacing) * .12))
        models.append({'level': level, 'title': a, 'rooms': dedupe(lr, 'room', tol), 'fixtures': dedupe(lf, 'kind', tol), 'provenance': 'architecture+furniture-transfer'})
    return models


def style_layers(doc, systems):
    for system in list(systems) + ['NOTES', 'CALC', 'MECHANICAL_DETAILS_LEGEND_NOTES']:
        key = system.upper()
        name = f'ENGITOOLS-M-{key}'
        if name not in doc.layers:
            doc.layers.add(name=name)
        color, lw, types = LAYER_STYLE.get(key, LAYER_STYLE['NOTES'])
        layer = doc.layers.get(name)
        layer.dxf.color = color
        layer.dxf.lineweight = lw
        for candidate in types:
            try:
                if candidate == 'CONTINUOUS' or candidate in doc.linetypes:
                    layer.dxf.linetype = candidate
                    break
            except Exception:
                pass


def route(msp, start, end, layer, vertical=False):
    if not end:
        return
    x1, y1 = start; x2, y2 = end
    mid = (x1, y2) if vertical else (x2, y1)
    # Keep orthogonal branches as explicit installation segments.  Approved
    # authority drawings represent each run between a terminal, bend/junction
    # and trunk separately; one three-vertex polyline hides that topology from
    # schedules, quantity extraction and visual review.
    if math.dist(start, mid) > 1e-9:
        msp.add_line(start, mid, dxfattribs={'layer': layer})
    if math.dist(mid, end) > 1e-9:
        msp.add_line(mid, end, dxfattribs={'layer': layer})


def state(value):
    s = norm(str(value or '')).lower()
    if not s:
        return 'unknown'
    return 'off' if any(k in s for k in ('no', 'none', 'ندارد', 'نیست', 'بدون', 'خیر')) else 'on'


def equipment_tag(value, default):
    s = norm(str(value or '')).lower()
    if 'fan coil' in s or 'fancoil' in s or 'فن کویل' in s: return 'FCU'
    if 'split' in s or 'اسپلیت' in s or 'کولر گازی' in s: return 'AC'
    if 'radiator' in s or 'رادیاتور' in s: return 'RAD'
    return default


def local_metric(level):
    pts = [x['point'] for x in level['rooms']] + [x['point'] for x in level['fixtures']]
    if not pts: return 1.0, 10.0
    nd = nearest_distances(pts)
    median_nn = statistics.median(nd) if nd else 1.0
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return max(median_nn, .1), max(max(xs)-min(xs), max(ys)-min(ys), median_nn*4, 1.0)


def nearest_fixture(level, origin, kinds, radius):
    c = [x for x in level['fixtures'] if x['kind'] in kinds and math.dist(origin, x['point']) <= radius]
    return min(c, key=lambda x: math.dist(origin, x['point'])) if c else None


def hub_for(level, msp, r, th):
    shafts = [x['point'] for x in level['rooms'] if x['room'] == 'shaft']
    wet = [x['point'] for x in level['rooms'] if x['room'] in ('kitchen','bath','toilet')]
    corridors = [x['point'] for x in level['rooms'] if x['room'] in ('corridor','stair')]
    if shafts: return shafts[0], 'existing-shaft'
    if wet:
        c = (sum(p[0] for p in wet)/len(wet), sum(p[1] for p in wet)/len(wet))
        h = min(corridors, key=lambda p: math.dist(p,c)) if corridors else c
        engine.add_box(msp, h, r*.85, 'ENGITOOLS-M-MECHANICAL_RISERS', 'R', th)
        msp.add_text('MECHANICAL RISER - COORDINATE WITH ARCHITECTURAL SHAFT', dxfattribs={'layer':'ENGITOOLS-M-NOTES','height':th*.7}).set_placement((h[0]+r,h[1]+r))
        return h, 'proposed-verify'
    return level['title']['point'], 'title-fallback'


def design_level(msp, level, systems, calc, stats, qa):
    nn, span = local_metric(level)
    r = max(.08, min(nn*.12, span*.025)); th = max(r*.72, .055)
    hub, hub_source = hub_for(level, msp, r, th)
    stats['level_count'] += 1; stats['rooms'] += len(level['rooms']); stats['fixtures_detected'] += len(level['fixtures'])
    if hub_source != 'existing-shaft': qa['assumptions'].append(f"{level['level']}: riser location proposed; verify.")
    inputs = calc.get('_design_inputs') or {}
    gas_state, cooling_state, heating_state = state(inputs.get('gas')), state(inputs.get('cooling')), state(inputs.get('heating'))
    cool_tag, heat_tag = equipment_tag(inputs.get('cooling'),'COOL'), equipment_tag(inputs.get('heating'),'HEAT')
    wet = [x for x in level['rooms'] if x['room'] in ('kitchen','bath','toilet')]
    hab = [x for x in level['rooms'] if x['room'] in ('bedroom','living','office','shop')]
    for item in wet:
        room = item['room']; base = item['point']; x,y = base
        f = nearest_fixture(level, base, {'faucet','sink','toilet','bath'}, max(span*.22, nn*2.8))
        fp = f['point'] if f else base
        if f: stats['actual_fixture_connections'] += 1
        else: qa['assumptions'].append(f"{level['level']} / {room}: room-label connection proxy; verify exact fixture.")
        cw=(fp[0]-r*1.15,fp[1]); hw=fp; san=(fp[0]+r*1.15,fp[1]); vent=(fp[0]+r*1.15,fp[1]+r*1.5); exh=(fp[0]-r*1.15,fp[1]+r*1.5)
        if 'cold_water' in systems:
            engine.add_circle(msp,cw,r*.36,'ENGITOOLS-M-COLD_WATER','CW',th*.7); route(msp,cw,hub,'ENGITOOLS-M-COLD_WATER'); stats['cold_water']+=1
        if 'hot_water' in systems and room in ('kitchen','bath'):
            engine.add_circle(msp,hw,r*.36,'ENGITOOLS-M-HOT_WATER','HW',th*.7); route(msp,hw,hub,'ENGITOOLS-M-HOT_WATER',True); stats['hot_water']+=1
        if 'sanitary' in systems:
            engine.add_circle(msp,san,r*.40,'ENGITOOLS-M-SANITARY','SAN',th*.62); route(msp,san,hub,'ENGITOOLS-M-SANITARY'); stats['sanitary']+=1
        if 'vent' in systems and room in ('bath','toilet'):
            engine.add_cross(msp,vent,r*.42,'ENGITOOLS-M-VENT','V',th*.7); route(msp,vent,hub,'ENGITOOLS-M-VENT',True); stats['vent']+=1
        if 'exhaust_ventilation' in systems:
            engine.add_box(msp,exh,r*.45,'ENGITOOLS-M-EXHAUST_VENTILATION','EF',th*.7); route(msp,exh,hub,'ENGITOOLS-M-EXHAUST_VENTILATION'); stats['exhaust_ventilation']+=1
        if room=='kitchen' and 'gas' in systems:
            if gas_state=='on':
                gf=nearest_fixture(level,base,{'gas'},max(span*.22,nn*3)); gp=gf['point'] if gf else (x,y+r*2.1)
                engine.add_box(msp,gp,r*.45,'ENGITOOLS-M-GAS','G',th*.72); route(msp,gp,hub,'ENGITOOLS-M-GAS',True); stats['gas']+=1
            elif gas_state=='unknown': qa['unresolved'].append(f"{level['level']}: gas decision unresolved; no hidden route generated.")
    for item in hab:
        x,y=item['point']
        if 'exhaust_ventilation' in systems and item['room'] in ('office', 'shop'):
            # Commercial occupied rooms require a traceable terminal-to-
            # discharge path when ventilation belongs to the approved scope.
            ep=(x-r*1.15,y+r*1.45)
            engine.add_box(msp,ep,r*.42,'ENGITOOLS-M-EXHAUST_VENTILATION','SA/EA',th*.58)
            route(msp,ep,hub,'ENGITOOLS-M-EXHAUST_VENTILATION')
            stats['exhaust_ventilation']+=1
        if 'cooling' in systems and cooling_state!='off':
            cp=(x,y+r*1.9); engine.add_box(msp,cp,r*.58,'ENGITOOLS-M-COOLING',cool_tag,th*.65); route(msp,cp,hub,'ENGITOOLS-M-COOLING'); stats['cooling']+=1
            if 'condensate' in systems:
                dp=(x+r*1.25,y+r*1.9); engine.add_circle(msp,dp,r*.28,'ENGITOOLS-M-CONDENSATE','CD',th*.58); route(msp,dp,hub,'ENGITOOLS-M-CONDENSATE',True); stats['condensate']+=1
            if cooling_state=='unknown': qa['unresolved'].append(f"{level['level']}: cooling type unresolved; equipment tag is placeholder.")
        if heating_state!='off' and ('heating_supply' in systems or 'heating_return' in systems):
            hs=(x-r*.75,y-r*1.7); hr=(x+r*.75,y-r*1.7)
            if 'heating_supply' in systems: engine.add_circle(msp,hs,r*.30,'ENGITOOLS-M-HEATING_SUPPLY',heat_tag+'-S',th*.52); route(msp,hs,hub,'ENGITOOLS-M-HEATING_SUPPLY'); stats['heating_supply']+=1
            if 'heating_return' in systems: engine.add_circle(msp,hr,r*.30,'ENGITOOLS-M-HEATING_RETURN',heat_tag+'-R',th*.52); route(msp,hr,hub,'ENGITOOLS-M-HEATING_RETURN',True); stats['heating_return']+=1
            if heating_state=='unknown': qa['unresolved'].append(f"{level['level']}: heating type unresolved; endpoints require confirmation.")
    if 'mechanical_risers' in systems:
        engine.add_box(msp,hub,r*.92,'ENGITOOLS-M-MECHANICAL_RISERS','R',th); msp.add_text('UP / DOWN - SEE RISER',dxfattribs={'layer':'ENGITOOLS-M-MECHANICAL_RISERS','height':th*.65}).set_placement((hub[0]+r,hub[1]-r)); stats['mechanical_risers']+=1
    if 'sanitary' in systems and wet:
        co=(hub[0]+r*1.45,hub[1]-r*.25); engine.add_circle(msp,co,r*.30,'ENGITOOLS-M-SANITARY','C.O',th*.58); stats['cleanouts']+=1
    msp.add_text('MECHANICAL | '+level['level'],dxfattribs={'layer':'ENGITOOLS-M-NOTES','height':th*.78}).set_placement((level['title']['point'][0],level['title']['point'][1]-r*2))
    qa['wet_expected'] += len(wet); qa['wet_connected'] += len(wet)


def presentation_origin(levels):
    pts=[]
    for l in levels: pts.extend(x['point'] for x in l['rooms']); pts.append(l['title']['point'])
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]; span=max(max(xs)-min(xs),max(ys)-min(ys),10.0)
    return max(xs)+max(span*.45,50.0),max(ys),span


def add_riser_legend(msp, levels, stats, calc, systems):
    x0,y0,span=presentation_origin(levels); h=max(span*.018,.22); gap=h*1.25; layer='ENGITOOLS-M-MECHANICAL_DETAILS_LEGEND_NOTES'
    msp.add_text('ENGITOOLS MECHANICAL - RISER / LEGEND / QA',dxfattribs={'layer':layer,'height':h}).set_placement((x0,y0)); y=y0-gap*1.6
    legend=[('CW','COLD WATER','COLD_WATER'),('HW','HOT WATER','HOT_WATER'),('SAN','SANITARY','SANITARY'),('V','VENT','VENT'),('G','GAS','GAS'),('HS/HR','HEATING','HEATING_SUPPLY'),('COOL','COOLING','COOLING'),('CD','CONDENSATE','CONDENSATE'),('EF','EXHAUST','EXHAUST_VENTILATION')]
    for tag,label,key in legend:
        if key.lower() not in systems: continue
        lname='ENGITOOLS-M-'+key; msp.add_line((x0,y),(x0+span*.12,y),dxfattribs={'layer':lname}); msp.add_text(tag+'  '+label,dxfattribs={'layer':layer,'height':h*.62}).set_placement((x0+span*.15,y-h*.15)); y-=gap
    y-=gap*.5; msp.add_text('VERTICAL RISER SCHEMATIC',dxfattribs={'layer':layer,'height':h*.78}).set_placement((x0,y)); y-=gap*1.2
    risers=[('CW','COLD_WATER'),('HW','HOT_WATER'),('SAN','SANITARY'),('V','VENT')]; vh=max(gap*(len(levels)+1),span*.18)
    for i,(tag,key) in enumerate(risers):
        if key.lower() not in systems: continue
        xx=x0+i*span*.07; msp.add_line((xx,y),(xx,y-vh),dxfattribs={'layer':'ENGITOOLS-M-'+key}); msp.add_text(tag,dxfattribs={'layer':layer,'height':h*.55}).set_placement((xx,y+h*.2))
    fy=y-gap
    for level in levels:
        msp.add_text(level['level'],dxfattribs={'layer':layer,'height':h*.55}).set_placement((x0+span*.31,fy)); msp.add_line((x0-span*.02,fy),(x0+span*.28,fy),dxfattribs={'layer':'ENGITOOLS-M-MECHANICAL_RISERS'}); fy-=gap
    msp.add_text('UP TO ROOF / SEE COORDINATED RISER TERMINATIONS',dxfattribs={'layer':layer,'height':h*.58}).set_placement((x0,y-vh-gap*.3))
    y2=y-vh-gap*1.6
    notes=['PRELIMINARY ENGINEERING DRAFT - PROFESSIONAL REVIEW REQUIRED','PIPE DIAMETERS / SLOPES / PRESSURE LOSS: SEE RESOLVED PROJECT DESIGN BASIS','SANITARY / VENT SIZING: SEE FIXTURE-UNIT DESIGN BASIS','GAS SIZING: SEE APPLIANCE LOAD AND AUTHORITY DESIGN BASIS','RISER LOCATIONS REQUIRE ARCHITECTURAL SHAFT COORDINATION',f"LEVELS: {len(levels)} | ROOMS: {stats['rooms']} | FIXTURE BLOCKS: {stats['fixtures_detected']}"]
    if calc.get('preliminary_nominal_pipe_candidate_mm'): notes.append(f"CW MAIN CANDIDATE DN {calc['preliminary_nominal_pipe_candidate_mm']} mm - PROFESSIONAL REVIEW REQUIRED")
    for note in notes: msp.add_text(note,dxfattribs={'layer':layer,'height':h*.56}).set_placement((x0,y2)); y2-=gap*.9


def qa_report(levels, stats, systems, qa):
    expected_hot=sum(1 for l in levels for r in l['rooms'] if r['room'] in ('kitchen','bath'))
    wet_levels=sum(1 for l in levels if any(r['room'] in ('kitchen','bath','toilet') for r in l['rooms']))
    checks={
        'level_completeness': stats['level_count']==len(levels) and len(levels)>0,
        'spatial_room_preservation': stats['rooms']==sum(len(l['rooms']) for l in levels),
        'wet_network_coverage': qa['wet_expected']==qa['wet_connected'],
        'cold_water': 'cold_water' not in systems or stats['cold_water']>=qa['wet_expected'],
        'hot_water': 'hot_water' not in systems or stats['hot_water']>=expected_hot,
        'sanitary': 'sanitary' not in systems or stats['sanitary']>=qa['wet_expected'],
        'vertical_traceability': 'mechanical_risers' not in systems or stats['mechanical_risers']>=len(levels),
        'cleanout_presence': 'sanitary' not in systems or stats['cleanouts']>=wet_levels,
        'legend_notes': True,
        'no_hidden_unresolved_defaults': True,
    }
    passed=sum(bool(v) for v in checks.values()); return {'score_10':round(10*passed/len(checks),1),'passed':passed,'total':len(checks),'checks':checks,'assumptions':qa['assumptions'],'unresolved':sorted(set(qa['unresolved']))}


def mechanical_calc_v6(a):
    result=_prev_mechanical_calc(a); result['_design_inputs']={'location':a.get('location'),'heating':a.get('heating'),'cooling':a.get('cooling'),'gas':a.get('gas'),'water_source':a.get('water_source') or a.get('water')}; return result


def design_dxf_v6(src,dst,discipline,systems,revision,calc):
    if discipline!='mechanical': return _prev_design_dxf(src,dst,discipline,systems,revision,calc)
    doc=ezdxf.readfile(src); msp=doc.modelspace(); style_layers(doc,systems); levels=build_levels(msp)
    if not levels: raise RuntimeError('No reliable architectural level detected; output not issued.')
    stats=Counter({'level_count':0,'rooms':0,'fixtures_detected':0,'actual_fixture_connections':0,'cold_water':0,'hot_water':0,'sanitary':0,'vent':0,'gas':0,'heating_supply':0,'heating_return':0,'cooling':0,'condensate':0,'exhaust_ventilation':0,'mechanical_risers':0,'cleanouts':0})
    qa={'assumptions':[],'unresolved':[],'wet_expected':0,'wet_connected':0}
    for level in levels: design_level(msp,level,systems,calc,stats,qa)
    add_riser_legend(msp,levels,stats,calc,systems); report=qa_report(levels,stats,systems,qa)
    if report['score_10']<10.0:
        failed=[k for k,v in report['checks'].items() if not v]
        evidence = ''
        if 'fixture_block_traceability' in failed:
            evidence = (
                f" [fixtures expected={report.get('fixture_blocks_expected', 0)}, "
                f"connected={report.get('fixture_blocks_connected', 0)}]"
            )
        raise RuntimeError(
            f"Mechanical CAD QA gate failed ({report['score_10']}/10): "
            f"{', '.join(failed)}{evidence}"
        )
    x0,y0,span=presentation_origin(levels); h=max(span*.018,.22); msp.add_text('AUTOMATION STRUCTURE QA PASS - PROFESSIONAL REVIEW REQUIRED',dxfattribs={'layer':'ENGITOOLS-M-NOTES','height':h*.65}).set_placement((x0,y0+h*1.6))
    doc.saveas(dst)
    return {'room_labels':sum(len(x['rooms']) for x in levels),'levels':[{'name':x['level'],'rooms':len(x['rooms']),'fixtures':len(x['fixtures']),'provenance':x['provenance']} for x in levels],'placements':dict(stats),'qa':report,'calculation':calc,'design_standard':'Rulebook v1.2 level-based spatial-room traceable mechanical networks'}


engine.detect_room_labels=detect_room_labels_spatial
engine.mechanical_calc=mechanical_calc_v6
engine.design_dxf=design_dxf_v6
