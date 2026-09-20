from app.runtime_topology import database_dialect, service_role, topology_status


def test_database_dialect_hides_credentials():
    assert database_dialect("postgresql+psycopg://user:secret@host/db") == "postgresql"


def test_worker_role_is_explicit():
    assert service_role(set()) == "web"
    assert service_role({"analysis"}) == "analysis_worker"
    assert service_role({"design"}) == "design_worker"


def test_deployed_sqlite_fails_closed(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "staging")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = topology_status("sqlite:////data/mep.db", set())
    assert result["status"] == "error"
    assert result["database"] == {
        "dialect": "sqlite",
        "shared": False,
        "acceptable_for_deployment": False,
        "explicit_url": False,
    }


def test_deployed_postgres_is_accepted(monkeypatch):
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "staging")
    monkeypatch.setenv("DATABASE_URL", "postgresql://hidden")
    result = topology_status("postgresql://hidden", {"analysis"})
    assert result["status"] == "ok"
    assert result["database"]["shared"] is True
    assert "hidden" not in repr(result)
