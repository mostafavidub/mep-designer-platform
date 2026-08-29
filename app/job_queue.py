"""Persistent PostgreSQL-backed queues for DXF analysis and CAD design."""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from . import artifact_storage
from . import mechanical_workflow


POLL_SECONDS = float(os.getenv('JOB_QUEUE_POLL_SECONDS', '2'))
MAX_ATTEMPTS = int(os.getenv('JOB_MAX_ATTEMPTS', '2'))
RETRY_DELAY_SECONDS = int(os.getenv('JOB_RETRY_DELAY_SECONDS', '30'))
STALE_AFTER_MINUTES = int(os.getenv('JOB_STALE_AFTER_MINUTES', '70'))


def register_job_queue(app, legacy):
    class Job(legacy.Base):
        __tablename__ = 'design_jobs'
        __table_args__ = (UniqueConstraint('revision_id', name='uq_design_jobs_revision'),)

        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        job_type: Mapped[str] = mapped_column(String(20), index=True)
        project_id: Mapped[int] = mapped_column(ForeignKey('projects.id'), index=True)
        revision_id: Mapped[int | None] = mapped_column(ForeignKey('revisions.id'), nullable=True)
        status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
        attempts: Mapped[int] = mapped_column(Integer, default=0)
        max_attempts: Mapped[int] = mapped_column(Integer, default=MAX_ATTEMPTS)
        available_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
        locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
        last_error: Mapped[str] = mapped_column(Text, default='')
        created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
        updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    Job.__table__.create(bind=legacy.engine, checkfirst=True)
    stop_event = threading.Event()

    original_analyze = legacy.analyze_project_job
    original_design = legacy.run_design
    previous_flow_payload = legacy.flow_payload

    def _active_job(db, project_id, job_type):
        return db.query(Job).filter(
            Job.project_id == project_id,
            Job.job_type == job_type,
            Job.status.in_(('queued', 'processing')),
        ).order_by(Job.id.desc()).first()

    def enqueue_analysis(project_id: int):
        db = legacy.Session()
        try:
            if _active_job(db, project_id, 'analysis'):
                return
            project = db.get(legacy.Project, project_id)
            if not project:
                return
            project.status = 'analyzing'
            project.last_error = ''
            db.add(Job(job_type='analysis', project_id=project_id, status='queued'))
            db.commit()
        finally:
            db.close()

    legacy.schedule_analysis = enqueue_analysis

    def _next_revision(db, project_id):
        current = db.query(func.max(legacy.Revision.revision_no)).filter(
            legacy.Revision.project_id == project_id
        ).scalar() or 0
        return int(current) + 1

    def _enqueue_design_record(db, project, feedback=''):
        active = _active_job(db, project.id, 'design')
        if active:
            return db.get(legacy.Revision, active.revision_id), active, False
        revision = legacy.Revision(
            project_id=project.id,
            revision_no=_next_revision(db, project.id),
            status='queued',
            feedback=feedback,
        )
        db.add(revision)
        db.flush()
        job = Job(
            job_type='design', project_id=project.id, revision_id=revision.id,
            status='queued', max_attempts=MAX_ATTEMPTS,
        )
        db.add(job)
        project.status = 'queued'
        project.last_error = ''
        db.commit()
        db.refresh(revision)
        db.refresh(job)
        return revision, job, True

    def _queue_position(db, job):
        if not job or job.status != 'queued':
            return 0
        return db.query(func.count(Job.id)).filter(
            Job.job_type == job.job_type,
            Job.status == 'queued',
            Job.id <= job.id,
        ).scalar() or 0

    def flow_payload(project):
        data = previous_flow_payload(project)
        db = legacy.Session()
        try:
            job = db.query(Job).filter(Job.project_id == project.id).order_by(Job.id.desc()).first()
            if job:
                data['job'] = {
                    'type': job.job_type,
                    'status': job.status,
                    'position': _queue_position(db, job),
                    'attempts': job.attempts,
                    'max_attempts': job.max_attempts,
                }
        finally:
            db.close()
        data['storage_durable'] = artifact_storage.configured()
        return data

    legacy.flow_payload = flow_payload

    def _claim(job_type):
        db = legacy.Session()
        try:
            query = db.query(Job).filter(
                Job.job_type == job_type,
                Job.status == 'queued',
                Job.available_at <= datetime.utcnow(),
            ).order_by(Job.id.asc())
            if not legacy.DB_URL.startswith('sqlite'):
                query = query.with_for_update(skip_locked=True)
            job = query.first()
            if not job:
                return None
            job.status = 'processing'
            job.locked_at = datetime.utcnow()
            job.attempts += 1
            job.updated_at = datetime.utcnow()
            if job_type == 'design':
                project = db.get(legacy.Project, job.project_id)
                revision = db.get(legacy.Revision, job.revision_id)
                if project: project.status = 'designing'
                if revision: revision.status = 'processing'
            db.commit()
            return job.id
        finally:
            db.close()

    def _transient(message):
        value = (message or '').lower()
        return any(token in value for token in (
            'timeout', 'timed out', 'connection', 'temporarily', 'reset by peer',
            '502', '503', '504', 'فایل معماری پروژه در فضای ذخیره‌سازی پیدا نشد',
        ))

    def _finish(job_id, success, error=''):
        db = legacy.Session()
        try:
            job = db.get(Job, job_id)
            if not job:
                return
            job.last_error = error or ''
            job.locked_at = None
            job.updated_at = datetime.utcnow()
            if success:
                job.status = 'completed'
            elif job.attempts < job.max_attempts and _transient(error):
                job.status = 'queued'
                job.available_at = datetime.utcnow() + timedelta(seconds=RETRY_DELAY_SECONDS)
                project = db.get(legacy.Project, job.project_id)
                if project:
                    project.status = 'queued' if job.job_type == 'design' else 'analyzing'
                    project.last_error = ''
                if job.revision_id:
                    revision = db.get(legacy.Revision, job.revision_id)
                    if revision:
                        revision.status = 'queued'
                        revision.error = ''
            else:
                job.status = 'failed'
            db.commit()
        finally:
            db.close()

    def _run_analysis(job_id):
        db = legacy.Session(); job = db.get(Job, job_id); project_id = job.project_id; db.close()
        try:
            project_dir = legacy.DATA_DIR / 'projects' / str(project_id)
            original = project_dir / 'architecture.zip'
            if not original.exists():
                original = project_dir / 'architecture.dxf'
            if original.exists():
                artifact_storage.upload_input(project_id, original)
            original_analyze(project_id)
            db = legacy.Session(); project = db.get(legacy.Project, project_id)
            success = bool(project and project.status not in ('awaiting_upload', 'uploading', 'analyzing'))
            error = '' if success else (project.last_error if project else 'پروژه پیدا نشد.')
            db.close(); _finish(job_id, success, error)
        except Exception as exc:
            _finish(job_id, False, str(exc))

    def _run_design(job_id):
        db = legacy.Session(); job = db.get(Job, job_id)
        project_id, revision_id = job.project_id, job.revision_id; db.close()
        try:
            artifact_storage.ensure_design_input(project_id, legacy.DATA_DIR, legacy.safe_extract)
            original_design(project_id, revision_id)
            db = legacy.Session(); revision = db.get(legacy.Revision, revision_id)
            success = bool(revision and revision.status == 'ready')
            error = '' if success else (revision.error if revision else 'Revision پیدا نشد.')
            db.close(); _finish(job_id, success, error)
        except Exception as exc:
            _finish(job_id, False, str(exc))

    def _worker(job_type):
        while not stop_event.is_set():
            job_id = _claim(job_type)
            if not job_id:
                stop_event.wait(POLL_SECONDS)
                continue
            if job_type == 'analysis':
                _run_analysis(job_id)
            else:
                _run_design(job_id)

    def _recover_stale_jobs():
        db = legacy.Session()
        try:
            jobs = db.query(Job).filter(
                Job.status == 'processing',
            ).all()
            for job in jobs:
                job.status = 'queued'
                job.available_at = datetime.utcnow()
                job.locked_at = None
                project = db.get(legacy.Project, job.project_id)
                if project: project.status = 'queued' if job.job_type == 'design' else 'analyzing'
                if job.revision_id:
                    revision = db.get(legacy.Revision, job.revision_id)
                    if revision: revision.status = 'queued'

            # Deploy-time recovery for uploads rejected by the former ENDSEC
            # normalizer. That implementation inserted a duplicate ENDSEC even
            # when the uploaded file already had a valid terminal section. Mark
            # each legacy failure before requeueing so it is retried only once.
            endsec_jobs = db.query(Job).filter(
                Job.job_type == 'analysis',
                Job.status == 'failed',
                Job.last_error.ilike('%ENDSEC%'),
            ).all()
            retried_project_ids = set()
            for job in endsec_jobs:
                project = db.get(legacy.Project, job.project_id)
                project_dir = legacy.DATA_DIR / 'projects' / str(job.project_id)
                if not project or not (
                    (project_dir / 'architecture.zip').exists()
                    or (project_dir / 'architecture.dxf').exists()
                ):
                    continue
                job.status = 'queued'
                job.available_at = datetime.utcnow()
                job.locked_at = None
                job.last_error = 'legacy ENDSEC retry scheduled'
                project.status = 'analyzing'
                project.last_error = ''
                retried_project_ids.add(project.id)

            # Some resumable uploads persisted the parser error on Project but
            # the queue worker did not copy it to Job. Recover those records as
            # well, reusing the latest analysis job or creating one if absent.
            affected_projects = db.query(legacy.Project).filter(
                legacy.Project.last_error.ilike('%ENDSEC%'),
            ).all()
            for project in affected_projects:
                if project.id in retried_project_ids:
                    continue
                project_dir = legacy.DATA_DIR / 'projects' / str(project.id)
                if not (
                    (project_dir / 'architecture.zip').exists()
                    or (project_dir / 'architecture.dxf').exists()
                ):
                    continue
                job = db.query(Job).filter(
                    Job.project_id == project.id,
                    Job.job_type == 'analysis',
                ).order_by(Job.id.desc()).first()
                if job is None:
                    job = Job(
                        job_type='analysis', project_id=project.id,
                        status='queued', max_attempts=MAX_ATTEMPTS,
                    )
                    db.add(job)
                else:
                    job.status = 'queued'
                    job.available_at = datetime.utcnow()
                    job.locked_at = None
                    job.last_error = 'legacy project ENDSEC retry scheduled'
                project.status = 'analyzing'
                project.last_error = ''
            db.commit()
        finally:
            db.close()

    @app.on_event('startup')
    def start_persistent_workers():
        _recover_stale_jobs()
        for job_type in ('analysis', 'design'):
            threading.Thread(target=_worker, args=(job_type,), daemon=True, name=f'{job_type}-queue').start()

    @app.on_event('shutdown')
    def stop_persistent_workers():
        stop_event.set()

    def _replace_route(path, method, endpoint):
        for route in list(app.router.routes):
            if getattr(route, 'path', None) == path and method in (getattr(route, 'methods', None) or set()):
                app.router.routes.remove(route)
        app.add_api_route(path, endpoint, methods=[method])

    def _prepare_design(db, project):
        if project.status in ('queued', 'designing', 'quality_check'):
            return False
        discipline = (project.answers or {}).get('discipline', (project.analysis or {}).get('discipline', 'mechanical'))
        if discipline == 'mechanical':
            if mechanical_workflow.refresh_stale_proposal(project):
                db.commit()
                return False
            if not mechanical_workflow.is_approved(project):
                project.status = 'drawing_set_review'
                db.commit()
                return False
        if project.status not in ('ready_to_design', 'failed', 'ready'):
            return False
        return True

    def design(pid: int, request: Request):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project: raise HTTPException(404)
        if _prepare_design(db, project):
            _enqueue_design_record(db, project)
        db.close()
        return RedirectResponse(f'/projects/{pid}', 303)

    def design_json(pid: int, request: Request):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project: raise HTTPException(404)
        accepted = _prepare_design(db, project)
        if accepted: _enqueue_design_record(db, project); db.refresh(project)
        data = legacy.flow_payload(project); db.close()
        return JSONResponse(data, status_code=200 if accepted else 409)

    async def feedback(pid: int, request: Request):
        form = await request.form(); feedback_text = str(form.get('feedback') or '').strip()
        if not feedback_text: raise HTTPException(422, 'شرح اصلاح الزامی است.')
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project: raise HTTPException(404)
        if any(x in feedback_text for x in ['همه پروژه','همیشه','باید در تمام','رول بوک','Rulebook']):
            db.add(legacy.RuleCandidate(project_id=project.id, feedback=feedback_text, candidate_rule=feedback_text))
        if project.status not in ('queued', 'designing', 'quality_check'):
            _enqueue_design_record(db, project, feedback_text)
        db.close(); return RedirectResponse(f'/projects/{pid}', 303)

    _replace_route('/projects/{pid}/design', 'POST', design)
    _replace_route('/projects/{pid}/design-json', 'POST', design_json)
    _replace_route('/projects/{pid}/feedback', 'POST', feedback)

    @app.get('/projects/{pid}/queue')
    def queue_status(pid: int, request: Request):
        user = legacy.current_user(request); db, project = legacy.own_project(pid, user.id)
        if not project: raise HTTPException(404)
        job = db.query(Job).filter(Job.project_id == pid).order_by(Job.id.desc()).first()
        payload = {'status': project.status, 'position': _queue_position(db, job), 'job_status': job.status if job else None}
        db.close(); return payload

    return Job
