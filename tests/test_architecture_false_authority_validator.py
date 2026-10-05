"""Independent destructive checks against promoted canonical authority."""
from copy import deepcopy

import pytest

from cad_engine.architecture_contract import assign_canonical_model_hash
from cad_engine.architecture_validator import validate_architecture
from test_architecture_input_foundation_v2 import contract


def report(model):
    assign_canonical_model_hash(model)
    before = deepcopy(model)
    result = validate_architecture(model)
    assert model == before
    return {row['code'] for row in result['hard_errors']}


def supported_space(model):
    space = model['physical_spaces'][0]
    points = space['polygon']
    space['geometry_status'] = 'VERIFIED'
    space['geometry_evidence'].update({
        'status': 'VERIFIED', 'source_handles': list(space['source_handles']),
        'segments': [[a, b] for a, b in zip(points, points[1:] + points[:1])]})
    return space


def test_explicit_structured_separator_contract_is_preserved():
    assert report(contract()) == set()


def test_independently_supported_boundary_is_accepted():
    model = contract()
    supported_space(model)
    assert report(model) == set()


@pytest.mark.parametrize('field,value', [
    ('source_roles', ['COLUMN']),
    ('negative_evidence', [{'classification': 'COLUMN'}]),
])
def test_column_cannot_be_verified_void(field, value):
    model = contract()
    model['voids'][0][field] = value
    assert 'COLUMN_AS_VERIFIED_VOID_FORBIDDEN' in report(model)


@pytest.mark.parametrize('role', ['DETAIL', 'REFERENCE_ONLY'])
@pytest.mark.parametrize('target', ['wall', 'frame'])
def test_reference_detail_cannot_be_material_wall(role, target):
    model = contract()
    row = model['walls'][0] if target == 'wall' else model['frames'][0]
    row['source_roles'] = [role]
    assert 'REFERENCE_DETAIL_MATERIAL_WALL_FORBIDDEN' in report(model)


def test_semantic_only_cannot_verify_physical_geometry():
    model = contract()
    model['physical_spaces'][0]['authority']['origins'] = ['SOURCE_SEMANTIC', 'DERIVED_DETERMINISTIC']
    assert 'SEMANTIC_ONLY_PHYSICAL_GEOMETRY_FORBIDDEN' in report(model)


@pytest.mark.parametrize('mutation', ['missing_side', 'unrelated', 'nan', 'empty', 'huge_claimed_tolerance'])
def test_claimed_verification_does_not_replace_boundary_geometry(mutation):
    model = contract()
    evidence = supported_space(model)['geometry_evidence']
    if mutation == 'missing_side':
        evidence['segments'].pop()
    elif mutation == 'unrelated':
        evidence['segments'] = [[[100, 100], [100, 110]]]
    elif mutation == 'nan':
        evidence['segments'] = [[['nan', 0], [5, 0]]]
    elif mutation == 'empty':
        evidence['segments'] = []
    else:
        evidence['segments'].pop()
        evidence['tolerance'] = 1e10
    assert 'PHYSICAL_BOUNDARY_GEOMETRY_UNSUPPORTED' in report(model)


def test_geometry_proof_cannot_be_replaced_by_semantic_status():
    model = contract()
    space = supported_space(model)
    space['semantic_status'] = 'VERIFIED'
    space['geometry_evidence']['status'] = 'INPUT_REQUIRED'
    assert 'PHYSICAL_BOUNDARY_EVIDENCE_UNSUPPORTED' in report(model)


def test_holes_also_need_boundary_support():
    model = contract()
    space = supported_space(model)
    space['interior_rings'] = [[[1, 1], [2, 1], [2, 2], [1, 2]]]
    assert 'PHYSICAL_BOUNDARY_GEOMETRY_UNSUPPORTED' in report(model)


def test_explicit_proof_cannot_omit_recomputable_segments():
    model = contract()
    space = supported_space(model)
    del space['geometry_evidence']['segments']
    assert 'PHYSICAL_BOUNDARY_EVIDENCE_UNSUPPORTED' in report(model)


def test_existing_bounded_reconstruction_uncertainty_is_supported():
    model = contract()
    proof = supported_space(model)['geometry_evidence']
    proof['segments'] = [[[x + 0.000001, y] for x, y in line] for line in proof['segments']]
    proof['tolerance'] = 0.002
    assert 'PHYSICAL_BOUNDARY_GEOMETRY_UNSUPPORTED' not in report(model)


def test_material_space_requires_source_provenance():
    model = contract()
    model['physical_spaces'][0]['source_handles'] = []
    assert 'PHYSICAL_BOUNDARY_SOURCE_REQUIRED' in report(model)


@pytest.mark.parametrize('contradiction', [
    {'negative_evidence': ['PHYSICAL_BOUNDARY_UNSUPPORTED']},
    {'unresolved_internal_segment_ids': ['INTERIOR-WALL-1']},
])
def test_positive_status_cannot_erase_boundary_contradiction(contradiction):
    model = contract()
    supported_space(model)['geometry_evidence'].update(contradiction)
    assert 'PHYSICAL_BOUNDARY_EVIDENCE_CONTRADICTORY' in report(model)


def test_adapter_cannot_promote_explicit_semantic_only_legacy_space():
    from cad_engine.architecture_contract import adapt_current_architecture
    from test_architecture_input_foundation_v2 import legacy_model
    legacy = legacy_model()
    legacy['physical_spaces'][0].update(
        semantic_status='VERIFIED', source_handles=['TEXT-1'],
        evidence=[{'class': 'TEXT', 'source_handles': ['TEXT-1']}],
        authority={'status': 'VERIFIED', 'origins': ['SOURCE_SEMANTIC']})
    model = adapt_current_architecture(legacy)
    space = model['physical_spaces'][0]
    assert space['geometry_status'] != 'VERIFIED'
    assert space['authority']['material_geometry'] is False


def test_reconstructed_reference_geometry_cannot_release_mechanical(tmp_path):
    import ezdxf
    from cad_engine.architectural_space_engine import reconstruct_architecture, require_complete_architecture
    doc = ezdxf.new('R2013')
    doc.header['$INSUNITS'] = 6
    doc.layers.add('FURNITURE')
    doc.modelspace().add_lwpolyline([(0, 0), (8, 0), (8, 6), (0, 6)], close=True,
                                  dxfattribs={'layer': 'FURNITURE'})
    doc.modelspace().add_text('BEDROOM', dxfattribs={'insert': (3, 3), 'height': .2})
    source = tmp_path / 'furniture_label.dxf'
    doc.saveas(source)
    model = reconstruct_architecture(source)
    assert require_complete_architecture(model)['allowed'] is False
    assert model['completeness']['downstream_engineering_allowed'] is False
    assert not any(room.get('status') == 'VERIFIED' for room in model.get('rooms') or [])
