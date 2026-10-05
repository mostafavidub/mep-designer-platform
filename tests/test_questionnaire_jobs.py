import time

from fastapi.testclient import TestClient

from app.main_health import app
from app import questionnaire_jobs


def _session(client, phone):
    headers = {"x-panel-token": "questionnaire-job-test-secret"}
    payload = client.post(
        "/internal/panel/customer/session", headers=headers, json={"phone": phone}).json()
    return {**headers, "x-customer-session": payload["session"]}


def _wait_for_terminal(client, job_id, headers):
    response = None
    for _ in range(80):
        response = client.get(f"/internal/panel/questionnaire/{job_id}", headers=headers)
        if response.status_code == 200:
            return response
        time.sleep(0.01)
    return response


def test_canonical_questionnaire_routes_are_registered_once():
    routes = [
        (route.path, frozenset(route.methods or ()))
        for route in app.routes
        if "questionnaire" in getattr(route, "path", "")
    ]
    assert routes.count(("/internal/panel/questionnaire/start", frozenset({"POST"}))) == 1
    assert routes.count(("/internal/panel/questionnaire/{job_id}", frozenset({"GET"}))) == 1


def test_questionnaire_job_is_deduplicated_resumable_and_owner_bound(monkeypatch, tmp_path):
    monkeypatch.setenv("PANEL_BRIDGE_TOKEN", "questionnaire-job-test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(questionnaire_jobs, "_analyze", lambda *_args: {
        "identity": "test", "questions": [], "inferred_answers": {},
        "panel_analysis": {"status": "ready"},
    })
    client = TestClient(app)
    owner = _session(client, "09120000001")
    other = _session(client, "09120000002")
    files = {"file": ("architecture.dxf", b"0\nEOF\n", "application/dxf")}
    first = client.post(
        "/internal/panel/questionnaire/start?discipline=mechanical&occupancy=residential",
        headers=owner, files=files)
    assert first.status_code in {200, 202}
    job_id = first.json()["job_id"]
    result = _wait_for_terminal(client, job_id, owner)
    assert result is not None and result.status_code == 200
    assert result.json()["status"] == "ready"
    assert client.get(f"/internal/panel/questionnaire/{job_id}", headers=other).status_code == 404
    repeated = client.post(
        "/internal/panel/questionnaire/start?discipline=mechanical&occupancy=residential",
        headers=owner, files=files)
    assert repeated.json()["job_id"] == job_id
    assert repeated.json()["status"] == "ready"


def test_questionnaire_job_rejects_missing_bridge_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("PANEL_BRIDGE_TOKEN", "questionnaire-job-test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    response = TestClient(app).post(
        "/internal/panel/questionnaire/start",
        files={"file": ("architecture.dxf", b"0\nEOF\n", "application/dxf")})
    assert response.status_code == 404


def test_terminal_analysis_failure_stops_without_retry_or_relaunch(monkeypatch, tmp_path):
    monkeypatch.setenv("PANEL_BRIDGE_TOKEN", "questionnaire-job-test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    calls = []

    def invalid_input(*_args):
        calls.append(1)
        raise ValueError("invalid dxf")

    monkeypatch.setattr(questionnaire_jobs, "_analyze", invalid_input)
    client = TestClient(app)
    owner = _session(client, "09120000003")
    files = {"file": ("architecture.dxf", b"0\nEOF\n", "application/dxf")}
    started = client.post(
        "/internal/panel/questionnaire/start?discipline=mechanical&occupancy=residential",
        headers=owner,
        files=files,
    )
    result = _wait_for_terminal(client, started.json()["job_id"], owner)
    assert result is not None and result.json() == {
        "status": "failed",
        "error": "فایل معماری قابل تحلیل نبود؛ فایل را بررسی و دوباره بارگذاری کنید.",
        "error_code": "invalid_architecture_input",
        "retryable": False,
        "attempts": 1,
        "finished_at": result.json()["finished_at"],
    }
    repeated = client.post(
        "/internal/panel/questionnaire/start?discipline=mechanical&occupancy=residential",
        headers=owner,
        files=files,
    )
    assert repeated.json()["status"] == "failed"
    assert len(calls) == 1


def test_temporary_failure_retries_with_bound_and_recovers(monkeypatch, tmp_path):
    monkeypatch.setenv("PANEL_BRIDGE_TOKEN", "questionnaire-job-test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    calls = []

    def temporarily_unavailable(*_args):
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("temporary")
        return {
            "identity": "test",
            "questions": [],
            "inferred_answers": {},
            "panel_analysis": {"status": "ready"},
        }

    monkeypatch.setattr(questionnaire_jobs, "_analyze", temporarily_unavailable)
    client = TestClient(app)
    owner = _session(client, "09120000004")
    started = client.post(
        "/internal/panel/questionnaire/start?discipline=mechanical&occupancy=residential",
        headers=owner,
        files={"file": ("architecture.dxf", b"0\nEOF\n", "application/dxf")},
    )
    result = _wait_for_terminal(client, started.json()["job_id"], owner)
    assert result is not None and result.json()["status"] == "ready"
    assert result.json()["attempts"] == 3
    assert len(calls) == 3


def test_temporary_failure_exhaustion_becomes_stable_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("PANEL_BRIDGE_TOKEN", "questionnaire-job-test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    calls = []

    def unavailable(*_args):
        calls.append(1)
        raise ConnectionError("temporary")

    monkeypatch.setattr(questionnaire_jobs, "_analyze", unavailable)
    client = TestClient(app)
    owner = _session(client, "09120000005")
    started = client.post(
        "/internal/panel/questionnaire/start?discipline=mechanical&occupancy=residential",
        headers=owner,
        files={"file": ("architecture.dxf", b"0\nEOF\n", "application/dxf")},
    )
    result = _wait_for_terminal(client, started.json()["job_id"], owner)
    payload = result.json()
    assert payload["status"] == "failed"
    assert payload["retryable"] is True
    assert payload["attempts"] == 3
    assert len(calls) == 3


def test_restart_after_last_attempt_cannot_remain_processing(monkeypatch, tmp_path):
    monkeypatch.setenv("PANEL_BRIDGE_TOKEN", "questionnaire-job-test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    client = TestClient(app)
    owner = _session(client, "09120000006")
    started = client.post(
        "/internal/panel/questionnaire/start?discipline=mechanical&occupancy=residential",
        headers=owner,
        files={"file": ("architecture.dxf", b"0\nEOF\n", "application/dxf")},
    )
    job_id = started.json()["job_id"]
    _wait_for_terminal(client, job_id, owner)
    questionnaire_jobs._TASKS.pop(job_id, None)
    state = tmp_path / "questionnaire-jobs" / job_id / "state.json"
    questionnaire_jobs._write(state, {"status": "processing", "attempts": 3})

    result = client.get(f"/internal/panel/questionnaire/{job_id}", headers=owner)

    assert result.status_code == 200
    assert result.json()["status"] == "failed"
    assert result.json()["attempts"] == 3
