import unittest
import ezdxf

from cad_engine import main_v8 as v8
from cad_engine.level_geometry_v11 import augment_levels, _equivalent


class LevelGeometryBridgeTests(unittest.TestCase):
    def test_normalizes_persian_mezzanine_variants(self):
        self.assertTrue(_equivalent('نیم طبقه', 'نیم‌طبقه'))
        self.assertTrue(_equivalent('نیم طبقه', 'پلان معماری نیم طبقه بالکن تجاری'))
        self.assertFalse(_equivalent('نیم طبقه', 'طبقه همکف'))

    def test_analyzer_active_mezzanine_is_added_to_cad_levels(self):
        doc = ezdxf.new('R2010')
        msp = doc.modelspace()
        msp.add_text('آشپزخانه', dxfattribs={'height': 0.2}).set_placement((101.0, 106.0))
        levels = [{
            'level': 'طبقه همکف',
            'title': {'type': 'architecture', 'level': 'طبقه همکف', 'point': (0.0, 0.0), 'text': 'طبقه همکف'},
            'rooms': [], 'fixtures': [],
        }]
        calc = {
            '_plan_analysis': {
                'architectural_auto': {
                    'level_profiles': [{
                        'name': 'نیم طبقه',
                        'title_point': [100.0, 100.0],
                        'source_type': 'model',
                        'source_name': 'Model',
                        'recognized_room_labels': 1,
                        'typical_confidence': 'insufficient',
                    }]
                }
            }
        }
        out = augment_levels(msp, levels, calc, v8)
        names = [row['level'] for row in out]
        self.assertIn('نیم طبقه', names)
        mezz = next(row for row in out if row['level'] == 'نیم طبقه')
        self.assertTrue(mezz['analyzer_geometry_bridge'])
        self.assertEqual(mezz['provenance'], 'analyzer-level-profile-bridge-v11')

    def test_existing_equivalent_level_is_not_duplicated(self):
        doc = ezdxf.new('R2010')
        levels = [{
            'level': 'نیم‌طبقه بالکن تجاری',
            'title': {'type': 'architecture', 'level': 'نیم‌طبقه بالکن تجاری', 'point': (10.0, 10.0)},
            'rooms': [], 'fixtures': [],
        }]
        calc = {'_plan_analysis': {'architectural_auto': {'level_profiles': [{
            'name': 'نیم طبقه', 'title_point': [10.0, 10.0], 'source_type': 'model'
        }]}}}
        out = augment_levels(doc.modelspace(), levels, calc, v8)
        self.assertEqual(len(out), 1)


if __name__ == '__main__':
    unittest.main()
