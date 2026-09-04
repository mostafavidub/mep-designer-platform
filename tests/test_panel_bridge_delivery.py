from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "app/panel_bridge.py").read_text(encoding="utf-8")
HEALTH = (ROOT / "app/main_health.py").read_text(encoding="utf-8")
PROGRESS = (ROOT / "app/design_progress.py").read_text(encoding="utf-8")


def test_panel_bridge_positive_queues_real_design_job():
    assert 'Job(' in BRIDGE
    assert 'job_type="design"' in BRIDGE
    assert 'set_project_progress(project, "queued")' in BRIDGE
    assert 'project_token(external_project_id, external_user_hash)' in BRIDGE
    assert 'existing.external_user_hash' in BRIDGE
    assert "register_panel_bridge(app, main_auto.legacy, DesignJob)" in HEALTH


def test_panel_bridge_negative_requires_both_service_and_project_tokens():
    assert 'os.getenv("PANEL_BRIDGE_TOKEN", "")' in BRIDGE
    assert 'request.headers.get("x-panel-token", "")' in BRIDGE
    assert 'request.headers.get("x-project-token", "")' in BRIDGE
    assert BRIDGE.count("secrets.compare_digest") >= 2
    assert 'raise HTTPException(409, project.last_error)' in BRIDGE


def test_panel_bridge_golden_uses_persisted_design_progress():
    assert "get_project_progress(project)" in BRIDGE
    assert 'data["progress"] = progress["percent"]' in BRIDGE
    assert "STAGES" in PROGRESS
    assert "setInterval" not in BRIDGE


def test_panel_bridge_web_contract_exposes_output_only_when_ready():
    assert 'project.status == "ready"' in BRIDGE
    assert 'data["download_url"]' in BRIDGE
    assert '@app.get("/internal/panel/projects/{pid}/output")' in BRIDGE
    assert "presigned_download" in BRIDGE
