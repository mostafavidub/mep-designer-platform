"""Protect project analysis workspaces from races and transient file loss.

The architecture analyzer uses a project-scoped temporary directory. If the
same project is analyzed twice concurrently in one process, the second run can
remove the first run's working directory and make an otherwise valid DXF vanish
mid-parse. This guard serializes only analyses for the same project while still
allowing different projects to run independently.

If a temporary workspace still disappears for an external reason, a project
whose original upload is already durable in object storage gets one safe retry.
"""
from __future__ import annotations

import threading

from . import artifact_storage


_locks_guard = threading.Lock()
_project_locks: dict[int, threading.RLock] = {}


def _project_lock(project_id: int) -> threading.RLock:
    with _locks_guard:
        lock = _project_locks.get(int(project_id))
        if lock is None:
            lock = threading.RLock()
            _project_locks[int(project_id)] = lock
        return lock


def _missing_workspace_error(message: str) -> bool:
    value = str(message or '').lower()
    return (
        'no such file or directory' in value
        and ('engitools-analysis' in value or '.dxf' in value)
    )


def _should_retry_from_durable_input(legacy, project_id: int) -> bool:
    db = legacy.Session()
    try:
        project = db.get(legacy.Project, int(project_id))
        if not project:
            return False
        if project.status not in ('awaiting_upload', 'failed'):
            return False
        if not _missing_workspace_error(project.last_error or ''):
            return False
    finally:
        db.close()
    try:
        return artifact_storage.input_is_durable(int(project_id))
    except Exception:
        return False


def install(legacy) -> None:
    """Wrap ``legacy.analyze_project_job`` with serialization and one safe retry."""
    if getattr(legacy, '_analysis_workspace_guard_installed', False):
        return

    original_analyze = legacy.analyze_project_job

    def guarded_analyze_project_job(project_id: int):
        with _project_lock(project_id):
            result = original_analyze(project_id)
            if _should_retry_from_durable_input(legacy, project_id):
                # The analyzer restores the durable original before rebuilding
                # its temporary workspace. Retry once only to avoid loops.
                result = original_analyze(project_id)
            return result

    guarded_analyze_project_job.__name__ = getattr(
        original_analyze, '__name__', 'analyze_project_job'
    )
    guarded_analyze_project_job.__doc__ = getattr(original_analyze, '__doc__', None)
    legacy.analyze_project_job = guarded_analyze_project_job
    legacy._analysis_workspace_guard_installed = True
