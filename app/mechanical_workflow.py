from pathlib import Path

from fastapi import Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .mechanical_drawing_set import predict_drawing_set

SYSTEM_LABELS = {
    'cooling': 'سرمایش',
    'heating': 'گرمایش',
    'water_supply': 'آب سرد و گرم',
    'sanitary': 'فاضلاب و ونت',
    'ventilation': 'تهویه',
    'gas': 'گاز',
    'roof_drainage': 'بام / آب باران',
    'riser': 'رایزر',
}


def _discipline(p):
    return (p.answers or {}).get('discipline', (p.analysis or {}).get('discipline', 'mechanical'))


def _negative(value):
    s = str(value or '').strip().lower()
    return any(x in s for x in ('ندارد', 'خیر', 'نیست', 'بدون', 'none', 'no '))


def _level_names(p):
    analysis = p.analysis or {}
    levels = []
    auto = analysis.get('architectural_auto') or {}
    for key in ('levels', 'detected_levels', 'floor_levels'):
        value = auto.get(key)
        if isinstance(value, list):
            for item in value:
                name = item.get('name') if isinstance(item, dict) else item
                if name and str(name) not in levels:
                    levels.append(str(name))
    if not levels:
        for f in analysis.get('files') or []:
            for text in f.get('texts') or []:
                t = str(text).strip()
                low = t.lower()
                for marker in ('پلان معماری', 'architectural plan', 'architecture plan'):
                    pos = low.find(marker.lower())
                    if pos >= 0:
                        name = (t[:pos] + t[pos + len(marker):]).strip(' -–—:_') or 'پلان معماری'
                        if name not in levels:
                            levels.append(name)
    if not levels:
        for f in analysis.get('files') or []:
            name = Path(str(f.get('file') or '')).stem.strip()
            if name and name not in levels:
                levels.append(name)
    return levels or ['پلان معماری']


def build_scope(p):
    answers = p.answers or {}
    levels = _level_names(p)
    gas = [] if _negative(answers.get('gas')) else list(levels)
    heating = [] if _negative(answers.get('heating')) else list(levels)
    cooling = [] if _negative(answers.get('cooling')) else list(levels)
    ventilation = [] if _negative(answers.get('ventilation')) else list(levels)
    roof_text = answers.get('roof')
    roof_exists = (not _negative(roof_text)) if roof_text is not None else any('بام' in x or 'roof' in x.lower() for x in levels)
    return {
        'conditioned_levels': cooling,
        'heated_levels': heating,
        'wet_fixture_levels': list(levels),
        'sanitary_fixture_levels': list(levels),
        'ventilation_required_levels': ventilation,
        'gas_consumer_levels': gas,
        'roof_exists': bool(roof_exists),
        'vertical_systems': len(levels) > 1,
    }


def create_proposal(p):
    proposal = predict_drawing_set(build_scope(p))
    proposal['labels'] = SYSTEM_LABELS
    analysis = dict(p.analysis or {})
    analysis['drawing_set'] = proposal
    p.analysis = analysis
    p.status = 'drawing_set_review'
    return proposal


def is_approved(p):
    ds = (p.analysis or {}).get('drawing_set') or {}
    return bool(ds.get('approved'))


def _replace_route(app, path, method, endpoint):
    method = method.upper()
    for route in list(app.router.routes):
        if getattr(route, 'path', None) == path and method in (getattr(route, 'methods', None) or set()):
            app.router.routes.remove(route)
    app.add_api_route(path, endpoint, methods=[method])


