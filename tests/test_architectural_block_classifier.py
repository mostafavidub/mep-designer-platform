from collections import Counter

from shapely.geometry import LineString

from cad_engine.architectural_block_classifier_qa import classify_instance


FRAME = [0, 0, 20, 30]


def classify(**overrides):
    values = {
        "name": "anonymous",
        "layer": "0",
        "entity_counts": Counter(LINE=8),
        "bounds": [2, 2, 8, 8],
        "line_geometries": [LineString(((2, 2), (8, 2)))],
        "external_connections": 4,
        "parallel_face_pairs": 2,
        "frame_bounds": FRAME,
        "metres_per_unit": 1.0,
    }
    values.update(overrides)
    return classify_instance(**values)


def test_positive_multi_evidence_partition_is_selectively_admitted():
    result = classify()
    assert result["role"] == "ARCHITECTURAL_PARTITION_ASSEMBLY"
    assert result["action"] == "ADMIT_WALL_CHILDREN"
    assert result["status"] == "PROVEN"
    assert {"MULTIPLE_EXTERNAL_WALL_CONNECTIONS", "LOCAL_WALL_THICKNESS_PAIRS",
            "ROOM_SCALE_EXTENT", "PREDOMINANTLY_LINEAR_GEOMETRY"}.issubset(result["positive_evidence"])


def test_furniture_signature_is_never_promoted_despite_connectivity_and_pairs():
    result = classify(name="TBL6L table", entity_counts=Counter(LINE=20, ARC=8, CIRCLE=2))
    assert result["role"] == "FURNITURE"
    assert result["action"] == "EXCLUDE_FROM_WALL_PIPELINE"
    assert result["status"] == "SUPPORTED_NON_WALL"


def test_unknown_nested_geometry_stays_fail_closed():
    result = classify(external_connections=0, parallel_face_pairs=0,
                      bounds=[1, 1, 1.8, 2.2], entity_counts=Counter(LINE=3))
    assert result["role"] == "UNKNOWN"
    assert result["action"] == "KEEP_EXCLUDED_UNRESOLVED"
    assert result["status"] == "UNRESOLVED"


def test_door_and_window_context_remain_portal_roles_not_walls():
    for name, expected in (("anonymous door", "DOOR_ASSEMBLY"), ("window unit", "WINDOW_ASSEMBLY")):
        result = classify(name=name)
        assert result["role"] == expected
        assert result["action"] == "EXCLUDE_FROM_WALL_PIPELINE"


def test_detail_with_dimensions_and_hatch_is_not_wall_geometry():
    result = classify(entity_counts=Counter(LINE=60, ARC=10, DIMENSION=1, HATCH=2, MTEXT=2))
    assert result["role"] == "DETAIL_GRAPHIC"
    assert result["action"] == "EXCLUDE_FROM_WALL_PIPELINE"
