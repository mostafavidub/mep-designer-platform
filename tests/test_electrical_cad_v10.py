import tempfile
import unittest
from pathlib import Path

import ezdxf

from cad_engine import main_v10_fix as fixed
v10 = fixed.v10


class ElectricalCadV10Tests(unittest.TestCase):
    def _source(self, path):
        doc=ezdxf.new('R2013')
        doc.header['$INSUNITS']=4
        msp=doc.modelspace()
        dim=msp.add_linear_dim(base=(0,1),p1=(0,0),p2=(3,0),angle=0); dim.render()
        msp.add_text('پلان معماری تیپ طبقات اول تا پنجم').set_placement((100,0))
        for text,p in [
            ('آشپزخانه',(98,8)),('اتاق خواب',(96,12)),('هال و پذیرایی',(102,12)),
            ('حمام',(99,6)),('شفت',(100,16)),('آسانسور',(103,16)),
        ]: msp.add_text(text).set_placement(p)
        msp.add_text('پلان جانمایی پارکینگ').set_placement((125,0))
        msp.add_text('پلان معماری پشت بام').set_placement((70,0))
        msp.add_text('بام').set_placement((72,10))
        doc.saveas(path)

    def test_end_to_end_electrical_generates_complete_rulebook_dxf(self):
        systems=['lighting','power','dedicated_loads','fire_alarm','elv','earthing_bonding','panels','single_line_diagram','electrical_risers','electrical_legend_notes']
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'architecture.dxf'; dst=Path(td)/'electrical.dxf'; self._source(src)
            calc={'discipline':'electrical','_design_inputs':{},'professional_verification_required':True}
            meta=v10.design_dxf_v10(src,dst,'electrical',systems,1,calc)
            self.assertTrue(dst.exists())
            self.assertEqual(meta['v10_final_qa']['score_10'],10.0)
            doc=ezdxf.readfile(dst)
            self.assertEqual(len(doc.audit().errors),0)
            names={x.name for x in doc.layouts}
            self.assertIn('E-SLD-RISER',names); self.assertIn('E-SCHEDULE',names)
            self.assertTrue(any(x.startswith('E-L-') for x in names))
            self.assertTrue(any(x.startswith('E-P-') for x in names))
            self.assertTrue(any(x.startswith('E-F-') for x in names))
            self.assertTrue(any(x.startswith('E-D-') for x in names))
            msp=doc.modelspace(); layers={e.dxf.layer for e in msp}
            for layer in ('ENGITOOLS-E-LIGHTING','ENGITOOLS-E-POWER','ENGITOOLS-E-FIRE_ALARM','ENGITOOLS-E-ELV','ENGITOOLS-E-EARTHING_BONDING','ENGITOOLS-E-ELECTRICAL_RISERS'):
                self.assertIn(layer,layers)
            self.assertTrue(any(e.dxftype()=='INSERT' and e.dxf.name=='ET_ELEVATOR_PANEL' for e in msp))

    def test_routes_are_orthogonal(self):
        doc=ezdxf.new('R2013'); msp=doc.modelspace()
        msp.add_lwpolyline([(0,0),(2,0),(2,3)],dxfattribs={'layer':'ENGITOOLS-E-WIRE'})
        self.assertTrue(v10._orthogonal_routes(msp))
        msp.add_lwpolyline([(0,0),(1,1)],dxfattribs={'layer':'ENGITOOLS-E-WIRE'})
        self.assertFalse(v10._orthogonal_routes(msp))


if __name__=='__main__': unittest.main()
