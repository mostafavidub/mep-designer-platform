import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine.engineering_qa_v11 import validate_generated_mechanical_output


class FinalEngineeringQATests(unittest.TestCase):
    def _base(self, path, code='M-W-01'):
        doc = ezdxf.new('R2013')
        doc.layouts.new(code)
        msp = doc.modelspace()
        msp.add_line((0, 0), (5, 0), dxfattribs={'layer': 'ENGITOOLS-M-COLD_WATER'})
        msp.add_line((0, 1), (5, 1), dxfattribs={'layer': 'ENGITOOLS-M-HOT_WATER'})
        doc.saveas(path)

    def test_passes_exact_manifest_and_engine_reports(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'out.dxf'
            self._base(path)
            calc = {'_approved_drawing_manifest': {
                'total_sheets': 1,
                'sheets': [{'code': 'M-W-01', 'family': 'water_supply', 'special': False}],
            }}
            meta = {
                'technical_quality': {'score_10': 10.0, 'failed': []},
                'compact_output': {'status': 'PASS'},
                'technical_design': {'shared_distribution_network': {'water_sanitary_status': 'PASS'}},
            }
            report = validate_generated_mechanical_output(path, calc, meta)
            self.assertEqual(report['status'], 'PASS')

    def test_manifest_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'out.dxf'
            self._base(path, 'M-W-02')
            calc = {'_approved_drawing_manifest': {
                'total_sheets': 1,
                'sheets': [{'code': 'M-W-01', 'family': 'water_supply', 'special': False}],
            }}
            meta = {
                'technical_quality': {'score_10': 10.0, 'failed': []},
                'compact_output': {'status': 'PASS'},
                'technical_design': {'shared_distribution_network': {'water_sanitary_status': 'PASS'}},
            }
            with self.assertRaisesRegex(RuntimeError, 'final engineering QA failed'):
                validate_generated_mechanical_output(path, calc, meta)


if __name__ == '__main__':
    unittest.main()
