import unittest

import ezdxf

from app.architecture_geometry_reconstruction import reconstruct_boundaries


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


if __name__ == "__main__":
    unittest.main()
