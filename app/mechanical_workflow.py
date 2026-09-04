from pathlib import Path
import re

from fastapi import Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .mechanical_drawing_set import approve_drawing_set, is_current_manifest, predict_drawing_set
from .mechanical_basis_contract import canonical_city, normalize_answers, numeric, persisted_answer_is_valid, shaft_approval

SYSTEM_LABELS = {
    'cooling': 'سرمایش', 'heating': 'گرمایش', 'water_supply': 'آب سرد و گرم',
    'sanitary': 'فاضلاب و ونت', 'ventilation': 'تهویه', 'gas': 'گاز',
    'roof_drainage': 'بام / آب باران', 'riser': 'رایزر',
}

REQUIRED_BASIS_QUESTION_SPECS = {
    'city': {
        'question': 'شهر پروژه را مشخص کنید. شهر برای شرایط اقلیمی و ضوابط محلی الزامی است.',
        'options': ['تهران', 'مشهد', 'اصفهان', 'شیراز'],
        'unit': None,
    },
    'water_inlet_pressure': {
        'question': 'فشار واقعی آب در محل کنتور/ورودی پروژه چند bar است؟ این مقدار باید از اندازه‌گیری یا اطلاعات معتبر پروژه تأیید شود.',
        'options': ['2.0 bar', '2.5 bar', '3.0 bar', '4.0 bar'],
        'unit': 'bar',
    },
    'rainfall_intensity': {
        'question': 'شدت بارندگی طراحی مورد تأیید پروژه/مرجع محلی چند mm/h است؟ بدون مقدار تأییدشده طراحی آب باران نهایی نمی‌شود.',
        'options': ['75 mm/h', '90 mm/h', '100 mm/h', '110 mm/h'],
        'unit': 'mm/h',
    },
    'gas_pressure': {
        'question': 'فشار سرویس گاز مورد تأیید پروژه چند mbar است؟ این مقدار باید از مشخصات انشعاب/شرکت گاز یا مدرک معتبر پروژه باشد.',
        'options': ['17.4 mbar', '20 mbar', '21 mbar', '22 mbar'],
        'unit': 'mbar',
    },
    'mechanical_shaft_route': {
        'question': 'مسیر عمودی تأسیسات مکانیکی را تأیید کنید. در صورت نبود شفت معماری، موتور فقط با اجازه صریح شما محل پیشنهادی ایجاد می‌کند.',
        'options': ['پیشنهاد نزدیک هسته فضاهای تر', 'شفت کنار راه‌پله', 'شفت‌های موجود معماری استفاده شوند', 'اجازه پیشنهاد مسیر و ابعاد شفت را دارید'],
        'unit': None,
    },
}


def _discipline(p):
    return (p.answers or {}).get('discipline', (p.analysis or {}).get('discipline', 'mechanical'))


def _negative(value):
    s = str(value or '').strip().lower()
    return any(x in s for x in ('ندارد', 'خیر', 'نیست', 'بدون', 'none', 'no '))


def _numeric(value):
    if value in (None, '', []): return None
    if isinstance(value, (int, float)): return float(value)
    text = str(value).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')).replace('٫', '.').replace(',', '.')
    match = re.search(r'[-+]?\d+(?:\.\d+)?', text)
    return float(match.group(0)) if match else None


def _fixture_schedule_quantified(value):
    text = str(value or '').strip().translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
    aliases = ('sink','faucet','toilet','bath','shower','سینک','روشویی','روشويی','توالت','دوش','وان')
    return bool(re.search(r'\d+', text)) and any(alias in text.lower() for alias in aliases)


def _enclosed_parking(value):
    s = str(value or '').strip().lower()
    return any(x in s for x in ('بسته', 'محصور', 'enclosed', 'closed')) and not _negative(value)


def _central_water_equipment(value):
    s = str(value or '').strip().lower()
    if not s or _negative(value): return False
    return any(x in s for x in ('مخزن', 'بوستر', 'پمپ', 'tank', 'booster', 'pump'))


