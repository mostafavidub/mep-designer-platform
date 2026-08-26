import tempfile
import unittest
from pathlib import Path

import ezdxf

from app.fixture_detection_v2 import enhance_dxf_result, enrich_auto_inference


class FixtureEquipmentDetectionV2Tests(unittest.TestCase):
    def _write_fixture(self):
        tmp = tempfile.NamedTemporaryFile(suffix='.dxf', delete=False)
        tmp.close()
        path = Path(tmp.name)
        doc = ezdxf.new('R2013')
        doc.layers.add('A-PLUMBING-FIXTURE-WC')
        doc.layers.add('A-FIXTURE')
        doc.layers.add('M-HVAC-EQUIP')
        doc.layers.add('A-DOOR')

        wc = doc.blocks.new('B_101')
        wc.add_circle((0, 0), 0.3)
        wc.add_line((-0.3, 0), (0.3, 0))

        basin = doc.blocks.new('B_202')
        basin.add_lwpolyline([(0, 0), (0.6, 0), (0.6, 0.4), (0, 0.4)], close=True)
        basin.add_circle((0.3, 0.2), 0.05)

        fcu = doc.blocks.new('FCU-01')
        fcu.add_lwpolyline([(0, 0), (1.2, 0), (1.2, 0.5), (0, 0.5)], close=True)

        door = doc.blocks.new('D-01')
        door.add_line((0, 0), (1, 0))
        door.add_arc((0, 0), 1, 0, 90)

        msp = doc.modelspace()
        msp.add_blockref('B_101', (10, 10), dxfattribs={'layer': 'A-PLUMBING-FIXTURE-WC'})
        msp.add_blockref('B_202', (20, 10), dxfattribs={'layer': 'A-FIXTURE'})
        msp.add_text('روشویی', dxfattribs={'height': 0.2}).set_placement((20.4, 10.2))
        msp.add_blockref('FCU-01', (30, 10), dxfattribs={'layer': 'M-HVAC-EQUIP'})
        msp.add_blockref('D-01', (40, 10), dxfattribs={'layer': 'A-DOOR'})
        doc.saveas(path)
        return path

    def test_multi_signal_detection_finds_numeric_blocks_and_equipment(self):
        path = self._write_fixture()
        try:
            base = {'geometry_bounds': [0, 0, 100, 100], 'fixture_blocks': []}
            result = enhance_dxf_result(path, base)
            detected = {(x['category'], x['type']) for x in result['fixture_detections'] + result['equipment_detections'] if x['status'] == 'detected'}
            self.assertIn(('fixture', 'toilet'), detected)
            self.assertIn(('fixture', 'basin'), detected)
            self.assertIn(('equipment', 'fan_coil'), detected)
            self.assertNotIn(('fixture', 'door'), detected)
            self.assertGreaterEqual(result['fixture_counts']['toilet'], 1)
            self.assertGreaterEqual(result['fixture_counts']['basin'], 1)
            self.assertGreaterEqual(result['equipment_counts']['fan_coil'], 1)
        finally:
            path.unlink(missing_ok=True)

    def test_text_only_evidence_stays_candidate(self):
        tmp = tempfile.NamedTemporaryFile(suffix='.dxf', delete=False)
        tmp.close()
        path = Path(tmp.name)
        try:
            doc = ezdxf.new('R2013')
            doc.modelspace().add_text('توالت', dxfattribs={'height': 0.2}).set_placement((5, 5))
            doc.saveas(path)
            result = enhance_dxf_result(path, {'geometry_bounds': [0, 0, 10, 10], 'fixture_blocks': []})
            candidates = [x for x in result['fixture_detections'] if x['type'] == 'toilet']
            self.assertTrue(candidates)
            self.assertTrue(all(x['status'] == 'candidate' for x in candidates))
            self.assertEqual(result['fixture_counts'].get('toilet', 0), 0)
        finally:
            path.unlink(missing_ok=True)

    def test_wet_level_without_detected_fixture_is_diagnostic_not_silent_zero(self):
        auto = {
            'level_profiles': [
                {'name': 'Mezzanine', 'title_point': [0, 0], 'room_counts': {'toilet': 1}, 'source_name': 'Model'},
            ]
        }
        analysis = {'files': [{'fixture_detections': [], 'equipment_detections': []}]}
        enriched = enrich_auto_inference(auto, analysis)
        self.assertIn('wet_level_without_detected_fixture:Mezzanine', enriched['evidence_diagnostics'])

    def test_detected_items_receive_level_and_evidence(self):
        auto = {
            'level_profiles': [
                {'name': 'Ground', 'title_point': [0, 0], 'room_counts': {'toilet': 1}, 'source_name': 'Model'},
                {'name': 'Mezzanine', 'title_point': [100, 0], 'room_counts': {'toilet': 1}, 'source_name': 'Model'},
            ]
        }
        detection = {
            'category': 'fixture', 'type': 'toilet', 'x': 95, 'y': 0,
            'source_name': 'Model', 'status': 'detected', 'confidence': .9,
            'evidence': [{'kind': 'block_name', 'value': 'WC'}],
        }
        enriched = enrich_auto_inference(auto, {'files': [{'fixture_detections': [detection], 'equipment_detections': []}]})
        self.assertEqual(enriched['fixture_detections'][0]['level'], 'Mezzanine')
        self.assertEqual(enriched['fixture_blocks_detected'], 1)
        self.assertEqual(enriched['fixture_detections'][0]['evidence'][0]['kind'], 'block_name')


if __name__ == '__main__':
    unittest.main()
