from fastapi.testclient import TestClient
import cad_engine.isolated_service as service

def test_isolated_service_serializes_design_through_worker(monkeypatch):
    monkeypatch.setattr(service,"_run_worker",lambda payload:(200,{"ok":True,"project_id":payload["project_id"]}))
    response=TestClient(service.app).post("/design",json={"project_id":"98"})
    assert response.status_code==200
    assert response.json()=={"ok":True,"project_id":"98"}

def test_isolated_service_surfaces_worker_termination(monkeypatch):
    monkeypatch.setattr(service,"_run_worker",lambda payload:(503,{"detail":{"code":"CAD_WORKER_TERMINATED"}}))
    response=TestClient(service.app).post("/design",json={"project_id":"98"})
    assert response.status_code==503
    assert response.json()["detail"]["code"]=="CAD_WORKER_TERMINATED"
