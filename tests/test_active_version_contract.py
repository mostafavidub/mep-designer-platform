import json
from pathlib import Path

from cad_engine.version_manifest import (
    CAD_API_VERSION,
    MECHANICAL_PIPELINE_VERSION,
    PLATFORM_RELEASE,
    PRODUCTION_CAD_ENTRYPOINT,
    active_version_manifest,
)
from cad_engine.version_sync_gate import assert_versions_synchronized, synchronization_errors

ROOT = Path(__file__).resolve().parents[1]


def test_active_runtime_and_public_version_contract_are_identical():
    assert PLATFORM_RELEASE == CAD_API_VERSION == "18.5.8"
    assert MECHANICAL_PIPELINE_VERSION.endswith("v18.5.8")
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


def test_authority_ci_uses_central_version_instead_of_stale_literal():
    workflow = (ROOT / ".github" / "workflows" / "mechanical-authority-v15.yml").read_text()
    assert "from cad_engine.version_manifest import PLATFORM_RELEASE" in workflow
    assert "platform_release'] == '18." not in workflow


def test_release_record_and_current_docs_do_not_drift():
    release = json.loads((ROOT / "standards" / "active-release.json").read_text())
    assert release["platform_release"] == PLATFORM_RELEASE
    assert release["production_cad_entrypoint"] == PRODUCTION_CAD_ENTRYPOINT
    assert release["mechanical_pipeline"] == MECHANICAL_PIPELINE_VERSION
    assert release == {
        **active_version_manifest(),
        "version_source": "cad_engine/version_manifest.py",
        "historical_snapshots_are_immutable": True,
    }
    matrix = (ROOT / "docs" / "ACTIVE_VERSION_MATRIX.md").read_text()
    standard = (ROOT / "docs" / "MECHANICAL_DRAWING_SET_STANDARD.md").read_text()
    fixture = (ROOT / "docs" / "FIXTURE_EQUIPMENT_DETECTION_STANDARD.md").read_text()
    assert "18.5.8" in matrix and PRODUCTION_CAD_ENTRYPOINT in matrix
    assert "Rule Book version: 4.3" in standard
    assert "Rule Book version: 2.4" in fixture


def test_historical_snapshot_stays_explicitly_historical():
    matrix = (ROOT / "docs" / "ACTIVE_VERSION_MATRIX.md").read_text().lower()
    assert "historical snapshots are immutable" in matrix
    assert (ROOT / "standards" / "releases" / "project-1" / "v18.1.snapshot.json").exists()


def test_all_active_site_engine_rulebook_and_release_versions_are_synchronized():
    assert synchronization_errors() == []
    assert assert_versions_synchronized()["status"] == "PASS"


def test_version_gate_is_destructive_and_detects_release_drift(monkeypatch, tmp_path):
    import cad_engine.version_sync_gate as gate

    copied_root = tmp_path / "repo"
    copied_root.mkdir()
    for relative in ("standards/active-release.json", "docs/ACTIVE_VERSION_MATRIX.md", "README.md", "start_services.sh", "cad_engine/Dockerfile"):
        source = ROOT / relative
        target = copied_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text())
    release_path = copied_root / "standards" / "active-release.json"
    release = json.loads(release_path.read_text())
    release["mechanical_rulebook"] = "stale-version"
    release_path.write_text(json.dumps(release))
    monkeypatch.setattr(gate, "ROOT", copied_root)
    assert any("mechanical_rulebook" in error for error in synchronization_errors())