def _hot_water_return_required(value):
    s = str(value or '').strip().lower()
    if not s or _negative(value): return False
    return any(x in s for x in ('برگشت', 'سیرکولاسیون', 'return', 'recirculation', 'recirc'))


def _level_names(p):
    analysis = p.analysis or {}; levels = []; auto = analysis.get('architectural_auto') or {}
    for key in ('levels', 'detected_levels', 'floor_levels'):
        value = auto.get(key)
        if isinstance(value, list):
            for item in value:
                name = item.get('name') if isinstance(item, dict) else item
                if name and str(name) not in levels: levels.append(str(name))
    if not levels:
        for f in analysis.get('files') or []:
            for text in f.get('texts') or []:
                t = str(text).strip(); low = t.lower()
                for marker in ('پلان معماری', 'architectural plan', 'architecture plan'):
                    pos = low.find(marker.lower())
                    if pos >= 0:
                        name = (t[:pos] + t[pos + len(marker):]).strip(' -–—:_') or 'پلان معماری'
                        if name not in levels: levels.append(name)
    if not levels:
        for f in analysis.get('files') or []:
            name = Path(str(f.get('file') or '')).stem.strip()
            if name and name not in levels: levels.append(name)
    return levels or ['پلان معماری']


def _typical_groups(p, levels):
    analysis = p.analysis or {}; auto = analysis.get('architectural_auto') or {}; candidates = None
    for key in ('typical_groups', 'typical_floors', 'level_groups', 'floor_groups'):
        value = auto.get(key)
        if value: candidates = value; break
    if not candidates:
        value = analysis.get('typical_groups')
        if value: candidates = value
    if not candidates: return []
    allowed = set(levels); out = []
    if isinstance(candidates, dict): candidates = [{'name': k, 'levels': v} for k, v in candidates.items()]
    for index, item in enumerate(candidates or [], 1):
        if isinstance(item, dict):
            members = item.get('levels') or item.get('floors') or item.get('members') or []; name = item.get('name') or item.get('label') or item.get('pattern') or f'Typical {index}'; confidence = item.get('confidence')
        elif isinstance(item, (list, tuple, set)): members = list(item); name = f'Typical {index}'; confidence = None
        else: continue
        members = list(dict.fromkeys(str(x) for x in members if str(x) in allowed))
        if len(members) >= 2:
            row = {'name': str(name), 'levels': members}
            if confidence: row['confidence'] = confidence
            out.append(row)
    return out


def _profile_levels(p, flag, fallback_levels):
    auto = (p.analysis or {}).get('architectural_auto') or {}; profiles = auto.get('level_profiles') or []
    if not profiles: return list(fallback_levels)
    result = []
    for profile in profiles:
        name = str(profile.get('name') or '')
        if name and profile.get(flag) and name not in result: result.append(name)
    return result


