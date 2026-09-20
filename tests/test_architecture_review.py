import unittest

from fastapi import HTTPException

from app.architecture_review import _require_revision, _resolve_boundary, _validate_space


def square_state():
    nodes = [
        {"id": "A", "x": 0, "y": 0}, {"id": "B", "x": 10, "y": 0},
        {"id": "C", "x": 10, "y": 10}, {"id": "D", "x": 0, "y": 10},
    ]
    segments = [
        {"a_id": "A", "b_id": "B"}, {"a_id": "B", "b_id": "C"},
        {"a_id": "C", "b_id": "D"}, {"a_id": "D", "b_id": "A"},
    ]
    return {"source_hash": "abc", "levels": [{"id": "L1", "frame": [-1, -1, 11, 11],
            "snap_points": nodes, "wall_segments": segments}], "spaces": []}


class ArchitectureReviewTests(unittest.TestCase):
    def test_stale_parallel_editor_is_rejected(self):
        with self.assertRaises(HTTPException) as error:
            _require_revision({"revision": 4}, {"review_revision": 3})
        self.assertEqual(error.exception.status_code, 409)

    def test_boundary_is_resolved_on_wall_graph_and_closed(self):
        state = square_state(); level = state["levels"][0]
        nodes = {row["id"]: (row["x"], row["y"]) for row in level["snap_points"]}
        self.assertEqual(_resolve_boundary(level, nodes, ["A", "B", "C", "D"], "INDEPENDENT"),
                         ["A", "B", "C", "D"])

    def test_rejects_free_or_unknown_coordinate_identifier(self):
        state = square_state()
        with self.assertRaises(HTTPException) as error:
            _validate_space(state, {"id": "S", "level_id": "L1", "label_point": [5, 5]},
                            {"space_type": "BEDROOM", "node_ids": ["A", "B", "5,10"],
                             "relationship": "INDEPENDENT"})
        self.assertEqual(error.exception.status_code, 422)

    def test_master_wet_room_must_be_separate(self):
        state = square_state()
        state["spaces"] = [{"id": "WET", "space_type": "BATHROOM", "display_name": "حمام مستر",
                            "label_point": [8, 8]}]
        with self.assertRaises(HTTPException) as error:
            _validate_space(state, {"id": "BED", "level_id": "L1", "label_point": [2, 2]},
                            {"space_type": "MASTER_BEDROOM", "node_ids": ["A", "B", "C", "D"],
                             "relationship": "MASTER_BEDROOM", "group_id": "MASTER-01"})
        self.assertIn("مرز مستقل", str(error.exception.detail))

    def test_source_artifact_is_required_for_confirmation(self):
        state = square_state(); state["source_hash"] = "SOURCE_NOT_LOCAL"
        with self.assertRaises(HTTPException) as error:
            _validate_space(state, {"id": "S", "level_id": "L1", "label_point": [5, 5]},
                            {"space_type": "BEDROOM", "node_ids": ["A", "B", "C", "D"]})
        self.assertEqual(error.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
