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


def test_isolated_service_routes_electrical_to_explicit_worker_operation(monkeypatch):
    seen={}
    def fake_worker(payload,operation="design"):
        seen["payload"]=payload;seen["operation"]=operation
        return 200,{"ok":True,"discipline":"electrical","pipeline_authority":"electrical-authority"}
    monkeypatch.setattr(service,"_run_worker",fake_worker)
    response=TestClient(service.app).post("/design-electrical",json={"project_id":"98","discipline":"electrical"})
    assert response.status_code==200
    assert seen["operation"]=="design-electrical"
    assert seen["payload"]["discipline"]=="electrical"


def test_isolated_service_exposes_electrical_status_and_design_routes():
    paths={route.path for route in service.app.routes}
    assert "/electrical/status" in paths
    assert "/design-electrical" in paths
