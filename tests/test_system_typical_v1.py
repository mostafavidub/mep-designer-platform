import unittest

from app.system_typical_v1 import build_system_typical_groups, install
from app import mechanical_drawing_set as planner


class SystemTypicalV1Tests(unittest.TestCase):
    def _auto(self):
        sig = ((('bath', 1), ('bedroom', 1), ('kitchen', 1), ('shaft', 1)), (('bath', .2, .2), ('bedroom', .8, .2), ('kitchen', .2, .8), ('shaft', .5, .5)), True)
        return {
            'level_profiles': [
                {'name': 'L1', 'roof': False, 'typical_signature': sig, 'typical_confidence': 'high', 'wet_fixture_candidate': True, 'sanitary_candidate': True, 'conditioned_candidate': True, 'gas_candidate': True, 'ventilation_candidate': True},
                {'name': 'L2', 'roof': False, 'typical_signature': sig, 'typical_confidence': 'high', 'wet_fixture_candidate': True, 'sanitary_candidate': True, 'conditioned_candidate': True, 'gas_candidate': True, 'ventilation_candidate': True},
            ],
            'typical_groups': [{'name': 'Typical L1/L2', 'levels': ['L1', 'L2'], 'confidence': 'high'}],
            'fixture_detections': [
                {'level': 'L1', 'type': 'toilet', 'status': 'detected'},
                {'level': 'L2', 'type': 'toilet', 'status': 'detected'},
            ],
            'equipment_detections': [],
        }

    def test_identical_system_evidence_allows_grouping(self):
        groups = build_system_typical_groups(self._auto())
        self.assertEqual(groups['water_supply'][0]['levels'], ['L1', 'L2'])
        self.assertEqual(groups['sanitary_vent'][0]['levels'], ['L1', 'L2'])

    def test_fixture_distribution_difference_blocks_water_and_sanitary_only(self):
        auto = self._auto()
        auto['fixture_detections'].append({'level': 'L2', 'type': 'sink', 'status': 'detected'})
        groups = build_system_typical_groups(auto)
        self.assertEqual(groups['water_supply'], [])
        self.assertEqual(groups['sanitary_vent'], [])
        self.assertEqual(groups['heating'][0]['levels'], ['L1', 'L2'])
        self.assertEqual(groups['cooling'][0]['levels'], ['L1', 'L2'])

    def test_equipment_difference_blocks_hvac_grouping(self):
        auto = self._auto()
        auto['equipment_detections'] = [
            {'level': 'L1', 'type': 'indoor_unit', 'status': 'detected'},
            {'level': 'L2', 'type': 'indoor_unit', 'status': 'detected'},
            {'level': 'L2', 'type': 'outdoor_unit', 'status': 'detected'},
        ]
        groups = build_system_typical_groups(auto)
        self.assertEqual(groups['heating'], [])
        self.assertEqual(groups['cooling'], [])
        self.assertTrue(groups['water_supply'])

    def test_planner_consumes_family_specific_groups(self):
        class Workflow:
            _system_typical_v1_installed = False
            @staticmethod
            def build_scope(project):
                return project.scope
        workflow = Workflow()
        install(workflow, planner)
        scope = {
            'all_levels': ['L1', 'L2'],
            'conditioned_levels': ['L1', 'L2'], 'heated_levels': ['L1', 'L2'],
            'wet_fixture_levels': ['L1', 'L2'], 'sanitary_fixture_levels': ['L1', 'L2'],
            'ventilation_required_levels': ['L1', 'L2'], 'gas_consumer_levels': ['L1', 'L2'],
            'roof_exists': False, 'vertical_systems': True, 'typical_groups': [],
            'system_typical_groups': {
                'water_supply': [{'name': 'W Typical', 'levels': ['L1', 'L2']}],
                'sanitary_vent': [], 'heating': [], 'cooling': [], 'gas': [], 'ventilation_exhaust': [],
            },
        }
        result = planner.predict_drawing_set(scope)
        self.assertEqual(result['sheet_families']['water_supply']['effective_levels'], ['L1', 'L2'])
        self.assertEqual(result['sheet_families']['water_supply']['sheets'][0]['levels'], ['L1', 'L2'])
        self.assertEqual(result['sheet_families']['heating']['count'], 2)


if __name__ == '__main__':
    unittest.main()
