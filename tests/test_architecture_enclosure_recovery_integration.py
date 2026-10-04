"""Synthetic DXF recall controls across extraction, topology and authority.

Task-B source-role/false-authority suites retain the exhaustive hard-exclusion
matrix and symbolic-chord controls; these fixtures exercise new recall paths.
"""
import ezdxf
import pytest
from shapely.geometry import Polygon, box

from cad_engine.architectural_space_engine import reconstruct_architecture
from cad_engine.architecture_contract import adapt_current_architecture
from cad_engine.architecture_enclosure_candidates import reconcile_enclosure_candidates
from cad_engine.architecture_validator import validate_architecture


def _drawing(tmp_path, monkeypatch, edges, labels=(), nested=False):
    monkeypatch.setenv('ARCH_VISION_PROVIDER', 'disabled')
    doc = ezdxf.new(); doc.header['$INSUNITS'] = 6
    doc.layers.new('WALL')
    target = doc.blocks.new('INNER') if nested else doc.modelspace()
    for a, b in edges:
        target.add_line(a, b, dxfattribs={'layer': 'WALL'})
    for text, point in labels:
        target.add_text(text, dxfattribs={'insert': point, 'height': .1})
    if nested:
        outer = doc.blocks.new('OUTER')
        outer.add_blockref('INNER', (3, 4), dxfattribs={'rotation': 90})
        doc.modelspace().add_blockref('OUTER', (40, 70), dxfattribs={'rotation': 30})
    path = tmp_path / 'source.dxf'; doc.saveas(path)
    return reconstruct_architecture(path)


def _edges(width, height):
    pts = [(0, 0), (width, 0), (width, height), (0, height), (0, 0)]
    return list(zip(pts, pts[1:]))


@pytest.mark.parametrize('size', [(2, 1), (8, 6), (40, 30)])
def test_supported_room_scale_does_not_drive_candidate_rejection(tmp_path, monkeypatch, size):
    width, height = size
    model = _drawing(tmp_path, monkeypatch, _edges(width, height), [('LIVING', (.5, .5))])
    canonical = adapt_current_architecture(model)
    assert len(canonical['physical_spaces']) == 1
    space = canonical['physical_spaces'][0]
    assert space['area_m2'] == pytest.approx(width * height)
    assert space['geometry_status'] == 'VERIFIED'
    # RAW WALL context proves geometry, not separator role (canonical 3.0).
    assert not space['authority']['material_geometry']
    assert space['geometry_evidence']['separator_status'] == 'AMBIGUOUS'
    from cad_engine.architecture_review_engine import plan_preflight, replay_review_decisions
    from tests.test_architecture_separator_evidence import payload
    plan = plan_preflight(canonical)
    answers = [payload(i, 'PHYSICAL_SEPARATOR') for i in plan['review_items'] if i['question_type'] == 'SOURCE_ROLE_CLASSIFICATION']
    result = replay_review_decisions(canonical, answers, plan)
    assert result['reviewed_canonical_model']['physical_spaces'][0]['authority']['material_geometry']
    assert not validate_architecture(canonical)['hard_errors']


def test_nested_rotated_source_occurrence_keeps_closed_room(tmp_path, monkeypatch):
    model = _drawing(tmp_path, monkeypatch, _edges(3, 2), [('LIVING', (1, 1))], nested=True)
    assert len(model['physical_spaces']) == 1
    space = model['physical_spaces'][0]
    assert space['area_m2'] == pytest.approx(6)
    assert space['geometry_status'] == 'VERIFIED'
    assert Polygon(space['polygon']).centroid.x > 30
    assert Polygon(space['polygon']).centroid.y > 60


@pytest.mark.parametrize('gap,expected_count', [(.001, 2), (.08, 1)])
def test_fragmented_partition_precision_is_locally_bounded(tmp_path, monkeypatch, gap, expected_count):
    edges = _edges(4, 2) + [((2, gap), (2, 1)), ((2, 1), (2, 2))]
    model = _drawing(tmp_path, monkeypatch, edges)
    assert len(model['physical_spaces']) == expected_count
    if gap < .002:
        assert sorted(s['area_m2'] for s in model['physical_spaces']) == pytest.approx([4, 4], abs=.01)
    else:
        assert model['physical_spaces'][0]['geometry_status'] == 'INPUT_REQUIRED'


def _records(edges):
    return [{'segment_id': 'S'+str(i), 'source_handle': str(i), 'status': 'ACCEPTED',
             'geometry': [a, b], 'evidence': [{'class': 'SOURCE_CONTEXT'}]}
            for i, (a, b) in enumerate(edges)]


def test_parent_with_two_proven_children_retains_both_children():
    edges = _edges(4, 2) + [((2, 0), (2, 2))]
    selected, diagnostics = reconcile_enclosure_candidates(
        [box(-1, -1, 5, 3)], _records(edges), [], [], .002, 'F')
    assert sorted(p.area for p in selected) == [4, 4]
    parent = next(r for r in diagnostics['candidates'] if r['area'] == 24)
    assert parent['candidate_role'] == 'PARENT_CONTAINER'


