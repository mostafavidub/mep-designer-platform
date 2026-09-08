"""Electrical drawing-set review/recovery UI parity with Mechanical."""
from html import escape

from fastapi import Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import electrical_workflow, electrical_drawing_set

CURRENT_ANALYZER_VERSIONS = {"3.5-project-evidence-gate"}
DESIGN_LOCKED_STATUSES = {"queued", "designing", "ready", "failed"}


def _discipline(project):
    return (project.answers or {}).get("discipline", (project.analysis or {}).get("discipline", "mechanical"))


def analyzer_needs_refresh(analysis, has_source=True):
    return bool(has_source and (analysis or {}).get("architecture_analyzer_version") not in CURRENT_ANALYZER_VERSIONS)


def _find_route(app, path, method):
    for route in app.router.routes:
        if getattr(route, "path", None) == path and method.upper() in (getattr(route, "methods", None) or set()):
            return route
    return None


def _replace_route(app, path, method, endpoint):
    route = _find_route(app, path, method)
    if route is not None:
        app.router.routes.remove(route)
    app.add_api_route(path, endpoint, methods=[method.upper()])


def review_question_html(drawing_set):
    rows = []
    for sheet in (drawing_set or {}).get("manifest") or []:
        rows.append(
            f"<li><b>{escape(str(sheet.get('code') or ''))}</b> — "
            f"{escape(str(sheet.get('title') or sheet.get('family') or ''))}</li>"
        )
    total = int((drawing_set or {}).get("sheet_count") or len(rows))
    items = "".join(rows) or "<li>شیت‌های برق بر اساس Scope و شواهد پروژه تعیین شدند.</li>"
    return (
        '<div style="text-align:right;font-size:16px;line-height:2">'
        '<div style="font-size:20px;font-weight:800;margin-bottom:8px">پیشنهاد نقشه‌های برق پروژه</div>'
        '<p style="font-size:14px;color:#667085;margin:0 0 10px">'
        'این لیست از طبقات و سیستم‌های واقعی پروژه ساخته شده و تعداد ثابت از قبل ندارد.</p>'
        f'<ul style="margin:8px 0 14px;padding-right:22px">{items}</ul>'
        f'<div style="font-size:18px;font-weight:800">تعداد شیت‌های تحویلی برق: {total} شیت</div>'
        '<p style="font-size:14px;color:#667085;margin:10px 0 14px">'
        'تأیید Manifest به معنی تأیید محدوده نقشه‌هاست؛ مقادیر فنی بدون Evidence همچنان Final نمی‌شوند.</p>'
        '<style>#answerForm textarea,#answerForm>button{display:none!important}</style>'
        '<button type="button" class="btn primary wide" '
        'onclick="document.getElementById(\'answer\').value=\'تأیید\';document.getElementById(\'answerForm\').requestSubmit()">'
        'تأیید Manifest و ادامه طراحی</button></div>'
    )


def decorate_review_payload(data, drawing_set):
    data = dict(data or {})
    data.update({
        "status": "asking", "question_count": 1, "current_index": 0, "progress": 100,
        "drawing_set": drawing_set or {},
        "question": {"key":"_electrical_drawing_set_approval", "question":review_question_html(drawing_set)},
    })
    return data


def _ensure_proposal(project):
    if electrical_workflow.required_basis_questions(project):
        return None
    analysis = dict(project.analysis or {})
    current = dict(analysis.get("drawing_set") or {})
    if electrical_drawing_set.approved_manifest_is_valid(current):
        return current
    proposed = electrical_drawing_set.proposal(project)
    analysis["drawing_set"] = proposed
    analysis["electrical_drawing_set"] = proposed
    project.analysis = analysis
    project.status = "drawing_set_review"
    return proposed


def register_electrical_review_fix(app, legacy):
    old_flow_route = _find_route(app, "/projects/{pid}/flow", "GET")
    old_answer_route = _find_route(app, "/projects/{pid}/answer-json", "POST")
    if old_flow_route is None or old_answer_route is None:
        raise RuntimeError("Electrical review fix could not find workflow routes")
    old_flow = old_flow_route.endpoint
    old_answer = old_answer_route.endpoint

    def project_flow(pid: int, request: Request):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project:
            raise HTTPException(404)
        if _discipline(project) != "electrical":
            db.close(); return old_flow(pid, request)
        if project.status in DESIGN_LOCKED_STATUSES:
            data = legacy.flow_payload(project); data["drawing_set"] = (project.analysis or {}).get("drawing_set"); db.close(); return JSONResponse(data)
        pdir = legacy.DATA_DIR / "projects" / str(project.id)
        has_source = (pdir / "architecture.zip").exists() or (pdir / "architecture.dxf").exists()
        if analyzer_needs_refresh(project.analysis, has_source):
            db.close(); legacy.analyze_project_job(pid); db, project = legacy.own_project(pid, user.id)
            if not project:
                raise HTTPException(404)
        missing = electrical_workflow.required_basis_questions(project)
        if missing:
            electrical_workflow.ensure_required_basis_questions(project); db.commit(); db.refresh(project)
            data = legacy.flow_payload(project); db.close(); return JSONResponse(data)
        drawing = _ensure_proposal(project)
        if project.status == "drawing_set_review":
            db.commit(); db.refresh(project)
            data = decorate_review_payload(legacy.flow_payload(project), drawing); db.close(); return JSONResponse(data)
        data = legacy.flow_payload(project); data["drawing_set"] = (project.analysis or {}).get("drawing_set"); db.close(); return JSONResponse(data)

    def _approve_project(db, project):
        drawing = electrical_drawing_set.approve_drawing_set((project.analysis or {}).get("drawing_set") or {})
        analysis = dict(project.analysis or {})
        analysis["drawing_set"] = drawing
        analysis["electrical_drawing_set"] = drawing
        project.analysis = analysis
        project.status = "ready_to_design"
        project.last_error = ""
        db.commit(); db.refresh(project)
        return drawing

    def approve_electrical_drawing_set(pid: int, request: Request):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project:
            raise HTTPException(404)
        if _discipline(project) != "electrical" or project.status != "drawing_set_review":
            db.close(); raise HTTPException(409, "Electrical drawing-set review is not active")
        _approve_project(db, project)
        db.close()
        return RedirectResponse(f"/projects/{pid}", status_code=303)

    def answer_json(pid: int, request: Request, answer: str = Form(...), expected_question_index: str = Form("")):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project:
            raise HTTPException(404)
        if _discipline(project) != "electrical" or project.status != "drawing_set_review":
            db.close(); return old_answer(pid, request, answer, expected_question_index)
        normalized = str(answer or "").strip().replace("ي", "ی")
        if normalized not in ("تأیید", "تایید", "approve", "yes"):
            data = decorate_review_payload(legacy.flow_payload(project), (project.analysis or {}).get("drawing_set") or {}); db.close(); return JSONResponse(data, status_code=409)
        drawing = _approve_project(db, project)
        data = legacy.flow_payload(project); data["drawing_set"] = drawing; db.close(); return JSONResponse(data)

    _replace_route(app, "/projects/{pid}/flow", "GET", project_flow)
    _replace_route(app, "/projects/{pid}/answer-json", "POST", answer_json)
    _replace_route(app, "/projects/{pid}/approve-electrical-drawing-set", "POST", approve_electrical_drawing_set)