def build_scope(p):
    answers = p.answers or {}; levels = _level_names(p); auto = (p.analysis or {}).get('architectural_auto') or {}; profiles_available = bool(auto.get('level_profiles'))
    conditioned_candidates = _profile_levels(p, 'conditioned_candidate', levels); wet_candidates = _profile_levels(p, 'wet_fixture_candidate', levels)
    sanitary_candidates = _profile_levels(p, 'sanitary_candidate', levels); ventilation_candidates = _profile_levels(p, 'ventilation_candidate', levels); gas_candidates = _profile_levels(p, 'gas_candidate', levels)
    if profiles_available:
        non_roof_levels = list(dict.fromkeys(str(profile.get('name')) for profile in (auto.get('level_profiles') or []) if profile.get('name') and not profile.get('roof')))
        wet_candidates = non_roof_levels; sanitary_candidates = non_roof_levels; ventilation_candidates = non_roof_levels
        if not _negative(answers.get('gas')):
            gas_candidates = non_roof_levels
    heating = [] if _negative(answers.get('heating')) else conditioned_candidates
    cooling = [] if _negative(answers.get('cooling')) else conditioned_candidates
    ventilation = [] if _negative(answers.get('ventilation')) else ventilation_candidates
    gas = [] if _negative(answers.get('gas')) else gas_candidates
    if profiles_available:
        detected_roof_names = [str(x.get('name')) for x in (auto.get('level_profiles') or []) if x.get('name') and x.get('roof')]
        roof_exists = bool(detected_roof_names) and bool(auto.get('roof_scope_reliable', True))
    else:
        detected_roof_names = [x for x in levels if 'بام' in x or 'roof' in x.lower()]; roof_exists = bool(detected_roof_names)
    roof_text = answers.get('roof')
    if roof_text is not None: roof_exists = not _negative(roof_text)
    effective_union = []
    for group in (heating, cooling, wet_candidates, sanitary_candidates, ventilation, gas):
        for level in group:
            if level not in effective_union: effective_union.append(level)
    return {
        'all_levels': list(levels), 'conditioned_levels': cooling, 'heated_levels': heating,
        'wet_fixture_levels': wet_candidates, 'sanitary_fixture_levels': sanitary_candidates,
        'ventilation_required_levels': ventilation, 'gas_consumer_levels': gas,
        'roof_exists': bool(roof_exists), 'roof_level_name': detected_roof_names[0] if detected_roof_names else 'Roof',
        'roof_requires_dedicated_plan': False, 'vertical_systems': len(effective_union) > 1,
        'enclosed_parking': _enclosed_parking(answers.get('parking_enclosure')), 'typical_groups': _typical_groups(p, levels),
        'central_water_equipment': _central_water_equipment(answers.get('water_source')),
        'hot_water_return_required': _hot_water_return_required(answers.get('hot_water_system')),
        'effective_level_source': 'architecture-level-profiles' if profiles_available else 'fallback-all-detected-levels',
    }


def required_basis_questions(p):
    if _discipline(p) != 'mechanical': return []
    answers = normalize_answers(p.answers or {}); scope = build_scope(p); required = []
    if not canonical_city(answers):
        required.append('city')
    if scope.get('wet_fixture_levels') and _numeric(answers.get('water_inlet_pressure') or answers.get('water_pressure')) is None:
        required.append('water_inlet_pressure')
    if scope.get('roof_exists') and numeric(answers.get('rainfall_intensity_mm_h') or answers.get('rainfall_intensity')) is None:
        required.append('rainfall_intensity')
    gas_enabled = bool(answers.get('gas')) and not _negative(answers.get('gas'))
    if gas_enabled and _numeric(answers.get('gas_pressure')) is None:
        required.append('gas_pressure')
    if scope.get('vertical_systems') and not shaft_approval(answers):
        required.append('mechanical_shaft_route')
    return required


def _question_payload(key):
    spec = REQUIRED_BASIS_QUESTION_SPECS[key]
    return {'key': key, 'question': spec['question'], 'input_type': 'radio', 'options': list(spec['options']), 'required': True, 'source': 'mechanical_basis_preflight'}


def ensure_required_basis_questions(p):
    missing = required_basis_questions(p)
    if not missing: return False
    qs = list(p.questions or [])
    # Replace any legacy question with the fail-closed copy so obsolete text
    # such as "unknown -> 2.5 bar default" can never reach the user.
    for key in missing:
        replacement = _question_payload(key); replaced = False
        for i, q in enumerate(qs):
            if isinstance(q, dict) and q.get('key') == key:
                qs[i] = replacement; replaced = True
        if not replaced: qs.append(replacement)
    p.questions = qs
    for i, q in enumerate(qs):
        if q.get('key') in missing:
            p.current_question = i; break
    p.status = 'asking'
    analysis = dict(p.analysis or {}); analysis['basis_preflight'] = {'status':'INPUT_REQUIRED','missing':missing}; p.analysis = analysis
    return True


