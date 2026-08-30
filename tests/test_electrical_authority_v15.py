from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine.electrical_v1.cleanup_policy import should_remove_footer_entity
from cad_engine.electrical_v1.release_contract_v15_2 import release_contract_status
from cad_engine.electrical_v1.strict_pipeline_v15_2 import run_strict_electrical_pipeline_v15_2
from tests.test_electrical_project_driven_v1 import make_architecture, fully_evidenced_config


class ElectricalAuthorityV15Tests(unittest.TestCase):
    def test_release_contract_modules_are_available(self):
        status = release_contract_status()
        self.assertEqual(status["status"], "PASS", status)
        self.assertEqual(status["passed_count"], status["required_count"])
        self.assertTrue(status["checks"]["preservation_first_cleanup"])
        self.assertTrue(status["checks"]["north_inherited_from_architecture"])

    def test_preservation_first_cleanup_never_deletes_architecture_by_region_only(self):
        self.assertFalse(should_remove_footer_entity(
            family="POWER", layer="WALL", entity_type="LINE",
            bbox_center_x=100.0, bbox_center_y=7.0,
            bbox_width=8.0, bbox_height=0.0,
            sheet_bounds=(0.0, 0.0, 420.0, 297.0),
        ))
        self.assertTrue(should_remove_footer_entity(
            family="POWER", layer="EL2", entity_type="TEXT",
            bbox_center_x=100.0, bbox_center_y=7.0,
            bbox_width=20.0, bbox_height=2.0,
            sheet_bounds=(0.0, 0.0, 420.0, 297.0),
            text="پلان معماری طبقه همکف",
        ))

    def test_missing_north_is_reported_but_never_fabricated(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "arch.dxf"; output = Path(td) / "electrical-v15.dxf"
            make_architecture(source)
            report = run_strict_electrical_pipeline_v15_2(source, output, fully_evidenced_config())
            north = report["gates"]["NORTH_ORIENTATION"]
            self.assertEqual(north["status"], "PASS", north)
            self.assertGreater(north["metrics"]["north_input_required"], 0)
            self.assertEqual(north["metrics"]["arrows_drawn"], 0)
            self.assertTrue(any(x.startswith("north_input_required:") for x in north["warnings"]))

    def test_architectural_compass_is_inherited_and_redrawn_on_final_file(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "arch.dxf"; output = Path(td) / "electrical-v15.dxf"
            make_architecture(source)
            doc = ezdxf.readfile(source); msp = doc.modelspace()
            msp.add_text("N", dxfattribs={"height":180, "layer":"NORTH"}).set_placement((9000,6500))
            msp.add_line((9000,5800),(9000,6100), dxfattribs={"layer":"NORTH"})
            msp.add_line((8850,5950),(9150,5950), dxfattribs={"layer":"NORTH"})
            doc.saveas(source)
            report = run_strict_electrical_pipeline_v15_2(source, output, fully_evidenced_config())
            north = report["gates"]["NORTH_ORIENTATION"]
            self.assertEqual(north["status"], "PASS", north)
            self.assertGreater(north["metrics"]["north_from_architecture"], 0)
            self.assertGreater(north["metrics"]["arrows_drawn"], 0)
            self.assertEqual(north["metrics"]["north_input_required"], 0)
            reopened = ezdxf.readfile(output)
            north_labels = sum(1 for layout in reopened.layouts if layout.name != "Model" for e in layout if e.dxftype()=="TEXT" and str(getattr(e.dxf,"layer", ""))=="ENGITOOLS-E-NORTH" and str(getattr(e.dxf,"text", ""))=="N")
            self.assertGreater(north_labels, 0)
            self.assertEqual(report["gates"]["FINAL_REOPEN_AUTHORITY"]["status"], "PASS")

    def test_fully_evidenced_project_passes_new_authority_gates(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "arch.dxf"; output = Path(td) / "electrical-v15.dxf"
            make_architecture(source)
            report = run_strict_electrical_pipeline_v15_2(source, output, fully_evidenced_config())
            for gate in (
                "PLAN_ISOLATION_AUTHORITY",
                "EQUIPMENT_REPRESENTATION_AUTHORITY",
                "DETAIL_REFERENCE_PARITY_AUTHORITY",
                "SEMANTIC_DUPLICATE_AUTHORITY",
                "FINAL_REOPEN_AUTHORITY",
                "SAFE_DRAWING_AREA_AUTHORITY",
                "NORTH_ORIENTATION",
                "ELECTRICAL_RELEASE_CONTRACT",
            ):
                self.assertEqual(report["gates"][gate]["status"], "PASS", (gate, report["gates"][gate]))
            self.assertTrue(output.exists())
            self.assertFalse(report["acceptance"]["production_release_allowed"])


if __name__ == "__main__":
    unittest.main()
