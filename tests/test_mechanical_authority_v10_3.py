import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine import main_v10_3 as authority


class MechanicalAuthorityV103Tests(unittest.TestCase):
    def _build_reference_architecture(self, path):
        doc = ezdxf.new('R2013')
        doc.header['$INSUNITS'] = 4
        msp = doc.modelspace()
        dim = msp.add_linear_dim(base=(0, -2), p1=(0, 0), p2=(3, 0), angle=0)
        dim.render()
        for name, ox in [('همکف', 0), ('طبقه اول', 40), ('طبقه دوم', 80)]:
            msp.add_text(f'{name} پلان معماری').set_placement((ox, 0))
            msp.add_text('آشپزخانه').set_placement((ox + 3, 6))
            msp.add_text('حمام').set_placement((ox + 7, 7))
            msp.add_text('سرویس').set_placement((ox + 7, 10))
            msp.add_text('اتاق خواب').set_placement((ox + 12, 6))
            msp.add_text('پذیرایی').set_placement((ox + 11, 12))
            msp.add_text('شفت').set_placement((ox + 6, 13))
        msp.add_text('پشت بام پلان معماری').set_placement((120, 0))
        msp.add_text('بام').set_placement((125, 8))
        msp.add_text('P.V.C 110 RD').set_placement((124, 11))
        doc.saveas(path)

    def test_reference_profile_issues_21_separate_authority_sheets(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'architecture.dxf'
            dst = Path(td) / 'mechanical.dxf'
            self._build_reference_architecture(src)
            systems = [
                'cold_water', 'hot_water', 'sanitary', 'vent', 'gas',
                'heating_supply', 'heating_return', 'cooling', 'condensate',
                'exhaust_ventilation', 'mechanical_risers',
            ]
            calc = {
                '_design_inputs': {'gas': 'بله', 'cooling': 'split', 'heating': 'radiator'},
                'design_water_flow_lps': 0.7,
                'preliminary_nominal_pipe_candidate_mm': 25,
                'cooling_load_kw': 15.0,
                'heating_load_kw': 12.0,
            }
            meta = authority.design_dxf_v10_3(src, dst, 'mechanical', systems, 1, calc)
            out = ezdxf.readfile(dst)
            names = [x.name for x in out.layouts if x.name.startswith('M-')]
            self.assertEqual(len(names), meta['authority_submission']['layout_count'])
            self.assertEqual(len(names), 21)
            self.assertEqual(meta['authority_submission']['counts'], {
                'W': 4, 'S': 3, 'H': 3, 'C': 4, 'G': 3, 'V': 3, 'R': 1,
            })
            self.assertEqual(len(out.audit().errors), 0)
            self.assertNotIn('M-RISER-CALC', names)
            self.assertFalse(any(x.startswith('M-P-') for x in names))
            for prefix in ('M-W-', 'M-S-', 'M-H-', 'M-C-', 'M-G-', 'M-V-', 'M-R-'):
                self.assertTrue(any(x.startswith(prefix) for x in names), prefix)


if __name__ == '__main__':
    unittest.main()
