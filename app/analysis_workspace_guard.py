"""Protect project analysis workspaces from same-process races.

The architecture analyzer uses a project-scoped temporary directory. If the
same project is analyzed twice concurrently in one process, the second run can
remove the first run's working directory and make an otherwise valid DXF vanish
mid-parse. This guard serializes only analyses for the same project while still
allowing different projects to run independently.
"""
from __future__ import annotations

import threading


_locks_guard = threading.Lock()
_project_locks: dict[int, threading.RLock] = {}


def _project_lock(project_id: int) -> threading.RLock:
    with _locks_guard:
        lock = _project_locks.get(int(project_id))
        if lock is None:
            lock = threading.RLock()
            _project_locks[int(project_id)] = lock
        return lock


def install(legacy) -> None:
    """Wrap ``legacy.analyze_project_job`` with a per-project lock once."""
    if getattr(legacy, '_analysis_workspace_guard_installed', False):
        return

    original_analyze = legacy.analyze_project_job

    def guarded_analyze_project_job(project_id: int):
        with _project_lock(project_id):
            return original_analyze(project_id)

    guarded_analyze_project_job.__name__ = getattr(
        original_analyze, '__name__', 'analyze_project_job'
    )
    guarded_analyze_project_job.__doc__ = getattr(original_analyze, '__doc__', None)
    legacy.analyze_project_job = guarded_analyze_project_job
    legacy._analysis_workspace_guard_installed = True
