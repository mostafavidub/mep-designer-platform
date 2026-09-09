import unittest

from cad_engine.engineering_runner_v13 import _add_locked_design_endpoints
from cad_engine.routing_endpoints import propose_connection_point
from cad_engine.routing_v13 import route_topology


def _key(point):
    return round(float(point[0]), 6), round(float(point[1]), 6)


class RoutingEndpointProposalTests(unittest.TestCase):
    def test_semantic_room_without_boundary_gets_distinct_proposed_not_detected_points(self):
        architecture = {
            "plans": [{"plan_id": "P1", "bounds": (0.0, 0.0, 100.0, 100.0)}],
            "rooms": [{"id": "R1", "plan_id": "P1", "type": "bathroom", "label_point": (50.0, 50.0)}],
        }
        recognition = {"detections": [], "fixtures": [], "equipment": [], "quality": {}}
        result = _add_locked_design_endpoints(architecture, recognition, {})
        rows = [row for row in result["detections"] if row.get("room_id") == "R1"]
        self.assertEqual({row["type"] for row in rows}, {"wc", "basin", "shower", "floor_drain", "exhaust_fan"})
        self.assertEqual(len({_key(row["point"]) for row in rows}), len(rows))
        self.assertTrue(all(row["status"] == "designed" and row["installed"] is False for row in rows))
        self.assertTrue(all(row["location_authority"] == "PROPOSED_NOT_SOURCE_DETECTED" for row in rows))
        self.assertTrue(all(row["requires_fixture_coordination"] is True for row in rows))
        self.assertTrue(all(row["room_boundary_known"] is False for row in rows))
        self.assertEqual(result["quality"]["proposed_endpoints_without_room_boundary"], len(rows))

    def test_polygon_backed_proposals_stay_inside_reconstructed_room(self):
        room = {
            "id": "R1",
            "plan_id": "P1",
            "type": "bathroom",
            "label_point": (50.0, 50.0),
            "polygon": [(40.0, 40.0), (60.0, 40.0), (60.0, 60.0), (40.0, 60.0)],
        }
        occupied = []
        proposals = []
        for ordinal in range(5):
            row = propose_connection_point(room, (0.0, 0.0, 100.0, 100.0), ordinal, occupied)
            self.assertIsNotNone(row)
            proposals.append(row)
            occupied.append(row["point"])
        self.assertEqual(len({_key(row["point"]) for row in proposals}), 5)
        self.assertTrue(all(40.0 < row["point"][0] < 60.0 and 40.0 < row["point"][1] < 60.0 for row in proposals))
        self.assertTrue(all(row["room_boundary_known"] is True for row in proposals))
        self.assertTrue(all(row["placement_basis"] == "RECONSTRUCTED_ROOM_POLYGON_PROPOSAL" for row in proposals))


class RoutingDeoverlapTests(unittest.TestCase):
    def _architecture(self):
        return {"plans": [{"plan_id": "P1", "bounds": (0.0, 0.0, 100.0, 100.0)}], "walls": []}

    def _topology(self, systems):
        nodes = [
            {"id": "F1", "plan_id": "P1", "category": "fixture", "point": (20.0, 20.0)},
            {"id": "S1", "plan_id": "P1", "category": "vertical", "point": (80.0, 80.0)},
        ]
        edges = [
            {"id": f"E{index}", "system": system, "from": "F1", "to": "S1", "plan_id": "P1"}
            for index, system in enumerate(systems, 1)
        ]
        return {"nodes": nodes, "edges": edges}

    def test_hot_and_cold_use_equal_safety_alternate_paths_instead_of_exact_overlay(self):
        result = route_topology(self._architecture(), self._topology(["cold_water", "hot_water"]))
        self.assertEqual(result["rejected"], [])
        self.assertEqual(len(result["routes"]), 2)
        self.assertNotEqual(_key(result["routes"][0]["points"][1]), _key(result["routes"][1]["points"][1]))
        self.assertEqual(result["quality"]["deoverlap_reroutes"], 1)
        self.assertEqual(result["routes"][1]["route_choice"], "deoverlap_equal_safety_alternative")

    def test_sanitary_and_vent_do_not_exactly_overlay(self):
        result = route_topology(self._architecture(), self._topology(["sanitary", "vent"]))
        self.assertEqual(result["rejected"], [])
        keys = [tuple(_key(point) for point in route["points"]) for route in result["routes"]]
        self.assertEqual(len(set(keys)), 2)
        self.assertEqual(result["quality"]["deoverlap_reroutes"], 1)

    def test_unavoidable_third_same_system_duplicate_fails_closed(self):
        result = route_topology(self._architecture(), self._topology(["cold_water", "cold_water", "cold_water"]))
        self.assertEqual(len(result["routes"]), 2)
        self.assertEqual(len(result["rejected"]), 1)
        self.assertEqual(result["rejected"][0]["reason"], "EXACT_OVERLAY_NO_EQUAL_SAFETY_ALTERNATIVE")
        self.assertEqual(result["quality"]["exact_overlay_rejections"], 1)


if __name__ == "__main__":
    unittest.main()
