import unittest

from cad_engine.equipment_representation_v14 import validate_split_representation


class EquipmentRepresentationV14Tests(unittest.TestCase):
    def _unit(self, i=1):
        return {
            "tag": f"AC-{i:02d}",
            "odu_tag": f"ODU-{i:02d}",
            "level": "GROUND",
            "sheet": "M-20",
            "equipment_type": "WALL-MOUNTED SPLIT AC",
            "mode": "COOLING & HEATING",
            "capacity_status": "INPUT/LOAD_CALC_REQUIRED",
            "refrigerant_size_source": "SELECTED MANUFACTURER TABLE",
            "condensate_nominal_diameter_mm": 25,
            "condensate_min_slope_percent": 1.0,
            "block": True,
            "airflow": True,
            "callout": True,
            "refrigerant": True,
            "condensate": True,
            "odu_destination_note": True,
            "schedule_match": True,
        }

    def test_complete_split_representation_passes(self):
        result = validate_split_representation([self._unit(i) for i in range(1, 8)])
        self.assertEqual(result["status"], "PASS", result)

    def test_missing_equipment_graphic_fails(self):
        unit = self._unit()
        unit["block"] = False
        result = validate_split_representation([unit])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("AC-01:missing_block", result["errors"])

    def test_missing_schedule_traceability_fails(self):
        unit = self._unit()
        unit["schedule_match"] = False
        result = validate_split_representation([unit])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("AC-01:missing_schedule_match", result["errors"])

    def test_final_capacity_requires_provenance(self):
        unit = self._unit()
        unit["capacity_status"] = "FINAL"
        result = validate_split_representation([unit])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("AC-01:final_capacity_without_provenance", result["errors"])


if __name__ == "__main__":
    unittest.main()
