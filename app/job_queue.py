"""Persistent PostgreSQL-backed queues for DXF analysis and CAD design."""
from __future__ import annotations

import os
import secrets
import shutil
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

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

    def _reclaim_failed_artifacts(exclude_project_id=None):
        """Reclaim generated files only; uploaded sources and ready outputs stay intact."""
        db = legacy.Session()
        try:
            ids = [row[0] for row in db.query(legacy.Project.id).filter(
                legacy.Project.status.in_(('failed', 'expired')),
                legacy.Project.id != exclude_project_id,
            ).all()]
        finally:
            db.close()
        for pid in ids:
            shutil.rmtree(Path(os.getenv('CAD_OUTPUT_DIR', '/data/cad-engine')) / str(pid), ignore_errors=True)
            project_dir = Path(legacy.DATA_DIR) / 'projects' / str(pid)
            for transient in (
                project_dir / 'architecture.zip',
                project_dir / 'architecture.dxf',
                project_dir / 'input',
                project_dir / '.upload_chunks',
                project_dir / 'output',
            ):
                if transient.is_dir():
                    shutil.rmtree(transient, ignore_errors=True)
                else:
                    transient.unlink(missing_ok=True)

    def _claim(job_type):
        if job_type == 'design':
            _reclaim_failed_artifacts()
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
            '502', '503', '504', 'no space left on device',
            'فایل معماری پروژه در فضای ذخیره‌سازی پیدا نشد',
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
                if 'no space left on device' in (error or '').lower():
                    _reclaim_failed_artifacts(job.project_id)
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
                project = db.get(legacy.Project, job.project_id)
                if project:
                    project.status = 'failed'
                    project.last_error = error or 'پردازش ناموفق بود.'
                if job.revision_id:
                    revision = db.get(legacy.Revision, job.revision_id)
                    if revision:
                        revision.status = 'failed'
                        revision.error = error or 'پردازش ناموفق بود.'
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

    def _migrate_ready_outputs_to_object_storage():
        """Move legacy ready artifacts to R2, then reclaim their local workspaces."""
        if not artifact_storage.configured():
            return
        db = legacy.Session()
        try:
            revisions = db.query(legacy.Revision).filter(
                legacy.Revision.status == 'ready',
            ).order_by(legacy.Revision.id.asc()).all()
            migrated_projects = set()
            for revision in revisions:
                stored = str(revision.pdf_path or '')
                if not stored or stored.startswith('s3://'):
                    if stored.startswith('s3://'):
                        migrated_projects.add(revision.project_id)
                    continue
                path = Path(stored)
                if not path.exists() or path.suffix.lower() not in ('.dxf', '.zip'):
                    continue
                project = db.get(legacy.Project, revision.project_id)
                if not project:
                    continue
                discipline = (project.answers or {}).get(
                    'discipline', (project.analysis or {}).get('discipline', 'mechanical')
                )
                artifact_storage.validate_output_artifact(path)
                durable_uri = artifact_storage.upload_output(
                    project.id, revision.revision_no, discipline, path,
                )
                if not durable_uri:
                    continue
                revision.pdf_path = durable_uri
                db.commit()
                path.unlink(missing_ok=True)
                migrated_projects.add(project.id)

            for project_id in migrated_projects:
                project_dir = Path(legacy.DATA_DIR) / 'projects' / str(project_id)
                for transient in (
                    project_dir / 'architecture.zip',
                    project_dir / 'architecture.dxf',
                    project_dir / 'input',
                    project_dir / '.upload_chunks',
                    project_dir / 'output',
                ):
                    if transient.is_dir():
                        shutil.rmtree(transient, ignore_errors=True)
                    else:
                        transient.unlink(missing_ok=True)
                shutil.rmtree(
                    Path(os.getenv('CAD_OUTPUT_DIR', '/data/cad-engine')) / str(project_id),
                    ignore_errors=True,
                )
        finally:
            db.close()

    def _recover_stale_jobs():
        """Fail interrupted design jobs and reclaim only their transient CAD files."""
        db = legacy.Session()
        interrupted_design_ids = []
        try:
            jobs = db.query(Job).filter(Job.status == 'processing').all()
            for job in jobs:
                job.locked_at = None
                job.updated_at = datetime.utcnow()
                project = db.get(legacy.Project, job.project_id)
                revision = db.get(legacy.Revision, job.revision_id) if job.revision_id else None
                if job.job_type == 'design':
                    error = 'طراحی هنگام انتشار نسخه جدید متوقف شد؛ دوباره روی شروع طراحی بزنید.'
                    job.status = 'failed'
                    job.last_error = error
                    if project:
                        project.status = 'failed'
                        project.last_error = error
                    if revision:
                        revision.status = 'failed'
                        revision.error = error
                    interrupted_design_ids.append(job.project_id)
                else:
                    job.status = 'queued'
                    job.available_at = datetime.utcnow()
                    if project:
                        project.status = 'analyzing'
                        project.last_error = ''
            db.commit()
        finally:
            db.close()
        for project_id in interrupted_design_ids:
            shutil.rmtree(
                Path(os.getenv('CAD_OUTPUT_DIR', '/data/cad-engine')) / str(project_id),
                ignore_errors=True,
            )
            shutil.rmtree(
                Path(legacy.DATA_DIR) / 'projects' / str(project_id) / 'output',
                ignore_errors=True,
            )

    @app.on_event('startup')
    def start_persistent_workers():
        # CAD workspaces for terminal failed/expired projects are transient only.
        _reclaim_failed_artifacts()
        _migrate_ready_outputs_to_object_storage()
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

    def _maintenance_authorized(request: Request):
        expected = os.getenv('INTERNAL_MAINTENANCE_TOKEN', '')
        supplied = request.headers.get('x-maintenance-token', '')
        if not expected or not secrets.compare_digest(supplied, expected):
            raise HTTPException(404)

    @app.get('/internal/maintenance/projects/{pid}')
    def maintenance_project(pid: int, request: Request):
        """Private production probe used for end-to-end artifact verification."""
        _maintenance_authorized(request)
        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            if not project:
                raise HTTPException(404)
            jobs = db.query(Job).filter(Job.project_id == pid).order_by(Job.id.asc()).all()
            revisions = db.query(legacy.Revision).filter(
                legacy.Revision.project_id == pid
            ).order_by(legacy.Revision.id.asc()).all()
            project_dir = legacy.DATA_DIR / 'projects' / str(pid)
            files = []
            if project_dir.exists():
                files = [
                    {'path': str(path.relative_to(project_dir)), 'size': path.stat().st_size}
                    for path in project_dir.rglob('*') if path.is_file()
                ]
            return {
                'project': {
                    'id': project.id, 'status': project.status,
                    'last_error': project.last_error or '',
                    'answers': project.answers or {},
                    'analysis': project.analysis or {},
                },
                'jobs': [
                    {'id': job.id, 'type': job.job_type, 'status': job.status,
                     'attempts': job.attempts, 'error': job.last_error or ''}
                    for job in jobs
                ],
                'revisions': [
                    {'id': revision.id, 'number': revision.revision_no,
                     'status': revision.status, 'error': revision.error or ''}
                    for revision in revisions
                ],
                'files': files,
            }
        finally:
            db.close()

    @app.post('/internal/maintenance/projects/{pid}/retry-analysis')
    def maintenance_retry_analysis(pid: int, request: Request):
        _maintenance_authorized(request)
        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            if not project:
                raise HTTPException(404)
            active = _active_job(db, pid, 'analysis')
            if not active:
                job = db.query(Job).filter(
                    Job.project_id == pid, Job.job_type == 'analysis'
                ).order_by(Job.id.desc()).first()
                if job is None:
                    job = Job(job_type='analysis', project_id=pid, status='queued')
                    db.add(job)
                else:
                    job.status = 'queued'
                    job.available_at = datetime.utcnow()
                    job.locked_at = None
                    job.last_error = ''
                    job.attempts = 0
            project.status = 'analyzing'
            project.last_error = ''
            db.commit()
            return {'queued': True, 'project_id': pid}
        finally:
            db.close()

    @app.post('/internal/maintenance/projects/{pid}/complete-defaults')
    def maintenance_complete_defaults(pid: int, request: Request):
        """Complete one production E2E run with conservative proposed answers."""
        _maintenance_authorized(request)
        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            if not project:
                raise HTTPException(404)
            if project.status not in ('asking', 'ready_to_design', 'drawing_set_review', 'failed'):
                return {'accepted': False, 'status': project.status}

            answers = dict(project.answers or {})
            auto = (project.analysis or {}).get('architectural_auto') or {}
            counts = auto.get('fixture_counts') or {}
            quantified_fixtures = '، '.join(
                f'{name} {count}' for name, count in counts.items() if int(count or 0) > 0
            ) or 'سینک ۱، روشویی ۱، توالت ۱، دوش ۱'
            overrides = {
                'location': 'مشهد',
                'gas': 'گاز برای پکیج و اجاق هر واحد',
                'fixture_schedule': quantified_fixtures,
            }
            for question in project.questions or []:
                key = question.get('key')
                if not key or str(answers.get(key) or '').strip():
                    continue
                options = list(legacy.QUESTION_OPTIONS.get(key, []))
                answers[key] = overrides.get(key) or (options[0] if options else 'تأیید')
            project.answers = answers
            project.current_question = len(project.questions or [])

            if (answers.get('discipline') or 'mechanical') == 'mechanical':
                proposal = mechanical_workflow.create_proposal(project)
                approved = mechanical_workflow.approve_drawing_set(proposal)
                analysis = dict(project.analysis or {})
                analysis['drawing_set'] = approved
                project.analysis = analysis
            project.status = 'ready_to_design'
            project.last_error = ''
            db.commit()
            revision, job, created = _enqueue_design_record(db, project)
            return {
                'accepted': True, 'created': created,
                'revision_id': revision.id if revision else None,
                'job_id': job.id if job else None,
            }
        finally:
            db.close()

    @app.post('/internal/maintenance/projects/{pid}/retry-design')
    def maintenance_retry_design(pid: int, request: Request):
        """Safely retry the latest design while preserving its uploaded source."""
        _maintenance_authorized(request)
        shutil.rmtree(Path(os.getenv('CAD_OUTPUT_DIR', '/data/cad-engine')) / str(pid), ignore_errors=True)
        shutil.rmtree(Path(legacy.DATA_DIR) / 'projects' / str(pid) / 'output', ignore_errors=True)
        db = legacy.Session()
        try:
            project = db.get(legacy.Project, pid)
            if not project:
                raise HTTPException(404)
            job = db.query(Job).filter(
                Job.project_id == pid, Job.job_type == 'design'
            ).order_by(Job.id.desc()).first()
            if not job or not job.revision_id:
                raise HTTPException(409, 'Design job پیدا نشد.')
            revision = db.get(legacy.Revision, job.revision_id)
            job.status = 'queued'
            job.attempts = 0
            job.available_at = datetime.utcnow()
            job.locked_at = None
            job.last_error = ''
            project.status = 'queued'
            project.last_error = ''
            if revision:
                revision.status = 'queued'
                revision.error = ''
            db.commit()
            return {'queued': True, 'project_id': pid, 'job_id': job.id}
        finally:
            db.close()

    return Job
