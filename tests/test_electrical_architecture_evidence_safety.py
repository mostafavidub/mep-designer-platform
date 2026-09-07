from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine.electrical_v1.architecture import reconstruct_architecture
from cad_engine.electrical_v1.models import EngineeringStatus


class ElectricalArchitectureEvidenceSafetyTests(unittest.TestCase):
    @staticmethod
    def _make_unit_case(path: Path, *, drawing_scale: float, dimension_value: float, header_units: int = 4):
        doc = ezdxf.new("R2013")
        doc.header["$INSUNITS"] = header_units
        msp = doc.modelspace()
        s = float(drawing_scale)
        msp.add_lwpolyline([(0, 0), (12*s, 0), (12*s, 8*s), (0, 8*s), (0, 0)], close=True, dxfattribs={"layer": "SHEET_FRAME"})
        msp.add_text("Architectural Plan Ground", dxfattribs={"height": 0.18*s, "layer": "TITLE"}).set_placement((0.4*s, 0.4*s))
        msp.add_lwpolyline([(1*s, 1*s), (11*s, 1*s), (11*s, 7*s), (1*s, 7*s), (1*s, 1*s)], close=True, dxfattribs={"layer": "ROOM"})
        msp.add_text("Living", dxfattribs={"height": 0.18*s, "layer": "ROOM_NAME"}).set_placement((5.5*s, 3.8*s))
        dim = msp.add_linear_dim(base=(0, 0.8*s), p1=(0, 0), p2=(dimension_value, 0), angle=0)
        dim.render()
        doc.saveas(path)

    def test_stale_mm_header_is_overridden_by_meter_dimension_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "stale-mm.dxf"
            self._make_unit_case(source, drawing_scale=1.0, dimension_value=3.7, header_units=4)
            model = reconstruct_architecture(source)
            self.assertEqual(model.units.status, EngineeringStatus.FINAL)
            self.assertEqual(model.units.value, "m")
            self.assertTrue(any("mm_to_m" in issue for issue in model.issues), model.issues)
            self.assertEqual(len(model.rooms), 1)
            self.assertAlmostEqual(float(model.rooms[0].area_m2.value), 60.0, places=5)

    def test_normal_mm_header_remains_mm_with_mm_dimension(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "normal-mm.dxf"
            self._make_unit_case(source, drawing_scale=1000.0, dimension_value=3700.0, header_units=4)
            model = reconstruct_architecture(source)
            self.assertEqual(model.units.value, "mm")
            self.assertFalse(any("unit_header_conflict_resolved" in issue for issue in model.issues), model.issues)
            self.assertAlmostEqual(float(model.rooms[0].area_m2.value), 60.0, places=5)

    def test_multi_room_helper_rectangle_cannot_become_room_geometry(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "helper-room.dxf"
            doc = ezdxf.new("R2013")
            doc.header["$INSUNITS"] = 4
            msp = doc.modelspace()
            msp.add_lwpolyline([(0, 0), (12000, 0), (12000, 8000), (0, 8000), (0, 0)], close=True, dxfattribs={"layer": "SHEET_FRAME"})
            msp.add_text("Architectural Plan Ground", dxfattribs={"height": 180, "layer": "TITLE"}).set_placement((400, 400))
            msp.add_lwpolyline([(1000, 1000), (11000, 1000), (11000, 7000), (1000, 7000), (1000, 1000)], close=True, dxfattribs={"layer": "support"})
            msp.add_text("Living", dxfattribs={"height": 180}).set_placement((3000, 4000))
            msp.add_text("Bedroom", dxfattribs={"height": 180}).set_placement((8000, 4000))
            doc.saveas(source)
            model = reconstruct_architecture(source)
            self.assertEqual(len(model.rooms), 2)
            self.assertTrue(all(room.polygon is None for room in model.rooms))
            self.assertTrue(all(room.area_m2.status == EngineeringStatus.UNKNOWN for room in model.rooms))

    def test_measurement_note_with_room_word_is_not_a_room(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "note-room.dxf"
            doc = ezdxf.new("R2013")
            doc.header["$INSUNITS"] = 4
            msp = doc.modelspace()
            msp.add_lwpolyline([(0, 0), (12000, 0), (12000, 8000), (0, 8000), (0, 0)], close=True, dxfattribs={"layer": "SHEET_FRAME"})
            msp.add_text("Architectural Plan Ground", dxfattribs={"height": 180}).set_placement((400, 400))
            msp.add_text("Living", dxfattribs={"height": 180}).set_placement((3000, 4000))
            msp.add_text("ارتفاع دیوار تراس=1/70", dxfattribs={"height": 180}).set_placement((8000, 4000))
            doc.saveas(source)
            model = reconstruct_architecture(source)
            self.assertEqual([room.label for room in model.rooms], ["Living"])

    def test_persian_ordinal_floor_title_beats_frame_order_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "persian-levels.dxf"
            doc = ezdxf.new("R2013")
            doc.header["$INSUNITS"] = 4
            msp = doc.modelspace()
            # Two non-overlapping architectural frames; the second title is an
            # explicit Persian ordinal and must resolve to LEVEL-1, not LEVEL-2.
            msp.add_lwpolyline([(0, 0), (12000, 0), (12000, 8000), (0, 8000), (0, 0)], close=True, dxfattribs={"layer": "SHEET_FRAME"})
            msp.add_text("پلان معماری طبقه همکف", dxfattribs={"height": 180}).set_placement((400, 400))
            msp.add_lwpolyline([(20000, 0), (32000, 0), (32000, 8000), (20000, 8000), (20000, 0)], close=True, dxfattribs={"layer": "SHEET_FRAME"})
            msp.add_text("پلان معماری طبقه اول", dxfattribs={"height": 180}).set_placement((20400, 400))
            doc.saveas(source)
            model = reconstruct_architecture(source)
            names = [level.name.value for level in model.levels]
            self.assertEqual(names, ["GROUND", "LEVEL-1"], names)
            self.assertTrue(all(level.name.status == EngineeringStatus.FINAL for level in model.levels))

    def test_fragmented_wall_faces_can_recover_unique_room(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "fragmented-wall-room.dxf"
            doc = ezdxf.new("R2013")
            doc.header["$INSUNITS"] = 4
            msp = doc.modelspace()
            msp.add_lwpolyline([(0, 0), (12000, 0), (12000, 8000), (0, 8000), (0, 0)], close=True, dxfattribs={"layer": "SHEET_FRAME"})
            msp.add_text("Architectural Plan Ground", dxfattribs={"height": 180}).set_placement((400, 400))
            msp.add_text("Bedroom", dxfattribs={"height": 180}).set_placement((3000, 2500))
            # Top wall has an opening centered on the label x-coordinate.  The
            # old cross-label resolver cannot see an upper wall, while the
            # coverage-based resolver can prove the fragmented enclosure.
            segments = [
                ((1000, 1000), (5000, 1000)),
                ((1000, 4000), (2800, 4000)), ((3200, 4000), (5000, 4000)),
                ((1000, 1000), (1000, 4000)), ((5000, 1000), (5000, 4000)),
            ]
            for a, b in segments:
                msp.add_line(a, b, dxfattribs={"layer": "WALL"})
            doc.saveas(source)
            model = reconstruct_architecture(source)
            self.assertEqual(len(model.rooms), 1)
            room = model.rooms[0]
            self.assertIsNotNone(room.polygon)
            self.assertEqual(room.area_m2.status, EngineeringStatus.FINAL)
            self.assertAlmostEqual(float(room.area_m2.value), 12.0, places=4)
            self.assertEqual(room.area_m2.reference, "wall_supported_unique_room_enclosure")

    def test_fragmented_shared_open_plan_is_not_partitioned_into_fake_rooms(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "shared-open-plan.dxf"
            doc = ezdxf.new("R2013")
            doc.header["$INSUNITS"] = 4
            msp = doc.modelspace()
            msp.add_lwpolyline([(0, 0), (12000, 0), (12000, 8000), (0, 8000), (0, 0)], close=True, dxfattribs={"layer": "SHEET_FRAME"})
            msp.add_text("Architectural Plan Ground", dxfattribs={"height": 180}).set_placement((400, 400))
            msp.add_text("Living", dxfattribs={"height": 180}).set_placement((2500, 2500))
            msp.add_text("Kitchen", dxfattribs={"height": 180}).set_placement((4000, 2500))
            for a, b in [
                ((1000, 1000), (5000, 1000)),
                ((1000, 4000), (2200, 4000)), ((2600, 4000), (5000, 4000)),
                ((1000, 1000), (1000, 4000)), ((5000, 1000), (5000, 4000)),
            ]:
                msp.add_line(a, b, dxfattribs={"layer": "WALL"})
            doc.saveas(source)
            model = reconstruct_architecture(source)
            self.assertEqual(len(model.rooms), 2)
            self.assertTrue(all(room.polygon is None for room in model.rooms), [(r.label, r.polygon) for r in model.rooms])
            self.assertTrue(all(room.area_m2.status == EngineeringStatus.UNKNOWN for room in model.rooms))

    def test_unique_four_wall_cell_can_recover_room_enclosure(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "wall-cell.dxf"
            doc = ezdxf.new("R2013")
            doc.header["$INSUNITS"] = 4
            msp = doc.modelspace()
            msp.add_lwpolyline([(0, 0), (12000, 0), (12000, 8000), (0, 8000), (0, 0)], close=True, dxfattribs={"layer": "SHEET_FRAME"})
            msp.add_text("Architectural Plan Ground", dxfattribs={"height": 180}).set_placement((400, 400))
            msp.add_text("Bedroom", dxfattribs={"height": 180}).set_placement((3000, 3000))
            for a, b in [((1000, 1000), (5000, 1000)), ((1000, 4000), (5000, 4000)), ((1000, 1000), (1000, 4000)), ((5000, 1000), (5000, 4000))]:
                msp.add_line(a, b, dxfattribs={"layer": "WALL"})
            doc.saveas(source)
            model = reconstruct_architecture(source)
            self.assertEqual(len(model.rooms), 1)
            self.assertIsNotNone(model.rooms[0].polygon)
            self.assertAlmostEqual(float(model.rooms[0].area_m2.value), 12.0, places=5)


if __name__ == "__main__":
    unittest.main()
