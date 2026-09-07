import unittest
from types import SimpleNamespace

from cad_engine.electrical_v1.distribution import build_electrical_riser
from cad_engine.electrical_v1.production import build_engine_config
import cad_engine.electrical_api as electrical_api


class ElectricalRiserTopologyTests(unittest.TestCase):
    def test_riser_reuses_radial_service_feeders_without_panel_chain(self):
        project=SimpleNamespace(levels=[SimpleNamespace(id="LVL-001"), SimpleNamespace(id="LVL-002")])
        panels=[SimpleNamespace(id="DB-LVL-001", level_id="LVL-001"), SimpleNamespace(id="DB-LVL-002", level_id="LVL-002")]
        topology={"panels":panels,"feeders":[
            {"destination":"DB-LVL-001","source":"MAIN","cable":"3x6","breaker":"C32A","route_length_m":10.0,"tag":"P1","status":"FINAL"},
            {"destination":"DB-LVL-002","source":"MAIN","cable":"3x6","breaker":"C32A","route_length_m":18.0,"tag":"P2","status":"FINAL"},
        ]}
        riser=build_electrical_riser(topology,project)
        self.assertEqual(riser["status"],"PASS")
        self.assertEqual({x["from_panel"] for x in riser["transitions"]},{"MAIN"})
        self.assertEqual({x["to_panel"] for x in riser["transitions"]},{"DB-LVL-001","DB-LVL-002"})
        self.assertFalse(any(x["from_panel"]=="DB-LVL-001" and x["to_panel"]=="DB-LVL-002" for x in riser["transitions"]))

    def test_feeder_schedule_populates_canonical_service_feeders(self):
        cfg=build_engine_config({"riser_feeder_schedule":"cable=3x6 Cu; breaker=C32A; route_length_m=18; tag=P1"},{})
        row=cfg["service_inputs"]["feeders"]["DB-LVL-001"]
        self.assertEqual(row["breaker"],"C32A")
        self.assertEqual(row["route_length_m"],18.0)

    def test_recovery_collapses_internal_feeder_ids(self):
        report={"data":{"basis":{"values":{}}},"gates":{
            "SINGLE_LINE":{"warnings":["service_or_feeder_input_required:feeder:DB-LVL-001"]},
            "RISER":{"warnings":["riser_input_required:feeder:DB-LVL-001"]},
        }}
        missing=electrical_api._missing_inputs(report)
        self.assertEqual(missing,["riser_feeder_schedule"])
        self.assertFalse(any("DB-LVL" in x for x in missing))

    def test_missing_panel_topology_is_not_exposed_as_customer_question(self):
        report={"data":{"basis":{"values":{}}},"gates":{"RISER":{"warnings":["riser_input_required:panel_topology"]}}}
        self.assertNotIn("panel_topology",electrical_api._missing_inputs(report))


if __name__=="__main__":
    unittest.main()
