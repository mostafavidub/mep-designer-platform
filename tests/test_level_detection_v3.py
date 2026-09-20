import unittest
from types import SimpleNamespace

from app import level_detection_v3 as v3


class LevelDetectionV3Tests(unittest.TestCase):
    def test_install_preserves_upstream_inference_fields(self):
        module=SimpleNamespace(
            infer_architecture_facts=lambda analysis,discipline:{
                'effective_unit_to_m':1.0,
                'unit_inference':{'status':'PASS'},
                'level_profiles':[],
            }
        )
        v3.install(module)
        result=module.infer_architecture_facts({'files':[]},'mechanical')
        self.assertEqual(result['effective_unit_to_m'],1.0)
        self.assertEqual(result['unit_inference']['status'],'PASS')

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

    def test_reused_roof_title_is_not_an_authoritative_level(self):
        analysis = {
            'files': [{
                'text_labels': [
                    {'text': 'پلان معماری طبقه همکف', 'x': 0, 'y': 0, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'اتاق خواب', 'x': 2, 'y': 2, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'پلان معماری بام', 'x': 100, 'y': 0, 'source_type': 'layout', 'source_name': 'Model'},
                    {'text': 'اتاق خواب', 'x': 102, 'y': 2, 'source_type': 'layout', 'source_name': 'Model'},
                ],
                'fixture_counts': {}, 'roof_drain_count': 0,
            }]
        }
        auto = v3.infer_architecture_facts(analysis, 'mechanical')
        self.assertFalse(auto['roof_scope_reliable'])
        self.assertNotIn('بام', [x['name'] for x in auto['levels']])
        self.assertNotIn('بام', [x['name'] for x in auto['level_profiles']])
        rejected = next(x for x in auto['candidate_levels'] if x['name'] == 'بام')
        self.assertEqual(rejected['rejection_reason'], 'occupied_floor_content_without_roof_drain_evidence')
        self.assertIn('pseudo_roof_removed_from_authoritative_levels', auto['level_detection_diagnostics'])


if __name__ == '__main__':
    unittest.main()
