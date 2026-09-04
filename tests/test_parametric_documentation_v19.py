import unittest
from cad_engine.parametric_documentation_v19 import generate_detail, generate_riser_from_network, documentation_gate


DETAIL = {"geometry":{"type":"section","points":[[0,0],[1,0],[1,1]]},"dimensions":{"pipe_mm":50},
          "fittings":[{"type":"cleanout","size_mm":50}],"material":"uPVC","clearance":{"service_mm":450},"tag":"CO-01"}
NETWORK = {"graph_id":"G-1","nodes":[{"id":"N1","level":"L1"},{"id":"N2","level":"L2"}],
           "edges":[{"id":"SAN-001","from":"N1","to":"N2","system":"sanitary","size":"DN100","material":"uPVC","fittings":["Y45"],"levels":["L1","L2"]}]}


class ParametricDocumentationV19Tests(unittest.TestCase):
    def test_detail_contains_all_executable_fields(self):
        result = generate_detail(DETAIL)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(set(DETAIL) <= set(result["detail"]))

    def test_detail_missing_geometry_fails_closed(self):
        value = dict(DETAIL); value.pop("geometry")
        self.assertEqual(generate_detail(value)["status"], "INPUT_REQUIRED")

    def test_riser_is_direct_graph_projection_with_zero_identity_mismatch(self):
        result = generate_riser_from_network(NETWORK)
        self.assertEqual(result["status"], "PASS")
        row = result["riser"]["segments"][0]
        self.assertEqual(len({row["plan_id"],row["riser_id"],row["calc_id"],row["schedule_id"]}), 1)
        self.assertTrue(result["reconciliation"]["zero_mismatch"])

    def test_dangling_graph_and_missing_size_are_blocked(self):
        dangling = {**NETWORK,"edges":[{**NETWORK["edges"][0],"to":"MISSING"}]}
        self.assertEqual(generate_riser_from_network(dangling)["status"], "FAIL")
        incomplete = {**NETWORK,"edges":[{**NETWORK["edges"][0],"size":None}]}
        self.assertEqual(generate_riser_from_network(incomplete)["status"], "FAIL")

    def test_documentation_gate_requires_every_component(self):
        self.assertEqual(documentation_gate([generate_detail(DETAIL)], generate_riser_from_network(NETWORK))["status"], "PASS")
        self.assertEqual(documentation_gate([generate_detail({})], generate_riser_from_network(NETWORK))["status"], "FAIL")


if __name__ == "__main__": unittest.main()
