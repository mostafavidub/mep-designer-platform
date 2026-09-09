from pathlib import Path

from cad_engine.runtime_contract import runtime_contract


ROOT = Path(__file__).resolve().parents[1]


def test_panel_transports_only_the_canonical_runtime_contract_and_entrypoint():
    source = (ROOT / "app/dxf_output.py").read_text(encoding="utf-8")
    assert "design_answers['_runtime_contract'] = runtime_contract()" in source
    assert "from cad_engine.main_transport import design" in source
    assert "design_answers['_canonical_input_contract']" in source
    assert "from cad_engine.main_v15 import design" not in source
    assert "design_answers['_v19_input_contract']" not in source
    assert "active_version_manifest" not in source


def test_exact_contract_passes_and_one_stale_field_fails_closed():
    from cad_engine.mechanical_authority import _runtime_contract_errors

    current = runtime_contract()
    assert _runtime_contract_errors({"_runtime_contract": current}) == []

    stale = dict(current)
    stale["site_manifest_revision"] = "stale"
    assert _runtime_contract_errors({"_runtime_contract": stale}) == [
        "runtime_contract_mismatch:site_manifest_revision"
    ]


def test_panel_verifies_response_build_contract_and_unversioned_authority():
    source = (ROOT / "app/dxf_output.py").read_text(encoding="utf-8")
    assert "data.get('build') != expected_contract['build_identity']" in source
    assert "report.get('pipeline_authority') != 'mechanical'" in source
    assert "report.get('runtime_contract') != expected_contract" in source
