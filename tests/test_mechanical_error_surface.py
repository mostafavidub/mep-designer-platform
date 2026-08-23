import inspect
import unittest

from app import dxf_output


class _Response:
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


if __name__ == '__main__':
    unittest.main()
