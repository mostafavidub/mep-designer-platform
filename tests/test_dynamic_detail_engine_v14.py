import unittest

from cad_engine.dynamic_detail_engine_v14 import (
    DETAIL_SHEETS,
    build_project_legend,
    resolve_detail_requirements,
    validate_detail_coverage,
)


class DynamicDetailEngineV14Tests(unittest.TestCase):
    def test_resolver_is_project_driven(self):
        systems = {
            "split_ac": True,
            "heating_radiator": True,
            "package_boiler": True,
            "sanitary": True,
            "vent": True,
            "water": True,
            "gas": True,
            "exhaust": True,
        }
        details = resolve_detail_requirements(systems)
        self.assertEqual(len(details), 17)
        self.assertIn("D-AC-01", details)
        self.assertIn("D-HT-04", details)
        self.assertIn("D-GS-02", details)
        self.assertIn("D-HV-01", details)

    def test_smaller_project_gets_smaller_detail_set(self):
        details = resolve_detail_requirements({"sanitary": True, "vent": True, "water": True})
        self.assertLess(len(details), 17)
        self.assertNotIn("D-AC-01", details)
        self.assertNotIn("D-GS-01", details)

    def test_coverage_gate_rejects_orphans_and_duplicates(self):
        required = ["D-PL-01", "D-PL-02"]
        self.assertEqual(validate_detail_coverage(required, required, required)["status"], "PASS")
        self.assertEqual(validate_detail_coverage(required, ["D-PL-01"], required)["status"], "FAIL")
        self.assertEqual(validate_detail_coverage(required, ["D-PL-01", "D-PL-01"], ["D-PL-01"])["status"], "FAIL")

    def test_all_catalog_details_have_target_sheet(self):
        systems = {
            "split_ac": True, "heating_radiator": True, "package_boiler": True,
            "sanitary": True, "vent": True, "water": True, "gas": True, "exhaust": True,
        }
        for detail_id in resolve_detail_requirements(systems):
            self.assertIn(detail_id, DETAIL_SHEETS)

    def test_legend_only_contains_used_symbols(self):
        meanings = {"AC": "Indoor Split Unit", "FD": "Floor Drain", "PUMP": "Pump"}
        legend = build_project_legend({"AC": True, "FD": True, "PUMP": False}, meanings)
        self.assertEqual([x["symbol"] for x in legend], ["AC", "FD"])


if __name__ == "__main__":
    unittest.main()
