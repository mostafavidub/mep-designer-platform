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

    def test_preservation_failure_exposes_counts_and_reason_without_geometry(self):
        class Rejection:
            status_code = 422

            def json(self):
                return {'detail': {
                    'stage': 'architecture_preservation_gate',
                    'architecture_preservation_qa': {
                        'critical_missing_count': 2,
                        'important_missing_count': 1,
                        'all_missing_count': 3,
                        'sheet_results': [{
                            'sheet': 'M-W-01',
                            'preservation_match': {'missing': [
                                {'reason': 'GEOMETRY_MISMATCH', 'expected_bbox': [1, 2, 3, 4]},
                            ]},
                        }],
                    },
                }}

        message = dxf_output._cad_error_message(Rejection())

        self.assertIn('critical_missing=2', message)
        self.assertIn('important_missing=1', message)
        self.assertIn('GEOMETRY_MISMATCH', message)
        self.assertNotIn('expected_bbox', message)


if __name__ == '__main__':
    unittest.main()
