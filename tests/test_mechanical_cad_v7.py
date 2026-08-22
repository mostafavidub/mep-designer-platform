import unittest

import ezdxf

from cad_engine import main_v6 as v6
from cad_engine import main_v7 as v7


class MechanicalCadV7RegressionTests(unittest.TestCase):
    def test_same_room_type_close_coordinates_are_not_collapsed(self):
        doc = ezdxf.new('R2013')
        msp = doc.modelspace()
        msp.add_text('حمام', dxfattribs={'height': 0.2}).set_placement((0, 0))
        msp.add_text('حمام', dxfattribs={'height': 0.2}).set_placement((10, 0))
        detector = getattr(v6, 'detect_room_labels_spatial')
        rooms = detector(msp)
        self.assertEqual(len([x for x in rooms if x['room'] == 'bath']), 2)

    def test_every_fixture_is_assigned_once_to_a_wet_room(self):
        room_a = {'room': 'kitchen', 'point': (0.0, 0.0)}
        room_b = {'room': 'toilet', 'point': (10.0, 0.0)}
        level = {
            'rooms': [room_a, room_b],
            'fixtures': [
                {'kind': 'sink', 'point': (1.0, 0.0), 'block': 'SINK'},
                {'kind': 'gas', 'point': (2.0, 0.0), 'block': 'GAS'},
                {'kind': 'toilet', 'point': (9.0, 0.0), 'block': 'WC'},
            ],
        }
        assigned, unassigned = v7._assign_fixtures(level)
        self.assertEqual(len(unassigned), 0)
        self.assertEqual(sum(len(items) for items in assigned.values()), 3)
        self.assertEqual(len(assigned[id(room_a)]), 2)
        self.assertEqual(len(assigned[id(room_b)]), 1)

    def test_qa_gate_rejects_silent_fixture_loss(self):
        levels = [{'rooms': [{'room': 'kitchen', 'point': (0, 0)}]}]
        stats = {
            'level_count': 1, 'rooms': 1, 'cold_water': 1, 'sanitary': 1,
            'mechanical_risers': 1, 'cleanouts': 1, 'room_proxy_connections': 0,
        }
        qa = {
            'fixtures_expected': 2, 'fixtures_connected': 1,
            'wet_expected': 1, 'wet_connected': 1,
            'assumptions': [], 'unresolved': ['fixture X could not be assigned'],
        }
        report = v7.qa_report_v7(levels, stats, ['cold_water','sanitary','mechanical_risers'], qa)
        self.assertLess(report['score_10'], 10.0)
        self.assertFalse(report['checks']['fixture_block_traceability'])
        self.assertFalse(report['checks']['no_silent_fixture_loss'])


if __name__ == '__main__':
    unittest.main()
