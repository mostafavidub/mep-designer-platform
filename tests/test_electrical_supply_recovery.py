import unittest

from app.electrical_basis_contract import normalize_answers
from cad_engine.electrical_v1.production import build_engine_config
import cad_engine.electrical_api as electrical_api


class ElectricalSupplyRecoveryTests(unittest.TestCase):
    def test_hyphenated_phase_supply_parses_phase_and_voltage(self):
        raw = '1-PHASE 220V/N/PE 50HZ'
        normalized = normalize_answers({'supply_configuration': raw})
        self.assertEqual(normalized['supply_configuration']['configuration'], 'single_phase')
        self.assertEqual(normalized['supply_configuration']['voltage_v'], 220.0)

        cfg = build_engine_config({'supply_configuration': raw}, {})
        self.assertEqual(cfg['design_basis']['phase_configuration'], 'single_phase')
        self.assertEqual(cfg['design_basis']['supply_voltage_v'], 220.0)

    def test_three_phase_notation_does_not_treat_phase_count_as_voltage(self):
        normalized = normalize_answers({'supply_configuration': '3-PHASE 400V/N/PE 50HZ'})
        self.assertEqual(normalized['supply_configuration']['configuration'], 'three_phase')
        self.assertEqual(normalized['supply_configuration']['voltage_v'], 400.0)

    def test_coarse_supply_warning_reopens_only_unresolved_basis(self):
        report = {
            'data': {'basis': {'values': {
                'supply_voltage_v': {'status': 'FINAL', 'value': 220},
                'phase_configuration': {'status': 'INPUT_REQUIRED', 'value': None},
                'utility_service': {'status': 'FINAL', 'value': 'approved service'},
            }}},
            'gates': {'PHASE_BALANCE': {'warnings': ['supply_voltage_or_phase_configuration_missing']}},
        }
        missing = electrical_api._missing_inputs(report)
        self.assertIn('supply_configuration', missing)
        self.assertNotIn('supply_voltage_v', missing)


if __name__ == '__main__':
    unittest.main()
