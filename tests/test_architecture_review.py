import unittest
from pathlib import Path

from fastapi import HTTPException

from app.architecture_review import (_augment_review_geometry, _require_admin, _require_mutable,
                                     _require_revision, _resolve_boundary, _validate_space)


def square_state():
    nodes = [
        {"id": "A", "x": 0, "y": 0}, {"id": "B", "x": 10, "y": 0},
        {"id": "C", "x": 10, "y": 10}, {"id": "D", "x": 0, "y": 10},
    ]
    segments = [
        {"a_id": "A", "b_id": "B", "a": [0, 0], "b": [10, 0]},
        {"a_id": "B", "b_id": "C", "a": [10, 0], "b": [10, 10]},
        {"a_id": "C", "b_id": "D", "a": [10, 10], "b": [0, 10]},
        {"a_id": "D", "b_id": "A", "a": [0, 10], "b": [0, 0]},
    ]
    return {"source_hash": "abc", "levels": [{"id": "L1", "frame": [-1, -1, 11, 11],
            "snap_points": nodes, "wall_segments": segments}], "spaces": []}


class ArchitectureReviewTests(unittest.TestCase):
    def test_review_ui_keeps_labels_screen_scaled_and_hides_nodes_until_selection(self):
        template = Path("app/templates/architecture_review.html").read_text(encoding="utf-8")
        self.assertIn("'font-size':Math.max(m.size*.012,m.w*.009)", template)
        self.assertIn("if(!admin&&spaceId)", template)
        self.assertIn("نمایش کامل پلان", template)
        self.assertIn("spaceTitle(s,index)", template)
        self.assertIn("نقاط آبی فقط بعد از انتخاب فضا نمایش داده می‌شوند", template)
        css = Path("app/static/architecture-review-v2.css").read_text(encoding="utf-8")
        self.assertIn(".architecture-label { display: none; }", css)
        self.assertIn("svg.addEventListener('pointermove'", template)
        self.assertIn("panY+=dy*", template)
        self.assertIn("touch-action: none", css)
        self.assertIn("function renderVisualUnderlay", template)
        self.assertIn("level.visual_entities||[]", template)
        self.assertIn("architecture-source-text", template)
        review_source = Path("app/architecture_review.py").read_text(encoding="utf-8")
        self.assertIn('"schema": "architecture-review/2"', review_source)
        self.assertIn('existing.get("visual_underlay_contract") == "source-faithful/2"', review_source)

    def test_selection_mode_and_automatic_relationship_ui(self):
        template = Path("app/templates/architecture_review.html").read_text(encoding="utf-8")
        css = Path("app/static/architecture-review-v2.css").read_text(encoding="utf-8")
        self.assertIn("mode!=='pan'", template)
        self.assertIn("applyRelationshipAutomation", template)
        self.assertIn("candidateSnapPoints(level)", template)
        self.assertIn("تنظیمات تخصصی (اختیاری)", template)
        self.assertIn(".architecture-canvas.is-selecting { cursor: crosshair; }", css)
        self.assertIn(".architecture-space-list-heading > b", css)

    def test_source_backed_jamb_adds_real_graph_endpoints(self):
        level = square_state()["levels"][0]
        level["visual_entities"] = [{"kind": "polyline", "entity_type": "LINE",
                                      "source_layer": "0", "points": [[0, 2], [10, 2]]}]
        augmented = _augment_review_geometry(level)
        coords = {(row["x"], row["y"]) for row in augmented["snap_points"]}
        self.assertIn((0.0, 2.0), coords)
        self.assertIn((10.0, 2.0), coords)
        self.assertEqual(augmented["review_bridge_count"], 1)

    def test_standalone_layer_zero_furniture_is_not_promoted(self):
        level = square_state()["levels"][0]
        level["visual_entities"] = [{"kind": "polyline", "entity_type": "LINE",
                                      "source_layer": "0", "points": [[2, 2], [3, 2]]}]
        self.assertNotIn("review_bridge_count", _augment_review_geometry(level))

    def test_confirmed_model_cannot_be_silently_edited(self):
        with self.assertRaises(HTTPException) as error:
            _require_mutable({"status": "CONFIRMED"})
        self.assertEqual(error.exception.status_code, 409)

    def test_admin_audit_rejects_untrusted_public_host(self):
        class Headers(dict):
            get = dict.get
        request = type("Request", (), {"headers": Headers({"host": "web-app.railway.app"})})()
        with self.assertRaises(HTTPException) as error:
            _require_admin(request)
        self.assertEqual(error.exception.status_code, 403)

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
