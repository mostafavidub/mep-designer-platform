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
        'central_water_equipment': False,
    }


class SingleLevelAuthorityManifestTests(unittest.TestCase):
    def test_single_level_direct_water_has_no_unjustified_water_equipment_or_calc(self):
        proposal = predict_drawing_set(scope())
        water = [x for x in proposal['drawing_manifest']['sheets'] if x.get('family') == 'water_supply']
        self.assertEqual(len([x for x in water if x.get('drawing_type') == 'floor_plan']), 1)
        self.assertIn('riser_diagram', {x.get('drawing_type') for x in water})
        self.assertNotIn('equipment_plan', {x.get('drawing_type') for x in water})
        self.assertNotIn('calculation_sheet', {x.get('drawing_type') for x in water})
        self.assertEqual(proposal['deliverable_sheet_count'], len(proposal['drawing_manifest']['sheets']))

    def test_single_level_primary_families_remain_separate(self):
        proposal = predict_drawing_set(scope())
        for family in ('water_supply', 'sanitary_vent', 'heating', 'cooling', 'ventilation_exhaust'):
            primary = [x for x in proposal['drawing_manifest']['sheets'] if x.get('family') == family and x.get('drawing_type') == 'floor_plan']
            self.assertEqual(len(primary), 1)
        self.assertFalse([x for x in proposal['drawing_manifest']['sheets'] if x.get('family') == 'gas'])

    def test_enclosed_parking_adds_only_its_dedicated_ventilation_support(self):
        base = predict_drawing_set(scope(False))
        enclosed = predict_drawing_set(scope(True))
        self.assertEqual(enclosed['deliverable_sheet_count'], base['deliverable_sheet_count'] + 1)
        extra = [x for x in enclosed['drawing_manifest']['sheets'] if x.get('family') == 'ventilation_exhaust' and x.get('drawing_type') == 'ventilation_plan']
        self.assertEqual(len(extra), 1)


if __name__ == '__main__':
    unittest.main()
