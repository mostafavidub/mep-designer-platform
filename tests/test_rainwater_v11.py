import unittest
import ezdxf

from cad_engine import main_v10_4 as v10_4
from cad_engine.rainwater_v11 import install, validate_rainwater


class RainwaterV11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install(v10_4)

    def _doc(self):
        doc=ezdxf.new('R2013')
        for layer in ('ENGITOOLS-M-ROOF_RAINWATER','ENGITOOLS-M-RAINWATER','ENGITOOLS-M-MECHANICAL_RISERS','ENGITOOLS-M-NOTES'):
            if layer not in doc.layers: doc.layers.add(layer)
        v10_4._ensure_symbol_blocks(doc)
        return doc

    def test_roof_drains_get_connected_routes_and_qa(self):
        doc=self._doc()
        level={'level':'Roof','title':{'point':(0.0,0.0)},'rooms':[],'fixtures':[],'roof_drains':[{'point':(1.0,1.0)},{'point':(8.0,1.0)}]}
        model={'roof_drain_dn_mm':90,'roof_flow_lps':2.2,'roof_drain_count':2}
        v10_4._add_standard_symbols(doc,[level],model)
        report=validate_rainwater(doc,{'sheets':[{'family':'roof_rainwater','code':'M-R-01'}]},model)
        self.assertEqual(report['status'],'PASS')
        msp=doc.modelspace()
        self.assertGreaterEqual(sum(1 for e in msp.query('LINE') if e.dxf.layer=='ENGITOOLS-M-ROOF_RAINWATER'),4)
        self.assertEqual(sum(1 for e in msp.query('INSERT') if e.dxf.name=='ET_M_ROOF_DRAIN'),2)

    def test_no_roof_family_is_not_blocked(self):
        self.assertEqual(validate_rainwater(self._doc(),{'sheets':[{'family':'heating'}]},{} )['status'],'NOT_APPLICABLE')


if __name__=='__main__': unittest.main()
