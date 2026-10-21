from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.local-staging.yml"


def _config():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_local_staging_reuses_canonical_production_image_and_startup():
    config = _config()
    app = config["services"]["app"]

    assert app["build"] == {"context": ".", "dockerfile": "Dockerfile"}
    assert "command" not in app
    assert (ROOT / "Dockerfile").read_text(encoding="utf-8").rstrip().endswith(
        'CMD ["./start_services.sh"]'
    )


def test_local_staging_database_is_explicitly_isolated():
    config = _config()
    database_url = config["services"]["app"]["environment"]["DATABASE_URL"]

    assert "@postgres:5432/planha_local_staging" in database_url
    for forbidden in ("railway", "planha.com", "production"):
        assert forbidden not in database_url.lower()
    assert config["services"]["postgres"]["image"] == "postgres:18"


def test_local_staging_does_not_inherit_cloud_credentials_or_public_networking():
    config = _config()
    app = config["services"]["app"]
    environment = app["environment"]

    assert not any(name.startswith("S3_") for name in environment)
    assert environment["PUBLIC_SITE_URL"] == "http://127.0.0.1:8080"
    assert app["ports"] == ["127.0.0.1:8080:8080"]
    assert environment["CANONICAL_REDIRECT_HOSTS"] == ""


def test_local_staging_has_database_and_application_health_gates():
    config = _config()
    services = config["services"]

    assert "pg_isready" in services["postgres"]["healthcheck"]["test"][1]
    assert services["app"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert "/system_health" in services["app"]["healthcheck"]["test"][-1]