def reopen_basis_questions(p, missing):
    """Return a late authority failure to its exact unanswered questions."""
    allowed=[key for key in missing if key in REQUIRED_BASIS_QUESTION_SPECS]
    answers=dict(p.answers or {})
    for key in allowed:
        if key == 'city':
            answers.pop('city', None); answers.pop('location', None)
        elif key == 'rainfall_intensity':
            answers.pop('rainfall_intensity', None); answers.pop('rainfall_intensity_mm_h', None)
        elif key == 'mechanical_shaft_route':
            answers.pop('mechanical_shaft_route', None); answers.pop('mechanical_shaft_approval', None)
        else:
            answers.pop(key, None)
    p.answers=answers
    questions=list(p.questions or [])
    for key in allowed:
        replacement=_question_payload(key)
        indices=[i for i,q in enumerate(questions) if isinstance(q,dict) and q.get('key')==key]
        if indices: questions[indices[0]]=replacement
        else: questions.append(replacement)
    p.questions=questions
    p.current_question=next((i for i,q in enumerate(questions) if q.get('key') in allowed),len(questions))
    p.status='asking'
    analysis=dict(p.analysis or {})
    analysis['basis_preflight']={'status':'INPUT_REQUIRED','missing':allowed,'resume_stage':'authority_contract'}
    p.analysis=analysis
    return bool(allowed)


def _basis_answer_error(key, answer):
    if key not in REQUIRED_BASIS_QUESTION_SPECS: return None
    if key == 'city':
        return None if canonical_city({'city': answer}) else 'شهر پروژه باید مشخص شود.'
    if key == 'mechanical_shaft_route':
        return None if shaft_approval(normalize_answers({}, answer_key=key, raw_answer=answer)) else 'یکی از مسیرهای شفت را به‌صورت صریح تأیید کنید.'
    value = _numeric(answer)
    if value is None or value <= 0:
        return f"برای {key} باید مقدار عددی معتبر و تأییدشده وارد شود؛ Default خودکار اعمال نمی‌شود."
    return None


def _clear_basis_preflight(p):
    analysis = dict(p.analysis or {}); analysis['basis_preflight'] = {'status':'PASS','missing':[]}; p.analysis = analysis


def _commit_and_verify_answer(db, p, key):
    """Commit, reload, and fail closed if canonical persistence was lost."""
    db.commit(); db.expire(p); db.refresh(p)
    if not persisted_answer_is_valid(p.answers or {}, key):
        p.status = 'asking'
        analysis = dict(p.analysis or {})
        analysis['answer_error'] = 'پاسخ در قرارداد پروژه ذخیره نشد؛ لطفاً همان مورد را دوباره ثبت کنید.'
        analysis['basis_persistence_qa'] = {'status':'FAIL','key':key}
        p.analysis = analysis; db.commit()
        return False
    analysis = dict(p.analysis or {})
    analysis['basis_persistence_qa'] = {'status':'PASS','key':key}
    p.analysis = analysis; db.commit(); db.refresh(p)
    return True


def _advance_mechanical(p):
    p.answers = normalize_answers(p.answers or {})
    if ensure_required_basis_questions(p): return False
    _clear_basis_preflight(p); create_proposal(p); return True


def create_proposal(p):
    proposal = predict_drawing_set(build_scope(p)); proposal['labels'] = SYSTEM_LABELS
    analysis = dict(p.analysis or {}); analysis['drawing_set'] = proposal; p.analysis = analysis; p.status = 'drawing_set_review'; return proposal


def proposal_is_current(p):
    ds = (p.analysis or {}).get('drawing_set') or {}; return is_current_manifest(ds.get('drawing_manifest'))


def refresh_stale_proposal(p):
    if _discipline(p) != 'mechanical': return False
    if ensure_required_basis_questions(p): return True
    ds = (p.analysis or {}).get('drawing_set') or {}
    if ds and not proposal_is_current(p): create_proposal(p); return True
    return False


def is_approved(p):
    ds = (p.analysis or {}).get('drawing_set') or {}; return bool(ds.get('approved')) and proposal_is_current(p) and not required_basis_questions(p)


def _replace_route(app, path, method, endpoint):
    method = method.upper()
    for route in list(app.router.routes):
        if getattr(route, 'path', None) == path and method in (getattr(route, 'methods', None) or set()): app.router.routes.remove(route)
    app.add_api_route(path, endpoint, methods=[method])


