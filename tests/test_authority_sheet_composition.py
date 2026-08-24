import unittest

from app.mechanical_drawing_set import predict_drawing_set


def scope(levels, enclosed_parking=False):
    return {
        'all_levels': levels,
        'conditioned_levels': levels,
        'heated_levels': levels,
        'wet_fixture_levels': levels,
        'sanitary_fixture_levels': levels,
        'ventilation_required_levels': levels,
        'gas_consumer_levels': [],
        'vertical_systems': len(levels) > 1,
        'typical_groups': [],
        'enclosed_parking': enclosed_parking,
    }


class AuthoritySheetCompositionTests(unittest.TestCase):
    def counts(self, proposal):
        return {
            key: proposal['sheet_families'][key]['count']
            for key in ('water_supply', 'sanitary_vent', 'heating', 'cooling', 'ventilation_exhaust')
        }

    def test_three_distinct_floor_patterns_match_duplex_authority_manifest(self):
        proposal = predict_drawing_set(scope(['Ground', 'First', 'Second'], enclosed_parking=True))
        self.assertEqual(proposal['total_plans'], 21)
        self.assertEqual(self.counts(proposal), {
            'water_supply': 6, 'sanitary_vent': 5, 'heating': 3,
            'cooling': 3, 'ventilation_exhaust': 4,
        })

    def test_two_patterns_without_enclosed_parking_match_standard_authority_manifest(self):
        proposal = predict_drawing_set(scope(['Ground', 'Typical']))
        self.assertEqual(proposal['total_plans'], 13)
        self.assertEqual(self.counts(proposal), {
            'water_supply': 3, 'sanitary_vent': 4, 'heating': 2,
            'cooling': 2, 'ventilation_exhaust': 2,
        })

    def test_enclosed_parking_adds_only_its_dedicated_exhaust_role(self):
        proposal = predict_drawing_set(scope(['Ground', 'Typical'], enclosed_parking=True))
        self.assertEqual(proposal['total_plans'], 14)
        self.assertEqual(self.counts(proposal), {
            'water_supply': 3, 'sanitary_vent': 4, 'heating': 2,
            'cooling': 2, 'ventilation_exhaust': 3,
        })
