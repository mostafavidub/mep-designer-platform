from __future__ import annotations

import unittest
from types import SimpleNamespace

from cad_engine.electrical_v1.geometry_acceptance import finalize_placements
from cad_engine.electrical_v1.models import EngineeringStatus, EvidenceValue


class ElectricalPlacementCompletenessTests(unittest.TestCase):
    @staticmethod
    def _requirement(req_id: str, quantity: int):
        return SimpleNamespace(
            id=req_id,
            quantity=EvidenceValue.final(quantity, "explicit_user_input", 1.0),
            equipment_type="LIGHT_SWITCH",
        )

    @staticmethod
    def _architecture():
        return SimpleNamespace(units=SimpleNamespace(value="m"), entities=[])

    def test_final_requirement_with_no_created_placement_is_preliminary(self):
        req=self._requirement("REQ-SW", 1)
        project=SimpleNamespace(rooms=[])
        result=finalize_placements([], [req], project, self._architecture(), {})
        self.assertEqual(result["status"], "PRELIMINARY")
        self.assertIn("placement_count_unresolved:REQ-SW:0/1", result["warnings"])

    def test_zero_quantity_requirement_does_not_require_placement(self):
        req=self._requirement("REQ-ZERO", 0)
        project=SimpleNamespace(rooms=[])
        result=finalize_placements([], [req], project, self._architecture(), {
            "opening_clearance_m": 0.2,
            "wall_host_tolerance_m": 0.05,
        })
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(any(x.startswith("placement_count_unresolved:") for x in result["warnings"]))

    def test_excess_placement_is_hard_failure(self):
        req=self._requirement("REQ-SW", 1)
        room=SimpleNamespace(id="ROOM-1", polygon=[(0,0),(4,0),(4,4),(0,4)])
        project=SimpleNamespace(rooms=[room])
        placements=[]
        for index in (1,2):
            placements.append(SimpleNamespace(
                requirement_id="REQ-SW", room_id="ROOM-1", point=(2,2),
                equipment_id=f"EQ-{index}", host_type="ceiling", frame_id="FRAME-1",
                status=EngineeringStatus.PRELIMINARY, qa={},
            ))
        result=finalize_placements(placements, [req], project, self._architecture(), {
            "opening_clearance_m": 0.2,
            "wall_host_tolerance_m": 0.05,
            "ceiling_layout_basis_confirmed": True,
        })
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("placement_count_exceeds_requirement:REQ-SW:2/1", result["errors"])


if __name__ == "__main__":
    unittest.main()
