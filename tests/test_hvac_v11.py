import unittest
import ezdxf

from cad_engine import main_v10_4 as v10_4
from cad_engine.water_sanitary_v11 import install as install_water_sanitary
from cad_engine.gas_v11 import install as install_gas
from cad_engine.hvac_v11 import install as install_hvac


class HVACV11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_water_sanitary(v10_4); install_gas(v10_4); install_hvac(v10_4)

    def _doc(self):
        doc=ezdxf.new('R2013')
        for layer in ('ENGITOOLS-M-HEATING_SUPPLY','ENGITOOLS-M-HEATING_RETURN','ENGITOOLS-M-COOLING','ENGITOOLS-M-CONDENSATE','ENGITOOLS-M-EXHAUST_VENTILATION','ENGITOOLS-M-MECHANICAL_RISERS','ENGITOOLS-M-NOTES'):
            if layer not in doc.layers: doc.layers.add(layer)
        v10_4._ensure_symbol_blocks(doc)
        return doc

    def test_hvac_and_ventilation_are_connected_and_resolved(self):
        doc=self._doc(); msp=doc.modelspace(); msp.add_blockref('ET_M_RISER',(5,6),dxfattribs={'layer':'ENGITOOLS-M-MECHANICAL_RISERS'})
        level={'level':'Ground','title':{'point':(0.0,0.0)},'rooms':[{'room':'living','point':(2.0,2.0)},{'room':'bedroom','point':(8.0,2.0)},{'room':'toilet','point':(2.0,5.0)},{'room':'shaft','point':(5.0,6.0)}],'fixtures':[],'roof_drains':[]}
        model={'water_main_dn_mm':25,'sanitary_slope_pct':2.0,'heating_load_kw':8.0,'cooling_load_kw':10.0,'per_room_heating_kw':{'living':4,'bedroom':4},'per_room_cooling_kw':{'living':5,'bedroom':5},'ventilation_airflow_m3h':180}
        calc={'_approved_drawing_manifest':{'sheets':[{'family':'heating'},{'family':'cooling'},{'family':'ventilation_exhaust'}]},'_design_inputs':{'gas':'no'}}
        report=v10_4._add_shared_distribution_networks(doc,[level],model,calc)
        self.assertEqual(report['hvac_ventilation_status'],'PASS')
        for layer in ('ENGITOOLS-M-HEATING_SUPPLY','ENGITOOLS-M-HEATING_RETURN','ENGITOOLS-M-COOLING','ENGITOOLS-M-CONDENSATE','ENGITOOLS-M-EXHAUST_VENTILATION'):
            self.assertGreaterEqual(sum(1 for e in msp.query('LINE') if e.dxf.layer==layer),1,layer)
        names=[e.dxf.name for e in msp.query('INSERT')]
        self.assertIn('ET_M_MAKEUP_AIR',names); self.assertIn('ET_M_AIR_DISCHARGE',names)

    def test_unrelated_family_not_blocked(self):
        doc=self._doc()
        report=v10_4._add_shared_distribution_networks(doc,[],{'water_main_dn_mm':25,'sanitary_slope_pct':2.0},{'_approved_drawing_manifest':{'sheets':[{'family':'water_supply'}]},'_design_inputs':{'gas':'no'}})
        self.assertEqual(report['hvac_ventilation_status'],'PASS')


if __name__=='__main__': unittest.main()
