import re
import shutil
from collections import Counter

import requests
from ezdxf import bbox
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from . import main as legacy
from .auto_inference_v2 import (
    INSUNITS_TO_M,
    infer_architecture_facts,
    canonical_auto_answers,
    dynamic_questions,
    auto_summary,
    classify_room,
)
from .mechanical_rulebook import RULEBOOK_VERSION
from .mechanical_rulebook import is_confirmation

app = legacy.app


def unanswered_questions(questions, answers):
    """Return only unresolved keys; submitted non-empty answers are final."""
    answers = answers or {}
    return [
        (key, prompt) for key, prompt in questions
        if not str(answers.get(key) or '').strip()
    ]


def _entity_text(e):
    try:
        if e.dxftype() == 'TEXT':
            return (e.dxf.text or '').strip()
        if e.dxftype() == 'MTEXT':
            return (e.plain_text() or '').strip()
    except Exception:
        return ''
    return ''


def _entity_insert(e):
    try:
        p = e.dxf.insert
        return float(p.x), float(p.y)
    except Exception:
        return None


def _expanded_entities(entities, depth=0):
    """Yield modelspace entities plus recursively transformed block contents."""
    if depth > 12:
        return
    for entity in entities:
        if entity.dxftype() == 'INSERT':
            yield entity
            try:
                yield from _expanded_entities(entity.virtual_entities(), depth + 1)
            except Exception:
                continue
        else:
            yield entity


