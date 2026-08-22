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

    def test_end_to_end_v9_generates_auditable_sheeted_dxf(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'architecture.dxf'
            dst = Path(td) / 'mechanical.dxf'
            doc = ezdxf.new('R2013')
            doc.header['$INSUNITS'] = 4
            msp = doc.modelspace()

            # Dimension measurements deliberately prove metre-scale geometry despite mm header.
            dim = msp.add_linear_dim(base=(0, -2), p1=(0, 0), p2=(3, 0), angle=0)
            dim.render()

            # Typical F1-F5 architecture + furniture source.
            msp.add_text('پلان معماری تیپ طبقات اول تا پنجم').set_placement((100, 0))
            msp.add_text('آشپزخانه').set_placement((98, 8))
            msp.add_text('حمام').set_placement((96, 11))
            msp.add_text('اتاق خواب').set_placement((104, 11))
            msp.add_text('هال').set_placement((104, 7))
            msp.add_text('شفت').set_placement((97, 14))
            msp.add_text('پلان مبلمان تیپ طبقات اول تا پنجم').set_placement((75, 0))
            msp.add_text('آشپزخانه').set_placement((73, 8))
            msp.add_text('حمام').set_placement((71, 11))
            msp.add_text('شفت').set_placement((72, 14))

            # Roof with rainwater source annotation.
            msp.add_text('پلان معماری پشت بام').set_placement((50, 0))
            msp.add_text('بام').set_placement((50, 10))
            msp.add_text('P.V.C 90').set_placement((48, 12))

            # Special parking/ground plan must survive Level Scope Matrix.
            msp.add_text('پلان جانمایی پارکینگ').set_placement((125, 0))
            msp.add_text('پارکینگ').set_placement((125, 8))
            msp.add_text('آشپزخانه').set_placement((121, 9))

            # Real fixture blocks in furniture plan for v7 fixture traceability.
            for name in ('SINK-2', 'BAT18'):
                block = doc.blocks.new(name=name)
                block.add_circle((0, 0), .15)
            msp.add_blockref('SINK-2', (73, 8))
            msp.add_blockref('BAT18', (71, 11))
            doc.saveas(src)

            systems = [
                'cold_water', 'hot_water', 'sanitary', 'vent', 'gas',
                'heating_supply', 'heating_return', 'cooling', 'condensate',
                'exhaust_ventilation', 'mechanical_risers',
            ]
            calc = {
                '_design_inputs': {'gas': 'ندارد', 'cooling': 'split', 'heating': 'radiator'},
                'design_water_flow_lps': 0.45,
                'preliminary_nominal_pipe_candidate_mm': 25,
                'cooling_load_kw': 8.0,
                'heating_load_kw': 6.0,
            }
            meta = v9.design_dxf_v9(src, dst, 'mechanical', systems, 1, calc)
            self.assertTrue(dst.exists())
            out = ezdxf.readfile(dst)
            self.assertEqual(int(out.header.get('$INSUNITS')), 6)
            self.assertIn('M-RISER-CALC', [x.name for x in out.layouts])
            self.assertGreater(len([x for x in out.layouts if x.name != 'Model']), 2)
            self.assertEqual(len(out.audit().errors), 0)
            self.assertEqual(meta['v9_final_qa']['score_10'], 10.0)
            self.assertTrue(any(e.dxf.layer == 'ENGITOOLS-M-RAINWATER' for e in out.modelspace()))


if __name__ == '__main__':
    unittest.main()
