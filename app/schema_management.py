"""Single-owner schema bootstrap for shared staging/production databases.

`legacy_auto` preserves local/backward-compatible installs.  Deployed services
use `migrate_once`: exactly one explicitly designated process owns DDL and all
other web/worker replicas remain read/write application clients only.
"""
from __future__ import annotations

import os

from sqlalchemy import text

MIGRATION_LOCK_ID = 731_904_217


def mode() -> str:
    return os.getenv("SCHEMA_MANAGEMENT_MODE", "legacy_auto").strip().lower()


def migration_owner() -> bool:
    return os.getenv("SCHEMA_MIGRATION_OWNER", "0").strip() == "1"


def registration_ddl_enabled() -> bool:
    return mode() == "legacy_auto"


def create_table_during_registration(table, engine) -> None:
    if registration_ddl_enabled():
        table.create(bind=engine, checkfirst=True)


def migrate_registered_schema(engine, metadata) -> dict:
    current_mode = mode()
    if current_mode == "legacy_auto":
        return {"mode": current_mode, "owner": False, "executed": False}
    if current_mode != "migrate_once":
        raise RuntimeError(f"Unsupported SCHEMA_MANAGEMENT_MODE: {current_mode}")
    if not migration_owner():
        return {"mode": current_mode, "owner": False, "executed": False}

    dialect = engine.url.get_backend_name()
    with engine.begin() as connection:
        if dialect == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": MIGRATION_LOCK_ID})
        metadata.create_all(bind=connection, checkfirst=True)
    return {"mode": current_mode, "owner": True, "executed": True}