def register_mechanical_workflow(app, legacy):
    original_analyze = legacy.analyze_project_job

    def analyze_project_job(project_id):
        original_analyze(project_id)
        db = legacy.Session()
        p = db.get(legacy.Project, project_id)
        try:
            if p and _discipline(p) == 'mechanical' and p.status == 'ready_to_design':
                create_proposal(p)
                db.commit()
        finally:
            db.close()

    legacy.analyze_project_job = analyze_project_job

    def answer(pid: int, request: Request, answer: str = Form(...)):
        u = legacy.current_user(request)
        db, p = legacy.own_project(pid, u.id)
        if not p:
            raise HTTPException(404)
        qs = p.questions or []
        idx = p.current_question
        if idx < len(qs):
            a = dict(p.answers or {})
            a[qs[idx]['key']] = answer
            p.answers = a
            p.current_question = idx + 1
            if p.current_question >= len(qs):
                if _discipline(p) == 'mechanical':
                    create_proposal(p)
                else:
                    p.status = 'ready_to_design'
            else:
                p.status = 'asking'
            db.commit()
        db.close()
        return RedirectResponse(f'/projects/{pid}', 303)

    def answer_json(pid: int, request: Request, answer: str = Form(...)):
        u = legacy.current_user(request)
        db, p = legacy.own_project(pid, u.id)
        if not p:
            raise HTTPException(404)
        qs = p.questions or []
        idx = p.current_question
        if p.status != 'asking' or idx >= len(qs):
            data = legacy.flow_payload(p)
            data['drawing_set'] = (p.analysis or {}).get('drawing_set')
            db.close()
            return JSONResponse(data)
        a = dict(p.answers or {})
        a[qs[idx]['key']] = answer.strip()
        p.answers = a
        p.current_question = idx + 1
        if p.current_question >= len(qs):
            if _discipline(p) == 'mechanical':
                create_proposal(p)
            else:
                p.status = 'ready_to_design'
        else:
            p.status = 'asking'
        db.commit(); db.refresh(p)
        data = legacy.flow_payload(p)
        data['drawing_set'] = (p.analysis or {}).get('drawing_set')
        db.close()
        return JSONResponse(data)

    def drawing_set(pid: int, request: Request):
        u = legacy.current_user(request)
        db, p = legacy.own_project(pid, u.id)
        if not p:
            raise HTTPException(404)
        if _discipline(p) != 'mechanical':
            db.close(); raise HTTPException(404)
        data = (p.analysis or {}).get('drawing_set')
        db.close()
        if not data:
            raise HTTPException(409, 'Drawing set proposal is not ready.')
        return JSONResponse(data)

    def approve(pid: int, request: Request):
        u = legacy.current_user(request)
        db, p = legacy.own_project(pid, u.id)
        if not p:
            raise HTTPException(404)
        ds = dict((p.analysis or {}).get('drawing_set') or {})
        if _discipline(p) != 'mechanical' or not ds:
            db.close(); raise HTTPException(409, 'Drawing set proposal is not ready.')
        ds['approved'] = True
        ds['approval_required'] = False
        analysis = dict(p.analysis or {})
        analysis['drawing_set'] = ds
        p.analysis = analysis
        p.status = 'ready_to_design'
        db.commit(); db.close()
        return RedirectResponse(f'/projects/{pid}', 303)

    def design(pid: int, request: Request):
        u = legacy.current_user(request)
        db, p = legacy.own_project(pid, u.id)
        if not p:
            raise HTTPException(404)
        if _discipline(p) == 'mechanical' and not is_approved(p):
            p.status = 'drawing_set_review'
            db.commit(); db.close()
            return RedirectResponse(f'/projects/{pid}', 303)
        rev_no = (p.current_revision or 0) + 1
        r = legacy.Revision(project_id=p.id, revision_no=rev_no, status='queued')
        db.add(r); p.status = 'queued'; db.commit(); db.refresh(r); rid = r.id; db.close()
        legacy.threading.Thread(target=legacy.run_design, args=(pid, rid), daemon=True).start()
        return RedirectResponse(f'/projects/{pid}', 303)

    def design_json(pid: int, request: Request):
        u = legacy.current_user(request)
        db, p = legacy.own_project(pid, u.id)
        if not p:
            raise HTTPException(404)
        if _discipline(p) == 'mechanical' and not is_approved(p):
            p.status = 'drawing_set_review'; db.commit()
            data = legacy.flow_payload(p); data['drawing_set'] = (p.analysis or {}).get('drawing_set')
            db.close(); return JSONResponse(data, status_code=409)
        if p.status != 'ready_to_design':
            data = legacy.flow_payload(p); db.close(); return JSONResponse(data, status_code=409)
        rev_no = (p.current_revision or 0) + 1
        r = legacy.Revision(project_id=p.id, revision_no=rev_no, status='queued')
        db.add(r); p.status = 'queued'; db.commit(); db.refresh(r); rid = r.id
        data = legacy.flow_payload(p); db.close()
        legacy.threading.Thread(target=legacy.run_design, args=(pid, rid), daemon=True).start()
        return JSONResponse(data)

    _replace_route(app, '/projects/{pid}/answer', 'POST', answer)
    _replace_route(app, '/projects/{pid}/answer-json', 'POST', answer_json)
    _replace_route(app, '/projects/{pid}/design', 'POST', design)
    _replace_route(app, '/projects/{pid}/design-json', 'POST', design_json)
    app.add_api_route('/projects/{pid}/drawing-set', drawing_set, methods=['GET'])
    app.add_api_route('/projects/{pid}/approve-drawing-set', approve, methods=['POST'])
