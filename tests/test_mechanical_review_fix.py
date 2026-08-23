import unittest

from app.mechanical_review_fix import decorate_review_payload, review_question_html


class MechanicalReviewFixTests(unittest.TestCase):
    def drawing_set(self):
        levels = ['همکف', 'اول', 'دوم']
        return {
            'approved': False,
            'approval_required': True,
            'total_plans': 13,
            'deliverable_sheet_count': 13,
            'count_semantics': 'customer_deliverable_sheets',
            'sheet_families': {
                'plumbing_gas': {
                    'code': 'M-P', 'label': 'آب سرد و گرم + گاز', 'count': 3,
                    'sheets': [
                        {'pattern': level, 'levels': [level], 'typical': False}
                        for level in levels
                    ],
                },
                'sanitary_vent_rain': {
                    'code': 'M-S', 'label': 'فاضلاب + ونت + آب باران', 'count': 3,
                    'sheets': [
                        {'pattern': level, 'levels': [level], 'typical': False}
                        for level in levels
                    ],
                },
                'heating_cooling_condensate': {
                    'code': 'M-H', 'label': 'گرمایش + سرمایش + درین کندانس', 'count': 3,
                    'sheets': [
                        {'pattern': level, 'levels': [level], 'typical': False}
                        for level in levels
                    ],
                },
                'ventilation_exhaust': {
                    'code': 'M-V', 'label': 'تهویه + اگزاست', 'count': 3,
                    'sheets': [
                        {'pattern': level, 'levels': [level], 'typical': False}
                        for level in levels
                    ],
                },
                'riser_calc': {
                    'code': 'M-RISER-CALC', 'label': 'رایزر + محاسبات + Legend', 'count': 1,
                    'sheets': [{'pattern': 'Building', 'levels': levels, 'typical': False}],
                },
            },
        }

    def test_review_is_rendered_as_modal_confirmation_step(self):
        payload = decorate_review_payload({'status': 'drawing_set_review'}, self.drawing_set())
        self.assertEqual(payload['status'], 'asking')
        self.assertEqual(payload['question_count'], 1)
        self.assertEqual(payload['question']['key'], '_drawing_set_approval')
        self.assertIn('تأیید لیست و ادامه', payload['question']['question'])
        self.assertIn('مجموع قابل تحویل: 13 شیت', payload['question']['question'])

    def test_review_html_contains_deliverable_family_breakdown_and_hides_old_textarea(self):
        html = review_question_html(self.drawing_set())
        self.assertIn('گرمایش + سرمایش + درین کندانس', html)
        self.assertIn('آب سرد و گرم + گاز', html)
        self.assertIn('M-P', html)
        self.assertIn('M-RISER-CALC', html)
        self.assertIn('#answerForm textarea', html)
        self.assertIn('requestSubmit()', html)

    def test_architecture_labels_are_escaped_before_modal_html(self):
        ds = self.drawing_set()
        ds['sheet_families']['plumbing_gas']['sheets'][0]['pattern'] = '<script>alert(1)</script>'
        html = review_question_html(ds)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;', html)


if __name__ == '__main__':
    unittest.main()
