import hashlib
import io
import json
import time
import zipfile
from uuid import uuid4

import ezdxf
import pytest
from fastapi.testclient import TestClient

from app import mechanical_workflow, questionnaire_jobs
from app.main_health import app, main_auto


legacy = main_auto.legacy


def _login(client, suffix):
    headers = {"x-panel-token": "finalization-test-secret"}
    response = client.post(
        "/internal/panel/customer/session",
        headers=headers,
        json={"phone": f"0912{suffix:07d}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {**headers, "x-customer-session": body["session"]}, int(body["userId"].split("-")[1])


def _valid_dxf(tmp_path):
    path = tmp_path / "architecture.dxf"
    document = ezdxf.new("R2010")
    model = document.modelspace()
    model.add_lwpolyline(
        [(0, 0), (8000, 0), (8000, 6000), (0, 6000)],
        close=True,
        dxfattribs={"layer": "WALL"},
    )
    model.add_text(
        "LIVING", dxfattribs={"layer": "ROOM", "height": 250}
    ).set_placement((4000, 3000))
    document.saveas(path)
    return path.read_bytes()


def _zip(content):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("architecture.dxf", content)
    return output.getvalue()


def _wait(client, headers, job_id):
    for _ in range(120):
        response = client.get(f"/internal/panel/questionnaire/{job_id}", headers=headers)
        if response.status_code == 200:
            return response
        time.sleep(0.01)
    raise AssertionError("questionnaire job did not finish")


def _create_ready_authority(owner, filename, content):
    job_id = hashlib.sha256(
        f"{owner}:mechanical:residential".encode() + content
    ).hexdigest()[:32]
    workspace = questionnaire_jobs._root() / job_id
    workspace.mkdir(parents=True)
    (workspace / filename).write_bytes(content)
    questionnaire_jobs._write(workspace / "metadata.json", {
        "owner": owner,
        "name": filename,
        "discipline": "mechanical",
        "occupancy": "residential",
        "created_at": int(time.time()),
    })
    result = questionnaire_jobs._analyze(
        workspace, filename, "mechanical", "residential", main_auto, legacy
    )
    questionnaire_jobs._write(workspace / "state.json", {
        "status": "ready", "result": result, "attempts": 1, "finished_at": int(time.time())
    })
    return job_id, result


def _finalize(client, headers, job_id, answers, external_id=None):
    return client.post(
        "/internal/panel/projects",
        headers=headers,
        data={
            "external_project_id": external_id or f"PRJ-{uuid4().hex[:12]}",
            "external_user_id": "ignored-client-identity",
            "name": "Ready authority finalization",
            "discipline": "mechanical",
            "occupancy": "residential",
            "analysis_job_id": job_id,
            "answers_json": json.dumps(answers),
        },
    )


@pytest.mark.parametrize("filename,content_type,archive", [
    ("architecture.dxf", "application/dxf", False),
    ("architecture.zip", "application/zip", True),
])
def test_real_ready_dxf_and_zip_finalize_without_second_analysis(
    monkeypatch, tmp_path, filename, content_type, archive,
):
    monkeypatch.setenv("PANEL_BRIDGE_TOKEN", "finalization-test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(mechanical_workflow, "required_basis_questions", lambda _project: [])
    calls = []
    monkeypatch.setattr(legacy, "analyze_project_job", lambda project_id: calls.append(project_id))
    saved_inputs = []
    monkeypatch.setattr(
        legacy,
        "save_project_input",
        lambda project_id, upload: saved_inputs.append((project_id, upload.filename, upload.file.read())),
    )
    client = TestClient(app, raise_server_exceptions=False)
    headers, _owner = _login(client, int(uuid4().hex[:7], 16) % 10_000_000)
    dxf = _valid_dxf(tmp_path)
    content = _zip(dxf) if archive else dxf
    job_id, result = _create_ready_authority(_owner, filename, content)
    answers = {question["key"]: "تأیید" for question in result["questions"] if question.get("key")}

    finalized = _finalize(client, headers, job_id, answers)

    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] == "ready_to_design"
    assert calls == []
    assert len(saved_inputs) == 1 and saved_inputs[0][2] == content
    with legacy.Session() as db:
        project = db.get(legacy.Project, finalized.json()["engine_project_id"])
        authority = project.analysis["questionnaire_authority"]
        assert authority["job_id"] == job_id
        assert len(authority["source_sha256"]) == 64


def test_finalization_is_idempotent_and_failed_replay_is_not_success(monkeypatch, tmp_path):
    monkeypatch.setenv("PANEL_BRIDGE_TOKEN", "finalization-test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(mechanical_workflow, "required_basis_questions", lambda _project: [])
    saved_inputs = []
    monkeypatch.setattr(
        legacy,
        "save_project_input",
        lambda project_id, upload: saved_inputs.append((project_id, upload.file.read())),
    )
    client = TestClient(app, raise_server_exceptions=False)
    headers, _owner = _login(client, int(uuid4().hex[:7], 16) % 10_000_000)
    content = _valid_dxf(tmp_path)
    job_id, result = _create_ready_authority(_owner, "architecture.dxf", content)
    answers = {question["key"]: "تأیید" for question in result["questions"] if question.get("key")}
    external_id = f"PRJ-IDEMPOTENT-{uuid4().hex[:8]}"

    first = _finalize(client, headers, job_id, answers, external_id)
    second = _finalize(client, headers, job_id, answers, external_id)

    assert first.status_code == second.status_code == 200
    assert first.json()["engine_project_id"] == second.json()["engine_project_id"]
    assert len(saved_inputs) == 1
    with legacy.Session() as db:
        project = db.get(legacy.Project, first.json()["engine_project_id"])
        project.status = "failed"
        project.last_error = "controlled finalization failure"
        db.commit()
    failed_replay = _finalize(client, headers, job_id, answers, external_id)
    assert failed_replay.status_code == 409
    assert failed_replay.json()["status"] == "failed"


def test_ready_authority_rejects_wrong_owner_and_changed_source(monkeypatch, tmp_path):
    monkeypatch.setenv("PANEL_BRIDGE_TOKEN", "finalization-test-secret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "jobs"))
    client = TestClient(app, raise_server_exceptions=False)
    owner_headers, _owner = _login(client, int(uuid4().hex[:7], 16) % 10_000_000)
    other_headers, _other = _login(client, int(uuid4().hex[:7], 16) % 10_000_000)
    job_id, _result = _create_ready_authority(_owner, "architecture.dxf", _valid_dxf(tmp_path))

    wrong_owner = _finalize(client, other_headers, job_id, {})
    assert wrong_owner.status_code == 409
    source = tmp_path / "jobs" / "questionnaire-jobs" / job_id / "architecture.dxf"
    source.write_bytes(source.read_bytes() + b"tampered")
    changed_source = _finalize(client, owner_headers, job_id, {})
    assert changed_source.status_code == 409
    assert "هویت فایل" in changed_source.json()["detail"]


def test_status_read_does_not_wait_for_background_analysis(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    workspace = tmp_path / "questionnaire-jobs" / ("a" * 32)
    workspace.mkdir(parents=True)
    questionnaire_jobs._write(workspace / "metadata.json", {
        "owner": 7, "name": "architecture.dxf", "discipline": "mechanical",
        "occupancy": "residential", "created_at": int(time.time()),
    })
    questionnaire_jobs._write(workspace / "state.json", {"status": "processing", "attempts": 1})
    questionnaire_jobs._TASKS["a" * 32] = object()
    monkeypatch.setattr(questionnaire_jobs, "session_user", lambda _request: 7)
    isolated = __import__("fastapi").FastAPI()
    questionnaire_jobs.register_questionnaire_jobs(isolated, main_auto, legacy)
    started = time.monotonic()
    response = TestClient(isolated).get(f"/internal/panel/questionnaire/{'a' * 32}")
    elapsed = time.monotonic() - started
    questionnaire_jobs._TASKS.pop("a" * 32, None)
    assert response.status_code == 202
    assert elapsed < 0.5
