import sqlite3
from pathlib import Path

from app.storage_bootstrap import checkpoint_sqlite, reclaim_transient_storage


def test_bootstrap_reclaims_only_regenerable_project_paths(tmp_path: Path):
    project = tmp_path / "projects" / "12"
    for relative in ("output/final.dxf", ".upload_chunks/000.part", "architecture.zip.uploading"):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"temporary")
    for relative in ("architecture.zip", "input/floor.dxf"):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"authoritative")
    legacy_cad = tmp_path / "cad-engine" / "12" / "R001" / "mechanical" / "draft.dxf"
    legacy_cad.parent.mkdir(parents=True)
    legacy_cad.write_bytes(b"regenerable")

    removed = reclaim_transient_storage(tmp_path)

    assert removed
    assert not (project / "output").exists()
    assert not (project / ".upload_chunks").exists()
    assert not (project / "architecture.zip.uploading").exists()
    assert not (tmp_path / "cad-engine").exists()
    assert (project / "architecture.zip").read_bytes() == b"authoritative"
    assert (project / "input/floor.dxf").read_bytes() == b"authoritative"


def test_bootstrap_checkpoints_sqlite_without_changing_data(tmp_path: Path):
    database = tmp_path / "mep.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE evidence (value TEXT)")
    connection.execute("INSERT INTO evidence VALUES ('preserved')")
    connection.commit()
    connection.close()

    checkpoint_sqlite(f"sqlite:///{database}")

    connection = sqlite3.connect(database)
    assert connection.execute("SELECT value FROM evidence").fetchone() == ("preserved",)
    connection.close()
