import unittest

from app.mechanical_drawing_set import predict_drawing_set


def scope(enclosed=False):
    level = ['طبقه همکف']
    return {
        'all_levels': ['بام', *level],
        'conditioned_levels': level,
        'heated_levels': level,
        'wet_fixture_levels': level,
        'sanitary_fixture_levels': level,
        'ventilation_required_levels': level,
        'gas_consumer_levels': [],
        'roof_exists': False,
        'vertical_systems': False,
        'enclosed_parking': enclosed,
        'typical_groups': [],
    }


class SingleLevelAuthorityManifestTests(unittest.TestCase):
    def test_single_level_reference_family_pattern_has_13_sheets(self):
        proposal = predict_drawing_set(scope())
        self.assertEqual(proposal['deliverable_sheet_count'], 13)
        self.assertEqual({
            key: proposal['sheet_families'][key]['count']
            for key in ('water_supply', 'sanitary_vent', 'heating', 'cooling', 'ventilation_exhaust')
        }, {
            'water_supply': 3, 'sanitary_vent': 4, 'heating': 2,
            'cooling': 2, 'ventilation_exhaust': 2,
        })

    def test_enclosed_parking_adds_only_its_dedicated_ventilation_sheet(self):
        proposal = predict_drawing_set(scope(True))
        self.assertEqual(proposal['deliverable_sheet_count'], 14)
        self.assertEqual(proposal['sheet_families']['ventilation_exhaust']['count'], 3)


if __name__ == '__main__':
    unittest.main()
