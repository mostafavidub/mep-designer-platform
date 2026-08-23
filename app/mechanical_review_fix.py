from html import escape

from fastapi import Form, HTTPException, Request
from fastapi.responses import JSONResponse


SYSTEM_ORDER = (
    'cooling', 'heating', 'water_supply', 'sanitary',
    'ventilation', 'gas', 'roof_drainage', 'riser',
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
    systems = drawing_set.get('systems') or {}
    labels = drawing_set.get('labels') or {}
    rows = []
    for key in SYSTEM_ORDER:
        item = systems.get(key) or {}
        count = int(item.get('count') or 0)
        if count <= 0:
            continue
        label = escape(str(labels.get(key) or key))
        levels = [escape(str(x)) for x in (item.get('levels') or [])]
        level_text = f" — {', '.join(levels)}" if levels else ''
        rows.append(f'<li><b>{label}:</b> {count} پلان{level_text}</li>')
    total = int(drawing_set.get('total_plans') or sum(int((systems.get(k) or {}).get('count') or 0) for k in systems))
    items = ''.join(rows) or '<li>پلان مکانیکی موردنیاز بر اساس تحلیل پروژه تعیین شد.</li>'
    return (
        '<div style="text-align:right;font-size:16px;line-height:2">'
        '<div style="font-size:20px;font-weight:800;margin-bottom:8px">لیست پلان‌های پیشنهادی مکانیک</div>'
        f'<ul style="margin:8px 0 14px;padding-right:22px">{items}</ul>'
        f'<div style="font-size:18px;font-weight:800">مجموع: {total} پلان</div>'
        '<p style="font-size:14px;font-weight:400;color:#667085;margin:10px 0 14px">'
        'طراحی CAD تا تأیید این لیست شروع نمی‌شود.</p>'
        '<style>#answerForm textarea,#answerForm>button{display:none!important}</style>'
        '<button type="button" class="btn primary wide" '
        'onclick="document.getElementById(\'answer\').value=\'تأیید\';document.getElementById(\'answerForm\').requestSubmit()">'
        'تأیید لیست و ادامه</button>'
        '</div>'
    )


def decorate_review_payload(data, drawing_set):
    data = dict(data or {})
    data['status'] = 'asking'
    data['question_count'] = 1
    data['current_index'] = 0
    data['progress'] = 100
    data['drawing_set'] = drawing_set or {}
    data['question'] = {
        'key': '_drawing_set_approval',
        'question': review_question_html(drawing_set),
    }
    return data


def _approve_project(legacy, p):
    ds = dict((p.analysis or {}).get('drawing_set') or {})
    if not ds:
        raise HTTPException(409, 'Drawing set proposal is not ready.')
    ds['approved'] = True
    ds['approval_required'] = False
    analysis = dict(p.analysis or {})
    analysis['drawing_set'] = ds
    p.analysis = analysis
    p.status = 'ready_to_design'
    return ds


def register_mechanical_review_fix(app, legacy):
    """Make drawing-set review compatible with the landing-page modal.

    The modal only knows the existing `asking` state. The mechanical workflow
    introduced `drawing_set_review`, so after the last answer the UI had no
    render branch and appeared frozen. This adapter presents the review as a
    final confirmation step and converts its explicit button click into approval.
    """
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
        if p.status == 'drawing_set_review':
            ds = (p.analysis or {}).get('drawing_set') or {}
            data = decorate_review_payload(legacy.flow_payload(p), ds)
            db.close()
            return JSONResponse(data)
        db.close()
        return old_flow(pid, request)

    def answer_json(pid: int, request: Request, answer: str = Form(...)):
        u = legacy.current_user(request)
        db, p = legacy.own_project(pid, u.id)
        if not p:
            raise HTTPException(404)
        if p.status != 'drawing_set_review':
            db.close()
            return old_answer_json(pid, request, answer)
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
