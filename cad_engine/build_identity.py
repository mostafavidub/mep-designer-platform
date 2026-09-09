"""Immutable, automatic identity for a deployed build and its artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PMM_SCHEMA_REVISION = "project-mechanical-model/v3"
RULEBOOK_SCHEMA_REVISION = "mechanical-rulebook/5.0"
MANUFACTURER_SCHEMA_REVISION = "manufacturer-catalogue/1"
COMPLIANCE_PROFILE_REVISION = "mechanical-design-governance/1"


def _sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    existing = sorted({path.resolve() for path in paths if path.is_file()})
    for path in existing:
        digest.update(str(path.relative_to(ROOT)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _commit_sha() -> str:
    return (
        os.getenv("GIT_COMMIT_SHA", "").strip()
        or os.getenv("RAILWAY_GIT_COMMIT_SHA", "").strip()
        or _git("rev-parse", "HEAD")
        or "UNKNOWN"
    )


def _build_timestamp() -> str:
    explicit = os.getenv("BUILD_TIMESTAMP", "").strip()
    if explicit:
        return explicit
    commit_time = _git("show", "-s", "--format=%cI", "HEAD")
    if commit_time:
        return commit_time
    commit_sha = _commit_sha()
    return f"commit:{commit_sha}"


def build_identity() -> dict[str, object]:
    dependency_files = [ROOT / "requirements.txt", ROOT / "cad_engine" / "requirements.txt"]
    rulebook_root = ROOT / "data" / "rulebook"
    rulebook_files = [
        path for path in rulebook_root.glob("*")
        if path.suffix.lower() in {".py", ".b64", ".txt"}
    ]
    manufacturer_root = ROOT / "data" / "manufacturer"
    manufacturer_files = list(manufacturer_root.rglob("*")) if manufacturer_root.exists() else []
    compliance_files = [ROOT / "standards" / "mechanical-design-governance-v1.json"]
    pmm_files = [ROOT / "app" / "project_mechanical_model.py", ROOT / "app" / "mechanical_basis_contract.py"]
    identity = {
        "commit_sha": _commit_sha(),
        "build_timestamp": _build_timestamp(),
        "production_entrypoint": "cad_engine.main:app",
        "pmm_schema_revision": PMM_SCHEMA_REVISION,
        "pmm_schema_hash": _sha256(pmm_files),
        "rulebook_schema_revision": RULEBOOK_SCHEMA_REVISION,
        "rulebook_hash": _sha256(rulebook_files),
        "manufacturer_schema_revision": MANUFACTURER_SCHEMA_REVISION,
        "manufacturer_db_hash": _sha256(manufacturer_files),
        "compliance_profile_revision": COMPLIANCE_PROFILE_REVISION,
        "compliance_profile_hash": _sha256(compliance_files),
        "dependency_hashes": {str(path.relative_to(ROOT)): _sha256([path]) for path in dependency_files},
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    identity["build_identity"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return identity


def stamp_artifact(metadata: dict | None = None) -> dict:
    stamped = dict(metadata or {})
    stamped["build"] = build_identity()
    return stamped
