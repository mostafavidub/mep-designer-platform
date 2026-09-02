import tempfile
import unittest
from pathlib import Path

import ezdxf

from app import mechanical_drawing_set as drawing_planner
from cad_engine import main_v10_5 as production


SYSTEMS = [
    'cold_water', 'hot_water', 'sanitary', 'vent', 'gas',
    'heating_supply', 'heating_return', 'cooling', 'condensate',
    'exhaust_ventilation', 'mechanical_risers',
]


def build_architecture(path):
    doc = ezdxf.new('R2013')
    doc.header['$INSUNITS'] = 4
    msp = doc.modelspace()
    dim = msp.add_linear_dim(base=(0, -2), p1=(0, 0), p2=(8, 0), angle=0)
    dim.render()
    msp.add_text('همکف پلان معماری').set_placement((0, 0))
    for text, point in (
        ('آشپزخانه', (3, 5)), ('حمام', (7, 6)), ('سرویس', (7, 9)),
        ('اتاق خواب', (12, 5)), ('پذیرایی', (12, 11)), ('شفت', (6, 13)),
    ):
        msp.add_text(text).set_placement(point)
    msp.add_text('پشت بام پلان معماری').set_placement((40, 0))
    msp.add_text('بام').set_placement((45, 8))
    msp.add_text('P.V.C 110 RD').set_placement((44, 11))
    msp.add_text('P.V.C 110 RD').set_placement((49, 11))
    doc.saveas(path)


def full_inputs():
    return {
        'questionnaire_evidence_version': '1.0',
        'location': 'Tehran, Iran',
        'heights': '3.20 m floor-to-floor',
        'fixture_schedule': 'sink 2; faucet 2; toilet 1; bath 1',
        'water_source': 'municipal meter, 500 L tank and booster pump',
        'water_service_connection': 'property boundary beside main entrance',
        'water_inlet_pressure': '3.0 bar at meter',
        'water_design_basis': 'PPR; Hazen-Williams C=150; 3.0 bar at meter; maximum loss 20 kPa/100 m',
        'hot_water_system': 'central combi source with return where route length requires',
        'mechanical_shaft_route': 'architectural wet-core shaft',
        'sanitary_outlet': 'municipal sewer at project boundary',
        'sanitary_design_basis': 'uPVC; 2 percent branches; 1 percent mains',
        'gas': 'yes',
        'gas_appliances': 'boiler 24 kW and cooker 10 kW; 21 mbar; meter and regulator at entrance',
        'cooling': 'split',
        'heating': 'radiator',
        'equipment_schedule': 'split units 18000 BTU/hr per conditioned room; outdoor units on roof; radiators per room load',
        'ventilation_design_basis': '500 m3/h; toilets 10 ACH; enclosed zones 6 ACH; make-up air from exterior; discharge above roof',
        'roof_drainage_basis': '120 m2 roof; 110 mm/h design rainfall; 2 drains',
        'local_mechanical_code': 'current Rulebook and city authority basis; no project-specific override',
    }


class Reference13Benchmark(unittest.TestCase):
    def test_synthetic_reference_equivalent_issues_exact_13(self):
        scope = {
            'all_levels': ['همکف', 'پشت بام'],
            'conditioned_levels': ['همکف'], 'heated_levels': ['همکف'],
            'wet_fixture_levels': ['همکف'], 'sanitary_fixture_levels': ['همکف'],
            'ventilation_required_levels': ['همکف'], 'gas_consumer_levels': ['همکف'],
            'roof_exists': True, 'roof_level_name': 'پشت بام',
            'vertical_systems': True, 'typical_groups': [],
        }
        manifest = drawing_planner.predict_drawing_set(scope)['drawing_manifest']
        self.assertEqual(manifest['total_sheets'], 11)

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / 'architecture.dxf'
            dst = Path(td) / 'mechanical.dxf'
            build_architecture(src)
            calc = {
                '_approved_drawing_manifest': manifest,
                '_design_inputs': full_inputs(),
                '_plan_analysis': {'architectural_auto': {'estimated_route_length_m': 30.0}},
                'design_water_flow_lps': 0.7,
                'cooling_load_kw': 8.0,
                'heating_load_kw': 6.0,
            }
            meta = production.design_dxf_v10_5(src, dst, 'mechanical', SYSTEMS, 1, calc)
            out = ezdxf.readfile(dst)
            actual = [x.name for x in out.layouts if x.name.startswith('M-')]
            expected = [x['code'] for x in manifest['sheets']]
            self.assertEqual(actual, expected)
            self.assertEqual(len(actual), 11)
            self.assertEqual(meta['final_engineering_qa']['status'], 'PASS')
            self.assertEqual(meta['technical_quality']['score_10'], 10.0)
            self.assertEqual(len(out.audit().errors), 0)


if __name__ == '__main__':
    unittest.main()
