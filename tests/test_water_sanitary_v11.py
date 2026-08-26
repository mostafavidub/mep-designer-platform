import unittest
import ezdxf

from cad_engine import main_v10_4 as v10_4
from cad_engine.water_sanitary_v11 import install


class WaterSanitaryV11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install(v10_4)

    def _doc(self):
        doc = ezdxf.new('R2013')
        for layer in (
            'ENGITOOLS-M-COLD_WATER','ENGITOOLS-M-HOT_WATER','ENGITOOLS-M-SANITARY','ENGITOOLS-M-VENT',
            'ENGITOOLS-M-MECHANICAL_RISERS','ENGITOOLS-M-NOTES','ENGITOOLS-M-MECHANICAL_DETAILS_LEGEND_NOTES'
        ):
            if layer not in doc.layers:
                doc.layers.add(layer)
        v10_4._ensure_symbol_blocks(doc)
        return doc

    def _level(self):
        return {
            'level': 'Ground', 'title': {'point': (0.0, 0.0)},
            'rooms': [
                {'room': 'kitchen', 'point': (2.0, 2.0)},
                {'room': 'bath', 'point': (5.0, 2.0)},
                {'room': 'toilet', 'point': (8.0, 2.0)},
                {'room': 'shaft', 'point': (5.0, 6.0)},
            ],
            'fixtures': [], 'roof_drains': [],
        }

    def test_real_water_and_sanitary_networks_are_required(self):
        doc = self._doc(); level = self._level()
        # Give the riser finder an explicit mechanical riser marker.
        doc.modelspace().add_blockref('ET_M_RISER', (5, 6), dxfattribs={'layer':'ENGITOOLS-M-MECHANICAL_RISERS'})
        model = {'water_main_dn_mm': 25, 'sanitary_slope_pct': 2.0}
        calc = {'_approved_drawing_manifest': {'sheets': [
            {'family':'water_supply'}, {'family':'sanitary_vent'}
        ]}}
        report = v10_4._add_shared_distribution_networks(doc, [level], model, calc)
        self.assertEqual(report['water_sanitary_status'], 'PASS')
        msp = doc.modelspace()
        self.assertGreaterEqual(sum(1 for e in msp.query('LINE') if e.dxf.layer == 'ENGITOOLS-M-COLD_WATER'), 2)
        self.assertGreaterEqual(sum(1 for e in msp.query('LINE') if e.dxf.layer == 'ENGITOOLS-M-SANITARY'), 2)
        self.assertGreaterEqual(sum(1 for e in msp.query('LINE') if e.dxf.layer == 'ENGITOOLS-M-HOT_WATER'), 1)
        self.assertGreaterEqual(len([e for e in msp.query('INSERT') if e.dxf.name == 'ET_M_CLEANOUT']), 1)
        self.assertGreaterEqual(len([e for e in msp.query('INSERT') if e.dxf.name == 'ET_M_ISOLATION_VALVE']), 1)

    def test_non_applicable_families_are_not_blocked(self):
        doc = self._doc()
        report = v10_4._add_shared_distribution_networks(
            doc, [self._level()], {'water_main_dn_mm':25,'sanitary_slope_pct':2.0},
            {'_approved_drawing_manifest': {'sheets':[{'family':'heating'}]}},
        )
        self.assertEqual(report['water_sanitary_status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
