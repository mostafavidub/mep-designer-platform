from pathlib import Path
import re

from tools.runtime_version_guard import active_runtime_closure

ROOT = Path(__file__).resolve().parents[1]


def test_production_entrypoint_has_no_versioned_runtime_import_or_route():
    text = (ROOT / "cad_engine/main.py").read_text(encoding="utf-8")
    assert not re.search(r"from\s+\.[A-Za-z0-9_]*_v\d+|import\s+\.[A-Za-z0-9_]*_v\d+", text)
    assert not re.search(r"/mechanical[^\"']*v\d+", text, re.I)
    assert 'runtime_identity"] = "mechanical"' in text
    assert "from .main_transport import app" in text


def test_canonical_mechanical_surfaces_exist():
    for path in (
        "cad_engine/main_transport.py",
        "cad_engine/mechanical_authority.py",
        "cad_engine/mechanical_pipeline.py",
        "cad_engine/mechanical_release_contract.py",
        "cad_engine/mechanical_governance.py",
        "cad_engine/runtime_contract.py",
    ):
        assert (ROOT / path).is_file(), path


def test_active_runtime_import_closure_is_fully_unversioned():
    closure = active_runtime_closure()
    assert closure["versioned_modules"] == [], closure
    assert closure["missing_modules"] == [], closure
    assert closure["import_errors"] == [], closure
    assert closure["literal_errors"] == [], closure
    assert "mechanical_authority" in closure["modules"]
    assert "mechanical_pipeline" in closure["modules"]
    assert "mechanical_cad_shell" in closure["modules"]


def test_visible_mechanical_workflow_names_are_unversioned():
    expected = {
        "mechanical-authority.yml": "Mechanical Authority",
        "mechanical-network-authority.yml": "Mechanical Network Authority",
        "mechanical-governance.yml": "Mechanical Governance",
        "mechanical-coordination.yml": "Mechanical Coordination",
    }
    workflows = ROOT / ".github/workflows"
    for filename, display in expected.items():
        text = (workflows / filename).read_text(encoding="utf-8")
        assert text.splitlines()[0].strip() == f"name: {display}"
        assert not re.search(rf"name:\s*{re.escape(display)}\s+v\d+", text, re.I)
    for filename in (
        "mechanical-authority-v15.yml",
        "mechanical-network-authority-v19.yml",
        "mechanical-governance-v1.yml",
        "mechanical-coordination-v19.yml",
    ):
        assert not (workflows / filename).exists(), filename


def test_deployment_launchers_reference_only_canonical_entrypoint():
    for rel in ("Dockerfile", "start_services.sh", "cad_engine/Dockerfile"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "cad_engine.main_v" not in text
        assert "version-locked v" not in text.lower()


def test_canonical_materializer_stamps_no_release_number():
    text = (ROOT / "cad_engine/mechanical_network_materializer.py").read_text(encoding="utf-8")
    assert 'APPID = "ENGITOOLS_MECHANICAL"' in text
    assert "ENGITOOLS_V19" not in text
    assert "V19_NETWORK_EDGE_ID" not in text


def test_runtime_contract_is_build_and_schema_metadata_not_engine_version_manifest():
    text = (ROOT / "cad_engine/runtime_contract.py").read_text(encoding="utf-8")
    assert 'RUNTIME_IDENTITY = "mechanical"' in text
    assert 'PMM_SCHEMA = "project-mechanical-model/v3"' in text
    assert "MECHANICAL_PIPELINE_VERSION" not in text
    assert "active_version_manifest" not in text
    assert "engine_version" not in text


def test_single_living_system_documents_git_only_engine_history():
    text = (ROOT / "docs/SINGLE_LIVING_SYSTEM_STANDARD.md").read_text(encoding="utf-8")
    assert "compatibility debt" in text
    assert "must never be imported by production" in text or "must never be configured as deployment entrypoints" in text
