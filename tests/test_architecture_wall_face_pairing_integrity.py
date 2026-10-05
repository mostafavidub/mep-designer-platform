"""Face-derived axes stay between source faces regardless of the base face."""
import math

import pytest
from shapely.geometry import LineString

from cad_engine.architectural_topology_quality import _pair_wall_faces


def _wall(name, points):
    line = LineString(points)
    a, b = points
    direction = [(b[i] - a[i]) / line.length for i in range(2)]
    return {"wall_id": name, "frame_id": "F", "centerline": points,
            "wall_solid": {"axis_origin": a, "axis_direction": direction,
                           "occupied_intervals": [[0, line.length]]},
            "source_fragments": ["SEG-" + name], "source_handles": [name],
            "interruptions": []}


@pytest.mark.parametrize("angle", [0, 37, 90, 143])
@pytest.mark.parametrize("longer_first", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_unequal_faces_center_axis_between_sources(angle, longer_first, reverse):
    theta = math.radians(angle)
    u = (math.cos(theta), math.sin(theta))
    n = (-u[1], u[0])

    def point(x, y):
        return [73 + x * u[0] + y * n[0], -41 + x * u[1] + y * n[1]]

    face_a = [point(1, 0), point(3, 0)]
    face_b = [point(0, .2), point(5, .2)]
    if reverse:
        face_a.reverse()
        face_b.reverse()
    walls = [_wall("A", face_a), _wall("B", face_b)]
    if longer_first:
        walls.reverse()
    result = _pair_wall_faces(walls, [{"median_thickness": .2}], .001)
    assert len(result) == 1
    paired = result[0]
    expected = LineString([point(0, .1), point(5, .1)])
    assert LineString(paired["centerline"]).hausdorff_distance(expected) < 1e-10
    assert paired["thickness"] == pytest.approx(.2)
    assert paired["source_handles"] == ["A", "B"]
    assert paired["source_fragments"] == ["SEG-A", "SEG-B"]


@pytest.mark.parametrize("other", [([[0, 2], [5, 2]]), ([[6, .2], [9, .2]]),
                                     ([[2, -1], [2, 1]])])
def test_pair_axis_correction_does_not_admit_unrelated_faces(other):
    result = _pair_wall_faces([_wall("A", [[0, 0], [5, 0]]), _wall("B", other)],
                              [{"median_thickness": .2}], .001)
    assert len(result) == 2
    assert all(row.get("representation") != "DOUBLE_FACE" for row in result)


def _material_world_intervals(wall):
    solid = wall['wall_solid']
    return sorted(sorted(solid['axis_origin'][0] + value * solid['axis_direction'][0]
                         for value in interval) for interval in solid['occupied_intervals'])


@pytest.mark.parametrize('reverse_order', [False, True])
def test_partial_face_does_not_fill_union_span_with_material(reverse_order):
    walls = [_wall('A', [[2, 0], [2.1, 0]]), _wall('B', [[0, .2], [7, .2]])]
    if reverse_order:
        walls.reverse()
    result = _pair_wall_faces(walls, [{'median_thickness': .2}], .001)[0]
    assert LineString(result['centerline']).length == pytest.approx(7)
    material = _material_world_intervals(result)
    assert len(material) == 1
    assert material[0] == pytest.approx([2, 2.1])
    assert result['face_a'] and result['face_b']


def test_interrupted_faces_only_share_intersected_material():
    first = _wall('A', [[0, 0], [10, 0]])
    second = _wall('B', [[0, .2], [10, .2]])
    first['wall_solid']['occupied_intervals'] = [[0, 3], [5, 10]]
    second['wall_solid']['occupied_intervals'] = [[0, 4], [6, 10]]
    first['interruptions'] = [{'interval': [3, 5]}]
    second['interruptions'] = [{'interval': [4, 6]}]
    result = _pair_wall_faces([first, second], [{'median_thickness': .2}], .001)[0]
    assert _material_world_intervals(result) == [[0, 3], [6, 10]]
    assert any(row['kind'] == 'SUPPORTED_OPENING' for row in result['interruptions'])


def test_subprecision_face_overlap_creates_no_long_material_strip():
    walls = [_wall('A', [[2, 0], [2.00001, 0]]), _wall('B', [[0, .2], [7, .2]])]
    result = _pair_wall_faces(walls, [{'median_thickness': .2}], .001)
    assert len(result) == 2
    assert {row['wall_id'] for row in result} == {'A', 'B'}
    assert all(row.get('representation') != 'DOUBLE_FACE' for row in result)
    assert sorted(handle for row in result for handle in row['source_handles']) == ['A', 'B']


def test_equal_uninterrupted_faces_preserve_full_material():
    walls = [_wall('A', [[0, 0], [7, 0]]), _wall('B', [[0, .2], [7, .2]])]
    result = _pair_wall_faces(walls, [{'median_thickness': .2}], .001)[0]
    assert _material_world_intervals(result) == [[0, 7]]
