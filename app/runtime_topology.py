"""Truthful, credential-free deployment topology diagnostics.

This module deliberately does not connect to the database.  It reports the
configuration that the process is actually using so a web replica cannot look
healthy while silently falling back to a private SQLite file.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit


def deployment_environment() -> str:
    return (
        os.getenv("DEPLOYMENT_ENV")
        or os.getenv("RAILWAY_ENVIRONMENT_NAME")
        or "local"
    ).strip().lower()


def database_dialect(database_url: str) -> str:
    scheme = urlsplit(database_url).scheme.lower().split("+", 1)[0]
    return scheme or "unknown"


def service_role(worker_types: set[str]) -> str:
    if not worker_types:
        return "web"
    if worker_types == {"analysis"}:
        return "analysis_worker"
    if worker_types == {"design"}:
        return "design_worker"
    return "combined_worker"


def topology_status(database_url: str, worker_types: set[str]) -> dict:
    environment = deployment_environment()
    dialect = database_dialect(database_url)
    deployed = environment not in {"", "local", "development", "test"}
    shared_database = dialect in {"postgres", "postgresql"}
    acceptable = not deployed or shared_database
    migration_mode = os.getenv("SCHEMA_MANAGEMENT_MODE", "legacy_auto").strip().lower()
    return {
        "environment": environment,
        "service_role": service_role(worker_types),
        "worker_types": sorted(worker_types),
        "database": {
            "dialect": dialect,
            "shared": shared_database,
            "acceptable_for_deployment": acceptable,
            "explicit_url": bool(os.getenv("DATABASE_URL", "").strip()),
        },
        "schema_management": {
            "mode": migration_mode,
            "startup_create_all": migration_mode == "legacy_auto",
        },
        "status": "ok" if acceptable else "error",
    }

