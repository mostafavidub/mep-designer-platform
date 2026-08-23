import unittest

from app.mechanical_review_fix import decorate_review_payload, review_question_html


class MechanicalReviewFixTests(unittest.TestCase):
    def drawing_set(self):
        levels = ['همکف', 'اول', 'دوم']
        def floor_sheets(label):
            return [{'pattern': level, 'levels': [level], 'typical': False, 'special': False, 'label': label} for level in levels]
        return {
            'approved': False,
            'approval_required': True,
            'total_plans': 21,
            'deliverable_sheet_count': 21,
            'count_semantics': 'authority_separated_customer_deliverables',
            'sheet_families': {
                'water_supply': {'code': 'M-W', 'label': 'آب سرد و گرم', 'count': 4, 'sheets': floor_sheets('آب سرد و گرم') + [{'pattern': 'System special', 'levels': levels, 'typical': False, 'special': True, 'label': 'آبرسانی — رایزر / تجهیزات / شماتیک'}]},
                'sanitary_vent': {'code': 'M-S', 'label': 'فاضلاب و ونت', 'count': 3, 'sheets': floor_sheets('فاضلاب و ونت')},
                'heating': {'code': 'M-H', 'label': 'گرمایش', 'count': 3, 'sheets': floor_sheets('گرمایش')},
                'cooling': {'code': 'M-C', 'label': 'سرمایش / HVAC', 'count': 4, 'sheets': floor_sheets('سرمایش') + [{'pattern': 'System special', 'levels': ['بام'], 'typical': False, 'special': True, 'label': 'سرمایش — تجهیزات / بام'}]},
                'gas': {'code': 'M-G', 'label': 'گاز', 'count': 3, 'sheets': floor_sheets('گاز')},
                'ventilation_exhaust': {'code': 'M-V', 'label': 'تهویه و اگزاست', 'count': 3, 'sheets': floor_sheets('تهویه و اگزاست')},
                'roof_rainwater': {'code': 'M-R', 'label': 'بام / آب باران', 'count': 1, 'sheets': [{'pattern': 'بام', 'levels': ['بام'], 'typical': False, 'special': True, 'label': 'بام / آب باران'}]},
            },
        }

    def test_review_is_rendered_as_modal_confirmation_step(self):
        payload = decorate_review_payload({'status': 'drawing_set_review'}, self.drawing_set())
        self.assertEqual(payload['status'], 'asking')
        self.assertEqual(payload['question_count'], 1)
        self.assertEqual(payload['question']['key'], '_drawing_set_approval')
        self.assertIn('تأیید لیست و ادامه', payload['question']['question'])
        self.assertIn('مجموع قابل تحویل: 21 شیت', payload['question']['question'])

    def test_review_html_contains_authority_family_breakdown(self):
        html = review_question_html(self.drawing_set())
        self.assertIn('آب سرد و گرم', html)
        self.assertIn('فاضلاب و ونت', html)
        self.assertIn('گرمایش', html)
        self.assertIn('سرمایش / HVAC', html)
        self.assertIn('گاز', html)
        self.assertIn('تهویه و اگزاست', html)
        self.assertIn('بام / آب باران', html)
        self.assertIn('M-W', html)
        self.assertNotIn('M-RISER-CALC', html)
        self.assertIn('#answerForm textarea', html)
        self.assertIn('requestSubmit()', html)

    def test_architecture_labels_are_escaped_before_modal_html(self):
        ds = self.drawing_set()
        ds['sheet_families']['water_supply']['sheets'][0]['pattern'] = '<script>alert(1)</script>'
        html = review_question_html(ds)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;', html)


if __name__ == '__main__':
    unittest.main()
