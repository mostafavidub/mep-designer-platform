import unittest

import ezdxf

from app.architecture_geometry_reconstruction import build_visual_underlay, reconstruct_boundaries


class ArchitectureGeometryReconstructionTests(unittest.TestCase):
    def _model(self):
        doc = ezdxf.new("R2013")
        for name in ("A-WALL", "door", "SHAFT", "Dime-Arch"):
            doc.layers.add(name)
        return doc, doc.modelspace()

    @staticmethod
    def _label(text, kind, point):
        return ({"text": text, "x": point[0], "y": point[1]}, kind, point)

    @staticmethod
    def _segments(msp, points, layer="A-WALL"):
        for start, end in zip(points, points[1:]):
            msp.add_line(start, end, dxfattribs={"layer": layer})

    def test_polygonizes_independent_rooms_from_open_line_entities(self):
        _doc, msp = self._model()
        self._segments(msp, [(0, 0), (5, 0), (5, 4), (0, 4), (0, 0)])
        self._segments(msp, [(5, 0), (10, 0), (10, 4), (5, 4)])
        labels = [self._label("اتاق خواب", "bedroom", (2, 2)),
                  self._label("حمام", "bath", (8, 2))]
        result = reconstruct_boundaries(msp, [0, 0, 10, 4], labels)
        self.assertEqual(set(result["accepted"]), {0, 1})
        self.assertEqual(result["quality"]["accepted_cell_count"], 2)
        for geometry in result["accepted"].values():
            self.assertEqual(geometry["provenance"], "INFERRED")
            self.assertGreaterEqual(geometry["geometry_evidence"]["source_entity_count"], 3)
            self.assertTrue(geometry["geometry_fingerprint"])

    def test_door_gap_can_segment_but_does_not_mutate_source_dxf(self):
        _doc, msp = self._model()
        self._segments(msp, [(0, 0), (10, 0), (10, 6), (0, 6), (0, 0)])
        msp.add_line((5, 0), (5, 2.5), dxfattribs={"layer": "A-WALL"})
        msp.add_line((5, 3.5), (5, 6), dxfattribs={"layer": "A-WALL"})
        # Door leaf closes the topological gap, but stays a door in the DXF.
        msp.add_line((5, 2.5), (5, 3.5), dxfattribs={"layer": "door"})
        before = len(msp)
        result = reconstruct_boundaries(
            msp, [0, 0, 10, 6],
            [self._label("خواب", "bedroom", (2, 3)), self._label("حمام", "bath", (8, 3))],
        )
        self.assertEqual(set(result["accepted"]), {0, 1})
        self.assertEqual(len(msp), before)
        self.assertTrue(any("door" in row["geometry_evidence"]["source_layers"]
                            for row in result["accepted"].values()))

    def test_reconstructs_shaft_from_actual_enclosure(self):
        _doc, msp = self._model()
        self._segments(msp, [(2, 2), (3, 2), (3, 3), (2, 3), (2, 2)], layer="SHAFT")
        result = reconstruct_boundaries(
            msp, [0, 0, 8, 8], [self._label("داکت", "shaft", (2.5, 2.5))]
        )
        shaft = result["accepted"][0]
        self.assertAlmostEqual(shaft["area_drawing_units2"], 1.0)
        self.assertIn("SHAFT", shaft["geometry_evidence"]["source_layers"])

    def test_rejects_one_outline_containing_multiple_labels(self):
        _doc, msp = self._model()
        self._segments(msp, [(0, 0), (10, 0), (10, 6), (0, 6), (0, 0)])
        result = reconstruct_boundaries(
            msp, [0, 0, 10, 6],
            [self._label("خواب", "bedroom", (2, 3)), self._label("حمام", "bath", (8, 3))],
        )
        self.assertEqual(result["accepted"], {})
        self.assertIn("rejected_multiple_semantic_labels:1", result["diagnostics"])

    def test_classifies_shared_kitchen_living_enclosure_as_open_plan_exception(self):
        _doc, msp = self._model()
        self._segments(msp, [(1, 1), (11, 1), (11, 7), (1, 7), (1, 1)])
        result = reconstruct_boundaries(
            msp, [0, 0, 12, 8],
            [self._label("آشپزخانه", "kitchen", (3, 4)),
             self._label("نشیمن", "living", (9, 4))],
        )
        self.assertEqual(set(result["accepted"]), {0, 1})
        self.assertTrue(all(row["relationship"] == "OPEN_PLAN_SHARED"
                            for row in result["accepted"].values()))
        self.assertEqual(len({row["group_id"] for row in result["accepted"].values()}), 1)
        self.assertTrue(all(row["polygon_confidence"] == "medium"
                            for row in result["accepted"].values()))

    def test_result_is_deterministic(self):
        _doc, msp = self._model()
        self._segments(msp, [(1, 1), (5, 1), (5, 5), (1, 5), (1, 1)])
        labels = [self._label("خواب", "bedroom", (3, 3))]
        first = reconstruct_boundaries(msp, [0, 0, 8, 8], labels)
        second = reconstruct_boundaries(msp, [0, 0, 8, 8], labels)
        self.assertEqual(first["accepted"][0]["geometry_fingerprint"],
                         second["accepted"][0]["geometry_fingerprint"])
        self.assertTrue(first["snap_points"])
        self.assertTrue(first["wall_segments"])
        self.assertTrue(all(row.get("a_id") and row.get("b_id") for row in first["wall_segments"]))

    def test_ignores_dimension_layer_as_room_boundary(self):
        _doc, msp = self._model()
        self._segments(msp, [(1, 1), (5, 1), (5, 5), (1, 5), (1, 1)], layer="Dime-Arch")
        result = reconstruct_boundaries(
            msp, [0, 0, 8, 8], [self._label("خواب", "bedroom", (3, 3))]
        )
        self.assertEqual(result["accepted"], {})

    def test_nested_layer_zero_block_is_visible_and_available_to_topology(self):
        doc, msp = self._model()
        block = doc.blocks.new("ROOM-ASSEMBLY")
        self._segments(block, [(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)], layer="0")
        block.add_arc((2, 0), 0.7, 0, 90, dxfattribs={"layer": "0"})
        msp.add_blockref("ROOM-ASSEMBLY", (10, 10), dxfattribs={"layer": "A-WALL"})
        result = reconstruct_boundaries(
            msp, [9, 9, 15, 15], [self._label("اتاق", "bedroom", (12, 12))]
        )
        self.assertIn(0, result["accepted"])
        visual = result["visual_underlay"]
        self.assertEqual(visual["status"], "PASS")
        self.assertGreaterEqual(visual["drawable_entity_count"], 5)
        self.assertTrue(any("ROOM-ASSEMBLY" in row["source_block_path"]
                            for row in visual["entities"]))
        self.assertTrue(any(row["entity_type"] == "ARC" for row in visual["entities"]))
        self.assertTrue(all(row["visual_entity_id"].startswith("VIS-") for row in visual["entities"]))
        self.assertTrue(all(row["source_handle"] for row in visual["entities"]))
        self.assertIn("A-WALL", result["accepted"][0]["geometry_evidence"]["source_layers"])

    def test_visual_underlay_reports_unsupported_instead_of_silent_drop(self):
        _doc, msp = self._model()
        msp.add_line((0, 0), (5, 0), dxfattribs={"layer": "A-WALL"})
        msp.add_circle((2, 2), 1, dxfattribs={"layer": "A-WALL"})
        msp.add_text("اتاق", dxfattribs={"height": .2}).set_placement((2, 1))
        msp.add_point((3, 3), dxfattribs={"layer": "A-WALL"})
        visual = build_visual_underlay(msp, [0, 0, 5, 5])
        self.assertEqual(visual["status"], "PASS")
        self.assertIn("CIRCLE", visual["inventory"])
        self.assertIn("TEXT", visual["inventory"])
        self.assertIn("POINT", visual["inventory"])
        self.assertNotIn("POINT", visual["unsupported"])
        self.assertEqual(visual["coverage_ratio"], 1.0)

    def test_unbound_xref_fails_visual_underlay_instead_of_showing_partial_plan(self):
        doc, msp = self._model()
        xref = doc.blocks.new("EXTERNAL-PLAN")
        xref.block.dxf.flags = 4
        msp.add_blockref("EXTERNAL-PLAN", (0, 0), dxfattribs={"layer": "A-WALL"})
        visual = build_visual_underlay(msp, [0, 0, 10, 10])
        self.assertEqual(visual["status"], "FAIL")
        self.assertEqual(visual["critical_unsupported_count"], 1)
        self.assertEqual(visual["unsupported"].get("INSERT"), 1)

    def test_empty_block_reference_fails_instead_of_disappearing(self):
        doc, msp = self._model()
        doc.blocks.new("EMPTY-ARCHITECTURE")
        msp.add_blockref("EMPTY-ARCHITECTURE", (2, 2), dxfattribs={"layer": "A-WALL"})
        visual = build_visual_underlay(msp, [0, 0, 10, 10])
        self.assertEqual(visual["status"], "FAIL")
        self.assertEqual(visual["unsupported"].get("INSERT"), 1)

    def test_unlabeled_closed_cell_is_exposed_as_review_exception(self):
        _doc, msp = self._model()
        self._segments(msp, [(1, 1), (5, 1), (5, 5), (1, 5), (1, 1)])
        result = reconstruct_boundaries(msp, [0, 0, 8, 8], [])
        self.assertEqual(len(result["unlabeled_cells"]), 1)
        cell = result["unlabeled_cells"][0]
        self.assertEqual(cell["provenance"], "GEOMETRY_ONLY")
        self.assertEqual(cell["polygon_confidence"], "low")


if __name__ == "__main__":
    unittest.main()
