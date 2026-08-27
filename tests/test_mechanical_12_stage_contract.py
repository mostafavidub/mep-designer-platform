"""Executable regression contract for the 12-stage mechanical drawing-set upgrade."""

import tempfile
import unittest
from pathlib import Path

import ezdxf

from app.mechanical_drawing_set import approve_drawing_set, predict_drawing_set
from cad_engine import main_v10_3 as authority


class MechanicalTwelveStageContractTests(unittest.TestCase):
    def _reference_scope(self, **overrides):
        levels = ["Ground", "First Duplex", "Second Duplex"]
        scope = {
            "all_levels": levels + ["Roof"],
            "conditioned_levels": levels, "heated_levels": levels,
            "wet_fixture_levels": levels, "sanitary_fixture_levels": levels,
            "ventilation_required_levels": levels, "gas_consumer_levels": levels,
            "roof_exists": True, "roof_level_name": "Roof",
            "vertical_systems": True, "typical_groups": [],
        }
        scope.update(overrides)
        return scope

    def test_stage_01_base_levels_are_not_the_deliverable_count(self):
        scope = self._reference_scope(); result = predict_drawing_set(scope)
        self.assertEqual(len(scope["all_levels"]), 4)
        self.assertGreater(result["deliverable_sheet_count"], len(scope["all_levels"]))
        self.assertEqual(result["count_semantics"], "authority_separated_customer_deliverables")

    def test_stage_02_system_families_are_authority_separated(self):
        result = predict_drawing_set(self._reference_scope())
        expected = {"water_supply", "sanitary_vent", "heating", "cooling", "gas", "ventilation_exhaust", "roof_rainwater"}
        self.assertTrue(expected.issubset(result["sheet_families"]))
        for key in expected - {"roof_rainwater"}:
            self.assertEqual(len(result["sheet_families"][key]["systems"]), 1)
        self.assertNotIn("plumbing_gas", result["sheet_families"])
        self.assertNotIn("heating_cooling_condensate", result["sheet_families"])

    def test_stage_03_non_floor_deliverables_are_first_class_manifest_items(self):
        sheets = predict_drawing_set(self._reference_scope())["drawing_manifest"]["sheets"]
        self.assertTrue(any(not sheet.get("special") for sheet in sheets))
        self.assertTrue(any(sheet.get("special") for sheet in sheets))
        special_codes = {sheet["code"] for sheet in sheets if sheet.get("special")}
        self.assertIn("M-W-RISER", special_codes)
        self.assertIn("M-C-EQUIP", special_codes)

    def test_stage_04_approval_freezes_exact_manifest_before_cad(self):
        approved = approve_drawing_set(predict_drawing_set(self._reference_scope()))
        frozen = approved["approved_manifest"]
        self.assertEqual(frozen, approved["drawing_manifest"])
        expected_id = frozen["manifest_id"]
        approved["drawing_manifest"]["sheets"][0]["label"] = "MUTATED AFTER APPROVAL"
        self.assertNotEqual(frozen["sheets"][0]["label"], "MUTATED AFTER APPROVAL")
        self.assertEqual(frozen["manifest_id"], expected_id)

    def test_stage_05_cad_refuses_mechanical_generation_without_approved_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "architecture.dxf"; dst = Path(td) / "mechanical.dxf"
            doc = ezdxf.new("R2013")
            doc.modelspace().add_text("Ground Architectural Plan").set_placement((0, 0))
            doc.saveas(src)
            with self.assertRaisesRegex(RuntimeError, "Approved mechanical drawing manifest"):
                authority.design_dxf_v10_3(src, dst, "mechanical", ["cold_water"], 1, {"_design_inputs": {}})


if __name__ == "__main__":
    unittest.main()
