from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine.electrical_v1.construction_qa import (
    construction_detail_qa,
    evidence_consistency_qa,
    plan_detail_link_qa,
)
from cad_engine.electrical_v1.construction_detail_render import upgrade_construction_details


class ElectricalConstructionQATests(unittest.TestCase):
    def _write_detail_dxf(self, path: Path, *, graphics: int, text: int = 2) -> None:
        doc = ezdxf.new("R2013")
        doc.layers.add("ENGITOOLS-E-DETAIL")
        layout = doc.layouts.new("E-10")
        for i in range(graphics):
            x = float(i % 12)
            y = float(i // 12)
            layout.add_line((x, y), (x + 0.5, y + 0.2), dxfattribs={"layer": "ENGITOOLS-E-DETAIL"})
        for i in range(text):
            value = "D-EL-PANEL-MOUNT" if i == 0 else f"NOTE-{i}"
            layout.add_text(value, dxfattribs={"layer": "ENGITOOLS-E-DETAIL", "height": 0.8}).set_placement((1, 15 + i))
        doc.saveas(path)

    def _manifest(self):
        return [
            {"sheet_id": "E-02", "family": "POWER"},
            {"sheet_id": "E-10", "family": "DETAILS"},
        ]

    def _detail(self, *, missing=None, status="FINAL"):
        return {
            "detail_id": "D-EL-PANEL-MOUNT",
            "geometry": [("wall_section",), ("panel_box",), ("dimension", "mounting_height"), ("clearance_zone",)],
            "parameters": {
                "mounting_height": {"value": "1500 mm", "status": "FINAL", "source": "explicit_user_input"},
                "wall_type": {"value": "masonry", "status": "FINAL", "source": "explicit_user_input"},
                "clearance": {"value": "1000 mm", "status": "FINAL", "source": "explicit_user_input"},
            },
            "missing": list(missing or []),
            "status": status,
        }

    def test_sparse_placeholder_detail_fails_even_when_dxf_reopens(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sparse.dxf"
            self._write_detail_dxf(path, graphics=3, text=10)
            result = construction_detail_qa(
                path,
                self._manifest(),
                [self._detail()],
                [{"sheet_id": "E-02", "detail_id": "D-EL-PANEL-MOUNT"}],
            )
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("too_sparse" in x or "too_text_heavy" in x for x in result["errors"]))

    def test_graphically_developed_detail_passes_structural_gate(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rich.dxf"
            self._write_detail_dxf(path, graphics=32, text=2)
            result = construction_detail_qa(
                path,
                self._manifest(),
                [self._detail()],
                [{"sheet_id": "E-02", "detail_id": "D-EL-PANEL-MOUNT"}],
            )
            self.assertEqual(result["status"], "PASS", result)

    def test_missing_detail_parameter_stays_input_required(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "input.dxf"
            self._write_detail_dxf(path, graphics=32, text=2)
            detail = self._detail(missing=["mounting_height"], status="PRELIMINARY")
            result = construction_detail_qa(
                path,
                self._manifest(),
                [detail],
                [{"sheet_id": "E-02", "detail_id": "D-EL-PANEL-MOUNT"}],
            )
            self.assertEqual(result["status"], "INPUT_REQUIRED")
            self.assertTrue(any("detail_parameters_input_required" in x for x in result["incomplete"]))

    def test_power_plan_requires_applicable_detail_reference(self):
        result = plan_detail_link_qa(self._manifest(), [self._detail()], [])
        self.assertEqual(result["status"], "INPUT_REQUIRED")
        self.assertIn("plan_detail_reference_required:E-02:POWER", result["incomplete"])

    def test_final_evidence_requires_value_and_source(self):
        result = evidence_consistency_qa({
            "panel": {"main_breaker": {"status": "FINAL", "value": None, "source": None}}
        })
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("final_value_missing" in x for x in result["errors"]))
        self.assertTrue(any("final_source_missing" in x for x in result["errors"]))

    def test_renderer_keeps_all_current_library_details_on_sheet(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "details.dxf"
            doc = ezdxf.new("R2013")
            doc.layers.add("ENGITOOLS-E-DETAIL")
            doc.layers.add("ENGITOOLS-E-DOC")
            doc.layouts.new("E-10")
            doc.saveas(path)
            ids = [
                "D-EL-PANEL-MOUNT", "D-EL-METER", "D-EL-CONDUIT-SUPPORT", "D-EL-WALL-PEN",
                "D-EL-EARTHING", "D-EL-LIGHT-MOUNT", "D-EL-SWITCH-OUTLET", "D-EL-FIRE-DETECTOR",
                "D-EL-EMERGENCY", "D-EL-JB", "D-EL-TERMINATION", "D-EL-ISOLATOR",
            ]
            details = [{"detail_id": value, "status": "PRELIMINARY", "parameters": {}, "missing": []} for value in ids]
            result = upgrade_construction_details(path, self._manifest(), details)
            self.assertEqual(result["status"], "PASS", result)
            self.assertEqual(result["rendered"], 12)
            reopened = ezdxf.readfile(path)
            texts = {
                str(getattr(entity.dxf, "text", "") or "")
                for entity in reopened.layouts.get("E-10")
                if entity.dxftype() == "TEXT"
            }
            for detail_id in ids:
                self.assertIn(detail_id, texts)

    def test_renderer_fails_closed_if_detail_library_outgrows_sheet_capacity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "too-many.dxf"
            doc = ezdxf.new("R2013")
            doc.layers.add("ENGITOOLS-E-DETAIL")
            doc.layouts.new("E-10")
            doc.saveas(path)
            details = [{"detail_id": f"D-{i}", "status": "PRELIMINARY"} for i in range(13)]
            result = upgrade_construction_details(path, self._manifest(), details)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("capacity_exceeded" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
