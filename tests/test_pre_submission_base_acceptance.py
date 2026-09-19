from pathlib import Path


def test_base_release_uses_bounded_disclosed_acceptance_view_without_mutating_original_result():
    source = Path('cad_engine/mechanical_cad_base.py').read_text(encoding='utf-8')
    assert '_DISCLOSABLE_ARCHITECTURE_CONSTRAINTS' in source
    assert 'acceptance_errors <= ({"TARGET_DESIGN_PACKAGES_MISSING"}|_DISCLOSABLE_EVIDENCE_CONSTRAINTS)' in source
    assert 'pipeline_release_qa, acceptance_release_qa, dxf_qa, semantic_qa' in source
    assert '("engineering_acceptance_gate",acceptance_release_qa)' in source
    assert '"engineering_acceptance":acceptance' in source
    assert '"engineering_acceptance_release_qa":acceptance_release_qa' in source


def test_base_acceptance_disclosure_requires_exact_bounded_reason_set():
    source = Path('cad_engine/mechanical_cad_base.py').read_text(encoding='utf-8')
    release=source[source.index('acceptance_release_qa = acceptance'):source.index('status="PASS"')]
    assert 'acceptance_errors <=' in release
    assert 'architecture:insufficient_room_geometry' in source
    assert 'architecture:no_real_shaft_evidence' in source
    assert 'route_crosses_architectural_wall' not in source[source.index('_DISCLOSABLE_ARCHITECTURE_CONSTRAINTS'):source.index('def _target_package_pre_submission')]
