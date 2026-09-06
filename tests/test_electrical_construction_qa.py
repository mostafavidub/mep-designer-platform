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
                "mounting_height": {"value": "PROJECT INPUT", "status": "FINAL", "source": "explicit_user_input"},
                "clearance": {"value": "PROJECT INPUT", "status": "FINAL", "source": "explicit_user_input"},
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


if __name__ == "__main__":
    unittest.main()
