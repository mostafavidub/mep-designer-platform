from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_production_entrypoint_has_no_versioned_runtime_import_or_route():
    text = (ROOT / "cad_engine/main.py").read_text(encoding="utf-8")
    assert not re.search(r"from\s+\.[A-Za-z0-9_]*_v\d+|import\s+\.[A-Za-z0-9_]*_v\d+", text)
    assert not re.search(r"/mechanical[^\"']*v\d+", text, re.I)
    assert 'runtime_identity"] = "mechanical"' in text


def test_canonical_mechanical_surfaces_exist():
    for path in (
        "cad_engine/mechanical_authority.py",
        "cad_engine/mechanical_pipeline.py",
        "cad_engine/mechanical_release_contract.py",
        "cad_engine/mechanical_governance.py",
    ):
        assert (ROOT / path).is_file(), path


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
    forbidden = (
        "mechanical-authority-v15.yml",
        "mechanical-network-authority-v19.yml",
        "mechanical-governance-v1.yml",
        "mechanical-coordination-v19.yml",
    )
    for filename in forbidden:
        assert not (workflows / filename).exists(), filename


def test_deployment_launchers_reference_only_canonical_entrypoint():
    for rel in ("Dockerfile", "start_services.sh", "cad_engine/Dockerfile"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "cad_engine.main_v" not in text


def test_legacy_modules_are_not_parallel_deployment_entrypoints():
    text = (ROOT / "docs/SINGLE_LIVING_SYSTEM_STANDARD.md").read_text(encoding="utf-8")
    assert "compatibility debt" in text
    assert "must never be imported by production" in text or "must never be configured as deployment entrypoints" in text
