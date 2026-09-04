import unittest
from cad_engine.coordination_v19 import build_coordination_model, route_25d


def valid_project():
    return {"coordination_inputs": {
        "documents": [
            {"type": "STRUCTURAL", "revision": "S1", "sha256": "a"*64},
            {"type": "RCP", "revision": "R1", "sha256": "b"*64},
        ],
        "entities": [
            {"id":"SL1","kind":"slab","level_id":"L1","xmin":0,"ymin":0,"zmin":3.0,"xmax":10,"ymax":10,"zmax":3.2,"source_id":"S1"},
            {"id":"CL1","kind":"ceiling","level_id":"L1","xmin":0,"ymin":0,"zmin":2.5,"xmax":10,"ymax":10,"zmax":2.51,"source_id":"R1"},
            {"id":"B1","kind":"beam","level_id":"L1","xmin":4,"ymin":4,"zmin":2.4,"xmax":6,"ymax":6,"zmax":3.0,"source_id":"S1"},
            {"id":"SZ1","kind":"service_zone","level_id":"L1","xmin":0,"ymin":0,"zmin":2.2,"xmax":10,"ymax":10,"zmax":2.4,"source_id":"R1"},
        ]}}


class CoordinationV19Tests(unittest.TestCase):
    def test_missing_inputs_fail_closed_without_clash_free_claim(self):
        model = build_coordination_model({})
        self.assertEqual(model["status"], "INPUT_REQUIRED")
        result = route_25d({"level_id":"L1","start":[1,1,2.3],"end":[9,9,2.3],"allowed_elevations":[2.3]}, model)
        self.assertEqual(result["status"], "INPUT_REQUIRED")
        self.assertNotIn("CLASH_FREE", str(result))

    def test_multiple_elevations_candidates_and_zero_warning_route(self):
        model = build_coordination_model(valid_project())
        result = route_25d({"level_id":"L1","system":"water","start":[1,1,2.3],"end":[9,1,2.3],"allowed_elevations":[2.25,2.3]}, model)
        self.assertEqual(model["status"], "PASS")
        self.assertEqual(len(result["candidates"]), 4)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["qa"]["zero_warnings"])

    def test_beam_clash_and_penetration_block_selection(self):
        model = build_coordination_model(valid_project())
        result = route_25d({"level_id":"L1","system":"water","start":[1,5,2.7],"end":[9,5,2.7],"allowed_elevations":[2.7]}, model)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(c["clashes"] for c in result["candidates"]))
        self.assertTrue(result["penetration_entities"])

    def test_gravity_slope_is_fail_closed(self):
        model = build_coordination_model(valid_project())
        result = route_25d({"level_id":"L1","system":"sanitary","start":[1,1,2.3],"end":[9,1,2.3],"allowed_elevations":[2.3],"required_slope":.02}, model)
        self.assertEqual(result["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
