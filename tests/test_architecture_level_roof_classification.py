import unittest

from app.auto_inference_v2 import _level_profiles_from_file
from cad_engine.main_v3 import classify_room as cad_classify_room


def label(text, x, y):
    return {
        'text': text,
        'x': x,
        'y': y,
        'source_type': 'layout',
        'source_name': 'Model',
    }


class RoofLevelClassificationTests(unittest.TestCase):
    def test_analyzer_and_cad_share_commercial_room_vocabulary(self):
        self.assertEqual(cad_classify_room('تجاری'), 'shop')
        self.assertEqual(cad_classify_room('فضای اداری'), 'office')

    def test_roof_annotation_inside_ground_floor_does_not_reclassify_level(self):
        file_info = {'text_labels': [
            label('پلان معماری طبقه همکف', 0, 0),
            label('اداری', 2, 1),
            label('فروشگاه', 3, 1),
            label('دسترسی به بام', 4, 1),
        ]}

        profiles = _level_profiles_from_file(file_info)

        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]['name'], 'طبقه همکف')
        self.assertFalse(profiles[0]['roof'])
        self.assertTrue(profiles[0]['conditioned_candidate'])

    def test_explicit_roof_level_title_is_roof(self):
        file_info = {'text_labels': [
            label('پلان معماری بام', 0, 0),
            label('دسترسی به بام', 2, 1),
        ]}

        profiles = _level_profiles_from_file(file_info)

        self.assertEqual(len(profiles), 1)
        self.assertTrue(profiles[0]['roof'])


if __name__ == '__main__':
    unittest.main()
