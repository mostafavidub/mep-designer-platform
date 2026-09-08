import unittest

from app import level_detection_v3 as v3


class LevelDetectionV3Tests(unittest.TestCase):
    def test_mezzanine_is_restored_when_explicit_layout_title_has_no_room_labels(self):
        analysis = {
            'files': [{
                'text_labels': [
                    {'text': 'پلان معماری طبقه همکف', 'x': 0, 'y': 0, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'فروشگاه', 'x': 4, 'y': 5, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'توالت', 'x': 6, 'y': 5, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'پلان معماری نیم طبقه بالکن تجاری', 'x': 100, 'y': 0, 'source_type': 'layout', 'source_name': 'Model'},
                ],
                'fixture_counts': {}, 'roof_drain_count': 0,
            }]
        }
        auto = v3.infer_architecture_facts(analysis, 'mechanical')
        names = [x['name'] for x in auto['levels']]
        self.assertIn('طبقه همکف', names)
        self.assertIn('نیم طبقه بالکن تجاری', names)
        self.assertIn('نیم طبقه بالکن تجاری', auto['restored_explicit_levels'])
        profile = next(x for x in auto['level_profiles'] if x['name'] == 'نیم طبقه بالکن تجاری')
        self.assertGreaterEqual(profile['level_confidence'], 0.85)
        self.assertEqual(profile['level_detection_status'], 'confirmed-from-explicit-title')

    def test_orphan_block_title_is_retained_but_not_activated(self):
        analysis = {
            'files': [{
                'text_labels': [
                    {'text': 'طبقه همکف پلان معماری', 'x': 0, 'y': 0, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'فروشگاه', 'x': 3, 'y': 4, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'توالت', 'x': 6, 'y': 4, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'طبقه چهارم پلان معماری', 'x': 9000, 'y': 9000, 'source_type': 'block', 'source_name': 'SAMPLE_TITLE'},
                ],
                'fixture_counts': {}, 'roof_drain_count': 0,
            }]
        }
        auto = v3.infer_architecture_facts(analysis, 'mechanical')
        names = [x['name'] for x in auto['levels']]
        self.assertNotIn('طبقه چهارم', names)
        self.assertIn('طبقه چهارم', [x['name'] for x in auto['candidate_levels']])
        self.assertIn('weak_level_titles_retained_as_candidates', auto['level_detection_diagnostics'])

    def test_title_only_restored_level_cannot_become_typical(self):
        analysis = {
            'files': [{
                'text_labels': [
                    {'text': 'پلان معماری طبقه همکف', 'x': 0, 'y': 0, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'فروشگاه', 'x': 3, 'y': 4, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'توالت', 'x': 7, 'y': 4, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'پلان معماری نیم طبقه', 'x': 100, 'y': 0, 'source_type': 'layout', 'source_name': 'Model'},
                ],
                'fixture_counts': {}, 'roof_drain_count': 0,
            }]
        }
        auto = v3.infer_architecture_facts(analysis, 'mechanical')
        mezz = next(x for x in auto['level_profiles'] if x['name'] == 'نیم طبقه')
        self.assertIsNone(mezz['typical_signature'])
        self.assertEqual(mezz['typical_confidence'], 'insufficient')
        self.assertFalse(any('نیم طبقه' in (g.get('levels') or []) for g in auto['typical_groups']))

    def test_english_mezzanine_and_basement_titles_are_recognized(self):
        self.assertEqual(v3._explicit_level_title('Mezzanine Floor Plan')[0], 'نیم طبقه')
        self.assertEqual(v3._explicit_level_title('Basement Plan')[0], 'زیرزمین')

    def test_non_level_support_titles_are_never_level_authority(self):
        for title in (
            'پلان شیب بندی بام', 'پلان جانمایی پارکینگ', 'DETAIL-1',
            'پلان نعل درگاه تیپ طبقات اول تا پنجم', 'Section A-A',
        ):
            self.assertIsNone(v3._explicit_level_title(title), title)

    def test_slope_plan_does_not_create_phantom_roof_level(self):
        analysis = {
            'files': [{
                'text_labels': [
                    {'text': 'پلان معماری طبقه همکف', 'x': 0, 'y': 0, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'فروشگاه', 'x': 3, 'y': 4, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'توالت', 'x': 6, 'y': 4, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'پلان شیب بندی بام', 'x': 100, 'y': 0, 'source_type': 'layout', 'source_name': 'Model'},
                ],
                'fixture_counts': {}, 'roof_drain_count': 0,
            }]
        }
        auto = v3.infer_architecture_facts(analysis, 'mechanical')
        names = [x['name'] for x in auto['levels']]
        self.assertNotIn('بام', names)
        self.assertTrue(auto['rejected_non_level_titles'])
        self.assertIn('non_level_support_drawings_rejected_from_level_authority', auto['level_detection_diagnostics'])

    def test_active_level_gets_stable_authority_id_and_source_file(self):
        analysis = {
            'files': [{
                'file': 'architecture-a.dxf',
                'text_labels': [
                    {'text': 'پلان معماری طبقه همکف', 'x': 0, 'y': 0, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'آشپزخانه', 'x': 3, 'y': 4, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'توالت', 'x': 6, 'y': 4, 'source_type': 'layout', 'source_name': 'Model'},
                ],
                'fixture_counts': {}, 'roof_drain_count': 0,
            }]
        }
        first = v3.infer_architecture_facts(analysis, 'mechanical')
        second = v3.infer_architecture_facts(analysis, 'mechanical')
        a = first['level_profiles'][0]; b = second['level_profiles'][0]
        self.assertEqual(a['source_file'], 'architecture-a.dxf')
        self.assertTrue(a['level_authority_id'].startswith('LVL-'))
        self.assertEqual(a['level_authority_id'], b['level_authority_id'])


if __name__ == '__main__':
    unittest.main()
