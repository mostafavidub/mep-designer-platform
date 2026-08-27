import unittest

from cad_engine.mechanical_engineering_v13 import reconstruct_architecture


class MechanicalEngineeringV13Step1Tests(unittest.TestCase):
    def test_reconstructs_rooms_and_nearest_shaft_without_inventing_geometry(self):
        analysis = {
            "levels": [{"name": "Ground", "elevation": 0}, {"name": "First", "elevation": 3200}],
            "shafts": [{"id": "S1", "level": "Ground", "point": [900, 900]}],
            "rooms": [
                {"id": "BATH-01", "level": "Ground", "type": "bathroom", "polygon": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]]},
                {"id": "BED-01", "level": "First", "type": "bedroom", "polygon": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]},
            ],
            "walls": [{"id": "W1"}], "doors": [{"id": "D1"}], "columns": [{"id": "C1"}],
        }
        model = reconstruct_architecture(analysis)
        self.assertTrue(model["evidence_complete"])
        self.assertEqual([x["name"] for x in model["levels"]], ["Ground", "First"])
        self.assertEqual(model["rooms"][0]["nearest_shaft"], "S1")
        self.assertIsNone(model["rooms"][1]["nearest_shaft"])
        self.assertEqual(model["walls"], [{"id": "W1"}])
        self.assertEqual(model["columns"], [{"id": "C1"}])

    def test_missing_room_evidence_fails_closed(self):
        model = reconstruct_architecture({"levels": ["Ground"]})
        self.assertFalse(model["evidence_complete"])
        self.assertIn("architecture_model_missing_levels_or_rooms", model["diagnostics"])


if __name__ == "__main__":
    unittest.main()
