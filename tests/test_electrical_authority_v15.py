from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cad_engine.electrical_v1.authority_qa import release_contract_status
from cad_engine.electrical_v1.cleanup_policy import should_remove_footer_entity
from cad_engine.electrical_v1.strict_pipeline_v15 import run_strict_electrical_pipeline_v15
from tests.test_electrical_project_driven_v1 import make_architecture, fully_evidenced_config


class ElectricalAuthorityV15Tests(unittest.TestCase):
    def test_release_contract_modules_are_available(self):
        status = release_contract_status()
        self.assertEqual(status["status"], "PASS", status)
        self.assertEqual(status["passed_count"], status["required_count"])

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

    def test_fully_evidenced_project_passes_new_authority_gates(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "arch.dxf"
            output = Path(td) / "electrical-v15.dxf"
            make_architecture(source)
            report = run_strict_electrical_pipeline_v15(source, output, fully_evidenced_config())
            for gate in (
                "PLAN_ISOLATION_AUTHORITY",
                "EQUIPMENT_REPRESENTATION_AUTHORITY",
                "DETAIL_REFERENCE_PARITY_AUTHORITY",
                "SEMANTIC_DUPLICATE_AUTHORITY",
                "FINAL_REOPEN_AUTHORITY",
                "SAFE_DRAWING_AREA_AUTHORITY",
                "ELECTRICAL_RELEASE_CONTRACT",
            ):
                self.assertEqual(report["gates"][gate]["status"], "PASS", (gate, report["gates"][gate]))
            self.assertTrue(output.exists())
            self.assertFalse(report["acceptance"]["production_release_allowed"])


if __name__ == "__main__":
    unittest.main()
