"""Token-protected bridge between the customer panel and design queue.

The panel never manufactures progress.  It creates one durable engine project,
queues the real CAD job, and reads the same persisted milestones used by the
public project page.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from . import artifact_storage, dxf_output, mechanical_workflow, questionnaire_jobs
from .design_progress import get_project_progress, set_project_progress
from .panel_checkout import register_panel_checkout, session_user


logger = logging.getLogger(__name__)


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
        # The panel persists its own project list. Always expose the current,
        # customer-safe failure separately so a stale local row cannot hide the
        # reason after the engine transitions to ``failed``.
        safe_error = dxf_output.customer_safe_error(project.last_error or data.get("error"))
        data["last_error"] = safe_error
        if project.status in ("failed", "awaiting_upload", "asking"):
            data["failure"] = {
                "message": safe_error or "فرآیند کامل نشد؛ وضعیت پروژه را دوباره بررسی کنید.",
                "action": (
                    "complete_answers" if project.status == "asking"
                    else "reupload" if project.status == "awaiting_upload"
                    else "technical_review"
                ),
            }
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
        data["primary_action"] = (
            {
                "type": "download",
                "label": "دانلود فایل خروجی",
                "format": data.get("output_format") or "DXF",
                "url": data["download_url"],
            }
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
        analysis_job_id: str = Form(""),
        answers_json: str = Form("{}"),
        file: Optional[UploadFile] = File(None),
    ):
        authorized(request)
        customer_id = session_user(request)
        external_user_id = f"CUST-{customer_id}"
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

        phase = "ANALYSIS_LOOKUP"
        started = time.monotonic()
        tracking_id = secrets.token_hex(6).upper()
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
                if project.status in {"failed", "awaiting_upload"}:
                    data = status_payload(project)
                    data.update({"project_token": access_token, "engine_project_id": project.id})
                    return JSONResponse(data, status_code=409)
                if project.status in {"uploading", "finalizing"}:
                    data = status_payload(project)
                    data.update({"project_token": access_token, "engine_project_id": project.id})
                    return JSONResponse(data, status_code=202)
                if project.status != "asking":
                    data = status_payload(project)
                    data.update({"project_token": access_token, "engine_project_id": project.id})
                    return JSONResponse(data)
        finally:
            db.close()
        try:
            authority = questionnaire_jobs.resolve_ready_analysis(
                analysis_job_id,
                owner=customer_id,
                discipline=discipline,
                occupancy=occupancy.strip(),
            )
        except questionnaire_jobs.AnalysisAuthorityError as exc:
            logger.warning(
                "panel_project_finalization event=rejected phase=%s reference_id=%s "
                "external_project_id=%s analysis_job_id=%s error_code=%s",
                phase, tracking_id, external_project_id, analysis_job_id, exc.code,
            )
            raise HTTPException(409, f"{exc} شناسه پیگیری: {tracking_id}")
        source_sha256 = authority["source_sha256"]

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
                if project.status in {"failed", "awaiting_upload"}:
                    data = status_payload(project)
                    data.update({"project_token": access_token, "engine_project_id": project.id})
                    return JSONResponse(data, status_code=409)
                if project.status in {"uploading", "finalizing"}:
                    data = status_payload(project)
                    data.update({"project_token": access_token, "engine_project_id": project.id})
                    return JSONResponse(data, status_code=202)
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
                project.status = "finalizing"
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
                    status="finalizing",
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
            phase = "FILE_IDENTITY"
            with authority["source_path"].open("rb") as source:
                trusted_upload = UploadFile(
                    filename=authority["source_path"].name,
                    file=source,
                    size=authority["source_path"].stat().st_size,
                )
                legacy.save_project_input(pid, trusted_upload)
            phase = "INPUT_VALIDATION"
            db = legacy.Session()
            try:
                project = db.get(legacy.Project, pid)
                if not project:
                    raise HTTPException(404)
                result = authority["result"]
                project.analysis = dict(authority["analysis"])
                project.questions = list(result.get("questions") or [])
                restored_answers = {
                    str(key): value
                    for key, value in dict(result.get("inferred_answers") or {}).items()
                    if str(value).strip()
                }
                restored_answers.update(
                    {str(key): value for key, value in supplied_answers.items() if str(value).strip()}
                )
                restored_answers["discipline"] = discipline
                if occupancy.strip():
                    restored_answers["occupancy"] = occupancy.strip()
                restored_answers["panel_external_project_id"] = external_project_id
                if discipline == "mechanical":
                    restored_answers = mechanical_workflow.normalize_answers(restored_answers)
                project.answers = restored_answers
                project.analysis["questionnaire_authority"] = {
                    "job_id": analysis_job_id,
                    "source_sha256": authority["source_sha256"],
                    "analysis_hash": authority["analysis_hash"],
                    "questionnaire_version": authority["questionnaire_version"],
                }
                basis_missing = mechanical_workflow.required_basis_questions(project)
                unanswered = [
                    question
                    for question in list(project.questions or [])
                    if isinstance(question, dict)
                    and question.get("key")
                    and not str(restored_answers.get(question["key"], "")).strip()
                ]
                unresolved_by_key = {question.get("key"): question for question in unanswered}
                for key in basis_missing:
                    unresolved_by_key[key] = mechanical_workflow._question_payload(key)
                unresolved = list(unresolved_by_key.values())
                if unresolved:
                    project.status = "asking"
                    project.last_error = "اطلاعات فنی پروژه کامل نیست؛ پاسخ‌های تکمیلی لازم است."
                    db.commit()
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
                phase = "FINALIZATION"
                project.status = "ready_to_design"
                project.last_error = ""
                db.commit()
                db.refresh(project)
                data = status_payload(project)
            finally:
                db.close()
            logger.info(
                "panel_project_finalization event=completed phase=%s external_project_id=%s "
                "engine_project_id=%s analysis_job_id=%s source_sha256=%s discipline=%s "
                "occupancy=%s elapsed_ms=%s result_status=ready_to_design",
                phase, external_project_id, pid, analysis_job_id, source_sha256[:12],
                discipline, occupancy.strip(), int((time.monotonic() - started) * 1000),
            )
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
            logger.exception(
                "panel_project_finalization event=failed phase=%s reference_id=%s "
                "external_project_id=%s engine_project_id=%s analysis_job_id=%s "
                "source_sha256=%s discipline=%s occupancy=%s elapsed_ms=%s exception_class=%s",
                phase, tracking_id, external_project_id, pid, analysis_job_id,
                source_sha256[:12], discipline, occupancy.strip(),
                int((time.monotonic() - started) * 1000), type(exc).__name__,
            )
            raise HTTPException(500, f"تکمیل پروژه انجام نشد. شناسه پیگیری: {tracking_id}")

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

    register_panel_checkout(app, legacy, Job, PanelProjectLink, status_payload, project_token)
    return PanelProjectLink