def register_mechanical_workflow(app, legacy):
    original_analyze = legacy.analyze_project_job
    def analyze_project_job(project_id):
        original_analyze(project_id); db = legacy.Session(); p = db.get(legacy.Project, project_id)
        try:
            if p and _discipline(p) == 'mechanical' and p.status == 'ready_to_design': _advance_mechanical(p); db.commit()
        finally: db.close()
    legacy.analyze_project_job = analyze_project_job

    def answer(pid: int, request: Request, answer: str = Form(...), expected_question_index: str = Form('')):
        u = legacy.current_user(request); db, p = legacy.own_project(pid, u.id)
        if not p: raise HTTPException(404)
        qs = p.questions or []; idx = p.current_question
        try: replayed = expected_question_index != '' and int(expected_question_index) != idx
        except (TypeError, ValueError): replayed = False
        if replayed:
            db.close(); return RedirectResponse(f'/projects/{pid}', 303)
        if idx < len(qs):
            key = qs[idx]['key']; cleaned = answer.strip(); error = _basis_answer_error(key, cleaned)
            if error:
                analysis = dict(p.analysis or {}); analysis['answer_error'] = error; p.analysis = analysis; p.status = 'asking'; db.commit(); db.close(); return RedirectResponse(f'/projects/{pid}', 303)
            p.answers = normalize_answers(p.answers or {}, answer_key=key, raw_answer=cleaned); p.current_question = idx + 1
            if p.current_question >= len(qs):
                if _discipline(p) == 'mechanical': _advance_mechanical(p)
                else: p.status = 'ready_to_design'
            else: p.status = 'asking'
            _commit_and_verify_answer(db, p, key)
        db.close(); return RedirectResponse(f'/projects/{pid}', 303)

    def answer_json(pid: int, request: Request, answer: str = Form(...), expected_question_index: str = Form('')):
        u = legacy.current_user(request); db, p = legacy.own_project(pid, u.id)
        if not p: raise HTTPException(404)
        qs = p.questions or []; idx = p.current_question
        try: replayed = expected_question_index != '' and int(expected_question_index) != idx
        except (TypeError, ValueError): replayed = False
        if replayed:
            data = legacy.flow_payload(p); data['drawing_set'] = (p.analysis or {}).get('drawing_set'); data['idempotent_replay'] = True; db.close(); return JSONResponse(data)
        if p.status != 'asking' or idx >= len(qs):
            data = legacy.flow_payload(p); data['drawing_set'] = (p.analysis or {}).get('drawing_set'); db.close(); return JSONResponse(data)
        current_question = qs[idx]; cleaned_answer = answer.strip(); key = current_question.get('key')
        if key == 'fixture_schedule' and not _fixture_schedule_quantified(cleaned_answer):
            data = legacy.flow_payload(p); data['drawing_set'] = (p.analysis or {}).get('drawing_set'); data['answer_error'] = 'برای این سؤال باید تعداد عددی تجهیزات را وارد کنید؛ مثال: سینک ۲، روشویی ۲، توالت ۲، دوش ۰.'; db.close(); return JSONResponse(data)
        error = _basis_answer_error(key, cleaned_answer)
        if error:
            data = legacy.flow_payload(p); data['drawing_set'] = (p.analysis or {}).get('drawing_set'); data['answer_error'] = error; db.close(); return JSONResponse(data)
        p.answers = normalize_answers(p.answers or {}, answer_key=key, raw_answer=cleaned_answer); p.current_question = idx + 1
        if p.current_question >= len(qs):
            if _discipline(p) == 'mechanical': _advance_mechanical(p)
            else: p.status = 'ready_to_design'
        else: p.status = 'asking'
        _commit_and_verify_answer(db, p, key); data = legacy.flow_payload(p); data['drawing_set'] = (p.analysis or {}).get('drawing_set'); db.close(); return JSONResponse(data)

    def drawing_set(pid: int, request: Request):
        u = legacy.current_user(request); db, p = legacy.own_project(pid, u.id)
        if not p: raise HTTPException(404)
        if _discipline(p) != 'mechanical': db.close(); raise HTTPException(404)
        if refresh_stale_proposal(p): db.commit(); db.refresh(p)
        if p.status == 'asking':
            data = legacy.flow_payload(p); data['drawing_set'] = None; db.close(); return JSONResponse(data, status_code=409)
        data = (p.analysis or {}).get('drawing_set'); db.close()
        if not data: raise HTTPException(409, 'Drawing set proposal is not ready.')
        return JSONResponse(data)

    def approve(pid: int, request: Request):
        u = legacy.current_user(request); db, p = legacy.own_project(pid, u.id)
        if not p: raise HTTPException(404)
        if ensure_required_basis_questions(p): db.commit(); db.close(); return RedirectResponse(f'/projects/{pid}', 303)
        if refresh_stale_proposal(p): db.commit(); db.refresh(p)
        ds = dict((p.analysis or {}).get('drawing_set') or {})
        if _discipline(p) != 'mechanical' or not ds: db.close(); raise HTTPException(409, 'Drawing set proposal is not ready.')
        try: ds = approve_drawing_set(ds)
        except ValueError as exc: db.close(); raise HTTPException(409, str(exc))
        analysis = dict(p.analysis or {}); analysis['drawing_set'] = ds; p.analysis = analysis; p.status = 'ready_to_design'; db.commit(); db.close(); return RedirectResponse(f'/projects/{pid}', 303)

    def design(pid: int, request: Request):
        u = legacy.current_user(request); db, p = legacy.own_project(pid, u.id)
        if not p: raise HTTPException(404)
        if ensure_required_basis_questions(p): db.commit(); db.close(); return RedirectResponse(f'/projects/{pid}', 303)
        if refresh_stale_proposal(p): db.commit(); db.close(); return RedirectResponse(f'/projects/{pid}', 303)
        if _discipline(p) == 'mechanical' and not is_approved(p): p.status = 'drawing_set_review'; db.commit(); db.close(); return RedirectResponse(f'/projects/{pid}', 303)
        rev_no = (p.current_revision or 0) + 1; r = legacy.Revision(project_id=p.id, revision_no=rev_no, status='queued'); db.add(r); p.status = 'queued'; db.commit(); db.refresh(r); rid = r.id; db.close(); legacy.threading.Thread(target=legacy.run_design, args=(pid, rid), daemon=True).start(); return RedirectResponse(f'/projects/{pid}', 303)

    def design_json(pid: int, request: Request):
        u = legacy.current_user(request); db, p = legacy.own_project(pid, u.id)
        if not p: raise HTTPException(404)
        if ensure_required_basis_questions(p):
            db.commit(); db.refresh(p); data = legacy.flow_payload(p); data['drawing_set'] = None; db.close(); return JSONResponse(data, status_code=409)
        if refresh_stale_proposal(p):
            db.commit(); db.refresh(p); data = legacy.flow_payload(p); data['drawing_set'] = (p.analysis or {}).get('drawing_set'); db.close(); return JSONResponse(data, status_code=409)
        if _discipline(p) == 'mechanical' and not is_approved(p):
            p.status = 'drawing_set_review'; db.commit(); data = legacy.flow_payload(p); data['drawing_set'] = (p.analysis or {}).get('drawing_set'); db.close(); return JSONResponse(data, status_code=409)
        if p.status != 'ready_to_design': data = legacy.flow_payload(p); db.close(); return JSONResponse(data, status_code=409)
        rev_no = (p.current_revision or 0) + 1; r = legacy.Revision(project_id=p.id, revision_no=rev_no, status='queued'); db.add(r); p.status = 'queued'; db.commit(); db.refresh(r); rid = r.id; data = legacy.flow_payload(p); db.close(); legacy.threading.Thread(target=legacy.run_design, args=(pid, rid), daemon=True).start(); return JSONResponse(data)

    _replace_route(app, '/projects/{pid}/answer', 'POST', answer)
    _replace_route(app, '/projects/{pid}/answer-json', 'POST', answer_json)
    _replace_route(app, '/projects/{pid}/design', 'POST', design)
    _replace_route(app, '/projects/{pid}/design-json', 'POST', design_json)
    app.add_api_route('/projects/{pid}/drawing-set', drawing_set, methods=['GET'])
    app.add_api_route('/projects/{pid}/approve-drawing-set', approve, methods=['POST'])
