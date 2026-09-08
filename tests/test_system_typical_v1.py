import unittest

from app.system_typical_v1 import build_system_typical_groups, install
from app import mechanical_drawing_set as planner


class SystemTypicalV1Tests(unittest.TestCase):
    def _auto(self, levels=('L1', 'L2')):
        sig = ((('bath', 1), ('bedroom', 1), ('kitchen', 1), ('shaft', 1)), (('bath', .2, .2), ('bedroom', .8, .2), ('kitchen', .2, .8), ('shaft', .5, .5)), True)
        profiles = []
        model_levels = []
        fixtures = []
        equipment = []
        for index, level in enumerate(levels):
            profiles.append({
                'name': level, 'roof': False, 'typical_signature': sig, 'typical_confidence': 'high',
                'wet_fixture_candidate': True, 'sanitary_candidate': True, 'conditioned_candidate': True,
                'gas_candidate': True, 'ventilation_candidate': True,
            })
            x0 = index * 100.0
            model_levels.append({
                'name': level, 'region_bounds': [x0, 0, x0 + 20, 20],
                'shafts': [{'centroid': [x0 + 10, 10]}],
            })
            fixtures.append({'level': level, 'type': 'toilet', 'status': 'detected', 'x': x0 + 4, 'y': 4})
            equipment.extend([
                {'level': level, 'type': 'radiator', 'status': 'detected', 'x': x0 + 16, 'y': 4},
                {'level': level, 'type': 'split_indoor', 'status': 'detected', 'x': x0 + 15, 'y': 15},
                {'level': level, 'type': 'gas_cooker', 'status': 'detected', 'x': x0 + 5, 'y': 15},
                {'level': level, 'type': 'exhaust_fan', 'status': 'detected', 'x': x0 + 4, 'y': 5},
            ])
        return {
            'level_profiles': profiles,
            'architecture_model': {'levels': model_levels},
            'typical_groups': [{'name': 'Typical ' + '/'.join(levels), 'levels': list(levels), 'confidence': 'high'}],
            'fixture_detections': fixtures,
            'equipment_detections': equipment,
        }

    def test_identical_system_evidence_allows_grouping(self):
        groups = build_system_typical_groups(self._auto())
        for family in ('water_supply', 'sanitary_vent', 'heating', 'cooling', 'gas', 'ventilation_exhaust'):
            self.assertEqual(groups[family][0]['levels'], ['L1', 'L2'], family)

    def test_fixture_distribution_difference_blocks_water_and_sanitary_only(self):
        auto = self._auto()
        auto['fixture_detections'].append({'level': 'L2', 'type': 'sink', 'status': 'detected', 'x': 106, 'y': 5})
        groups = build_system_typical_groups(auto)
        self.assertEqual(groups['water_supply'], [])
        self.assertEqual(groups['sanitary_vent'], [])
        self.assertEqual(groups['heating'][0]['levels'], ['L1', 'L2'])
        self.assertEqual(groups['cooling'][0]['levels'], ['L1', 'L2'])

    def test_equipment_difference_blocks_only_relevant_family(self):
        auto = self._auto()
        auto['equipment_detections'].append({'level': 'L2', 'type': 'split_outdoor', 'status': 'detected', 'x': 118, 'y': 18})
        groups = build_system_typical_groups(auto)
        self.assertEqual(groups['cooling'], [])
        self.assertTrue(groups['heating'])
        self.assertTrue(groups['water_supply'])

    def test_same_count_but_different_normalized_position_blocks_typical(self):
        auto = self._auto()
        for row in auto['equipment_detections']:
            if row['level'] == 'L2' and row['type'] == 'split_indoor':
                row['x'], row['y'] = 102, 18
        groups = build_system_typical_groups(auto)
        self.assertEqual(groups['cooling'], [])
        self.assertTrue(groups['heating'])

    def test_missing_family_evidence_never_falls_back_to_geometry_only(self):
        auto = self._auto()
        auto['equipment_detections'] = [r for r in auto['equipment_detections'] if r['type'] != 'split_indoor']
        groups = build_system_typical_groups(auto)
        self.assertEqual(groups['cooling'], [])
        self.assertTrue(groups['water_supply'])

    def test_large_architectural_typical_is_partitioned_by_cooling_evidence(self):
        auto = self._auto(('L1', 'L2', 'L3', 'L4', 'L5'))
        # Floors 1-3: one IDU at the same normalized position. Floors 4-5:
        # two IDUs, also mutually identical. This must produce two cooling
        # typical groups instead of either L1-L5 or five separate false peers.
        auto['equipment_detections'] = [r for r in auto['equipment_detections'] if r['type'] != 'split_indoor']
        for index, level in enumerate(('L1', 'L2', 'L3', 'L4', 'L5')):
            x0 = index * 100.0
            auto['equipment_detections'].append({'level': level, 'type': 'split_indoor', 'status': 'detected', 'x': x0 + 15, 'y': 15})
            if level in {'L4', 'L5'}:
                auto['equipment_detections'].append({'level': level, 'type': 'split_indoor', 'status': 'detected', 'x': x0 + 5, 'y': 15})
        groups = build_system_typical_groups(auto)
        partitions = [g['levels'] for g in groups['cooling']]
        self.assertIn(['L1', 'L2', 'L3'], partitions)
        self.assertIn(['L4', 'L5'], partitions)
        self.assertNotIn(['L1', 'L2', 'L3', 'L4', 'L5'], partitions)
        self.assertTrue(all(g['partitioned'] for g in groups['cooling']))

    def test_planner_consumes_family_specific_groups_and_empty_is_authoritative(self):
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
            'roof_exists': False, 'vertical_systems': True,
            # Generic group must NOT leak into heating when family-specific
            # evidence says the floors are not equivalent.
            'typical_groups': [{'name': 'Generic Typical', 'levels': ['L1', 'L2']}],
            'system_typical_groups': {
                'water_supply': [{'name': 'W Typical', 'levels': ['L1', 'L2']}],
                'sanitary_vent': [], 'heating': [], 'cooling': [], 'gas': [], 'ventilation_exhaust': [],
            },
        }
        result = planner.predict_drawing_set(scope)
        self.assertEqual(result['sheet_families']['water_supply']['sheets'][0]['levels'], ['L1', 'L2'])
        heating_floor_sheets = [s for s in result['sheet_families']['heating']['sheets'] if s.get('drawing_type') == 'floor_plan']
        self.assertEqual([s['levels'] for s in heating_floor_sheets], [['L1'], ['L2']])


if __name__ == '__main__':
    unittest.main()