def analyze_dxf_enhanced(path):
    input_recovery = legacy.normalize_input_copy(path)
    doc, reader_recovery = legacy.read_input_dxf(path)
    if reader_recovery.get('recovered'):
        input_recovery = reader_recovery
    msp = doc.modelspace()
    counts = Counter(e.dxftype() for e in msp)
    def normalized(value):
        return str(value or '').replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ').lower()

    def is_plan_title(value):
        value = normalized(value)
        markers = ('پلان معماری', 'architectural plan', 'architecture plan', 'roof plan', 'floor plan', 'پلان شیب', 'پلان شيب')
        return any(marker in value for marker in markers)

    def is_architecture_label(value):
        return is_plan_title(value) or classify_room(normalized(value)) is not None

    fixture_keys = {
        'faucet': ('faucet', 'tap', 'water point'),
        'sink': ('sink', 'basin', 'lav'),
        'toilet': ('toalet', 'toilet', 'farangi', 'wc'),
        'bath': ('bath', 'shower', 'bat'),
        'gas': ('k_gaz', 'gaz', 'gas', 'stove'),
    }

    def fixture_kind(name):
        low = normalized(name)
        for kind, keys in fixture_keys.items():
            if any(key in low for key in keys):
                return kind
        return None

    def collect(container, source_type, source_name):
        raw_texts, labels, fixtures = [], [], []
        for entity in _expanded_entities(container):
            if entity.dxftype() == 'INSERT':
                kind = fixture_kind(getattr(entity.dxf, 'name', ''))
                point = _entity_insert(entity)
                if kind and point:
                    fixtures.append({'kind': kind, 'name': str(entity.dxf.name), 'x': point[0], 'y': point[1]})
                continue
            if entity.dxftype() not in ('TEXT', 'MTEXT'):
                continue
            value = _entity_text(entity)
            if not value:
                continue
            raw_texts.append(value)
            point = _entity_insert(entity)
            if point and is_architecture_label(value):
                labels.append({
                    'text': value, 'x': point[0], 'y': point[1],
                    'source_type': source_type, 'source_name': source_name,
                })
        title_count = sum(1 for item in labels if is_plan_title(item['text']))
        room_count = sum(1 for item in labels if classify_room(normalized(item['text'])) is not None)
        return raw_texts, labels, fixtures, (title_count, room_count)

    # Evaluate layouts and named block definitions independently. Some exported
    # authority DXFs keep the usable architectural sheet in an unreferenced
    # named block; mixing unrelated blocks would corrupt spatial assignment.
    candidates = [
        collect(layout, 'layout', str(getattr(layout, 'name', '') or ''))
        for layout in doc.layouts
    ]
    for block in doc.blocks:
        name = str(getattr(block, 'name', '') or '')
        if name.lower().startswith(('*model_space', '*paper_space')):
            continue
        candidates.append(collect(block, 'block', name))
    usable = [item for item in candidates if item[3][0] > 0]
    if usable:
        # Exported consultant files may split one project across several named
        # blocks. Merge their semantic labels in the shared drawing coordinate
        # system, removing exact duplicate block copies.
        texts = []
        text_labels = []
        fixture_blocks = []
        seen_labels = set()
        seen_fixtures = set()
        # Do not merge every title-bearing block indiscriminately. Consultant
        # templates often contain an orphan sample/title block such as
        # ``پلان معماری طبقه اول و دوم``. Treating that block as part of the
        # submitted architecture creates phantom levels in every project.
        # Keep sources that carry a meaningful share of the detected room
        # evidence; if there are no room labels, retain only the strongest
        # title source as a conservative fallback.
        # Prefer an actual drawing layout/modelspace whenever it carries
        # substantial architectural evidence.  Named blocks in consultant
        # files frequently contain reusable demo/title-library plans; merging
        # one of those with the real model makes unrelated projects acquire
        # the same rooms and levels.  Block sources remain supported for
        # exports whose model/layout genuinely contains no usable plan.
        layout_usable = [
            item for item in usable
            if item[1] and item[1][0].get('source_type') == 'layout'
            and item[3][1] >= 3
        ]
        max_rooms = max(score[1] for *_rest, score in usable)
        strongest_layout_rooms = max((item[3][1] for item in layout_usable), default=0)
        if layout_usable and strongest_layout_rooms >= max(3, int(max_rooms * .35)):
            usable = layout_usable
            max_rooms = strongest_layout_rooms
        if max_rooms:
            threshold = max(1, int(max_rooms * 0.12))
            coherent = [item for item in usable if item[3][1] >= threshold]
        else:
            coherent = [max(usable, key=lambda item: item[3][0])]
        for raw_texts, labels, fixtures, _score in coherent:
            texts.extend(raw_texts)
            for item in labels:
                key = (normalized(item['text']), round(item['x'], 4), round(item['y'], 4))
                if key in seen_labels:
                    continue
                seen_labels.add(key)
                text_labels.append(item)
            for item in fixtures:
                key = (item['kind'], round(item['x'], 4), round(item['y'], 4))
                if key in seen_fixtures:
                    continue
                seen_fixtures.add(key)
                fixture_blocks.append(item)
    elif candidates:
        texts, text_labels, fixture_blocks, _ = max(candidates, key=lambda item: (item[3][1], item[3][0]))
    else:
        texts, text_labels, fixture_blocks = [], [], []

    insunits = int(doc.header.get('$INSUNITS', 0) or 0)
    unit_to_m = INSUNITS_TO_M.get(insunits)
    geom = [e for e in msp if e.dxftype() not in ('TEXT', 'MTEXT', 'DIMENSION', 'LEADER', 'MLEADER')]
    minx = miny = maxx = maxy = None
    try:
        ext = bbox.extents(geom, fast=True)
        if ext.has_data:
            minx, miny = float(ext.extmin.x), float(ext.extmin.y)
            maxx, maxy = float(ext.extmax.x), float(ext.extmax.y)
    except Exception:
        pass

    width_m = height_m = area_m2 = None
    if unit_to_m and None not in (minx, miny, maxx, maxy):
        width_m = abs(maxx - minx) * unit_to_m
        height_m = abs(maxy - miny) * unit_to_m
        area_m2 = width_m * height_m

    # The selected candidate has already been semantically filtered across
    # its complete entity stream; only unrelated raw text is bounded here.
    semantic_labels = text_labels
    semantic_texts = [item['text'] for item in semantic_labels]
    retained_texts = list(dict.fromkeys(texts[:1000] + semantic_texts))
    fixture_counts = Counter(item['kind'] for item in fixture_blocks)
    roof_drain_count = sum(1 for value in retained_texts if re.search(r'\b(?:RD|R\.D)\b|کف.?خواب|ناودان', str(value), re.I))

    return {
        'file': path.name,
        'version': doc.dxfversion,
        'insunits': insunits,
        'layers': [l.dxf.name for l in doc.layers],
        'entities': dict(counts),
        'texts': retained_texts[:20000],
        'text_labels': semantic_labels[:20000],
        'fixture_blocks': fixture_blocks[:20000],
        'fixture_counts': dict(fixture_counts),
        'roof_drain_count': roof_drain_count,
        'geometry_bounds': [minx, miny, maxx, maxy] if minx is not None else None,
        'geometry_width_m': round(width_m, 3) if width_m is not None else None,
        'geometry_height_m': round(height_m, 3) if height_m is not None else None,
        'geometry_area_m2': round(area_m2, 2) if area_m2 is not None else None,
    }


