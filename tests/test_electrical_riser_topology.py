import unittest
from types import SimpleNamespace

from cad_engine.electrical_v1.distribution import build_electrical_riser
from cad_engine.electrical_v1.production import build_engine_config
from cad_engine.electrical_v1.service import build_service_feeders
import cad_engine.electrical_api as electrical_api


class ElectricalRiserTopologyTests(unittest.TestCase):
    def test_riser_reuses_radial_service_feeders_without_panel_chain(self):
        project=SimpleNamespace(levels=[SimpleNamespace(id="LVL-001"),SimpleNamespace(id="LVL-002")])
        panels=[SimpleNamespace(id="DB-LVL-001",level_id="LVL-001"),SimpleNamespace(id="DB-LVL-002",level_id="LVL-002")]
        topology={"panels":panels,"feeders":[
            {"destination":"DB-LVL-001","cable":"3x6","breaker":"C32A","route_length_m":10.0,"tag":"P1","status":"FINAL"},
            {"destination":"DB-LVL-002","cable":"3x6","breaker":"C32A","route_length_m":18.0,"tag":"P2","status":"FINAL"},
        ]}
        riser=build_electrical_riser(topology,project)
        self.assertEqual(riser["status"],"PASS")
        self.assertEqual({x["from_panel"] for x in riser["transitions"]},{"MAIN"})
        self.assertFalse(any(x["from_panel"]=="DB-LVL-001" and x["to_panel"]=="DB-LVL-002" for x in riser["transitions"]))

    def test_flat_recovery_populates_canonical_service_feeders(self):
        cfg=build_engine_config({"riser_feeder_schedule":"cable=3x6 Cu; breaker=C32A; route_length_m=18; tag=P1"},{})
        row=cfg["service_inputs"]["feeders"]["DB-LVL-001"]
        self.assertEqual(row["breaker"],"C32A")
        self.assertEqual(row["route_length_m"],18.0)

    def test_named_multiple_panel_rows_are_preserved(self):
        cfg=build_engine_config({"riser_feeder_schedule":
            "DB-LVL-001: cable=3x6 Cu; protection=C32A; route_length_m=12; tag=P1\n"
            "DB-LVL-002: cable=3x10 Cu; breaker=C40A; route_length_m=21.5; tag=P2"},{})
        feeders=cfg["service_inputs"]["feeders"]
        self.assertEqual(set(feeders),{"DB-LVL-001","DB-LVL-002"})
        self.assertEqual(feeders["DB-LVL-002"]["route_length_m"],21.5)

    def test_missing_feeders_recover_as_one_semantic_question(self):
        panel=SimpleNamespace(id="DB-LVL-001",demand_load_w=SimpleNamespace(value=None,status=None))
        topology={"panels":[panel]}
        result=build_service_feeders(topology,{"service":"s","meter":"m","main_distribution":"mdp"})
        self.assertEqual(result["missing"],["riser_feeder_schedule"])
        report={"data":{"basis":{"values":{}}},"gates":{"SINGLE_LINE":{"warnings":["service_or_feeder_input_required:riser_feeder_schedule"]}}}
        self.assertEqual(electrical_api._missing_inputs(report),["riser_feeder_schedule"])

    def test_upstream_dependency_does_not_reask_completed_feeder(self):
        project=SimpleNamespace(levels=[SimpleNamespace(id="LVL-001"),SimpleNamespace(id="LVL-002")])
        panels=[SimpleNamespace(id="DB-LVL-001",level_id="LVL-001"),SimpleNamespace(id="DB-LVL-002",level_id="LVL-002")]
        topology={"panels":panels,"feeders":[
            {"destination":"DB-LVL-001","cable":"3x6","breaker":"C32A","route_length_m":10.0,"tag":"P1","status":"INPUT_REQUIRED"},
            {"destination":"DB-LVL-002","cable":"3x6","breaker":"C32A","route_length_m":18.0,"tag":"P2","status":"INPUT_REQUIRED"},
        ]}
        riser=build_electrical_riser(topology,project)
        self.assertEqual(riser["missing"],[])
        self.assertTrue(riser["internal_dependencies"])


if __name__=="__main__":
    unittest.main()
