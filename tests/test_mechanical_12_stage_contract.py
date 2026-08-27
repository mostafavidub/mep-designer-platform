"""Executable regression contract for the 12-stage mechanical drawing-set upgrade."""

import tempfile
import unittest
from pathlib import Path

import ezdxf

from app.mechanical_drawing_set import approve_drawing_set, predict_drawing_set
from app.mechanical_rulebook import plan_detail_requirements
from cad_engine import main_v10_3 as authority
from cad_engine.documentation_v12 import annotate_issued_sheets
from cad_engine.drawing_content_qa_v12 import validate_independent_drawing_content
from cad_engine.mechanical_upgrade_v11 import _system_special_sheet


class MechanicalTwelveStageContractTests(unittest.TestCase):
    def _reference_scope(self, **overrides):
        levels = ["Ground", "First Duplex", "Second Duplex"]
        scope = {
            "all_levels": levels + ["Roof"], "conditioned_levels": levels,
            "heated_levels": levels, "wet_fixture_levels": levels,
            "sanitary_fixture_levels": levels, "ventilation_required_levels": levels,
            "gas_consumer_levels": levels, "roof_exists": True,
            "roof_level_name": "Roof", "vertical_systems": True, "typical_groups": [],
        }
        scope.update(overrides); return scope

    def test_stage_01_base_levels_are_not_the_deliverable_count(self):
        scope = self._reference_scope(); result = predict_drawing_set(scope)
        self.assertEqual(len(scope["all_levels"]), 4); self.assertGreater(result["deliverable_sheet_count"], len(scope["all_levels"]))
        self.assertEqual(result["count_semantics"], "authority_separated_customer_deliverables")

    def test_stage_02_system_families_are_authority_separated(self):
        result = predict_drawing_set(self._reference_scope()); expected = {"water_supply", "sanitary_vent", "heating", "cooling", "gas", "ventilation_exhaust", "roof_rainwater"}
        self.assertTrue(expected.issubset(result["sheet_families"]))
        for key in expected - {"roof_rainwater"}: self.assertEqual(len(result["sheet_families"][key]["systems"]), 1)
        self.assertNotIn("plumbing_gas", result["sheet_families"]); self.assertNotIn("heating_cooling_condensate", result["sheet_families"])

    def test_stage_03_non_floor_deliverables_are_first_class_manifest_items(self):
        sheets = predict_drawing_set(self._reference_scope())["drawing_manifest"]["sheets"]
        self.assertTrue(any(not s.get("special") for s in sheets)); self.assertTrue(any(s.get("special") for s in sheets))
        special_codes = {s["code"] for s in sheets if s.get("special")}; self.assertIn("M-W-RISER", special_codes); self.assertIn("M-C-EQUIP", special_codes)

    def test_stage_04_approval_freezes_exact_manifest_before_cad(self):
        approved = approve_drawing_set(predict_drawing_set(self._reference_scope())); frozen = approved["approved_manifest"]
        self.assertEqual(frozen, approved["drawing_manifest"]); expected_id = frozen["manifest_id"]
        approved["drawing_manifest"]["sheets"][0]["label"] = "MUTATED AFTER APPROVAL"
        self.assertNotEqual(frozen["sheets"][0]["label"], "MUTATED AFTER APPROVAL"); self.assertEqual(frozen["manifest_id"], expected_id)

    def test_stage_05_cad_refuses_mechanical_generation_without_approved_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "architecture.dxf"; dst = Path(td) / "mechanical.dxf"; doc = ezdxf.new("R2013")
            doc.modelspace().add_text("Ground Architectural Plan").set_placement((0, 0)); doc.saveas(src)
            with self.assertRaisesRegex(RuntimeError, "Approved mechanical drawing manifest"):
                authority.design_dxf_v10_3(src, dst, "mechanical", ["cold_water"], 1, {"_design_inputs": {}})

    def test_stage_06_special_sheet_has_independent_riser_content_not_floor_viewport(self):
        doc = ezdxf.new("R2013"); levels = [{"level": x, "rooms": [], "fixtures": []} for x in ("Ground", "First", "Second")]
        row = _system_special_sheet(doc, authority, levels, "TEST-PROJECT", {"code": "M-W-RISER", "family": "water_supply", "special": True, "levels": ["Ground", "First", "Second"], "label": "Water Riser"}, "W", {"ENGITOOLS-M-COLD_WATER", "ENGITOOLS-M-HOT_WATER"})
        layout = doc.layouts.get("M-W-RISER"); self.assertEqual(row["drawing_role"], "riser"); self.assertEqual(len(layout.query("VIEWPORT")), 0)
        self.assertGreaterEqual(len(layout.query("LINE")), 5); self.assertGreater(len(layout.query("TEXT")) + len(layout.query("MTEXT")), 3)

    def test_stage_07_rulebook_detail_library_covers_every_authority_family(self):
        requirements = {family: set(plan_detail_requirements(family)) for family in ("water_supply", "sanitary_vent", "heating", "cooling", "gas", "ventilation_exhaust", "roof_rainwater")}
        for family, tokens in requirements.items(): self.assertTrue(tokens, family)
        self.assertIn("isolation_valve", requirements["water_supply"]); self.assertIn("cleanout", requirements["sanitary_vent"])
        self.assertIn("outdoor_unit_location", requirements["cooling"]); self.assertIn("meter_regulator", requirements["gas"]); self.assertIn("roof_drain", requirements["roof_rainwater"])

    def test_stage_08_annotation_engine_generates_owned_dimension_leader_and_callout(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "issued.dxf"; doc = ezdxf.new("R2013"); doc.layouts.new("M-W-01"); doc.saveas(path)
            calc = {"_approved_drawing_manifest": {"total_sheets": 1, "sheets": [{"code": "M-W-01", "family": "water_supply"}]}}
            report = annotate_issued_sheets(path, calc); self.assertEqual(report["status"], "PASS"); out = ezdxf.readfile(path); layout = out.layouts.get("M-W-01")
            self.assertEqual(len(layout.query("DIMENSION")), 1); self.assertEqual(len(layout.query("LEADER")), 1); self.assertIn("WATER:", " ".join(str(x.dxf.text) for x in layout.query("TEXT")))

    def test_stage_09_typical_floor_consolidation_is_system_specific(self):
        typical = ["Floor 1", "Floor 2", "Floor 3", "Floor 4", "Floor 5"]
        result = predict_drawing_set({
            "all_levels": ["Ground"] + typical + ["Roof"],
            "conditioned_levels": typical, "heated_levels": typical,
            "wet_fixture_levels": ["Ground"] + typical,
            "sanitary_fixture_levels": ["Ground", "Floor 1"],
            "ventilation_required_levels": typical, "gas_consumer_levels": typical,
            "roof_exists": True, "roof_level_name": "Roof", "vertical_systems": True,
            "typical_groups": [{"name": "Typical Floors 1-5", "levels": typical}],
        })
        water = [s for s in result["drawing_manifest"]["sheets"] if s["family"] == "water_supply" and not s.get("special")]
        sanitary = [s for s in result["drawing_manifest"]["sheets"] if s["family"] == "sanitary_vent" and not s.get("special")]
        self.assertEqual(len(water), 2); self.assertTrue(any(len(s.get("levels") or []) == 5 for s in water))
        self.assertEqual(len(sanitary), 2); self.assertFalse(any(len(s.get("levels") or []) > 1 for s in sanitary))

    def test_stage_11_layout_count_alone_is_not_accepted_as_real_deliverables(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stage11.dxf"
            doc = ezdxf.new("R2013")
            plan = doc.layouts.new("M-W-01")
            plan.add_viewport(center=(100, 100), size=(100, 100), view_center_point=(0, 0), view_height=10)
            special = doc.layouts.new("M-W-RISER")
            special.add_line((10, 10), (10, 100))
            doc.saveas(path)
            calc = {
                "_approved_drawing_manifest": {"total_sheets": 2, "sheets": [
                    {"code": "M-W-01", "family": "water_supply", "levels": ["Ground"], "special": False},
                    {"code": "M-W-RISER", "family": "water_supply", "levels": ["Ground", "First"], "special": True},
                ]},
                "_plan_analysis": {"architectural_auto": {"level_profiles": [
                    {"name": "Ground"}, {"name": "First"}, {"name": "Second"}, {"name": "Roof"}
                ]}},
            }
            annotate_issued_sheets(path, calc)
            report = validate_independent_drawing_content(path, calc)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["base_architectural_view_count"], 4)
            self.assertEqual(report["approved_deliverable_count"], 2)
            self.assertEqual(report["independent_issued_drawing_content_count"], 2)
            self.assertEqual(report["issued_layout_count"], 2)

            bad = ezdxf.readfile(path)
            bad.layouts.get("M-W-RISER").delete_all_entities()
            bad.saveas(path)
            with self.assertRaisesRegex(RuntimeError, "CAD output does not match approved drawing manifest"):
                validate_independent_drawing_content(path, calc)


if __name__ == "__main__": unittest.main()