def analyze_project_job(project_id):
    db = legacy.Session()
    p = db.get(legacy.Project, project_id)
    if not p:
        db.close()
        return
    try:
        pdir = legacy.DATA_DIR / 'projects' / str(project_id)
        inp = pdir / 'input'
        shutil.rmtree(inp, ignore_errors=True)
        inp.mkdir(parents=True, exist_ok=True)
        z, d = pdir / 'architecture.zip', pdir / 'architecture.dxf'
        if z.exists():
            legacy.safe_extract(z, inp)
        elif d.exists():
            shutil.copy2(d, inp / d.name)
        else:
            raise ValueError('فایل ورودی پروژه پیدا نشد.')

        files = sorted(x for x in inp.rglob('*.dxf') if legacy.is_real_dxf_path(x))
        if not files:
            raise ValueError('هیچ فایل DXF معتبر پیدا نشد.')

        discipline = (p.answers or {}).get('discipline', 'mechanical')
        analysis = {
            'discipline': discipline,
            'architecture_analyzer_version': '3.5-project-evidence-gate',
            'file_count': len(files),
            'files': [analyze_dxf_enhanced(x) for x in files],
            'inference_mode': 'architecture-first-v2-spatial',
        }
        auto = infer_architecture_facts(analysis, discipline)
        analysis['architectural_auto'] = auto
        analysis['auto_summary'] = auto_summary(auto, discipline)

        # Analysis may be re-run for a migrated analyzer or a replacement DXF.
        # Never discard already submitted project facts: doing so resets the
        # questionnaire to question one every time /flow is polled.
        prior_answers = dict(p.answers or {})
        answers = {'discipline': discipline}
        answers.update(canonical_auto_answers(auto, discipline))
        question_keys = {key for key, _prompt in dynamic_questions(analysis, discipline, auto)}
        for key in question_keys:
            value = prior_answers.get(key)
            if value is not None and str(value).strip():
                # A short confirmation accepts the full Rule Book proposal; it
                # must not replace a calculation-ready canonical value with the
                # literal word "تأیید".
                if not (is_confirmation(value) and str(answers.get(key) or '').strip()):
                    answers[key] = value
        qs = unanswered_questions(dynamic_questions(analysis, discipline, auto), answers)

        p.analysis = analysis
        p.questions = legacy.qlist(qs)
        p.current_question = 0
        p.answers = answers
        p.status = 'asking' if qs else 'ready_to_design'
        p.last_error = ''
        db.commit()
    except Exception as e:
        p.status = 'awaiting_upload'
        p.last_error = str(e)
        db.commit()
    finally:
        db.close()


def flow_payload(p):
    data = legacy._original_flow_payload(p) if hasattr(legacy, '_original_flow_payload') else None
    if data is None:
        questions = p.questions or []
        idx = p.current_question or 0
        discipline = (p.answers or {}).get('discipline', (p.analysis or {}).get('discipline', 'mechanical'))
        cfg = legacy.DISCIPLINES.get(discipline, legacy.DISCIPLINES['mechanical'])
        current = questions[idx] if idx < len(questions) else None
        data = {
            'project_id': p.id, 'name': p.name, 'status': p.status,
            'discipline': discipline, 'discipline_title': cfg['title'],
            'error': p.last_error or '', 'question_count': len(questions),
            'current_index': idx, 'progress': round((idx * 100 / len(questions)), 1) if questions else 100,
            'question': current, 'ready_to_design': p.status == 'ready_to_design',
            'current_revision': p.current_revision or 0,
            'pdf_url': f'/projects/{p.id}/pdf/{p.current_revision}' if p.status == 'ready' and p.current_revision else None,
        }
    data['auto_summary'] = (p.analysis or {}).get('auto_summary') or []
    data['auto_inference'] = (p.analysis or {}).get('architectural_auto') or {}
    data['questionnaire_mode'] = 'dynamic-unresolved-project-evidence-only'
    data['inference_mode'] = (p.analysis or {}).get('inference_mode', 'architecture-first-v2-spatial')
    return data


