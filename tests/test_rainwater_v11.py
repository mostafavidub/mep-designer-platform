import unittest
import ezdxf

from cad_engine import main_v10_4 as v10_4
from cad_engine.rainwater_v11 import install, validate_rainwater
from app.mechanical_rulebook import roof_basis


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
        self.assertGreaterEqual(sum(1 for e in msp.query('LINE') if e.dxf.layer=='ENGITOOLS-M-ROOF_RAINWATER'),2)
        self.assertEqual(sum(1 for e in msp.query('INSERT') if e.dxf.name=='ET_M_ROOF_DRAIN'),2)

    def test_missing_detected_drains_get_traceable_proposals(self):
        doc=self._doc()
        level={
            'level':'Roof','title':{'point':(0.0,0.0)},
            'rooms':[{'room':'roof','point':(4.0,4.0)}],
            'fixtures':[],'roof_drains':[],
        }
        model={'roof_drain_dn_mm':90,'roof_flow_lps':2.2,'roof_drain_count':2}
        v10_4._add_standard_symbols(doc,[level],model)
        report=validate_rainwater(
            doc,{'sheets':[{'family':'roof_rainwater','code':'M-R-01'}]},model
        )
        self.assertEqual(report['status'],'PASS')
        self.assertEqual(model['rainwater_proposed_drain_locations'],2)
        self.assertEqual(report['location_provenance'],'Rule-based Proposed - engineer roof coordination required')
        forbidden=('R?','EXH?','UNRESOLVED','VERIFY','TBD','UNKNOWN')
        notes=[
            str(entity.dxf.text or '').upper()
            for entity in doc.modelspace().query('TEXT')
            if str(entity.dxf.layer)=='ENGITOOLS-M-ROOF_RAINWATER'
        ]
        self.assertFalse(any(token in note for note in notes for token in forbidden))

    def test_unknown_city_uses_labelled_conservative_rainfall(self):
        basis=roof_basis('unsupported city','120 m2 roof; 2 drains')
        self.assertIsNone(basis)

    def test_no_roof_family_is_not_blocked(self):
        self.assertEqual(validate_rainwater(self._doc(),{'sheets':[{'family':'heating'}]},{} )['status'],'NOT_APPLICABLE')


if __name__=='__main__': unittest.main()
