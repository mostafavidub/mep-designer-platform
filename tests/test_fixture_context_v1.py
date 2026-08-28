import unittest

from app.fixture_context_v1 import enrich_fixture_context


class FixtureContextV1Tests(unittest.TestCase):
    def test_polygon_room_assignment_and_level_schedule(self):
        auto = {
            'architecture_model': {'levels': [{
                'name': 'Ground', 'region_bounds': [0, 0, 20, 20], 'title_point': [10, -2],
                'rooms': [
                    {'id': 'L01-R001', 'type': 'kitchen', 'center': [5, 5], 'bounds': [0, 0, 10, 10],
                     'polygon': [[0,0],[10,0],[10,10],[0,10]]},
                    {'id': 'L01-R002', 'type': 'bath', 'center': [15, 5], 'bounds': [10, 0, 20, 10],
                     'polygon': [[10,0],[20,0],[20,10],[10,10]]},
                ],
                'wet_cores': [{'id': 'L01-WC01', 'room_ids': ['L01-R001','L01-R002']}],
            }]},
            'fixture_detections': [
                {'category': 'fixture', 'type': 'sink', 'x': 4, 'y': 4, 'status': 'detected', 'confidence': .92},
                {'category': 'fixture', 'type': 'toilet', 'x': 15, 'y': 4, 'status': 'detected', 'confidence': .92},
            ],
            'equipment_detections': [
                {'category': 'equipment', 'type': 'gas_cooker', 'x': 6, 'y': 6, 'status': 'detected', 'confidence': .92},
            ],
        }
        result = enrich_fixture_context(auto)
        sink = result['fixture_detections'][0]
        toilet = result['fixture_detections'][1]
        cooker = result['equipment_detections'][0]
        self.assertEqual(sink['room_id'], 'L01-R001')
        self.assertEqual(sink['room_type'], 'kitchen')
        self.assertEqual(toilet['room_id'], 'L01-R002')
        self.assertEqual(cooker['room_id'], 'L01-R001')
        self.assertEqual(sink['wet_core_id'], 'L01-WC01')
        self.assertEqual(result['fixture_equipment_model']['room_assigned_detected_count'], 3)
        level = result['fixture_equipment_model']['levels'][0]
        self.assertEqual(level['fixture_counts']['sink'], 1)
        self.assertEqual(level['fixture_counts']['toilet'], 1)
        self.assertEqual(level['equipment_counts']['gas_cooker'], 1)

    def test_far_item_does_not_get_false_room_assignment(self):
        auto = {
            'architecture_model': {'levels': [{
                'name': 'Ground', 'region_bounds': [0, 0, 10, 10], 'title_point': [5, -2],
                'rooms': [{'id': 'R1', 'type': 'kitchen', 'center': [2, 2], 'bounds': [0,0,4,4], 'polygon': None}],
                'wet_cores': [],
            }]},
            'fixture_detections': [{'category':'fixture','type':'sink','x':9.8,'y':9.8,'status':'detected','confidence':.9}],
            'equipment_detections': [],
        }
        result = enrich_fixture_context(auto)
        self.assertIsNone(result['fixture_detections'][0].get('room_id'))
        self.assertEqual(result['fixture_equipment_model']['levels'][0]['unassigned_detected_count'], 1)


if __name__ == '__main__':
    unittest.main()
