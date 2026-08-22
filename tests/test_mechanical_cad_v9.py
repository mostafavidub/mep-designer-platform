import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine import main_v8 as v8
from cad_engine import main_v9 as v9


class MechanicalCadV9RegressionTests(unittest.TestCase):
    def test_mm_header_with_meter_scale_dimensions_is_overridden(self):
        doc = ezdxf.new('R2013')
        doc.header['$INSUNITS'] = 4
        msp = doc.modelspace()
        dim = msp.add_linear_dim(base=(0, 1), p1=(0, 0), p2=(3, 0), angle=0)
        dim.render()
        info = v9._dimension_unit_inference(doc)
        self.assertEqual(info['source_insunits'], 4)
        self.assertEqual(info['effective_insunits'], 6)
        self.assertEqual(info['confidence'], 'high')

    def test_parking_special_plan_is_not_silently_dropped(self):
        doc = ezdxf.new('R2013')
        msp = doc.modelspace()
        msp.add_text('پلان معماری تیپ طبقات اول تا پنجم').set_placement((100, 0))
        msp.add_text('آشپزخانه').set_placement((98, 8))
        msp.add_text('شفت').set_placement((99, 10))
        msp.add_text('پلان جانمایی پارکینگ').set_placement((130, 0))
        msp.add_text('پارکینگ').set_placement((129, 7))
        levels = v8.build_levels_v8(msp)
        self.assertTrue(any(x.get('special_type') == 'parking' for x in levels))
        self.assertGreaterEqual(len(levels), 2)

    def test_vertical_reference_is_projected_consistently(self):
        levels = [
            {'level': 'F1-F5', 'title': {'point': (100.0, 0.0)}, 'rooms': [{'room': 'shaft', 'point': (97.5, 17.6)}], 'fixtures': []},
            {'level': 'ROOF', 'title': {'point': (70.0, 0.0)}, 'rooms': [], 'fixtures': []},
            {'level': 'PARKING', 'title': {'point': (130.0, 0.0)}, 'rooms': [], 'fixtures': []},
        ]
        v8._apply_vertical_reference(levels)
        vectors = []
        for level in levels:
            p = level['forced_hub']
            t = level['title']['point']
            vectors.append((round(p[0]-t[0], 6), round(p[1]-t[1], 6)))
        self.assertEqual(len(set(vectors)), 1)

    def test_standard_scale_returns_known_plot_scale(self):
        self.assertEqual(v8._nearest_standard_scale(25, 20), 75)
        self.assertEqual(v8._nearest_standard_scale(35, 25), 100)


if __name__ == '__main__':
    unittest.main()
