import copy
import unittest

from app.mechanical_drawing_set import approve_drawing_set, is_current_manifest, predict_drawing_set


class MechanicalManifestReleaseTests(unittest.TestCase):
    def scope(self, *, typical=False, roof=True, gas=True):
        levels = ["Ground", "First", "Second"]
        return {
            "all_levels": levels + (["Roof"] if roof else []),
            "conditioned_levels": levels,
            "heated_levels": levels,
            "wet_fixture_levels": levels,
            "sanitary_fixture_levels": levels,
            "ventilation_required_levels": levels,
            "gas_consumer_levels": levels if gas else [],
            "roof_exists": roof,
            "roof_level_name": "Roof",
            "vertical_systems": True,
            "typical_groups": [{"name": "Typical Floors", "levels": ["First", "Second"]}] if typical else [],
        }

    def test_current_release_manifest_is_self_consistent_not_fixed_to_legacy_count(self):
        proposal = predict_drawing_set(self.scope())
        manifest = approve_drawing_set(proposal)["approved_manifest"]
        self.assertTrue(is_current_manifest(manifest))
        self.assertEqual(manifest["total_sheets"], len(manifest["sheets"]))
        self.assertEqual(len({x["code"] for x in manifest["sheets"]}), len(manifest["sheets"]))
        self.assertEqual(manifest, proposal["drawing_manifest"])
        self.assertTrue(any(x.get("drawing_type") == "calculation_sheet" for x in manifest["sheets"]))

    def test_typical_consolidation_changes_only_project_justified_manifest(self):
        full = predict_drawing_set(self.scope(typical=False, roof=False))
        typical = predict_drawing_set(self.scope(typical=True, roof=False))
        self.assertLess(typical["deliverable_sheet_count"], full["deliverable_sheet_count"])
        for family in ("water_supply", "sanitary_vent", "heating", "cooling", "gas", "ventilation_exhaust"):
            primary = [x for x in typical["drawing_manifest"]["sheets"] if x.get("family") == family and x.get("drawing_type") == "floor_plan"]
            # Ground remains unique while First/Second consolidate as one typical plan.
            self.assertEqual(len(primary), 2)
        self.assertTrue(any(x.get("family") == "water_supply" and x.get("drawing_type") == "calculation_sheet" for x in typical["drawing_manifest"]["sheets"]))

    def test_gas_off_removes_gas_from_release_manifest(self):
        manifest = approve_drawing_set(predict_drawing_set(self.scope(gas=False)))["approved_manifest"]
        self.assertFalse([x for x in manifest["sheets"] if x.get("family") == "gas"])

    def test_five_identical_floors_collapse_to_one_typical_primary_per_family(self):
        levels = ["L1", "L2", "L3", "L4", "L5"]
        scope = self.scope(roof=False)
        for key in ("all_levels", "conditioned_levels", "heated_levels", "wet_fixture_levels",
                    "sanitary_fixture_levels", "ventilation_required_levels", "gas_consumer_levels"):
            scope[key] = levels
        scope["typical_groups"] = [{"name": "Typical L1-L5", "levels": levels}]
        result = predict_drawing_set(scope)
        for family in ("water_supply", "sanitary_vent", "heating", "cooling", "gas", "ventilation_exhaust"):
            primary = [x for x in result["drawing_manifest"]["sheets"] if x.get("family") == family and x.get("drawing_type") == "floor_plan"]
            self.assertEqual(len(primary), 1)
            self.assertTrue(primary[0]["typical"])

    def test_manifest_count_tampering_is_not_current_and_cannot_be_approved(self):
        proposal = predict_drawing_set(self.scope())
        broken = copy.deepcopy(proposal)
        broken["drawing_manifest"]["total_sheets"] -= 1
        self.assertFalse(is_current_manifest(broken["drawing_manifest"]))
        with self.assertRaises(ValueError):
            approve_drawing_set(broken)


if __name__ == "__main__":
    unittest.main()
