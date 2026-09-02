"""Fail-closed validation for active production version synchronization."""

from __future__ import annotations

import json
from pathlib import Path

from app.fixture_equipment_rulebook import RULEBOOK_VERSION as FIXTURE_RULEBOOK_VERSION
from app.mechanical_rulebook import RULEBOOK_VERSION as APP_RULEBOOK_VERSION

from .version_manifest import active_version_manifest


ROOT = Path(__file__).resolve().parents[1]
RULEBOOK_GENERATOR = ROOT / "data" / "rulebook" / "generate_rulebook_v4.py"


def _generator_uses_active_rulebook_version() -> bool:
    """Verify the generator contract without importing optional python-docx."""
    source = RULEBOOK_GENERATOR.read_text(encoding="utf-8")
    return (
        "from cad_engine.version_manifest import MECHANICAL_RULEBOOK_VERSION" in source
        and "VERSION = MECHANICAL_RULEBOOK_VERSION" in source
    )


def synchronization_errors() -> list[str]:
    active = active_version_manifest()
    errors: list[str] = []

    release = json.loads((ROOT / "standards" / "active-release.json").read_text())
    for key, value in active.items():
        if release.get(key) != value:
            errors.append(f"active-release:{key}:expected={value}:actual={release.get(key)}")

    if APP_RULEBOOK_VERSION != active["mechanical_rulebook"]:
        errors.append("application-rulebook-version-drift")
    if not _generator_uses_active_rulebook_version():
        errors.append("generated-rulebook-version-drift")
    if FIXTURE_RULEBOOK_VERSION != active["fixture_equipment_rulebook"]:
        errors.append("fixture-rulebook-version-drift")

    matrix = (ROOT / "docs" / "ACTIVE_VERSION_MATRIX.md").read_text()
    for key, value in active.items():
        if str(value) not in matrix:
            errors.append(f"active-version-matrix-missing:{key}:{value}")

    readme = (ROOT / "README.md").read_text()
    if active["platform_release"] not in readme:
        errors.append("readme-platform-version-drift")
    if active["production_cad_entrypoint"] not in readme:
        errors.append("readme-production-entrypoint-drift")

    launcher_text = "\n".join(
        (ROOT / path).read_text()
        for path in ("start_services.sh", "cad_engine/Dockerfile")
    )
    expected_launch = f"uvicorn {active['production_cad_entrypoint']}"
    if launcher_text.count(expected_launch) != 2:
        errors.append("production-launcher-version-drift")

    return errors


def assert_versions_synchronized() -> dict[str, object]:
    errors = synchronization_errors()
    if errors:
        raise RuntimeError("Active version synchronization FAIL: " + "; ".join(errors))
    return {"status": "PASS", "versions": active_version_manifest()}


if __name__ == "__main__":
    print(json.dumps(assert_versions_synchronized(), indent=2, sort_keys=True))
