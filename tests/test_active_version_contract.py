import json
from pathlib import Path
from cad_engine.build_identity import build_identity
from cad_engine.version_manifest import CAD_API_VERSION, PLATFORM_RELEASE, PRODUCTION_CAD_ENTRYPOINT, active_version_manifest
from cad_engine.version_sync_gate import assert_versions_synchronized, synchronization_errors

ROOT = Path(__file__).resolve().parents[1]

def test_active_runtime_uses_automatic_git_identity():
    identity = build_identity()
    assert PLATFORM_RELEASE == CAD_API_VERSION == identity["commit_sha"]
    assert PRODUCTION_CAD_ENTRYPOINT == "cad_engine.main:app"
    assert active_version_manifest()["build_identity"] == identity

def test_every_production_launcher_uses_the_canonical_entrypoint():
    text = (ROOT / "start_services.sh").read_text() + (ROOT / "cad_engine" / "Dockerfile").read_text()
    assert text.count("uvicorn cad_engine.main:app") == 2
    assert "uvicorn cad_engine.main_v" not in text

def test_release_record_contains_only_policy_and_semantic_revisions():
    release = json.loads((ROOT / "standards" / "active-release.json").read_text())
    assert release["identity_policy"] == "git-commit-and-content-hashes"
    assert release["production_cad_entrypoint"] == PRODUCTION_CAD_ENTRYPOINT
    assert release["rollback_source"] == "approved-git-commit-or-tag"
    assert not any(key in release for key in ("platform_release", "cad_api", "mechanical_pipeline"))

def test_all_identity_consumers_are_synchronized():
    assert synchronization_errors() == []
    assert assert_versions_synchronized()["status"] == "PASS"

def test_identity_gate_detects_entrypoint_drift(monkeypatch, tmp_path):
    import cad_engine.version_sync_gate as gate
    copied = tmp_path / "repo"
    for relative in ("standards/active-release.json","docs/ACTIVE_VERSION_MATRIX.md","README.md","start_services.sh","cad_engine/Dockerfile"):
        target = copied / relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_text((ROOT / relative).read_text())
    release_path = copied / "standards/active-release.json"; release = json.loads(release_path.read_text()); release["production_cad_entrypoint"] = "cad_engine.main_v999:app"; release_path.write_text(json.dumps(release))
    monkeypatch.setattr(gate, "ROOT", copied)
    assert "active-release:production_cad_entrypoint" in synchronization_errors()
