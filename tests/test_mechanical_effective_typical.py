import unittest
from types import SimpleNamespace

from app.auto_inference_v2 import level_profiles_from_files, typical_groups_from_profiles
from app.mechanical_workflow import build_scope
from app.mechanical_drawing_set import predict_drawing_set


def labels_for_floor(name, ox, oy, rooms):
    labels = [{'text': f'{name} پلان معماری', 'x': ox, 'y': oy}]
    for room, dx, dy in rooms:
        labels.append({'text': room, 'x': ox + dx, 'y': oy + dy})
    return labels


class EffectiveTypicalInferenceTests(unittest.TestCase):
    def test_translated_identical_architecture_becomes_typical_group(self):
        pattern = [
            ('آشپزخانه', 3, 4), ('حمام', 7, 5), ('اتاق خواب', 12, 4),
            ('پذیرایی', 10, 11), ('شفت', 6, 7),
        ]
        labels = []
        labels += labels_for_floor('طبقه اول', 0, 0, pattern)
        labels += labels_for_floor('طبقه دوم', 100, 0, pattern)
        profiles = level_profiles_from_files([{'text_labels': labels}])
        groups = typical_groups_from_profiles(profiles)
        self.assertEqual(len(profiles), 2)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['levels'], ['طبقه اول', 'طبقه دوم'])
        self.assertEqual(groups[0]['confidence'], 'high')

    def test_changed_wet_core_prevents_false_typical_group(self):
        floor1 = [
            ('آشپزخانه', 3, 4), ('حمام', 7, 5), ('اتاق خواب', 12, 4),
            ('پذیرایی', 10, 11), ('شفت', 6, 7),
        ]
        floor2 = [
            ('آشپزخانه', 3, 4), ('حمام', 14, 12), ('اتاق خواب', 12, 4),
            ('پذیرایی', 10, 11), ('شفت', 2, 13),
        ]
        labels = labels_for_floor('طبقه اول', 0, 0, floor1) + labels_for_floor('طبقه دوم', 100, 0, floor2)
        profiles = level_profiles_from_files([{'text_labels': labels}])
        self.assertEqual(typical_groups_from_profiles(profiles), [])

    def test_authority_scope_keeps_non_roof_levels_when_labels_are_missing(self):
        p = SimpleNamespace(
            answers={'discipline': 'mechanical', 'heating': 'رادیاتور', 'cooling': 'اسپلیت', 'gas': 'بله'},
            analysis={'architectural_auto': {
                'levels': [{'name': 'Ground'}, {'name': 'Office'}, {'name': 'Roof'}],
                'level_profiles': [
                    {'name': 'Ground', 'wet_fixture_candidate': True, 'sanitary_candidate': True, 'conditioned_candidate': True, 'ventilation_candidate': True, 'gas_candidate': True, 'roof': False},
                    {'name': 'Office', 'wet_fixture_candidate': False, 'sanitary_candidate': False, 'conditioned_candidate': True, 'ventilation_candidate': False, 'gas_candidate': False, 'roof': False},
                    {'name': 'Roof', 'wet_fixture_candidate': False, 'sanitary_candidate': False, 'conditioned_candidate': False, 'ventilation_candidate': False, 'gas_candidate': False, 'roof': True},
                ],
                'typical_groups': [],
            }},
        )
        scope = build_scope(p)
        self.assertEqual(scope['wet_fixture_levels'], ['Ground', 'Office'])
        self.assertEqual(scope['sanitary_fixture_levels'], ['Ground', 'Office'])
        self.assertEqual(scope['conditioned_levels'], ['Ground', 'Office'])
        self.assertEqual(scope['heated_levels'], ['Ground', 'Office'])
        self.assertEqual(scope['gas_consumer_levels'], ['Ground', 'Office'])
        self.assertEqual(scope['ventilation_required_levels'], ['Ground', 'Office'])
        self.assertTrue(scope['roof_exists'])

    def test_typical_group_reduces_primary_plans_but_keeps_required_water_service_documents(self):
        levels = ['L1', 'L2', 'L3']
        result = predict_drawing_set({
            'all_levels': levels,
            'conditioned_levels': levels,
            'heated_levels': levels,
            'wet_fixture_levels': levels,
            'sanitary_fixture_levels': levels,
            'ventilation_required_levels': levels,
            'gas_consumer_levels': levels,
            'roof_exists': False,
            'vertical_systems': True,
            'typical_groups': [{'name': 'Typical L1-L3', 'levels': levels, 'confidence': 'high'}],
        })
        primary = [x for x in result['deliverable_sheets'] if x.get('drawing_type') == 'floor_plan']
        self.assertEqual(len(primary), 6)
        self.assertTrue(all(x.get('typical') for x in primary))
        water_types = [x.get('drawing_type') for x in result['deliverable_sheets'] if x.get('family') == 'water_supply']
        self.assertIn('riser_diagram', water_types)
        self.assertIn('equipment_plan', water_types)
        self.assertIn('calculation_sheet', water_types)
        self.assertEqual(result['deliverable_sheet_count'], len(result['deliverable_sheets']))


if __name__ == '__main__':
    unittest.main()
