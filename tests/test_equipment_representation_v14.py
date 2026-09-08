import unittest

from cad_engine.equipment_representation_v14 import validate_equipment_integrity, validate_split_representation


class EquipmentRepresentationV14Tests(unittest.TestCase):
    def _unit(self, i=1):
        return {
            "tag": f"AC-{i:02d}", "odu_tag": f"ODU-{i:02d}", "level": "GROUND", "sheet": "M-20",
            "equipment_type": "WALL-MOUNTED SPLIT AC", "mode": "COOLING & HEATING",
            "capacity_status": "INPUT/LOAD_CALC_REQUIRED", "refrigerant_size_source": "SELECTED MANUFACTURER TABLE",
            "condensate_nominal_diameter_mm": 25, "condensate_min_slope_percent": 1.0,
            "block": True, "airflow": True, "callout": True, "refrigerant": True, "condensate": True,
            "odu_destination_note": True, "schedule_match": True,
        }

    def test_complete_split_representation_passes(self):
        result = validate_split_representation([self._unit(i) for i in range(1, 8)])
        self.assertEqual(result["status"], "PASS", result)

    def test_missing_equipment_graphic_fails(self):
        unit = self._unit(); unit["block"] = False
        result = validate_split_representation([unit])
        self.assertEqual(result["status"], "FAIL"); self.assertIn("AC-01:missing_block", result["errors"])

    def test_missing_schedule_traceability_fails(self):
        unit = self._unit(); unit["schedule_match"] = False
        result = validate_split_representation([unit])
        self.assertEqual(result["status"], "FAIL"); self.assertIn("AC-01:missing_schedule_match", result["errors"])

    def test_final_capacity_requires_provenance(self):
        unit = self._unit(); unit["capacity_status"] = "FINAL"
        result = validate_split_representation([unit])
        self.assertEqual(result["status"], "FAIL"); self.assertIn("AC-01:final_capacity_without_provenance", result["errors"])

    def test_schedule_odu_tag_cannot_replace_real_outdoor_entity(self):
        entities=[{"id":"AC-01","kind":"split_indoor","plan_id":"P1","point":[2,2]}]
        result=validate_split_representation([self._unit()],entities)
        self.assertEqual(result["status"],"FAIL")
        self.assertIn("AC-01:odu_tag_without_plan_outdoor_entity",result["errors"])

    def test_real_indoor_and_outdoor_entities_match_schedule(self):
        entities=[{"id":"AC-01","kind":"split_indoor","plan_id":"P1","point":[2,2]},
                  {"id":"ODU-01","kind":"split_outdoor","plan_id":"P1","point":[8,8]}]
        result=validate_split_representation([self._unit()],entities)
        self.assertEqual(result["status"],"PASS",result)

    def test_same_source_severe_coordinate_collapse_fails(self):
        rows=[{"id":f"ODU-{i}","kind":"split_outdoor","point":[4,4],"source_file":"a.dxf","level_authority_id":"L1"} for i in range(4)]
        result=validate_equipment_integrity(rows,require_split_pairs=False)
        self.assertEqual(result["status"],"FAIL")
        self.assertEqual(result["metrics"]["collapsed_groups"],1)

    def test_equal_coordinates_in_different_sources_are_independent(self):
        rows=[{"id":f"ODU-{i}","kind":"split_outdoor","point":[4,4],"source_file":f"source-{i}.dxf","level_authority_id":"L1"} for i in range(4)]
        result=validate_equipment_integrity(rows,require_split_pairs=False)
        self.assertEqual(result["status"],"PASS",result)
        self.assertEqual(result["metrics"]["collapsed_groups"],0)

    def test_generated_split_requires_explicit_outdoor_pair(self):
        rows=[{"id":"AC-I-01","kind":"split_indoor","plan_id":"P1","point":[2,2]},
              {"id":"AC-O-01","kind":"split_outdoor","plan_id":"P1","point":[8,8]}]
        result=validate_equipment_integrity(rows,require_split_pairs=True)
        self.assertEqual(result["status"],"INPUT_REQUIRED")
        self.assertIn("split_pair_missing:AC-I-01",result["missing_inputs"])

    def test_nonfinite_equipment_point_is_input_required(self):
        result=validate_equipment_integrity([{"id":"ODU-1","kind":"split_outdoor","point":[float('nan'),2]}],require_split_pairs=False)
        self.assertEqual(result["status"],"INPUT_REQUIRED")
        self.assertIn("invalid_equipment_point:ODU-1",result["missing_inputs"])


if __name__ == "__main__": unittest.main()
