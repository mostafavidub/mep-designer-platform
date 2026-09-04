import unittest
from cad_engine.mechanical_pipeline_v19 import run_v19_pipeline
from cad_engine.mechanical_release_contract_v19 import release_contract_status


def payload():
    return {"coordination_inputs":{"documents":[{"type":"STRUCTURAL","revision":"S1","sha256":"a"*64},{"type":"RCP","revision":"R1","sha256":"b"*64}],
            "entities":[{"id":"SL","kind":"slab","level_id":"L1","xmin":0,"ymin":0,"zmin":3,"xmax":10,"ymax":10,"zmax":3.2,"source_id":"S1"},{"id":"CL","kind":"ceiling","level_id":"L1","xmin":0,"ymin":0,"zmin":2.5,"xmax":10,"ymax":10,"zmax":2.51,"source_id":"R1"}]},
            "route_request":{"level_id":"L1","system":"water","start":[1,1,2.3],"end":[9,1,2.3],"allowed_elevations":[2.3]},
            "equipment_requirements":{"design_capacity_kw":10},
            "manufacturer_catalogue":[{"manufacturer":"Official","model":"X12","equipment_type":"split","capacity_kw":12,"dimensions_mm":{"w":900,"d":350,"h":700},"connections":{"liquid_mm":9.52},"clearance_mm":{"front":1000},"max_pipe_length_m":30,"max_elevation_m":15,"pump":{},"fan":{},"datasheet":{"official_url":"https://official.example/x12.pdf","revision":"1","sha256":"c"*64}}],
            "detail_specs":[{"geometry":{"type":"section","points":[[0,0],[1,1]]},"dimensions":{"pipe_mm":50},"fittings":["union"],"material":"PPR","clearance":{"service_mm":300},"tag":"DT-1"}],
            "network_graph":{"graph_id":"G","nodes":[{"id":"N1"},{"id":"N2"}],"edges":[{"id":"W-1","from":"N1","to":"N2","system":"water","size":"DN25","material":"PPR"}]},
            "golden_result":{"status":"PASS"}}


class MechanicalPipelineV19Tests(unittest.TestCase):
    def test_contract_loads_every_capability(self):
        status=release_contract_status(); self.assertEqual(status["status"],"PASS"); self.assertEqual(status["required_count"],status["passed_count"])

    def test_full_pipeline_passes_only_in_order(self):
        result=run_v19_pipeline(payload()); self.assertEqual(result["status"],"PASS"); self.assertTrue(result["submission"]["release_allowed"])

    def test_missing_structural_rcp_stops_before_manufacturer(self):
        value=payload(); value.pop("coordination_inputs")
        result=run_v19_pipeline(value); self.assertEqual(result["blocked_at"],"coordination"); self.assertNotIn("manufacturer",result["phases"])

    def test_envelope_stops_before_documentation(self):
        value=payload(); value["manufacturer_catalogue"]=[]
        result=run_v19_pipeline(value); self.assertEqual(result["blocked_at"],"manufacturer"); self.assertNotIn("documentation",result["phases"])

    def test_missing_golden_blocks_release(self):
        value=payload(); value.pop("golden_result")
        result=run_v19_pipeline(value); self.assertEqual(result["status"],"FAIL"); self.assertFalse(result["submission"]["release_allowed"])


if __name__ == "__main__": unittest.main()
