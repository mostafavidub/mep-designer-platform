import tempfile
import unittest
from pathlib import Path

import ezdxf

from app.mechanical_drawing_set import approve_drawing_set, predict_drawing_set
from cad_engine import main_v10_5 as production
from tests.test_reference_13_v11 import SYSTEMS, full_inputs


class Reference21Benchmark(unittest.TestCase):
    def _build_architecture(self, path):
        doc = ezdxf.new('R2013')
        doc.header['$INSUNITS'] = 4
        msp = doc.modelspace()
        dim = msp.add_linear_dim(base=(0, -2), p1=(0, 0), p2=(8, 0), angle=0)
        dim.render()
        for name, ox in [('همکف', 0), ('طبقه اول', 40), ('طبقه دوم', 80)]:
            msp.add_text(f'{name} پلان معماری').set_placement((ox, 0))
            for text, dx, dy in (
                ('آشپزخانه', 3, 5), ('حمام', 7, 6), ('سرویس', 7, 9),
                ('اتاق خواب', 12, 5), ('پذیرایی', 12, 11), ('شفت', 6, 13),
            ):
                msp.add_text(text).set_placement((ox + dx, dy))
        msp.add_text('پشت بام پلان معماری').set_placement((120, 0))
        msp.add_text('بام').set_placement((125, 8))
        msp.add_text('P.V.C 110 RD').set_placement((124, 11))
        msp.add_text('P.V.C 110 RD').set_placement((129, 11))
        doc.saveas(path)

    def test_reference_profile_issues_exact_21_through_production_wrapper(self):
        occupied = ['همکف', 'طبقه اول', 'طبقه دوم']
        scope = {
            'all_levels': occupied + ['پشت بام'],
            'conditioned_levels': occupied, 'heated_levels': occupied,
            'wet_fixture_levels': occupied, 'sanitary_fixture_levels': occupied,
            'ventilation_required_levels': occupied, 'gas_consumer_levels': occupied,
            'roof_exists': True, 'roof_level_name': 'پشت بام',
            'vertical_systems': True, 'typical_groups': [],
        }
        approved = approve_drawing_set(predict_drawing_set(scope))
        manifest = approved['approved_manifest']
        self.assertEqual(manifest['total_sheets'], 21)

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'architecture.dxf'
            dst = Path(td) / 'mechanical.dxf'
            self._build_architecture(src)
            calc = {
                '_approved_drawing_manifest': manifest,
                '_design_inputs': full_inputs(),
                '_plan_analysis': {'architectural_auto': {'estimated_route_length_m': 75.0}},
                'design_water_flow_lps': 1.2,
                'cooling_load_kw': 24.0,
                'heating_load_kw': 18.0,
            }
            meta = production.design_dxf_v10_5(src, dst, 'mechanical', SYSTEMS, 1, calc)
            out = ezdxf.readfile(dst)
            actual = [x.name for x in out.layouts if x.name.startswith('M-')]
            expected = [x['code'] for x in manifest['sheets']]
            self.assertEqual(actual, expected)
            self.assertEqual(len(actual), 21)
            self.assertEqual(meta['final_engineering_qa']['status'], 'PASS')
            self.assertEqual(meta['technical_quality']['score_10'], 10.0)
            self.assertEqual(len(out.audit().errors), 0)
            self.assertNotIn('M-RISER-CALC', actual)


if __name__ == '__main__':
    unittest.main()
