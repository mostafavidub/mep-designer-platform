from pathlib import Path


def test_base_release_uses_disclosed_acceptance_view_without_mutating_original_result():
    source = Path('cad_engine/mechanical_cad_base.py').read_text(encoding='utf-8')
    assert 'acceptance_errors == {"TARGET_DESIGN_PACKAGES_MISSING"}' in source
    assert 'pipeline_release_qa, acceptance_release_qa, dxf_qa, semantic_qa' in source
    assert '("engineering_acceptance_gate",acceptance_release_qa)' in source
    assert '"engineering_acceptance":acceptance' in source
    assert '"engineering_acceptance_release_qa":acceptance_release_qa' in source


def test_base_acceptance_disclosure_requires_exact_single_reason():
    source = Path('cad_engine/mechanical_cad_base.py').read_text(encoding='utf-8')
    assert 'acceptance_errors == {"TARGET_DESIGN_PACKAGES_MISSING"}' in source
    assert 'acceptance_errors <=' not in source[source.index('acceptance_release_qa = acceptance'):source.index('status="PASS"')]
