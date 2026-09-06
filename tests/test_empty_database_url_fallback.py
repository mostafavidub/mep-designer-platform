import os
import subprocess
import sys


def test_empty_database_url_uses_persistent_sqlite_default(tmp_path):
    env = dict(os.environ)
    env.update({"DATABASE_URL": "", "DATA_DIR": str(tmp_path)})
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import DB_URL; print(DB_URL)"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == f"sqlite:///{tmp_path / 'mep.db'}"
