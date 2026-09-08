import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine.mechanical_integrity import validate_generated_mechanical_integrity


def _report(family='WATER', code='M-111'):
    return {
        'composition': {
            'manifest': [{'family': family, 'purpose': 'PLAN', 'old_sheet': 'B1', 'approved_code': code}],
            'boards': {'B1': {'plan_area': [0, 0, 100, 100]}},
        }
    }


def _save(builder):
    td = tempfile.TemporaryDirectory()
    path = Path(td.name) / 'drawing.dxf'
    doc = ezdxf.new('R2013')
    builder(doc, doc.modelspace())
    doc.saveas(path)
    return td, path


class MechanicalIntegrityTests(unittest.TestCase):
    def test_valid_plan_with_real_route_passes(self):
        def build(doc, msp):
            msp.add_text('پلان معماری طبقه همکف').set_placement((5, 5))
            msp.add_line((10, 20), (80, 20), dxfattribs={'layer': 'ENGITOOLS-M-COLD_WATER'})
            msp.add_line((20, 20), (20, 60), dxfattribs={'layer': 'ENGITOOLS-M-HOT_WATER'})
        td, path = _save(build)
        try:
            result = validate_generated_mechanical_integrity(path, _report(), {})
            self.assertEqual(result['status'], 'PASS', result['errors'])
        finally:
            td.cleanup()

    def test_mixed_occupied_levels_fail(self):
        def build(doc, msp):
            msp.add_text('پلان مبلمان طبقه همکف').set_placement((5, 5))
            msp.add_text('پلان مبلمان طبقه اول').set_placement((50, 5))
            msp.add_line((10, 20), (80, 20), dxfattribs={'layer': 'ENGITOOLS-M-COLD_WATER'})
            msp.add_line((20, 20), (20, 60), dxfattribs={'layer': 'ENGITOOLS-M-HOT_WATER'})
        td, path = _save(build)
        try:
            result = validate_generated_mechanical_integrity(path, _report(), {})
            self.assertTrue(any('mixed_primary_plan_titles' in e for e in result['errors']))
        finally:
            td.cleanup()

    def test_support_drawing_mixed_with_floor_fails(self):
        def build(doc, msp):
            msp.add_text('پلان معماری طبقه همکف').set_placement((5, 5))
            msp.add_text('پلان جانمایی پارکینگ').set_placement((50, 5))
            msp.add_line((10, 20), (80, 20), dxfattribs={'layer': 'ENGITOOLS-M-COLD_WATER'})
            msp.add_line((20, 20), (20, 60), dxfattribs={'layer': 'ENGITOOLS-M-HOT_WATER'})
        td, path = _save(build)
        try:
            result = validate_generated_mechanical_integrity(path, _report(), {})
            self.assertTrue(any('rejected_frame_mixed_with_occupied_plan' in e for e in result['errors']))
        finally:
            td.cleanup()

    def test_marker_only_network_fails(self):
        def build(doc, msp):
            msp.add_text('پلان معماری طبقه همکف').set_placement((5, 5))
            msp.add_lwpolyline([(10, 20), (10.1, 20), (10.1, 20.1), (10, 20.1), (10, 20)], dxfattribs={'layer': 'ENGITOOLS-M-COLD_WATER'})
            msp.add_lwpolyline([(11, 20), (11.1, 20), (11.1, 20.1), (11, 20.1), (11, 20)], dxfattribs={'layer': 'ENGITOOLS-M-HOT_WATER'})
        td, path = _save(build)
        try:
            result = validate_generated_mechanical_integrity(path, _report(), {})
            self.assertTrue(any('degenerate_network_topology' in e for e in result['errors']))
        finally:
            td.cleanup()

    def test_idu_without_odu_and_coordinate_collapse_fail(self):
        def build(doc, msp):
            doc.blocks.new('ENGI_AC_INDOOR').add_line((0, 0), (1, 0))
            msp.add_text('پلان معماری طبقه همکف').set_placement((5, 5))
            for _ in range(6):
                msp.add_blockref('ENGI_AC_INDOOR', (30, 30))
        td, path = _save(build)
        try:
            result = validate_generated_mechanical_integrity(path, _report('SPLIT_AC', 'M-161'), {})
            self.assertIn('cooling:idu_without_outdoor_unit', result['errors'])
            self.assertTrue(any('equipment_coordinate_collapse:ENGI_AC_INDOOR' in e for e in result['errors']))
        finally:
            td.cleanup()

    def test_zero_branch_riser_cannot_pass(self):
        def build(doc, msp):
            msp.add_text('BRANCHES | 0').set_placement((5, 5))
            msp.add_text('STATUS: TRUE').set_placement((5, 10))
            msp.add_line((10, 20), (80, 20), dxfattribs={'layer': 'ENGITOOLS-M-COLD_WATER'})
            msp.add_line((20, 20), (20, 60), dxfattribs={'layer': 'ENGITOOLS-M-HOT_WATER'})
        td, path = _save(build)
        try:
            result = validate_generated_mechanical_integrity(path, _report(), {})
            self.assertIn('riser:zero_branches_marked_pass', result['errors'])
        finally:
            td.cleanup()

    def test_unverified_numeric_utility_pressure_and_unmaterialized_details_fail(self):
        def build(doc, msp):
            msp.add_text('DETAIL REGISTER D-PL-01 D-PL-02 D-HV-01').set_placement((5, 5))
            msp.add_text('UTILITY PRESSURE = 2.5 bar').set_placement((5, 10))
            msp.add_line((10, 20), (80, 20), dxfattribs={'layer': 'ENGITOOLS-M-COLD_WATER'})
            msp.add_line((20, 20), (20, 60), dxfattribs={'layer': 'ENGITOOLS-M-HOT_WATER'})
        td, path = _save(build)
        try:
            result = validate_generated_mechanical_integrity(path, _report(), {})
            self.assertIn('calculation_uses_unverified_utility_pressure', result['errors'])
            self.assertTrue(any(e.startswith('detail_register_not_materialized:') for e in result['errors']))
        finally:
            td.cleanup()


if __name__ == '__main__':
    unittest.main()
