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


def _typical_groups(p, levels):
    """Collect only architecture-derived typical-floor groups."""
    analysis = p.analysis or {}
    auto = analysis.get('architectural_auto') or {}
    candidates = None
    for key in ('typical_groups', 'typical_floors', 'level_groups', 'floor_groups'):
        value = auto.get(key)
        if value:
            candidates = value
            break
    if not candidates:
        value = analysis.get('typical_groups')
        if value:
            candidates = value
    if not candidates:
        return []
    allowed = set(levels)
    out = []
    if isinstance(candidates, dict):
        candidates = [{'name': k, 'levels': v} for k, v in candidates.items()]
    for index, item in enumerate(candidates or [], 1):
        if isinstance(item, dict):
            members = item.get('levels') or item.get('floors') or item.get('members') or []
            name = item.get('name') or item.get('label') or item.get('pattern') or f'Typical {index}'
            confidence = item.get('confidence')
        elif isinstance(item, (list, tuple, set)):
            members = list(item); name = f'Typical {index}'; confidence = None
        else:
            continue
        members = [str(x) for x in members if str(x) in allowed]
        members = list(dict.fromkeys(members))
        if len(members) >= 2:
            row = {'name': str(name), 'levels': members}
            if confidence: row['confidence'] = confidence
            out.append(row)
    return out


def _profile_levels(p, flag, fallback_levels):
    auto = (p.analysis or {}).get('architectural_auto') or {}
    profiles = auto.get('level_profiles') or []
    if not profiles:
        return list(fallback_levels)
    result = []
    for profile in profiles:
        name = str(profile.get('name') or '')
        if name and profile.get(flag) and name not in result:
            result.append(name)
    # Profiles are authoritative only when level inference succeeded. Empty is a
    # meaningful result (e.g. roof-only level has no plumbing fixtures).
    return result


