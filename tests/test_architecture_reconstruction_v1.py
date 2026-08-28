import tempfile
import unittest
from pathlib import Path

import ezdxf

from app.architecture_reconstruction_v1 import reconstruct_dxf, enrich_auto


class ArchitectureReconstructionV1Tests(unittest.TestCase):
    def _write_architecture(self):
        tmp = tempfile.NamedTemporaryFile(suffix='.dxf', delete=False)
        tmp.close(); path = Path(tmp.name)
        doc = ezdxf.new('R2013')
        for layer in ('WALL', 'door', 'WINDOW', 'Columns', 'peleh', 'SHAFT', 'FUR'):
            if layer not in doc.layers:
                doc.layers.add(layer)
        door = doc.blocks.new('door 90')
        door.add_line((0, 0), (0.9, 0))
        window = doc.blocks.new('WINDOW-120')
        window.add_line((0, 0), (1.2, 0))
        column = doc.blocks.new('COLUMN-40')
        column.add_lwpolyline([(0, 0), (.4, 0), (.4, .4), (0, .4)], close=True)
        stair = doc.blocks.new('STAIR-01')
        stair.add_lwpolyline([(0, 0), (2, 0), (2, 3), (0, 3)], close=True)
        shaft = doc.blocks.new('SHAFT-01')
        shaft.add_lwpolyline([(0, 0), (1, 0), (1, 1), (0, 1)], close=True)
        msp = doc.modelspace()
        # Ground plan around x=0..20
        msp.add_lwpolyline([(0, 0), (20, 0), (20, 12), (0, 12)], close=True, dxfattribs={'layer': 'WALL'})
        msp.add_lwpolyline([(1, 1), (8, 1), (8, 6), (1, 6)], close=True, dxfattribs={'layer': 'FUR'})
        msp.add_text('آشپزخانه', dxfattribs={'height': .25}).set_placement((3, 3))
        msp.add_text('پلان معماری طبقه همکف', dxfattribs={'height': .3}).set_placement((10, -2))
        msp.add_blockref('door 90', (8, 3), dxfattribs={'layer': 'door'})
        msp.add_blockref('WINDOW-120', (4, 12), dxfattribs={'layer': 'WINDOW'})
        msp.add_blockref('COLUMN-40', (10, 5), dxfattribs={'layer': 'Columns'})
        msp.add_blockref('STAIR-01', (15, 4), dxfattribs={'layer': 'peleh'})
        msp.add_blockref('SHAFT-01', (13, 5), dxfattribs={'layer': 'SHAFT'})
        # Second plan far away to verify spatial separation.
        msp.add_lwpolyline([(100, 0), (120, 0), (120, 12), (100, 12)], close=True, dxfattribs={'layer': 'WALL'})
        msp.add_lwpolyline([(101, 1), (108, 1), (108, 6), (101, 6)], close=True, dxfattribs={'layer': 'FUR'})
        msp.add_text('اتاق خواب', dxfattribs={'height': .25}).set_placement((103, 3))
        msp.add_text('پلان معماری طبقه اول', dxfattribs={'height': .3}).set_placement((110, -2))
        msp.add_blockref('door 90', (108, 3), dxfattribs={'layer': 'door'})
        doc.saveas(path)
        return path

    def test_reconstructs_semantic_primitives_and_room_polygons(self):
        path = self._write_architecture()
        try:
            base = {'text_labels': [
                {'text': 'آشپزخانه', 'x': 3, 'y': 3, 'source_type': 'layout', 'source_name': 'Model'},
                {'text': 'اتاق خواب', 'x': 103, 'y': 3, 'source_type': 'layout', 'source_name': 'Model'},
            ]}
            result = reconstruct_dxf(path, base)
            counts = result['architecture_primitive_counts']
            self.assertGreaterEqual(counts.get('wall', 0), 2)
            self.assertGreaterEqual(counts.get('door', 0), 2)
            self.assertGreaterEqual(counts.get('window', 0), 1)
            self.assertGreaterEqual(counts.get('column', 0), 1)
            self.assertGreaterEqual(counts.get('stair', 0), 1)
            self.assertGreaterEqual(counts.get('shaft', 0), 1)
            rooms = result['architecture_rooms']
            self.assertEqual(len(rooms), 2)
            self.assertTrue(all(r['polygon'] for r in rooms))
            self.assertTrue(all(r['polygon_confidence'] == 'high' for r in rooms))
        finally:
            path.unlink(missing_ok=True)

    def test_builds_separate_level_models_without_cross_stealing(self):
        path = self._write_architecture()
        try:
            base = {'text_labels': [
                {'text': 'آشپزخانه', 'x': 3, 'y': 3, 'source_type': 'layout', 'source_name': 'Model'},
                {'text': 'اتاق خواب', 'x': 103, 'y': 3, 'source_type': 'layout', 'source_name': 'Model'},
            ]}
            analysis_file = reconstruct_dxf(path, base)
            auto = {'level_profiles': [
                {'name': 'طبقه همکف', 'title_point': [10, -2], 'roof': False},
                {'name': 'طبقه اول', 'title_point': [110, -2], 'roof': False},
            ]}
            enriched = enrich_auto(auto, {'files': [analysis_file]})
            model = enriched['architecture_model']
            self.assertEqual(model['level_count'], 2)
            ground, first = model['levels']
            self.assertEqual([r['type'] for r in ground['rooms']], ['kitchen'])
            self.assertEqual([r['type'] for r in first['rooms']], ['bedroom'])
            self.assertGreaterEqual(ground['counts']['door'], 1)
            self.assertGreaterEqual(first['counts']['door'], 1)
            self.assertGreaterEqual(ground['counts']['shaft'], 1)
            self.assertEqual(first['counts']['shaft'], 0)
        finally:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
