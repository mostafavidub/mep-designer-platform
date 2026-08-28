import tempfile
import unittest
from pathlib import Path

import ezdxf

from app.fixture_detection_v2 import enhance_dxf_result


class ApprovedProjectFixtureAliasesTests(unittest.TestCase):
    def test_observed_approved_project_block_names_are_recognized(self):
        tmp = tempfile.NamedTemporaryFile(suffix='.dxf', delete=False)
        tmp.close(); path = Path(tmp.name)
        try:
            doc = ezdxf.new('R2013')
            for name in ('TOALET-2', 'FARANGI', 'SINK-2', 'LAVE-3', 'Faucet', 'K_GAZ1', 'RAD-90', 'FCU-01'):
                block = doc.blocks.new(name)
                block.add_lwpolyline([(0, 0), (.8, 0), (.8, .5), (0, .5)], close=True)
            msp = doc.modelspace()
            positions = {
                'TOALET-2': (0, 0), 'FARANGI': (2, 0), 'SINK-2': (4, 0), 'LAVE-3': (6, 0),
                'Faucet': (8, 0), 'K_GAZ1': (10, 0), 'RAD-90': (12, 0), 'FCU-01': (14, 0),
            }
            for name, point in positions.items():
                msp.add_blockref(name, point)
            doc.saveas(path)
            result = enhance_dxf_result(path, {'geometry_bounds': [0, 0, 20, 10], 'fixture_blocks': []})
            detected = {(x['category'], x['type']) for x in result['fixture_detections'] + result['equipment_detections'] if x['status'] == 'detected'}
            for expected in (
                ('fixture', 'toilet'), ('fixture', 'sink'), ('fixture', 'basin'), ('fixture', 'faucet'),
                ('equipment', 'gas_cooker'), ('equipment', 'radiator'), ('equipment', 'fan_coil'),
            ):
                self.assertIn(expected, detected)
        finally:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
