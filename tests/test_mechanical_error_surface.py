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


if __name__ == '__main__':
    unittest.main()
