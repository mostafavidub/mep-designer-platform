import json
from pathlib import Path

from cad_engine.build_identity import build_identity
from cad_engine.runtime_contract import PMM_SCHEMA, PRODUCTION_CAD_ENTRYPOINT, RUNTIME_IDENTITY, runtime_contract
from cad_engine.runtime_contract_sync_gate import assert_runtime_contract_synchronized, contract_synchronization_errors

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_uses_automatic_git_build_identity():
    identity = build_identity()
    contract = runtime_contract()
    assert contract["runtime_identity"] == RUNTIME_IDENTITY == "mechanical"
    assert contract["production_cad_entrypoint"] == PRODUCTION_CAD_ENTRYPOINT == "cad_engine.main:app"
    assert contract["pmm_schema"] == PMM_SCHEMA == "project-mechanical-model/v3"
    assert contract["build_identity"] == identity


def test_every_production_launcher_uses_only_canonical_entrypoint_and_generator():
    text = (ROOT / "start_services.sh").read_text() + (ROOT / "cad_engine" / "Dockerfile").read_text()
    assert text.count("uvicorn cad_engine.main:app") == 2
    assert "uvicorn cad_engine.main_v" not in text
    assert "generate_rulebook_v" not in text


def test_release_record_contains_build_policy_and_semantic_revisions_only():
    release = json.loads((ROOT / "standards" / "active-release.json").read_text())
    assert release["identity_policy"] == "git-commit-and-content-hashes"
    assert release["production_cad_entrypoint"] == PRODUCTION_CAD_ENTRYPOINT
    assert release["pmm_schema_revision"] == PMM_SCHEMA
    assert release["rollback_source"] == "approved-git-commit-or-tag"
    assert release["build_identity_source"] == "cad_engine/build_identity.py"
    assert "version_source" not in release
    assert not any(key in release for key in ("platform_release", "cad_api", "mechanical_pipeline"))


def test_runtime_contract_is_fully_synchronized():
    assert contract_synchronization_errors() == []
    assert assert_runtime_contract_synchronized()["status"] == "PASS"


def test_contract_gate_detects_entrypoint_drift(monkeypatch, tmp_path):
    import cad_engine.runtime_contract_sync_gate as gate

    copied = tmp_path / "repo"
    for relative in (
        "standards/active-release.json",
        "docs/RUNTIME_CONTRACT_MATRIX.md",
        "README.md",
        "start_services.sh",
        "cad_engine/Dockerfile",
        "data/rulebook/generate_rulebook.py",
    ):
        target = copied / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / relative).read_text())
    release_path = copied / "standards/active-release.json"
    release = json.loads(release_path.read_text())
    release["production_cad_entrypoint"] = "cad_engine.main_v999:app"
    release_path.write_text(json.dumps(release))
    monkeypatch.setattr(gate, "ROOT", copied)
    monkeypatch.setattr(gate, "RULEBOOK_GENERATOR", copied / "data/rulebook/generate_rulebook.py")
    monkeypatch.setattr(gate, "RUNTIME_MATRIX", copied / "docs/RUNTIME_CONTRACT_MATRIX.md")
    assert "release-contract:production_cad_entrypoint" in gate.contract_synchronization_errors()
