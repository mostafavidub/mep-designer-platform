import shutil
from collections import Counter
from pathlib import Path

import requests
from ezdxf import bbox
from fastapi.responses import JSONResponse

from . import main as legacy
from .auto_inference import (
    INSUNITS_TO_M,
    infer_architecture_facts,
    canonical_auto_answers,
    dynamic_questions,
    auto_summary,
)

app = legacy.app


def analyze_dxf_enhanced(path):
    doc = legacy.ezdxf.readfile(path)
    msp = doc.modelspace()
    counts = Counter(e.dxftype() for e in msp)
    texts = []
    for e in msp:
        try:
            if e.dxftype() == 'TEXT' and e.dxf.text.strip():
                texts.append(e.dxf.text.strip())
            elif e.dxftype() == 'MTEXT' and e.plain_text().strip():
                texts.append(e.plain_text().strip())
        except Exception:
            pass

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
        # Bounding area is used only behind plausibility guards in auto_inference.
        area_m2 = width_m * height_m

    return {
        'file': path.name,
        'version': doc.dxfversion,
        'insunits': insunits,
        'layers': [l.dxf.name for l in doc.layers],
        'entities': dict(counts),
        'texts': texts[:500],
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
            'file_count': len(files),
            'files': [analyze_dxf_enhanced(x) for x in files],
            'inference_mode': 'architecture-first-v1',
        }
        auto = infer_architecture_facts(analysis, discipline)
        analysis['architectural_auto'] = auto
        analysis['auto_summary'] = auto_summary(auto, discipline)

        answers = {'discipline': discipline}
        answers.update(canonical_auto_answers(auto, discipline))
        qs = dynamic_questions(analysis, discipline, auto)

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
    data['questionnaire_mode'] = 'dynamic-unresolved-only'
    return data


# Monkey-patch globals referenced by the original route functions. This keeps all existing URLs/session logic intact.
legacy._original_flow_payload = legacy.flow_payload
legacy.analyze_dxf = analyze_dxf_enhanced
legacy.analyze_project_job = analyze_project_job
legacy.flow_payload = flow_payload

# Remove engineering-computation prompts from static landing previews; actual project questions are generated after DXF analysis.
legacy.DISCIPLINES['electrical']['questions'] = [
    ('location', 'محل پروژه، فقط اگر از نقشه قابل تشخیص نباشد'),
    ('supply', 'نوع انشعاب برق، فقط اگر در مدارک معماری/پروژه مشخص نباشد'),
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
    result = {'ok': True, 'web': {'ok': True, 'mode': 'architecture-first-dynamic-questionnaire'}}
    try:
        r = requests.get(legacy.CAD_DESIGNER_URL + '/engine-capabilities', timeout=5)
        result['cad'] = r.json() if r.ok else {'ok': False, 'status_code': r.status_code}
        result['ok'] = bool(r.ok)
    except Exception as exc:
        result['cad'] = {'ok': False, 'error': str(exc)}
        result['ok'] = False
    return JSONResponse(result, status_code=200 if result['ok'] else 503)
