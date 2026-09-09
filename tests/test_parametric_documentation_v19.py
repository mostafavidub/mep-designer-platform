import unittest
from cad_engine.parametric_documentation_v19 import (
    generate_detail, generate_riser_from_network, documentation_gate,
    reconcile_calculation_outputs, required_detail_families,
    validate_detail_family_coverage, generate_annotation_support, generate_final_parametric_detail,
)


DETAIL = {"geometry":{"type":"section","points":[[0,0],[1,0],[1,1]]},"dimensions":{"pipe_mm":50},
          "fittings":[{"type":"cleanout","size_mm":50}],"material":"uPVC","clearance":{"service_mm":450},"tag":"CO-01"}
NETWORK = {"graph_id":"G-1","nodes":[{"id":"N1","level":"L1"},{"id":"N2","level":"L2"}],
           "edges":[{"id":"SAN-001","calc_id":"CALC-ABC","from":"N1","to":"N2","system":"sanitary","size":"DN100","material":"uPVC","fittings":["Y45"],"levels":["L1","L2"]}]}


class ParametricDocumentationV19Tests(unittest.TestCase):
    def test_detail_contains_all_executable_fields(self):
        result = generate_detail(DETAIL)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(set(DETAIL) <= set(result["detail"]))

    def test_detail_missing_geometry_fails_closed(self):
        value = dict(DETAIL); value.pop("geometry")
        self.assertEqual(generate_detail(value)["status"], "INPUT_REQUIRED")

    def test_radiator_final_detail_is_executable_and_manufacturer_locked(self):
        manufacturer={'catalogue_id':'MFR-X','manufacturer':'Official','model':'R500',
                      'dimensions_mm':{'width':1200,'height':500,'depth':90},
                      'official_document':{'revision':'1','sha256':'a'*64}}
        spec={'family':'radiator_connection','source_plan_id':'M-131','source_pmm_id':'RAD-L1-03',
              'source_calc_id':'CALC-HT-3','manufacturer_record':manufacturer,'parameters':{
                'dimensions_mm':manufacturer['dimensions_mm'],'installation_height_mm':120,'trv':{'dn_mm':15},
                'lockshield':{'dn_mm':15},'flow_connection':{'side':'left'},'return_connection':{'side':'right'},
                'pipe_dn_mm':16,'wall_clearance_mm':50,'sleeve':{'required':True}}}
        result=generate_final_parametric_detail(spec)
        self.assertEqual(result['status'],'PASS',result)
        self.assertFalse(result['qa']['label_only'])
        self.assertEqual(result['detail']['identity']['source_pmm_id'],'RAD-L1-03')
        self.assertEqual(result['detail']['geometry']['envelope_mm'],manufacturer['dimensions_mm'])
        bad={**spec,'parameters':{**spec['parameters'],'dimensions_mm':{'width':999}}}
        self.assertEqual(generate_final_parametric_detail(bad)['status'],'FAIL')

    def test_odu_and_sanitary_details_require_every_installation_component(self):
        manufacturer={'catalogue_id':'MFR-ODU','manufacturer':'Official','model':'O30',
                      'dimensions_mm':{'width':900,'height':700,'depth':350},
                      'official_document':{'revision':'1','sha256':'b'*64}}
        odu={'family':'odu_installation','source_plan_id':'M-162','source_pmm_id':'ODU-G-1','source_calc_id':'CALC-CL-1',
             'manufacturer_record':manufacturer,'parameters':{'dimensions_mm':manufacturer['dimensions_mm'],
             'service_clearance_mm':{'front':1000},'base':{'height_mm':150},'vibration_isolator':{'type':'neoprene'},
             'anchors':{'count':4},'power_isolator':{'rating_a':20},'refrigerant_connections':{'liquid_mm':6.35,'gas_mm':12.7},
             'drain':{'dn_mm':25}}}
        self.assertEqual(generate_final_parametric_detail(odu)['status'],'PASS')
        sanitary={'family':'sanitary_connection','source_plan_id':'M-101','source_pmm_id':'WC-L1-1',
                   'source_calc_id':'CALC-SAN-1','parameters':{'pipe_dn_mm':110,'trap':{'seal_mm':50},
                   'vent':{'dn_mm':50},'cleanout':{'access_mm':450},'sleeve':{'dn_mm':150},
                   'waterproofing':{'system':'project_spec'},'firestop':{'rating':'project_spec'}}}
        self.assertEqual(generate_final_parametric_detail(sanitary)['status'],'PASS')
        del sanitary['parameters']['firestop']
        self.assertEqual(generate_final_parametric_detail(sanitary)['status'],'INPUT_REQUIRED')

    def test_riser_is_direct_graph_projection_with_zero_identity_mismatch(self):
        result = generate_riser_from_network(NETWORK)
        self.assertEqual(result["status"], "PASS")
        row = result["riser"]["segments"][0]
        self.assertEqual(row["calc_id"], "CALC-ABC")
        self.assertEqual(len({row["plan_id"],row["riser_id"],row["calc_id"],row["schedule_id"]}), 1)
        self.assertTrue(result["reconciliation"]["zero_mismatch"])

    def test_dangling_graph_and_missing_size_are_blocked(self):
        dangling = {**NETWORK,"edges":[{**NETWORK["edges"][0],"to":"MISSING"}]}
        self.assertEqual(generate_riser_from_network(dangling)["status"], "FAIL")
        incomplete = {**NETWORK,"edges":[{**NETWORK["edges"][0],"size":None}]}
        self.assertEqual(generate_riser_from_network(incomplete)["status"], "FAIL")

    def test_explicit_cross_output_identity_mismatch_is_not_overwritten(self):
        bad = {**NETWORK,"edges":[{**NETWORK["edges"][0],"plan_id":"PLAN-OTHER"}]}
        result = generate_riser_from_network(bad)
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["reconciliation"]["zero_mismatch"])

    def test_detail_levels_can_never_contaminate_riser_topology(self):
        contaminated={**NETWORK,"nodes":NETWORK['nodes']+[{"id":"D1","level":"DETAIL-1"}],
                      "edges":NETWORK['edges']+[{**NETWORK['edges'][0],"id":"E-D","from":"N2","to":"D1",
                                                   "levels":["L2","DETAIL-1"]}]}
        result=generate_riser_from_network(contaminated)
        self.assertEqual(result['status'],'FAIL')
        self.assertIn('DETAIL-1',result['errors'][0])

    def test_typed_level_registry_rejects_detail_and_plan_change_updates_riser_hash(self):
        typed={**NETWORK,"levels":[{"id":"L1","type":"GROUND"},{"id":"L2","type":"FIRST"}]}
        first=generate_riser_from_network(typed)
        self.assertEqual(first['status'],'PASS')
        changed={**typed,"edges":[{**typed['edges'][0],"size":"DN125"}]}
        second=generate_riser_from_network(changed)
        self.assertNotEqual(first['riser']['source_plan_graph_hash'],second['riser']['source_plan_graph_hash'])
        invalid={**typed,"levels":typed['levels']+[{"id":"DETAIL-2","type":"DETAIL"}]}
        self.assertEqual(generate_riser_from_network(invalid)['status'],'FAIL')

    def test_mandatory_families_fail_closed_without_invented_detail_inputs(self):
        required = required_detail_families({"sanitary":True,"cooling":True})
        self.assertIn("sanitary_riser", required)
        self.assertIn("split_connection", required)
        detail = generate_detail({**DETAIL,"family":"cleanout"})
        coverage = validate_detail_family_coverage([detail], required)
        self.assertEqual(coverage["status"], "INPUT_REQUIRED")
        self.assertIn("DETAIL_FAMILY:split_connection", coverage["missing_inputs"])

    def test_annotation_and_enlarged_plan_support_is_identity_bound(self):
        ok = generate_annotation_support(NETWORK,[{"network_edge_id":"SAN-001","label":"DN100"}],
                                         [{"id":"ENL-1","source_plan_id":"PLAN-L1","bounds":[0,0,2,2],"scale":"1:20"}])
        self.assertEqual(ok["status"], "PASS")
        missing = generate_annotation_support(NETWORK,[],[])
        self.assertEqual(missing["status"], "INPUT_REQUIRED")
        invalid = generate_annotation_support(NETWORK,[{"network_edge_id":"UNKNOWN"}],
                                              [{"id":"ENL-X","scale":"1:20"}])
        self.assertEqual(invalid["status"], "FAIL")

    def test_calculation_output_reconciliation_passes_only_for_exact_identity_set(self):
        riser = generate_riser_from_network(NETWORK)
        self.assertEqual(reconcile_calculation_outputs([{"calc_id":"CALC-ABC"}], riser)["status"], "PASS")
        bad = reconcile_calculation_outputs([{"calc_id":"CALC-OTHER"}], riser)
        self.assertEqual(bad["status"], "FAIL")
        self.assertIn("CALC-OTHER", bad["orphaned_calc_ids"])
        self.assertIn("CALC-ABC", bad["unknown_output_calc_ids"])

    def test_documentation_gate_requires_every_component_and_calc_reconciliation(self):
        riser = generate_riser_from_network(NETWORK)
        self.assertEqual(documentation_gate([generate_detail(DETAIL)], riser, [{"calc_id":"CALC-ABC"}])["status"], "PASS")
        self.assertEqual(documentation_gate([generate_detail({})], riser)["status"], "FAIL")
        self.assertEqual(documentation_gate([generate_detail(DETAIL)], riser, [{"calc_id":"CALC-X"}])["status"], "FAIL")


if __name__ == "__main__": unittest.main()