def build_scope(p):
    answers = p.answers or {}
    levels = _level_names(p)
    auto = (p.analysis or {}).get('architectural_auto') or {}
    profiles_available = bool(auto.get('level_profiles'))

    conditioned_candidates = _profile_levels(p, 'conditioned_candidate', levels)
    wet_candidates = _profile_levels(p, 'wet_fixture_candidate', levels)
    sanitary_candidates = _profile_levels(p, 'sanitary_candidate', levels)
    ventilation_candidates = _profile_levels(p, 'ventilation_candidate', levels)
    gas_candidates = _profile_levels(p, 'gas_candidate', levels)

    heating = [] if _negative(answers.get('heating')) else conditioned_candidates
    cooling = [] if _negative(answers.get('cooling')) else conditioned_candidates
    ventilation = [] if _negative(answers.get('ventilation')) else ventilation_candidates
    gas = [] if _negative(answers.get('gas')) else gas_candidates

    if profiles_available:
        roof_exists = any(bool(x.get('roof')) for x in (auto.get('level_profiles') or []))
    else:
        roof_exists = any('بام' in x or 'roof' in x.lower() for x in levels)
    roof_text = answers.get('roof')
    if roof_text is not None:
        roof_exists = not _negative(roof_text)

    effective_union = []
    for group in (heating, cooling, wet_candidates, sanitary_candidates, ventilation, gas):
        for level in group:
            if level not in effective_union:
                effective_union.append(level)

    return {
        'all_levels': list(levels),
        'conditioned_levels': cooling,
        'heated_levels': heating,
        'wet_fixture_levels': wet_candidates,
        'sanitary_fixture_levels': sanitary_candidates,
        'ventilation_required_levels': ventilation,
        'gas_consumer_levels': gas,
        'roof_exists': bool(roof_exists),
        'roof_requires_dedicated_plan': False,
        'vertical_systems': len(effective_union) > 1,
        'typical_groups': _typical_groups(p, levels),
        'effective_level_source': 'architecture-level-profiles' if profiles_available else 'fallback-all-detected-levels',
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
        u = legacy.current_user(request); db, p = legacy.own_project(pid, u.id)
        if not p: raise HTTPException(404)
        qs = p.questions or []; idx = p.current_question
        if idx < len(qs):
            a = dict(p.answers or {}); a[qs[idx]['key']] = answer; p.answers = a; p.current_question = idx + 1
            if p.current_question >= len(qs):
                if _discipline(p) == 'mechanical': create_proposal(p)
                else: p.status = 'ready_to_design'
            else: p.status = 'asking'
            db.commit()
        db.close(); return RedirectResponse(f'/projects/{pid}', 303)

    def answer_json(pid: int, request: Request, answer: str = Form(...)):
        u = legacy.current_user(request); db, p = legacy.own_project(pid, u.id)
        if not p: raise HTTPException(404)
        qs = p.questions or []; idx = p.current_question
        if p.status != 'asking' or idx >= len(qs):
            data = legacy.flow_payload(p); data['drawing_set'] = (p.analysis or {}).get('drawing_set'); db.close(); return JSONResponse(data)
        a = dict(p.answers or {}); a[qs[idx]['key']] = answer.strip(); p.answers = a; p.current_question = idx + 1
        if p.current_question >= len(qs):
            if _discipline(p) == 'mechanical': create_proposal(p)
            else: p.status = 'ready_to_design'
        else: p.status = 'asking'
        db.commit(); db.refresh(p); data = legacy.flow_payload(p); data['drawing_set'] = (p.analysis or {}).get('drawing_set'); db.close(); return JSONResponse(data)

    def drawing_set(pid: int, request: Request):
        u = legacy.current_user(request); db, p = legacy.own_project(pid, u.id)
        if not p: raise HTTPException(404)
        if _discipline(p) != 'mechanical': db.close(); raise HTTPException(404)
        data = (p.analysis or {}).get('drawing_set'); db.close()
        if not data: raise HTTPException(409, 'Drawing set proposal is not ready.')
        return JSONResponse(data)

    def approve(pid: int, request: Request):
        u = legacy.current_user(request); db, p = legacy.own_project(pid, u.id)
        if not p: raise HTTPException(404)
        ds = dict((p.analysis or {}).get('drawing_set') or {})
        if _discipline(p) != 'mechanical' or not ds: db.close(); raise HTTPException(409, 'Drawing set proposal is not ready.')
        ds['approved'] = True; ds['approval_required'] = False
        analysis = dict(p.analysis or {}); analysis['drawing_set'] = ds; p.analysis = analysis; p.status = 'ready_to_design'
        db.commit(); db.close(); return RedirectResponse(f'/projects/{pid}', 303)

    def design(pid: int, request: Request):
        u = legacy.current_user(request); db, p = legacy.own_project(pid, u.id)
        if not p: raise HTTPException(404)
        if _discipline(p) == 'mechanical' and not is_approved(p):
            p.status = 'drawing_set_review'; db.commit(); db.close(); return RedirectResponse(f'/projects/{pid}', 303)
        rev_no = (p.current_revision or 0) + 1; r = legacy.Revision(project_id=p.id, revision_no=rev_no, status='queued')
        db.add(r); p.status = 'queued'; db.commit(); db.refresh(r); rid = r.id; db.close()
        legacy.threading.Thread(target=legacy.run_design, args=(pid, rid), daemon=True).start(); return RedirectResponse(f'/projects/{pid}', 303)

    def design_json(pid: int, request: Request):
        u = legacy.current_user(request); db, p = legacy.own_project(pid, u.id)
        if not p: raise HTTPException(404)
        if _discipline(p) == 'mechanical' and not is_approved(p):
            p.status = 'drawing_set_review'; db.commit(); data = legacy.flow_payload(p); data['drawing_set'] = (p.analysis or {}).get('drawing_set'); db.close(); return JSONResponse(data, status_code=409)
        if p.status != 'ready_to_design':
            data = legacy.flow_payload(p); db.close(); return JSONResponse(data, status_code=409)
        rev_no = (p.current_revision or 0) + 1; r = legacy.Revision(project_id=p.id, revision_no=rev_no, status='queued')
        db.add(r); p.status = 'queued'; db.commit(); db.refresh(r); rid = r.id; data = legacy.flow_payload(p); db.close()
        legacy.threading.Thread(target=legacy.run_design, args=(pid, rid), daemon=True).start(); return JSONResponse(data)

    _replace_route(app, '/projects/{pid}/answer', 'POST', answer)
    _replace_route(app, '/projects/{pid}/answer-json', 'POST', answer_json)
    _replace_route(app, '/projects/{pid}/design', 'POST', design)
    _replace_route(app, '/projects/{pid}/design-json', 'POST', design_json)
    app.add_api_route('/projects/{pid}/drawing-set', drawing_set, methods=['GET'])
    app.add_api_route('/projects/{pid}/approve-drawing-set', approve, methods=['POST'])
