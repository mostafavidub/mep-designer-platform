from html import escape

from fastapi import Form, HTTPException, Request
from fastapi.responses import JSONResponse

from .mechanical_drawing_set import approve_drawing_set
from .mechanical_workflow import _discipline, create_proposal, proposal_is_current


FAMILY_ORDER = (
    'water_supply',
    'sanitary_vent',
    'heating',
    'cooling',
    'gas',
    'ventilation_exhaust',
    'roof_rainwater',
)

CURRENT_ANALYZER_VERSIONS = {
    '3.4-authority-roof-scope',
    '3.5-project-evidence-gate',
}

# Once CAD generation has started, status polling must be read-only. Re-running
# analyzer/proposal migration here can regress an active project back to the
# review or ready-to-design screens.
DESIGN_LOCKED_STATUSES = {'queued', 'designing', 'ready', 'failed'}


def analyzer_needs_refresh(analysis, has_source=True):
    return bool(
        has_source
        and (analysis or {}).get('architecture_analyzer_version') not in CURRENT_ANALYZER_VERSIONS
    )


def _find_route(app, path, method):
    method = method.upper()
    for route in app.router.routes:
        if getattr(route, 'path', None) == path and method in (getattr(route, 'methods', None) or set()):
            return route
    return None


def _replace_route(app, path, method, endpoint):
    route = _find_route(app, path, method)
    if route is not None:
        app.router.routes.remove(route)
    app.add_api_route(path, endpoint, methods=[method.upper()])


def review_question_html(drawing_set):
    drawing_set = drawing_set or {}
    families = drawing_set.get('sheet_families') or {}
    rows = []
    for key in FAMILY_ORDER:
        item = families.get(key) or {}
        count = int(item.get('count') or 0)
        if count <= 0:
            continue
        label = escape(str(item.get('label') or key))
        code = escape(str(item.get('code') or ''))
        sheets = item.get('sheets') or []
        pattern_names = []
        for sheet in sheets:
            name = sheet.get('pattern') or ', '.join(str(x) for x in (sheet.get('levels') or []))
            if sheet.get('special') and sheet.get('label'):
                name = sheet.get('label')
            if name:
                pattern_names.append(escape(str(name)))
        detail = f" — {', '.join(pattern_names)}" if pattern_names else ''
        code_text = f' <span style="color:#667085">({code})</span>' if code else ''
        rows.append(f'<li><b>{label}</b>{code_text}: {count} شیت{detail}</li>')

    total = int(drawing_set.get('deliverable_sheet_count') or drawing_set.get('total_plans') or 0)
    items = ''.join(rows) or '<li>شیت‌های مکانیکی موردنیاز بر اساس تحلیل پروژه تعیین شد.</li>'
    return (
        '<div style="text-align:right;font-size:16px;line-height:2">'
        '<div style="font-size:20px;font-weight:800;margin-bottom:8px">پیشنهاد نقشه‌های مکانیکی پروژه</div>'
        '<p style="font-size:14px;color:#667085;margin:0 0 10px">'
        'بر اساس تحلیل معماری، شیت‌های مکانیکی موردنیاز و قابل تحویل به شرح زیر است.</p>'
        f'<ul style="margin:8px 0 14px;padding-right:22px">{items}</ul>'
        f'<div style="font-size:18px;font-weight:800">تعداد شیت‌های تحویلی مکانیک: {total} شیت</div>'
        '<p style="font-size:14px;font-weight:400;color:#667085;margin:10px 0 14px">'
        'Effective Level و طبقات تیپ فقط داخل همان سیستم اعمال می‌شوند. طراحی CAD تا تأیید این لیست شروع نمی‌شود.</p>'
        '<style>#answerForm textarea,#answerForm>button{display:none!important}</style>'
        '<button type="button" class="btn primary wide" '
        'onclick="document.getElementById(\'answer\').value=\'تأیید\';document.getElementById(\'answerForm\').requestSubmit()">'
        'تأیید و شروع طراحی — تأیید همین Manifest</button>'
        '</div>'
    )


