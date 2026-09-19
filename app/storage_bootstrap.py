"""Conservative pre-start reclamation for the persistent application volume."""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path


def reclaim_transient_storage(data_dir: Path) -> list[str]:
    """Remove only regenerable workspaces; preserve inputs, DBs and issued files."""
    removed: list[str] = []
    targets = [data_dir / "cad-engine"]
    projects = data_dir / "projects"
    if projects.is_dir():
        for project in projects.iterdir():
            if not project.is_dir():
                continue
            targets.extend((project / "output", project / ".upload_chunks"))
            targets.extend(project.glob("*.uploading"))
    for target in targets:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            if not target.exists():
                removed.append(str(target))
        elif target.is_file():
            target.unlink(missing_ok=True)
            removed.append(str(target))
    return removed


def checkpoint_sqlite(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return
    path = Path(database_url[len(prefix):])
    if not path.exists():
        return
    connection = sqlite3.connect(path, timeout=30)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


def main() -> None:
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    reclaim_transient_storage(data_dir)
    checkpoint_sqlite(os.getenv("DATABASE_URL", f"sqlite:///{data_dir / 'mep.db'}"))


if __name__ == "__main__":
    main()
