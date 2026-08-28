import unittest

from cad_engine.adaptive_sheet_planner_v13 import (
    build_adaptive_manifest,
    validate_independent_sheet_set,
)


class AdaptiveSheetPlannerV13Tests(unittest.TestCase):
    def test_current_three_level_project_builds_independent_reference_like_set(self):
        levels = ["GROUND", "LEVEL-01", "LEVEL-02"]
        density = {}
        for family in ("SANITARY_VENT", "WATER", "HEATING", "SPLIT_AC"):
            for level in levels:
                density[(family, level)] = 1

        manifest = build_adaptive_manifest(levels, density)
        self.assertEqual(len(manifest), 20)
        self.assertEqual(manifest[0]["family"], "SANITARY_VENT")
        self.assertEqual(manifest[-1]["family"], "EQUIPMENT_SCHEDULE")

        qa = validate_independent_sheet_set(
            manifest,
            layout_count=20,
            entities_outside_bounds=0,
        )
        self.assertEqual(qa["status"], "PASS", qa)

    def test_cross_sheet_geometry_fails_gate(self):
        manifest = build_adaptive_manifest(
            ["GROUND", "LEVEL-01", "LEVEL-02"],
            {(family, level): 1 for family in ("SANITARY_VENT", "WATER", "HEATING", "SPLIT_AC") for level in ("GROUND", "LEVEL-01", "LEVEL-02")},
        )
        qa = validate_independent_sheet_set(manifest, 20, 1)
        self.assertEqual(qa["status"], "FAIL")
        self.assertIn("cross_sheet_geometry", qa["errors"])


if __name__ == "__main__":
    unittest.main()
