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

    def test_rejects_shared_outline_as_room_geometry_and_promotes_shaft_label(self):
        path = self._write_architecture()
        try:
            base = {'text_labels': [
                {'text': 'آشپزخانه', 'x': 3, 'y': 3, 'source_type': 'layout', 'source_name': 'Model'},
                {'text': 'حمام', 'x': 5, 'y': 4, 'source_type': 'layout', 'source_name': 'Model'},
                {'text': 'داکت', 'x': 6, 'y': 5, 'source_type': 'layout', 'source_name': 'Model'},
            ]}
            analysis_file = reconstruct_dxf(path, base)
            # The same closed outline contains three semantic labels, so it is
            # not accepted as three fabricated room/shaft polygons.
            self.assertTrue(all(row['polygon'] is None for row in analysis_file['architecture_rooms']))
            auto = {'level_profiles': [
                {'name': 'طبقه همکف', 'title_point': [10, -2], 'roof': False},
            ]}
            level = enrich_auto(auto, {'files': [analysis_file]})['architecture_model']['levels'][0]
            self.assertEqual([row['type'] for row in level['rooms']], ['kitchen', 'bath'])
            self.assertEqual(len(level['shafts']), 2)  # semantic block + explicit shaft label
            label_shaft = next(row for row in level['shafts'] if row['entity_type'] == 'TEXT_EVIDENCE')
            self.assertEqual(label_shaft['geometry_confidence'], 'label_only')
            model = enrich_auto(auto, {'files': [analysis_file]})['architecture_model']
            self.assertEqual(model['status'], 'INPUT_REQUIRED')
            self.assertIn('ROOM_BOUNDARY_GEOMETRY', model['missing_inputs'])
            self.assertIn('SHAFT_BOUNDARY_GEOMETRY', model['missing_inputs'])
            self.assertEqual(model['quality']['fabricated_geometry_count'], 0)
        finally:
            path.unlink(missing_ok=True)

    def test_canonical_print_frame_prevents_non_plan_labels_and_entities_from_leaking(self):
        analysis_file = {
            'architecture_rooms': [
                {'type': 'bath', 'label': 'حمام', 'label_point': [5, 5]},
                {'type': 'stair', 'label': 'دال راه پله', 'label_point': [105, 5]},
            ],
            'architecture_primitives': [
                {'kind': 'door', 'layer': 'door', 'entity_type': 'LINE',
                 'bounds': [4, 4, 5, 5], 'centroid': [4.5, 4.5]},
                {'kind': 'door', 'layer': 'door', 'entity_type': 'LINE',
                 'bounds': [104, 4, 105, 5], 'centroid': [104.5, 4.5]},
            ],
            'architecture_plan_frames': [
                {'bounds': [0, 0, 20, 20], 'drawing_type': 'ARCH_FLOOR_PLAN', 'level': 'GROUND'},
                {'bounds': [100, 0, 120, 20], 'drawing_type': 'SECTION', 'level': None},
            ],
        }
        auto = {'level_profiles': [
            {'name': 'طبقه همکف', 'title_point': [10, 10], 'roof': False},
        ]}
        level = enrich_auto(auto, {'files': [analysis_file]})['architecture_model']['levels'][0]
        self.assertEqual([row['type'] for row in level['rooms']], ['bath'])
        self.assertEqual(level['counts']['door'], 1)
        self.assertEqual(level['region_bounds'], [0.0, 0.0, 20.0, 20.0])

    def test_unlabeled_cell_type_is_inferred_from_fixture_but_remains_reviewable(self):
        analysis_file = {
            'architecture_rooms': [{
                'type': 'unknown', 'label': 'فضای بدون عنوان', 'label_point': [5, 5],
                'polygon': [[1, 1], [9, 1], [9, 9], [1, 9]],
                'bounds': [1, 1, 9, 9], 'polygon_confidence': 'low',
                'provenance': 'GEOMETRY_ONLY',
            }],
            'architecture_primitives': [{
                'kind': 'bed_fixture', 'layer': 'FURN', 'entity_type': 'INSERT',
                'block': 'DOUBLE-BED', 'bounds': [3, 3, 7, 6], 'centroid': [5, 4.5],
            }],
            'architecture_plan_frames': [{
                'bounds': [0, 0, 10, 10], 'drawing_type': 'ARCH_FLOOR_PLAN',
                'level': 'GROUND', 'handle': 'FRAME-1',
            }],
            'architecture_boundary_reconstruction': [{
                'frame_handle': 'FRAME-1', 'snap_points': [], 'wall_segments': [],
                'visual_underlay': {'status': 'PASS', 'entities': [{'kind': 'polyline'}]},
            }],
        }
        auto = {'level_profiles': [{'name': 'طبقه همکف', 'title_point': [5, 5], 'roof': False}]}
        room = enrich_auto(auto, {'files': [analysis_file]})['architecture_model']['levels'][0]['rooms'][0]
        self.assertEqual(room['type'], 'bedroom')
        self.assertEqual(room['type_provenance'], 'INFERRED_FROM_INSTALLED_FIXTURE')
        self.assertEqual(room['polygon_confidence'], 'low')


if __name__ == '__main__':
    unittest.main()