def test_missing_partition_remains_unresolved_without_invented_child():
    edges = _edges(4, 2) + [((2, .5), (2, 1.5))]
    selected, diagnostics = reconcile_enclosure_candidates(
        [box(0, 0, 4, 2)], _records(edges), [], [], .002, 'F')
    assert len(selected) == 1 and selected[0].area == 8
    row = next(r for r in diagnostics['candidates'] if r['area'] == 8)
    assert row['boundary_evidence']['status'] == 'INPUT_REQUIRED'
    assert row['boundary_evidence']['unresolved_internal_segment_ids']


def test_short_source_partition_at_t_junction_preserves_two_small_rooms(tmp_path, monkeypatch):
    model = _drawing(tmp_path, monkeypatch, _edges(2, .4) + [((1, 0), (1, .4))])
    assert sorted(s['area_m2'] for s in model['physical_spaces']) == pytest.approx([.4, .4])
    assert all(s['geometry_status'] == 'VERIFIED' for s in model['physical_spaces'])


def test_disconnected_unclassified_line_does_not_close_missing_boundary():
    incomplete = _records([((0, 0), (2, 0)), ((2, 0), (2, 1)), ((2, 1), (0, 1))])
    incomplete.append({'segment_id': 'UNSUPPORTED', 'source_handle': 'U', 'status': 'REJECTED',
                       'geometry': [(0, 1), (0, 0)], 'evidence': []})
    selected, diagnostics = reconcile_enclosure_candidates([], incomplete, [], [], .002, 'F')
    assert selected == []
    assert diagnostics['synthetic_wall_count'] == 0


def test_residual_uncovered_boundary_cannot_be_verified_by_aggregate_tolerance():
    from cad_engine.architecture_boundary_evidence import physical_boundary_evidence
    edges = [((0, 0), (.99, 0)), ((1.01, 0), (2, 0)),
             ((2, 0), (2, 1)), ((2, 1), (0, 1)), ((0, 1), (0, 0))]
    proof = physical_boundary_evidence(box(0, 0, 2, 1), _records(edges), [], [], .002)
    assert 0 < proof['uncovered_length'] < proof['tolerance']
    assert proof['status'] == 'INPUT_REQUIRED'
    assert proof['uncovered_boundary_segments']


def test_local_face_thickness_identifies_material_strip_without_global_family():
    from cad_engine.architectural_space_engine import _filter_wall_solid_cells
    source = [{'evidence': [{'class': 'LOCAL_PARALLEL_FACE_PAIR', 'thicknesses': [.05]}]}]
    selected, rejected = _filter_wall_solid_cells([box(0, 0, 8, .05)], source,
                                                 {'texts': [], 'objects': []}, 1.0)
    assert not selected
    assert rejected[0]['reason'] == 'WALL_SOLID_STRIP'


def test_tolerance_bands_cannot_manufacture_resolvable_sliver_interior():
    from cad_engine.architecture_boundary_evidence import physical_boundary_evidence
    thin = box(0, 0, .01, 2)
    proof = physical_boundary_evidence(thin, _records(_edges(.01, 2)), [], [], .002)
    assert proof['coverage_ratio'] == 1
    assert proof['status'] == 'INPUT_REQUIRED'
    assert 'NO_RESOLVABLE_INTERIOR_AT_EVIDENCE_TOLERANCE' in proof['negative_evidence']


def test_serialization_invalidity_is_retained_only_as_candidate_diagnostic(tmp_path, monkeypatch):
    import cad_engine.architectural_space_engine as engine
    original = engine.reconcile_enclosure_candidates
    def with_subprecision_hole(*args, **kwargs):
        selected, diagnostic = original(*args, **kwargs)
        if selected:
            raw = Polygon(selected[0].exterior.coords,
                          [[(1, 1), (2, 1), (2, 1 + 1e-10), (1, 1 + 1e-10)]])
            assert raw.is_valid
            row = next(r for r in diagnostic['candidates'] if r['selected'])
            row['polygon'] = [list(p) for p in raw.exterior.coords]
            row['interior_rings'] = [[list(p) for p in h.coords] for h in raw.interiors]
            selected[0] = raw
        return selected, diagnostic
    monkeypatch.setattr(engine, 'reconcile_enclosure_candidates', with_subprecision_hole)
    model = _drawing(tmp_path, monkeypatch, _edges(4, 3))
    assert not model['physical_spaces']
    invalid = [r for f in model['enclosure_candidates'] for r in f['candidates']
               if r['candidate_role'] == 'INVALID_DIAGNOSTIC']
    assert invalid and all(not r['selected'] for r in invalid)
    assert invalid[0]['serialized_interior_rings']
