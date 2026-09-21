import time

from fastapi.testclient import TestClient

from app.main_health import app
from app import questionnaire_jobs


def _session(client, phone):
    headers = {"x-panel-token": "questionnaire-job-test-secret"}
    payload = client.post(
        "/internal/panel/customer/session", headers=headers, json={"phone": phone}).json()
    return {**headers, "x-customer-session": payload["session"]}


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
    result = None
    for _ in range(20):
        result = client.get(f"/internal/panel/questionnaire/{job_id}", headers=owner)
        if result.status_code == 200:
            break
        time.sleep(0.01)
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
