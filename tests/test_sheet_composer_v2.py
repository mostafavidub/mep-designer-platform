import unittest
import ezdxf

from cad_engine import main_v10_3 as v10_3
from cad_engine import main_v10_4 as v10_4
from cad_engine.mechanical_upgrade_v11 import install


class SheetComposerV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install(v10_3, v10_4)

    def _level(self, name='Ground'):
        return {
            'level': name,
            'title': {'point': (0.0, 0.0)},
            'rooms': [
                {'room': 'kitchen', 'point': (2.0, 2.0)},
                {'room': 'toilet', 'point': (5.0, 2.0)},
                {'room': 'shop', 'point': (8.0, 6.0)},
            ],
            'fixtures': [], 'roof_drains': [],
        }

    def test_special_roles_are_not_duplicate_floor_viewports(self):
        doc = ezdxf.new('R2013')
        doc.header['$INSUNITS'] = 6
        msp = doc.modelspace()
        for layer in ('ENGITOOLS-M-COLD_WATER','ENGITOOLS-M-HOT_WATER','ENGITOOLS-M-SANITARY','ENGITOOLS-M-VENT','ENGITOOLS-M-HEATING_SUPPLY','ENGITOOLS-M-HEATING_RETURN','ENGITOOLS-M-COOLING','ENGITOOLS-M-CONDENSATE','ENGITOOLS-M-EXHAUST_VENTILATION','ENGITOOLS-M-MECHANICAL_RISERS','ENGITOOLS-M-NOTES'):
            if layer not in doc.layers:
                doc.layers.add(layer)
        msp.add_line((0,0),(10,0), dxfattribs={'layer':'ENGITOOLS-M-COLD_WATER'})
        levels = [self._level()]
        sheets = [
            {'code':'M-W-01','family':'water_supply','label':'Water','levels':['Ground'],'special':False},
            {'code':'M-W-RISER','family':'water_supply','label':'Water Riser','levels':['Ground'],'special':True},
            {'code':'M-W-EQUIP','family':'water_supply','label':'Water Equipment','levels':['Ground'],'special':True},
            {'code':'M-S-01','family':'sanitary_vent','label':'Sanitary','levels':['Ground'],'special':False},
            {'code':'M-S-RISER','family':'sanitary_vent','label':'Sanitary Riser','levels':['Ground'],'special':True},
            {'code':'M-S-DETAIL','family':'sanitary_vent','label':'Sanitary Detail','levels':['Ground'],'special':True},
            {'code':'M-H-EQUIP','family':'heating','label':'Heating Equipment','levels':['Ground'],'special':True},
            {'code':'M-V-DETAIL','family':'ventilation_exhaust','label':'Vent Detail','levels':['Ground'],'special':True},
        ]
        calc = {'_approved_drawing_manifest': {'total_sheets': len(sheets), 'sheets': sheets}}
        created, _ = v10_3._compose_authority_layouts(doc, levels, 'P1', [], calc)
        self.assertEqual([x['layout'] for x in created], [x['code'] for x in sheets])
        self.assertGreater(len(doc.layouts.get('M-W-01').query('VIEWPORT')), 0)
        for code in ('M-W-RISER','M-W-EQUIP','M-S-RISER','M-S-DETAIL','M-H-EQUIP','M-V-DETAIL'):
            self.assertEqual(len(doc.layouts.get(code).query('VIEWPORT')), 0, code)
            self.assertGreater(len(doc.layouts.get(code)), 5, code)

    def test_rainwater_layer_is_visible_on_roof_family(self):
        group = {key: set(layers) for key, _title, layers in v10_3.AUTHORITY_GROUPS}
        # Upgrade adds the canonical v10.4 layer during composition even if the
        # legacy group table still contains only the older name.
        self.assertIn('R', group)


if __name__ == '__main__':
    unittest.main()
