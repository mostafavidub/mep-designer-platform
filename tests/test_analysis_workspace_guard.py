import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

import app.analysis_workspace_guard as guard
from app.analysis_workspace_guard import install


class _FakeLegacy:
    def __init__(self, root: Path):
        self.root = root
        self.failures = []
        self.started = 0
        self._started_lock = threading.Lock()
        self.analyze_project_job = self._analyze

    def _analyze(self, project_id: int):
        workspace = self.root / 'engitools-analysis' / str(project_id)
        shutil.rmtree(workspace, ignore_errors=True)
        workspace.mkdir(parents=True, exist_ok=True)
        drawing = workspace / '000 architecture.dxf'
        drawing.write_bytes(b'DXF-CONTENT')
        with self._started_lock:
            self.started += 1
        # Without the guard a concurrent invocation removes this workspace here.
        time.sleep(0.08)
        try:
            self.asserted_bytes = drawing.read_bytes()
        except Exception as exc:
            self.failures.append(exc)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


class _Project:
    def __init__(self):
        self.status = 'analyzing'
        self.last_error = ''


class _DB:
    def __init__(self, project):
        self.project = project

    def get(self, _model, _project_id):
        return self.project

    def close(self):
        pass


class _RetryLegacy:
    Project = object

    def __init__(self):
        self.project = _Project()
        self.attempts = 0
        self.analyze_project_job = self._analyze

    def Session(self):
        return _DB(self.project)

    def _analyze(self, project_id: int):
        self.attempts += 1
        if self.attempts == 1:
            self.project.status = 'awaiting_upload'
            self.project.last_error = (
                "No such file or directory: '/tmp/engitools-analysis/74/000 architecture.dxf'"
            )
        else:
            self.project.status = 'asking'
            self.project.last_error = ''


class AnalysisWorkspaceGuardTests(unittest.TestCase):
    def test_same_project_analysis_cannot_delete_active_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            legacy = _FakeLegacy(Path(td))
            install(legacy)
            threads = [
                threading.Thread(target=legacy.analyze_project_job, args=(74,)),
                threading.Thread(target=legacy.analyze_project_job, args=(74,)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
            self.assertEqual(legacy.started, 2)
            self.assertEqual(legacy.failures, [])

    def test_different_projects_are_not_globally_serialized(self):
        with tempfile.TemporaryDirectory() as td:
            legacy = _FakeLegacy(Path(td))
            install(legacy)
            start = time.monotonic()
            threads = [
                threading.Thread(target=legacy.analyze_project_job, args=(74,)),
                threading.Thread(target=legacy.analyze_project_job, args=(75,)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
            elapsed = time.monotonic() - start
            self.assertEqual(legacy.failures, [])
            self.assertLess(elapsed, 0.15)

    def test_missing_workspace_retries_once_when_original_is_durable(self):
        legacy = _RetryLegacy()
        original = guard.artifact_storage.input_is_durable
        guard.artifact_storage.input_is_durable = lambda project_id: project_id == 74
        try:
            install(legacy)
            legacy.analyze_project_job(74)
        finally:
            guard.artifact_storage.input_is_durable = original
        self.assertEqual(legacy.attempts, 2)
        self.assertEqual(legacy.project.status, 'asking')
        self.assertEqual(legacy.project.last_error, '')


if __name__ == '__main__':
    unittest.main()
