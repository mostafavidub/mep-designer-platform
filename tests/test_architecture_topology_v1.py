import unittest

from app.architecture_topology_v1 import enrich_architecture_topology


class ArchitectureTopologyV1Tests(unittest.TestCase):
    def test_builds_room_relations_wet_cores_and_equipment_zones(self):
        auto = {
            'architecture_model': {
                'levels': [{
                    'name': 'Ground', 'roof': False, 'region_bounds': [0, 0, 20, 20], 'title_point': [10, -2],
                    'rooms': [
                        {'type': 'kitchen', 'label_point': [4, 4], 'bounds': [1, 1, 8, 8]},
                        {'type': 'bath', 'label_point': [9, 4], 'bounds': [8, 1, 12, 8]},
                        {'type': 'bedroom', 'label_point': [16, 12], 'bounds': [12, 8, 20, 20]},
                    ],
                    'doors': [{'bounds': [7.8, 3, 8.2, 4], 'centroid': [8, 3.5]}],
                    'windows': [{'bounds': [14, 19, 16, 19.2], 'centroid': [15, 19.1]}],
                    'shafts': [{'bounds': [10, 3, 11, 4], 'centroid': [10.5, 3.5]}],
                    'stairs': [{'bounds': [0, 10, 3, 16], 'centroid': [1.5, 13]}],
                    'columns': [{'bounds': [13, 9, 14, 10], 'centroid': [13.5, 9.5]}],
                }]
            }
        }
        result = enrich_architecture_topology(auto)
        level = result['architecture_model']['levels'][0]
        self.assertEqual(len(level['rooms']), 3)
        self.assertGreaterEqual(len(level['wet_cores']), 1)
        self.assertEqual(len(level['equipment_candidate_zones']), 2)
        self.assertTrue(level['rooms'][0]['nearest_shaft_id'])
        self.assertTrue(level['doors'][0].get('nearest_room_id'))
        self.assertTrue(level['windows'][0].get('nearest_room_id'))
        self.assertEqual(result['architecture_model']['wet_core_count'], len(level['wet_cores']))

    def test_roof_gets_service_zone_even_without_rooms(self):
        auto = {'architecture_model': {'levels': [{
            'name': 'Roof', 'roof': True, 'region_bounds': [0, 0, 15, 10], 'title_point': [7, -2],
            'rooms': [], 'doors': [], 'windows': [], 'shafts': [], 'stairs': [], 'columns': [],
        }]}}
        result = enrich_architecture_topology(auto)
        zones = result['architecture_model']['levels'][0]['equipment_candidate_zones']
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0]['kind'], 'roof_service_zone')


if __name__ == '__main__':
    unittest.main()
