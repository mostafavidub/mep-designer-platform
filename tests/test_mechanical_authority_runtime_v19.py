import unittest
from pathlib import Path
from unittest.mock import patch

from cad_engine import mechanical_authority_site_v19 as authority


class MechanicalAuthorityRuntimeV19Tests(unittest.TestCase):
    def setUp(self):
        self.pmm = {
            'schema': 'project-mechanical-model/v3',
            'traceability_contract': {'policy': 'NO_ORPHAN_ENGINEERING_OUTPUT'},
            'systems': {'wet_fixture_levels': ['L1'], 'conditioned_levels': ['L1']},
        }
        self.graph = {
            'graph_id': 'G1',
            'levels': [{'id': 'L1', 'type': 'FIRST'}],
            'nodes': [{'id': 'N1', 'level': 'L1'}, {'id': 'N2', 'level': 'L1'}],
            'edges': [{
                'id': 'E1', 'from': 'N1', 'to': 'N2', 'system': 'cold_water',
                'calc_id': 'CALC-1', 'plan_id': 'CALC-1', 'riser_id': 'CALC-1',
                'schedule_id': 'CALC-1', 'size': 'DN20', 'material': 'PPR',
                'levels': ['L1'],
            }],
        }
        self.rows = [{'calc_id': 'CALC-1'}]
        self.runtime = authority.active_version_manifest()

    def answers(self, **contract):
        return {'_runtime_contract': self.runtime, '_v19_input_contract': contract}

    def passing_pipeline(self):
        return {
            'status': 'PASS',
            'blocked_at': None,
            'phases': {
                'documentation': {
                    'status': 'PASS',
                    'pmm_traceability_required': True,
                    'calculation_reconciliation': {'status': 'PASS', 'zero_mismatch': True},
                }
            },
            'submission': {'status': 'PASS', 'release_allowed': True, 'submission_ready': True},
        }

    def test_payload_carries_pmm_calculations_graph_and_active_systems_from_plan_analysis(self):
        payload = authority._v19_payload({}, {
            'project_mechanical_model': self.pmm,
            'calculation_rows_v19': self.rows,
            'network_graph_v19': self.graph,
        })
        self.assertEqual(payload['project_mechanical_model']['schema'], 'project-mechanical-model/v3')
        self.assertEqual(payload['calculation_rows'], self.rows)
        self.assertEqual(payload['network_graph'], self.graph)
        self.assertTrue(payload['active_systems']['cold_water'])
        self.assertTrue(payload['active_systems']['cooling'])

    @patch.object(authority, 'build_authoritative_topology')
    @patch.object(authority, '_design_v17')
    @patch.object(authority, 'run_v19_pipeline')
    def test_missing_authority_inputs_block_renderer(self, pipeline, renderer, topology):
        topology.return_value = {'status': 'INPUT_REQUIRED', 'missing_inputs': ['PROJECT_MECHANICAL_MODEL_V3']}
        result = authority.design_mechanical_authority_site(Path('in.dxf'), Path('out.dxf'),
                                                             answers=self.answers(), plan_analysis={})
        self.assertEqual(result['stage'], 'v19_network_authority_gate')
        self.assertEqual(result['input_required']['status'], 'INPUT_REQUIRED')
        self.assertIn('PROJECT_MECHANICAL_MODEL_V3', result['input_required']['missing_inputs'])
        pipeline.assert_not_called()
        renderer.assert_not_called()

    @patch.object(authority, '_design_v17')
    @patch.object(authority, 'run_v19_pipeline')
    def test_v19_failure_blocks_renderer(self, pipeline, renderer):
        pipeline.return_value = {
            'status': 'INPUT_REQUIRED', 'blocked_at': 'coordination',
            'phases': {'coordination': {'model': {'missing_inputs': ['STRUCTURAL_MODEL']}}},
            'submission': {'status': 'FAIL', 'release_allowed': False},
        }
        result = authority.design_mechanical_authority_site(
            Path('in.dxf'), Path('out.dxf'),
            answers=self.answers(project_mechanical_model=self.pmm, calculation_rows=self.rows,
                                 network_graph=self.graph), plan_analysis={})
        self.assertEqual(result['stage'], 'v19_authority_release_gate')
        self.assertIn('STRUCTURAL_MODEL', result['input_required']['missing_inputs'])
        renderer.assert_not_called()

    @patch.object(authority, '_design_v17')
    @patch.object(authority, 'run_v19_pipeline')
    def test_reconciliation_not_pass_blocks_renderer(self, pipeline, renderer):
        failed = self.passing_pipeline()
        failed['phases']['documentation']['calculation_reconciliation'] = {'status': 'FAIL', 'zero_mismatch': False}
        pipeline.return_value = failed
        result = authority.design_mechanical_authority_site(
            Path('in.dxf'), Path('out.dxf'),
            answers=self.answers(project_mechanical_model=self.pmm, calculation_rows=self.rows,
                                 network_graph=self.graph), plan_analysis={})
        self.assertEqual(result['stage'], 'v19_authority_release_gate')
        self.assertIn('CALCULATION_OUTPUT_RECONCILIATION_NOT_PASS', result['input_required']['missing_inputs'])
        renderer.assert_not_called()

    @patch.object(authority, 'materialize_authoritative_network')
    @patch.object(authority, '_design_v17')
    @patch.object(authority, 'run_v19_pipeline')
    def test_v17_is_shell_and_v19_network_materializer_runs_after_authority_pass(self, pipeline, renderer, materializer):
        pipeline.return_value = self.passing_pipeline()
        renderer.return_value = {'status': 'PASS', 'composition': {}}
        materializer.return_value = {'status': 'PASS', 'materialized_segments': 1, 'exact_file_reopened': True}
        result = authority.design_mechanical_authority_site(
            Path('in.dxf'), Path('out.dxf'),
            answers=self.answers(project_mechanical_model=self.pmm, calculation_rows=self.rows,
                                 network_graph=self.graph), plan_analysis={})
        renderer.assert_called_once()
        materializer.assert_called_once()
        self.assertEqual(result['engineering_authority'], 'PMM_V3_V19')
        self.assertEqual(result['pipeline_authority'], 'mechanical-v19')
        self.assertEqual(result['cad_materializer'], 'legacy-v17-shell+graph-native-v19-network')
        self.assertEqual(result['legacy_renderer_role'], 'CAD_SHELL_ONLY')
        self.assertEqual(result['submission_state'], 'SUBMISSION_READY')
        self.assertTrue(result['v19_traceability_preflight']['zero_mismatch'])
        self.assertTrue(result['v19_materialization_qa']['exact_file_reopened'])

    @patch.object(authority, 'materialize_authoritative_network')
    @patch.object(authority, '_design_v17')
    @patch.object(authority, 'run_v19_pipeline')
    def test_materialization_failure_blocks_submission(self, pipeline, renderer, materializer):
        pipeline.return_value = self.passing_pipeline()
        renderer.return_value = {'status': 'PASS', 'composition': {}}
        materializer.return_value = {'status': 'FAIL', 'errors': ['SEGMENT_DUPLICATED']}
        result = authority.design_mechanical_authority_site(
            Path('in.dxf'), Path('out.dxf'),
            answers=self.answers(project_mechanical_model=self.pmm, calculation_rows=self.rows,
                                 network_graph=self.graph), plan_analysis={})
        self.assertEqual(result['stage'], 'v19_network_materialization_gate')
        self.assertEqual(result['input_required']['status'], 'FAIL')
        self.assertIn('SEGMENT_DUPLICATED', result['input_required']['missing_inputs'])

    @patch.object(authority, '_design_v17')
    @patch.object(authority, 'run_v19_pipeline')
    def test_runtime_contract_mismatch_blocks_everything(self, pipeline, renderer):
        result = authority.design_mechanical_authority_site(
            Path('in.dxf'), Path('out.dxf'), answers={'_runtime_contract': {}}, plan_analysis={})
        self.assertEqual(result['stage'], 'v19_runtime_contract_gate')
        pipeline.assert_not_called()
        renderer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
