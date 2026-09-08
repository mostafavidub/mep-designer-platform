import inspect
import unittest

from app import dxf_output


class _Response:
    status_code = 422

    def json(self):
        return {
            'detail': (
                'Authority-ready mechanical generation blocked: unresolved engineering inputs: '
                'water inlet pressure'
            )
        }


class MechanicalErrorSurfaceTests(unittest.TestCase):
    def test_nested_documentation_failure_diagnostic_is_bounded(self):
        class Rejection:
            status_code=422
            def json(self):
                return {'detail':{'failed_stage_qa':{'status':'INPUT_REQUIRED',
                    'riser_integrity':{'status':'INPUT_REQUIRED','missing_inputs':['PLAN_BRANCH:G1:GAS']},
                    'documentation_package':{'private_geometry':'PRIVATE'},
                    'errors':['x'*500]*100}}}
        qa=dxf_output._cad_rejection_diagnostic(Rejection())['failed_stage_qa']
        self.assertEqual(qa['riser_integrity']['missing_inputs'],['PLAN_BRANCH:G1:GAS'])
        self.assertEqual(len(qa['errors']),30)
        self.assertEqual(len(qa['errors'][0]),300)
        self.assertNotIn('PRIVATE',str(qa))

    def test_preservation_diagnostic_reports_failed_sheet_without_source_geometry(self):
        class Rejection:
            status_code = 422

            def json(self):
                return {'detail': {'stage': 'architecture_preservation_gate',
                    'architecture_preservation_qa': {'status': 'FAIL',
                        'failures': ['topology'], 'all_missing_count': 1,
                        'sheet_results': [{'sheet': 'M-101', 'status': 'FAIL',
                            'preservation_match': {'pass': False, 'missing': [
                                {'source': {'bbox': [123, 456, 789, 1000], 'text': 'PRIVATE'}}]},
                            'topology': {'pass': False}, 'visibility': {'pass': True}},
                            {'sheet': 'M-102', 'status': 'PASS'}]}}}
        diagnostic = dxf_output._cad_rejection_diagnostic(Rejection())
        qa = diagnostic['architecture_preservation_qa']
        self.assertEqual(qa['failed_sheet_count'], 1)
        self.assertEqual(qa['failed_sheets'][0]['missing_count'], 1)
        self.assertFalse(qa['failed_sheets'][0]['topology_pass'])
        self.assertNotIn('PRIVATE', str(diagnostic))
        self.assertNotIn('bbox', str(diagnostic))

    def test_active_dxf_flow_translates_422_instead_of_raise_for_status(self):
        message = dxf_output._cad_error_message(_Response())
        self.assertIn('فشار مبنای آب ورودی', message)
        self.assertNotIn('Client Error', message)
        self.assertNotIn('127.0.0.1:8081', message)
        source = inspect.getsource(dxf_output.run_design_dxf)
        self.assertNotIn('raise_for_status()', source)

    def test_server_diagnostic_keeps_qa_evidence_but_excludes_geometry(self):
        class Rejection:
            status_code = 422

            def json(self):
                return {'detail': {
                    'code': 'MECHANICAL_QA_FAILED',
                    'stage': 'engineering_acceptance_gate',
                    'engineering_acceptance': {
                        'status': 'FAIL',
                        'errors': ['routing:route_crosses_architectural_wall'],
                        'metrics': {'wall_crossings': 2},
                        'project_geometry': {'rooms': [1, 2, 3]},
                    },
                }}

        diagnostic = dxf_output._cad_rejection_diagnostic(Rejection())
        self.assertEqual(diagnostic['engineering_acceptance']['errors'], [
            'routing:route_crosses_architectural_wall'
        ])
        self.assertEqual(diagnostic['engineering_acceptance']['metrics'], {'wall_crossings': 2})
        self.assertNotIn('project_geometry', str(diagnostic))

    def test_customer_error_does_not_misreport_warning_as_failure(self):
        class Rejection:
            status_code = 422

            def json(self):
                return {'detail': {
                    'stage': 'pipeline_qa',
                    'pipeline_qa': {'status': 'FAIL', 'errors': ['route_sizing_without_project_load']},
                    'engineering_acceptance': {'status': 'FAIL', 'errors': ['routing:route_crosses_architectural_wall']},
                    'dxf_qa': {'status': 'PASS', 'errors': [], 'warnings': ['architectural_north_not_provided:M-101']},
                }}

        message = dxf_output._cad_error_message(Rejection())
        self.assertIn('route_sizing_without_project_load', message)
        self.assertIn('route_crosses_architectural_wall', message)
        self.assertNotIn('architectural_north_not_provided', message)


if __name__ == '__main__':
    unittest.main()
