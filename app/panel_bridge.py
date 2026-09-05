"""Token-protected bridge between the customer panel and design queue.

The panel never manufactures progress.  It creates one durable engine project,
queues the real CAD job, and reads the same persisted milestones used by the
public project page.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from . import artifact_storage, dxf_output, mechanical_workflow
from .design_progress import get_project_progress, set_project_progress


def register_panel_bridge(app, legacy, Job):
    class PanelProjectLink(legacy.Base):
        __tablename__ = "panel_project_links"
        external_project_id: Mapped[str] = mapped_column(String(80), primary_key=True)
        external_user_hash: Mapped[str] = mapped_column(String(64), index=True)
        project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), unique=True, index=True)
        access_token_hash: Mapped[str] = mapped_column(String(64))

    PanelProjectLink.__table__.create(bind=legacy.engine, checkfirst=True)

    def authorized(request: Request):
        expected = os.getenv("PANEL_BRIDGE_TOKEN", "")
        supplied = request.headers.get("x-panel-token", "")
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(404)

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def project_token(external_project_id: str, external_user_hash: str) -> str:
        """Derive a retry-safe bearer token without storing it in plaintext."""
        secret = os.getenv("PANEL_BRIDGE_TOKEN", "").encode("utf-8")
        message = f"{external_project_id}:{external_user_hash}".encode("utf-8")
        return hmac.new(secret, message, hashlib.sha256).hexdigest()

    def linked_project(db, pid: int, request: Request):
        link = db.query(PanelProjectLink).filter(PanelProjectLink.project_id == pid).first()
        supplied = request.headers.get("x-project-token", "")
        if not link or not supplied or not secrets.compare_digest(link.access_token_hash, digest(supplied)):
            raise HTTPException(404)
        project = db.get(legacy.Project, pid)
        if not project:
            raise HTTPException(404)
        return project

    def status_payload(project):
        data = legacy.flow_payload(project)
        progress = get_project_progress(project)
        if progress:
            data["design_progress"] = progress
            data["progress"] = progress["percent"]
        data["output_ready"] = bool(data.get("output_url")) and project.status == "ready"
        data["download_url"] = (
            f"/internal/panel/projects/{project.id}/output"
            if data["output_ready"]
            else None
        )
        return data

    @app.post("/internal/panel/projects")
    def create_panel_project(
        request: Request,
        external_project_id: str = Form(...),
        external_user_id: str = Form(...),
        name: str = Form(...),
        discipline: str = Form(...),
        occupancy: str = Form(""),
        answers_json: str = Form("{}"),
        file: UploadFile = File(...),
    ):
        authorized(request)
        if discipline not in legacy.DISCIPLINES:
            raise HTTPException(400, "Unknown discipline")
        try:
            supplied_answers = json.loads(answers_json)
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid answers")
        if not isinstance(supplied_answers, dict):
            raise HTTPException(400, "Invalid answers")
        external_project_id = external_project_id.strip()[:80]
        external_user_hash = digest(external_user_id.strip())
        if not external_project_id or not external_user_id.strip():
            raise HTTPException(400, "Missing project identity")

        db = legacy.Session()
        try:
            existing = db.get(PanelProjectLink, external_project_id)
            if existing:
                if not secrets.compare_digest(existing.external_user_hash, external_user_hash):
                    raise HTTPException(404)
                project = db.get(legacy.Project, existing.project_id)
                if not project:
                    raise HTTPException(404)
                access_token = project_token(external_project_id, external_user_hash)
                if not secrets.compare_digest(existing.access_token_hash, digest(access_token)):
                    raise HTTPException(409, "Project link cannot be recovered")
                if project.status != "asking":
                    data = status_payload(project)
                    data.update({"project_token": access_token, "engine_project_id": project.id})
                    return JSONResponse(data)
                answers = dict(project.answers or {})
                answers.update({str(k): v for k, v in supplied_answers.items() if str(v).strip()})
                answers["discipline"] = discipline
                if occupancy.strip():
                    answers["occupancy"] = occupancy.strip()
                project.answers = answers
                project.status = "uploading"
                project.last_error = ""
                db.commit()
                pid = project.id
            else:
                email = f"panel-{external_user_hash[:32]}@local"
                user = db.query(legacy.User).filter(legacy.User.email == email).first()
                if not user:
                    user = legacy.User(email=email)
                    db.add(user)
                    db.flush()
                answers = {str(k): v for k, v in supplied_answers.items() if str(v).strip()}
                answers["discipline"] = discipline
                if occupancy.strip():
                    answers["occupancy"] = occupancy.strip()
                answers["panel_external_project_id"] = external_project_id
                project = legacy.Project(
                    user_id=user.id,
                    name=name.strip()[:255] or external_project_id,
                    questions=legacy.qlist(legacy.DISCIPLINES[discipline]["questions"]),
                    answers=answers,
                    status="uploading",
                    last_error="",
                )
                db.add(project)
                db.commit()
                db.refresh(project)
                access_token = project_token(external_project_id, external_user_hash)
                db.add(
                    PanelProjectLink(
                        external_project_id=external_project_id,
                        external_user_hash=external_user_hash,
                        project_id=project.id,
                        access_token_hash=digest(access_token),
                    )
                )
                db.commit()
                pid = project.id
        finally:
            db.close()

        try:
            legacy.save_project_input(pid, file)
            # The panel already collected the exact file-aware questionnaire.
            # Re-run the authority analyzer synchronously, merge those answers,
            # and fail closed if the engine discovers any unresolved input.
            legacy.analyze_project_job(pid)
            db = legacy.Session()
            try:
                project = db.get(legacy.Project, pid)
                if not project:
                    raise HTTPException(404)
                if project.status == "asking":
                    project.last_error = "اطلاعات فنی پروژه کامل نیست؛ پاسخ‌های تکمیلی لازم است."
                    db.commit()
                    missing = mechanical_workflow.required_basis_questions(project)
                    unresolved = (
                        [mechanical_workflow._question_payload(key) for key in missing]
                        if missing
                        else [
                            question for question in list(project.questions or [])
                            if isinstance(question, dict) and not (project.answers or {}).get(question.get("key"))
                        ]
                    )
                    return JSONResponse(
                        {
                            "status": "asking",
                            "error": project.last_error,
                            "detail": project.last_error,
                            "questions": unresolved,
                            "question_count": len(unresolved),
                            "inferred_answers": {
                                str(key): str(value)
                                for key, value in dict(project.answers or {}).items()
                                if isinstance(value, (str, int, float, bool)) and str(value).strip()
                            },
                        },
                        status_code=409,
                    )
                if discipline == "mechanical":
                    drawing_set = dict((project.analysis or {}).get("drawing_set") or {})
                    if not drawing_set:
                        drawing_set = mechanical_workflow.create_proposal(project)
                    approved = mechanical_workflow.approve_drawing_set(drawing_set)
                    analysis = dict(project.analysis or {})
                    analysis["drawing_set"] = approved
                    project.analysis = analysis
                project.status = "ready_to_design"
                revision_no = (project.current_revision or 0) + 1
                revision = legacy.Revision(
                    project_id=project.id,
                    revision_no=revision_no,
                    status="queued",
                )
                db.add(revision)
                db.flush()
                job = Job(
                    job_type="design",
                    project_id=project.id,
                    revision_id=revision.id,
                    status="queued",
                )
                db.add(job)
                project.status = "queued"
                project.last_error = ""
                set_project_progress(project, "queued")
                db.commit()
                db.refresh(project)
                data = status_payload(project)
            finally:
                db.close()
            data.update({"project_token": access_token, "engine_project_id": pid})
            return JSONResponse(data)
        except HTTPException:
            raise
        except Exception as exc:
            db = legacy.Session()
            try:
                project = db.get(legacy.Project, pid)
                if project:
                    project.status = "failed"
                    project.last_error = str(exc)[:1200]
                    db.commit()
            finally:
                db.close()
            raise HTTPException(500, "شروع تولید خروجی انجام نشد.")

    @app.get("/internal/panel/projects/{pid}/status")
    def panel_project_status(pid: int, request: Request):
        authorized(request)
        db = legacy.Session()
        try:
            project = linked_project(db, pid, request)
            return JSONResponse(status_payload(project))
        finally:
            db.close()

    @app.get("/internal/panel/projects/{pid}/output")
    def panel_project_output(pid: int, request: Request):
        authorized(request)
        db = legacy.Session()
        try:
            project = linked_project(db, pid, request)
            revision = db.query(legacy.Revision).filter(
                legacy.Revision.project_id == pid,
                legacy.Revision.revision_no == project.current_revision,
            ).first()
            discipline = (project.answers or {}).get(
                "discipline", (project.analysis or {}).get("discipline", "mechanical")
            )
            if project.status != "ready" or not revision or revision.status != "ready":
                raise HTTPException(409, "Output is not ready")
            stored = dxf_output._resolve_existing_cad_artifact(
                pid, project.current_revision, discipline, revision.pdf_path
            )
        finally:
            db.close()
        if isinstance(stored, str) and stored.startswith("s3://"):
            suffix = Path(stored).suffix.lower()
            filename = (
                f"EngiTools_{discipline}_{pid}_R{project.current_revision}.dxf"
                if suffix == ".dxf"
                else f"EngiTools_{discipline}_{pid}_R{project.current_revision}_DXF.zip"
            )
            return RedirectResponse(artifact_storage.presigned_download(stored, filename), status_code=307)
        if not isinstance(stored, Path) or not stored.exists():
            raise HTTPException(404)
        media_type = "application/dxf" if stored.suffix.lower() == ".dxf" else "application/zip"
        return FileResponse(stored, media_type=media_type, filename=stored.name)

    return PanelProjectLink