legacy._original_flow_payload = legacy.flow_payload
legacy.analyze_dxf = analyze_dxf_enhanced
legacy.analyze_project_job = analyze_project_job
legacy.flow_payload = flow_payload

legacy.DISCIPLINES['electrical']['questions'] = [
    ('location', 'محل پروژه، فقط اگر از نقشه قابل تشخیص نباشد'),
    ('supply', 'نوع انشعاب برق، فقط اگر در مدارک پروژه مشخص نباشد'),
    ('emergency', 'نیاز به برق اضطراری، به‌عنوان تصمیم کارفرما'),
    ('special_loads', 'بارهای خاصی که از پلان معماری قابل تشخیص نیستند'),
]
legacy.DISCIPLINES['mechanical']['questions'] = [
    ('location', 'محل پروژه، فقط اگر از نقشه قابل تشخیص نباشد'),
    ('heating', 'انتخاب سیستم گرمایش، اگر در مدارک مشخص نشده باشد'),
    ('cooling', 'انتخاب سیستم سرمایش، اگر در مدارک مشخص نشده باشد'),
    ('gas', 'وجود انشعاب گاز، اگر در نقشه مشخص نباشد'),
    ('water_source', 'اطلاعات قطعی ورودی آب/مخزن/پمپ، فقط در صورت وجود تصمیم قبلی'),
]


@app.get('/system-health')
def system_health():
    result = {'ok': True, 'web': {
        'ok': True,
        'mode': 'architecture-first-v3.5-project-evidence-gate',
        'mechanical_rulebook_version': RULEBOOK_VERSION,
        'questionnaire': 'short-answer-rulebook-proposals',
    }}
    try:
        r = requests.get(legacy.CAD_DESIGNER_URL + '/engine-capabilities', timeout=5)
        result['cad'] = r.json() if r.ok else {'ok': False, 'status_code': r.status_code}
        result['ok'] = bool(r.ok)
    except Exception as exc:
        result['cad'] = {'ok': False, 'error': str(exc)}
        result['ok'] = False
    return JSONResponse(result, status_code=200 if result['ok'] else 503)


# Only canonical, indexable public pages belong in the XML sitemap.
# /architect intentionally remains noindex until the service is live.
PUBLIC_SEO_PATHS = [
    '/', '/mechanical', '/electrical', '/blog',
    '/blog/mep-input-guide', '/blog/electrical-plan-scope', '/blog/mechanical-plan-scope'
]


def _public_root(request: Request):
    scheme = request.headers.get('x-forwarded-proto', 'https').split(',')[0].strip()
    return f"{scheme}://{request.url.netloc}"


@app.get('/robots.txt', include_in_schema=False)
def robots(request: Request):
    root = _public_root(request)
    body = "\n".join([
        'User-agent: *',
        'Allow: /',
        'Disallow: /projects/',
        'Disallow: /login',
        'Disallow: /register',
        'Disallow: /system-health',
        'Disallow: /system_health',
        'Disallow: /health',
        f'Sitemap: {root}/sitemap.xml',
        ''
    ])
    return Response(body, media_type='text/plain; charset=utf-8', headers={'Cache-Control': 'public, max-age=3600'})


@app.get('/sitemap.xml', include_in_schema=False)
def sitemap(request: Request):
    root = _public_root(request)
    urls = ''.join(
        f'<url><loc>{root}{path}</loc><lastmod>2026-08-21</lastmod><changefreq>{"weekly" if path.startswith("/blog") else "monthly"}</changefreq><priority>{"1.0" if path == "/" else "0.9" if path in ("/mechanical", "/electrical") else "0.7"}</priority></url>'
        for path in PUBLIC_SEO_PATHS
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return Response(xml, media_type='application/xml; charset=utf-8', headers={'Cache-Control': 'public, max-age=3600'})
