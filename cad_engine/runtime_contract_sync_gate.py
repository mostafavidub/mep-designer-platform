"""Fail-closed synchronization for the single canonical Mechanical runtime contract."""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.fixture_equipment_rulebook import RULEBOOK_IDENTITY as FIXTURE_RULEBOOK_IDENTITY
from app.mechanical_rulebook import RULEBOOK_IDENTITY as APP_RULEBOOK_IDENTITY

from .build_identity import build_identity
from .runtime_contract import (
    FIXTURE_EQUIPMENT_RULEBOOK_IDENTITY,
    MECHANICAL_RULEBOOK_IDENTITY,
    PMM_SCHEMA,
    PRODUCTION_CAD_ENTRYPOINT,
    RUNTIME_IDENTITY,
    runtime_contract,
)

ROOT = Path(__file__).resolve().parents[1]
RULEBOOK_GENERATOR = ROOT / "data" / "rulebook" / "generate_rulebook.py"
RUNTIME_MATRIX = ROOT / "docs" / "RUNTIME_CONTRACT_MATRIX.md"


def _generator_uses_contract_identity() -> bool:
    if not RULEBOOK_GENERATOR.is_file():
        return False
    source = RULEBOOK_GENERATOR.read_text(encoding="utf-8")
    return (
        "from cad_engine.runtime_contract import MECHANICAL_RULEBOOK_IDENTITY" in source
        and "RULEBOOK_IDENTITY = MECHANICAL_RULEBOOK_IDENTITY" in source
    )


def contract_synchronization_errors() -> list[str]:
    contract = runtime_contract()
    errors: list[str] = []

    release = json.loads((ROOT / "standards" / "active-release.json").read_text())
    if release.get("production_cad_entrypoint") != PRODUCTION_CAD_ENTRYPOINT:
        errors.append("release-contract:production_cad_entrypoint")
    if release.get("identity_policy") != "git-commit-and-content-hashes":
        errors.append("release-contract:identity_policy")
    if release.get("pmm_schema_revision") != PMM_SCHEMA:
        errors.append("release-contract:pmm_schema_revision")
    if release.get("mechanical_rulebook_identity") != MECHANICAL_RULEBOOK_IDENTITY:
        errors.append("release-contract:mechanical_rulebook_identity")
    if release.get("build_identity_source") != "cad_engine/build_identity.py":
        errors.append("release-contract:build_identity_source")
    if "version_source" in release:
        errors.append("release-contract:legacy_version_source")

    if contract.get("runtime_identity") != RUNTIME_IDENTITY:
        errors.append("runtime-contract:identity")
    if contract.get("production_cad_entrypoint") != PRODUCTION_CAD_ENTRYPOINT:
        errors.append("runtime-contract:entrypoint")
    if APP_RULEBOOK_IDENTITY != MECHANICAL_RULEBOOK_IDENTITY:
        errors.append("application-rulebook-identity-drift")
    if FIXTURE_RULEBOOK_IDENTITY != FIXTURE_EQUIPMENT_RULEBOOK_IDENTITY:
        errors.append("fixture-rulebook-identity-drift")
    if not _generator_uses_contract_identity():
        errors.append("generated-rulebook-identity-drift")

    identity = build_identity()
    if identity.get("production_entrypoint") != PRODUCTION_CAD_ENTRYPOINT:
        errors.append("build-identity:entrypoint")
    if identity.get("pmm_schema_revision") != PMM_SCHEMA:
        errors.append("build-identity:pmm_schema_revision")
    if identity.get("rulebook_identity") != MECHANICAL_RULEBOOK_IDENTITY:
        errors.append("build-identity:rulebook_identity")

    if not RUNTIME_MATRIX.is_file():
        errors.append("runtime-contract-matrix-missing")
    else:
        matrix = RUNTIME_MATRIX.read_text(encoding="utf-8")
        if PRODUCTION_CAD_ENTRYPOINT not in matrix:
            errors.append("runtime-contract-matrix:entrypoint")
        if re.search(r"Mechanical\s+(?:pipeline|authority|runtime)\s+v\d+", matrix, re.I):
            errors.append("runtime-contract-matrix:engine-version-identity")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if PRODUCTION_CAD_ENTRYPOINT not in readme:
        errors.append("readme:production-entrypoint")

    launcher_text = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in ("start_services.sh", "cad_engine/Dockerfile"))
    expected_launch = f"uvicorn {PRODUCTION_CAD_ENTRYPOINT}"
    if launcher_text.count(expected_launch) != 2:
        errors.append("production-launcher-entrypoint-drift")
    if "cad_engine.main_v" in launcher_text:
        errors.append("production-launcher-versioned-entrypoint")
    if re.search(r"generate_rulebook_v\d+\.py", launcher_text):
        errors.append("production-launcher-versioned-rulebook-generator")

    return sorted(set(errors))


def assert_runtime_contract_synchronized() -> dict[str, object]:
    errors = contract_synchronization_errors()
    if errors:
        raise RuntimeError("Runtime contract synchronization FAIL: " + "; ".join(errors))
    return {"status": "PASS", "runtime_contract": runtime_contract()}


if __name__ == "__main__":
    print(json.dumps(assert_runtime_contract_synchronized(), indent=2, sort_keys=True))