def decorate_review_payload(data, drawing_set):
    data = dict(data or {})
    data['status'] = 'asking'
    data['question_count'] = 1
    data['current_index'] = 0
    data['progress'] = 100
    data['drawing_set'] = drawing_set or {}
    data['question'] = {'key': '_drawing_set_approval', 'question': review_question_html(drawing_set)}
    return data


def _approve_project(legacy, p):
    ds = dict((p.analysis or {}).get('drawing_set') or {})
    if not ds:
        raise HTTPException(409, 'Drawing set proposal is not ready.')
    try:
        ds = approve_drawing_set(ds)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    analysis = dict(p.analysis or {})
    analysis['drawing_set'] = ds
    p.analysis = analysis
    p.status = 'ready_to_design'
    return ds


def register_mechanical_review_fix(app, legacy):
    old_flow_route = _find_route(app, '/projects/{pid}/flow', 'GET')
    old_answer_route = _find_route(app, '/projects/{pid}/answer-json', 'POST')
    if old_flow_route is None or old_answer_route is None:
        raise RuntimeError('Mechanical review fix could not find workflow routes.')
    old_flow = old_flow_route.endpoint
    old_answer_json = old_answer_route.endpoint

    def project_flow(pid: int, request: Request):
        u = legacy.current_user(request)
        db, p = legacy.own_project(pid, u.id)
        if not p:
            raise HTTPException(404)

        if p.status in DESIGN_LOCKED_STATUSES:
            data = legacy.flow_payload(p)
            data['drawing_set'] = (p.analysis or {}).get('drawing_set')
            db.close()
            return JSONResponse(data)

        # Existing projects may contain a proposal produced by the old two-level
        # analyzer. Re-run once from the persisted architecture source so the
        # customer never approves a stale 2/13-sheet contract.
        analysis = p.analysis or {}
        pdir = legacy.DATA_DIR / 'projects' / str(p.id)
        has_source = (pdir / 'architecture.zip').exists() or (pdir / 'architecture.dxf').exists()
        analyzer_stale = (
            _discipline(p) == 'mechanical'
            and analyzer_needs_refresh(analysis, has_source)
        )
        if analyzer_stale:
            db.close()
            legacy.analyze_project_job(pid)
            db, p = legacy.own_project(pid, u.id)
            if not p:
                raise HTTPException(404)

        if _discipline(p) == 'mechanical' and (p.analysis or {}).get('drawing_set') and not proposal_is_current(p):
            create_proposal(p)
            db.commit(); db.refresh(p)

        if p.status == 'drawing_set_review':
            ds = (p.analysis or {}).get('drawing_set') or {}
            data = decorate_review_payload(legacy.flow_payload(p), ds)
            db.close()
            return JSONResponse(data)
        data = legacy.flow_payload(p)
        data['drawing_set'] = (p.analysis or {}).get('drawing_set')
        db.close()
        return JSONResponse(data)

    def answer_json(pid: int, request: Request, answer: str = Form(...), expected_question_index: str = Form('')):
        u = legacy.current_user(request)
        db, p = legacy.own_project(pid, u.id)
        if not p:
            raise HTTPException(404)
        if p.status != 'drawing_set_review':
            db.close()
            return old_answer_json(pid, request, answer, expected_question_index)
        normalized = str(answer or '').strip().replace('ي', 'ی').replace('أ', 'ا').replace('إ', 'ا')
        if normalized not in ('تأیید', 'تایید', 'approve', 'yes'):
            ds = (p.analysis or {}).get('drawing_set') or {}
            data = decorate_review_payload(legacy.flow_payload(p), ds)
            db.close()
            return JSONResponse(data, status_code=409)
        ds = _approve_project(legacy, p)
        db.commit(); db.refresh(p)
        data = legacy.flow_payload(p)
        data['drawing_set'] = ds
        db.close()
        return JSONResponse(data)

    _replace_route(app, '/projects/{pid}/flow', 'GET', project_flow)
    _replace_route(app, '/projects/{pid}/answer-json', 'POST', answer_json)
