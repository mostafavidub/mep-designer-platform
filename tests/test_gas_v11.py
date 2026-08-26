import unittest
import ezdxf

from cad_engine import main_v10_4 as v10_4
from cad_engine.water_sanitary_v11 import install as install_water_sanitary
from cad_engine.gas_v11 import install as install_gas


class GasV11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_water_sanitary(v10_4)
        install_gas(v10_4)

    def _doc(self):
        doc = ezdxf.new('R2013')
        for layer in ('ENGITOOLS-M-GAS','ENGITOOLS-M-MECHANICAL_RISERS','ENGITOOLS-M-NOTES'):
            if layer not in doc.layers:
                doc.layers.add(layer)
        v10_4._ensure_symbol_blocks(doc)
        return doc

    def _level(self):
        return {
            'level':'Ground','title':{'point':(0.0,0.0)},
            'rooms':[{'room':'kitchen','point':(2.0,2.0)},{'room':'shaft','point':(5.0,6.0)}],
            'fixtures':[], 'roof_drains':[],
        }

    def test_gas_enabled_builds_meter_regulator_valve_and_network(self):
        doc = self._doc(); doc.modelspace().add_blockref('ET_M_RISER',(5,6),dxfattribs={'layer':'ENGITOOLS-M-MECHANICAL_RISERS'})
        model = {'gas_load_kw':34.0,'gas_flow_m3h':3.58,'gas_pressure_mbar':21.0,'gas_main_dn_mm':25,'gas_meter_regulator_defined':True,'water_main_dn_mm':25,'sanitary_slope_pct':2.0}
        calc = {'_approved_drawing_manifest':{'sheets':[{'family':'gas'}]},'_design_inputs':{'gas':'yes'}}
        report = v10_4._add_shared_distribution_networks(doc,[self._level()],model,calc)
        self.assertEqual(report['gas_network_status'],'PASS')
        msp=doc.modelspace()
        self.assertGreaterEqual(sum(1 for e in msp.query('LINE') if e.dxf.layer=='ENGITOOLS-M-GAS'),1)
        names=[e.dxf.name for e in msp.query('INSERT')]
        self.assertIn('ET_M_GAS_METER',names)
        self.assertIn('ET_M_GAS_REGULATOR',names)
        self.assertIn('ET_M_GAS_VALVE',names)

    def test_explicit_no_gas_is_not_blocked(self):
        doc=self._doc()
        report=v10_4._add_shared_distribution_networks(doc,[self._level()],{'water_main_dn_mm':25,'sanitary_slope_pct':2.0},{'_approved_drawing_manifest':{'sheets':[{'family':'gas'}]},'_design_inputs':{'gas':'بدون گاز'}})
        self.assertEqual(report['gas_network_status'],'NOT_APPLICABLE')


if __name__=='__main__':
    unittest.main()
