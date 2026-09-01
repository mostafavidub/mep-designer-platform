import json
from pathlib import Path

from cad_engine.version_manifest import (
    CAD_API_VERSION,
    MECHANICAL_PIPELINE_VERSION,
    PLATFORM_RELEASE,
    PRODUCTION_CAD_ENTRYPOINT,
    active_version_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def test_active_runtime_and_public_version_contract_are_identical():
    assert PLATFORM_RELEASE == CAD_API_VERSION == "18.3.0"
    assert MECHANICAL_PIPELINE_VERSION.endswith("v18.3")
    assert PRODUCTION_CAD_ENTRYPOINT == "cad_engine.main_v18:app"
    assert active_version_manifest()["platform_release"] == PLATFORM_RELEASE
    main_v15 = (ROOT / "cad_engine" / "main_v15.py").read_text()
    main_v18 = (ROOT / "cad_engine" / "main_v18.py").read_text()
    assert 'version=CAD_API_VERSION' in main_v15
    assert '"version": CAD_API_VERSION' in main_v15
    assert '"mechanical_pipeline_version": MECHANICAL_PIPELINE_VERSION' in main_v15
    assert 'from .main_v17 import app' in main_v18
    assert 'return active_version_manifest()' in main_v18


def test_every_production_launcher_uses_the_active_entrypoint():
    launcher = (ROOT / "start_services.sh").read_text()
    dockerfile = (ROOT / "cad_engine" / "Dockerfile").read_text()
    assert "uvicorn cad_engine.main_v18:app" in launcher
    assert "uvicorn cad_engine.main_v18:app" in dockerfile
    assert "uvicorn cad_engine.main_v15:app" not in launcher + dockerfile
    assert "uvicorn cad_engine.main_v17:app" not in launcher + dockerfile


def test_release_record_and_current_docs_do_not_drift():
    release = json.loads((ROOT / "standards" / "active-release.json").read_text())
    assert release["platform_release"] == PLATFORM_RELEASE
    assert release["production_cad_entrypoint"] == PRODUCTION_CAD_ENTRYPOINT
    assert release["mechanical_pipeline"] == MECHANICAL_PIPELINE_VERSION
    matrix = (ROOT / "docs" / "ACTIVE_VERSION_MATRIX.md").read_text()
    standard = (ROOT / "docs" / "MECHANICAL_DRAWING_SET_STANDARD.md").read_text()
    fixture = (ROOT / "docs" / "FIXTURE_EQUIPMENT_DETECTION_STANDARD.md").read_text()
    assert "18.3.0" in matrix and PRODUCTION_CAD_ENTRYPOINT in matrix
    assert "Rule Book version: 4.2" in standard
    assert "Rule Book version: 2.4" in fixture


def test_historical_snapshot_stays_explicitly_historical():
    matrix = (ROOT / "docs" / "ACTIVE_VERSION_MATRIX.md").read_text().lower()
    assert "historical snapshots are immutable" in matrix
    assert (ROOT / "standards" / "releases" / "project-1" / "v18.1.snapshot.json").exists()
