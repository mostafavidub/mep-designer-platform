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
            "submission_checks":{
                "route_warnings":0,"structural_clashes":0,"mep_clashes":0,
                "unapproved_penetrations":0,"gravity_violations":0,
                "equipment_without_manufacturer_basis":0,"manufacturer_limit_violations":0,
                "missing_details":0,"plan_riser_schedule_mismatches":0,"unreadable_annotations":0},
            "engineer_review":{"reviewer_id":"ENG-INDEPENDENT-1","review_evidence_sha256":"d"*64,"redlines":[]},
            "quality_metrics":{"structural_mep_clashes":0,"routing_warnings":0,
                "unapproved_penetrations":0,"manufacturer_violations":0,"missing_required_details":0,
                "plan_riser_schedule_mismatches":0,"route_efficiency_percent":90,
                "equipment_placement_score":90,"detail_completeness_percent":95,
                "package_average_score":90,"main_plan_scores":{"M-101":85}},
            "golden_result":{"status":"PASS"}}


def pmm_v3():
    return {"schema":"project-mechanical-model/v3","traceability_contract":{"policy":"NO_ORPHAN_ENGINEERING_OUTPUT"}}


class MechanicalPipelineV19Tests(unittest.TestCase):
    def test_contract_loads_every_capability(self):
        status=release_contract_status(); self.assertEqual(status["status"],"PASS"); self.assertEqual(status["required_count"],status["passed_count"])

    def test_full_pipeline_passes_only_in_order(self):
        result=run_v19_pipeline(payload()); self.assertEqual(result["status"],"PASS"); self.assertTrue(result["submission"]["release_allowed"])

    def test_pmm_v3_requires_calculation_rows_and_exact_output_identity(self):
        value=payload(); value["project_mechanical_model"]=pmm_v3()
        result=run_v19_pipeline(value)
        self.assertEqual(result["blocked_at"],"documentation")
        self.assertEqual(result["status"],"FAIL")
        value["network_graph"]["edges"][0]["calc_id"]="CALC-WATER-1"
        value["calculation_rows"]=[{"calc_id":"CALC-WATER-1"}]
        result=run_v19_pipeline(value)
        self.assertEqual(result["status"],"PASS")
        self.assertTrue(result["phases"]["documentation"]["calculation_reconciliation"]["zero_mismatch"])

    def test_pmm_v3_orphan_calculation_blocks_release(self):
        value=payload(); value["project_mechanical_model"]=pmm_v3()
        value["network_graph"]["edges"][0]["calc_id"]="CALC-WATER-1"
        value["calculation_rows"]=[{"calc_id":"CALC-OTHER"}]
        result=run_v19_pipeline(value)
        self.assertEqual(result["blocked_at"],"documentation")
        self.assertFalse(result["submission"]["release_allowed"])

    def test_missing_structural_rcp_stops_before_manufacturer(self):
        value=payload(); value.pop("coordination_inputs")
        result=run_v19_pipeline(value); self.assertEqual(result["blocked_at"],"coordination"); self.assertNotIn("manufacturer",result["phases"])

    def test_envelope_stops_before_documentation(self):
        value=payload(); value["manufacturer_catalogue"]=[]
        result=run_v19_pipeline(value); self.assertEqual(result["blocked_at"],"manufacturer"); self.assertNotIn("documentation",result["phases"])

    def test_requested_manufacturer_database_must_be_complete_before_coordination(self):
        value=payload(); value['manufacturer_database_records']=[]
        result=run_v19_pipeline(value)
        self.assertEqual(result['blocked_at'],'manufacturer_database')
        self.assertEqual(result['status'],'INPUT_REQUIRED')
        self.assertNotIn('coordination',result['phases'])

    def test_missing_golden_blocks_release(self):
        value=payload(); value.pop("golden_result")
        result=run_v19_pipeline(value); self.assertEqual(result["status"],"FAIL"); self.assertFalse(result["submission"]["release_allowed"])

    def test_missing_or_nonzero_submission_evidence_blocks_release(self):
        value=payload(); value.pop("submission_checks")
        result=run_v19_pipeline(value)
        self.assertEqual(result["blocked_at"],"submission_quality")
        self.assertEqual(result["status"],"INPUT_REQUIRED")
        value=payload(); value["submission_checks"]["mep_clashes"]=1
        result=run_v19_pipeline(value)
        self.assertEqual(result["blocked_at"],"submission_quality")
        self.assertEqual(result["status"],"FAIL")

    def test_engineer_feedback_and_quality_targets_block_in_order(self):
        value=payload(); value.pop("engineer_review")
        result=run_v19_pipeline(value)
        self.assertEqual(result["blocked_at"],"engineer_feedback")
        self.assertEqual(result["status"],"INPUT_REQUIRED")
        value=payload(); value["quality_metrics"]["detail_completeness_percent"]=94
        result=run_v19_pipeline(value)
        self.assertEqual(result["blocked_at"],"quality_targets")
        self.assertEqual(result["status"],"FAIL")

    def test_active_system_requires_mandatory_detail_family_coverage(self):
        value=payload(); value["active_systems"]={"sanitary":True}
        result=run_v19_pipeline(value)
        self.assertEqual(result["status"],"INPUT_REQUIRED")
        self.assertEqual(result["blocked_at"],"documentation")
        self.assertIn("DETAIL_FAMILY:sanitary_riser", result["phases"]["documentation"]["errors"])

    def test_annotation_support_blocks_unidentified_network_output(self):
        value=payload(); value["annotations"]=[]; value["enlarged_plans"]=[]
        result=run_v19_pipeline(value)
        self.assertEqual(result["status"],"INPUT_REQUIRED")
        self.assertIn("ANNOTATION:W-1", result["phases"]["documentation"]["errors"])

    def test_requested_calculation_book_blocks_unverified_equipment(self):
        value=payload(); value['equipment_selection_checks']=[]; value['declared_equipment_ids']=['IDU-1']
        result=run_v19_pipeline(value)
        self.assertEqual(result['blocked_at'],'calculation_book')
        self.assertEqual(result['status'],'INPUT_REQUIRED')

    def test_annotation_solver_failure_blocks_before_documentation(self):
        value=payload(); value['annotation_solver']={'plan':{'plan_id':'P','bounds':[0,0,10,10],'print_scale':10,
          'obstacles':[[0,0,10,10]]},'requests':[{'id':'A','text':'DN25','target':[5,5],'priority':1,'source_id':'W-1'}],
          'config':{'minimum_text_height_mm':2.5,'clearance_model_units':1,'candidate_offsets':[[0,0]],
                    'auto_enlarge':False,'enlarged_scale':'1:20'}}
        result=run_v19_pipeline(value)
        self.assertEqual(result['blocked_at'],'annotation_solver')
        self.assertEqual(result['status'],'FAIL')


if __name__ == "__main__": unittest.main()
