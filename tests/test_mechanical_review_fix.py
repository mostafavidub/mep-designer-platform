import unittest

from app.mechanical_review_fix import decorate_review_payload, review_question_html


class MechanicalReviewFixTests(unittest.TestCase):
    def drawing_set(self):
        return {
            'approved': False,
            'approval_required': True,
            'total_plans': 21,
            'labels': {
                'cooling': 'سرمایش',
                'heating': 'گرمایش',
                'water_supply': 'آب سرد و گرم',
                'sanitary': 'فاضلاب و ونت',
                'ventilation': 'تهویه',
                'gas': 'گاز',
                'roof_drainage': 'بام / آب باران',
                'riser': 'رایزر',
            },
            'systems': {
                'cooling': {'count': 3, 'levels': ['همکف', 'اول', 'دوم']},
                'heating': {'count': 3, 'levels': ['همکف', 'اول', 'دوم']},
                'water_supply': {'count': 4, 'levels': ['همکف', 'اول', 'دوم', 'سوم']},
                'sanitary': {'count': 3, 'levels': ['همکف', 'اول', 'دوم']},
                'ventilation': {'count': 3, 'levels': ['همکف', 'اول', 'دوم']},
                'gas': {'count': 3, 'levels': ['همکف', 'اول', 'دوم']},
                'roof_drainage': {'count': 1, 'levels': ['Roof']},
                'riser': {'count': 1, 'levels': ['Riser Diagram']},
            },
        }

    def test_review_is_rendered_as_modal_confirmation_step(self):
        payload = decorate_review_payload({'status': 'drawing_set_review'}, self.drawing_set())
        self.assertEqual(payload['status'], 'asking')
        self.assertEqual(payload['question_count'], 1)
        self.assertEqual(payload['question']['key'], '_drawing_set_approval')
        self.assertIn('تأیید لیست و ادامه', payload['question']['question'])
        self.assertIn('مجموع: 21 پلان', payload['question']['question'])

    def test_review_html_contains_system_breakdown_and_hides_old_textarea(self):
        html = review_question_html(self.drawing_set())
        self.assertIn('سرمایش', html)
        self.assertIn('آب سرد و گرم', html)
        self.assertIn('#answerForm textarea', html)
        self.assertIn("requestSubmit()", html)

    def test_architecture_labels_are_escaped_before_modal_html(self):
        ds = self.drawing_set()
        ds['systems']['cooling']['levels'] = ['<script>alert(1)</script>']
        html = review_question_html(ds)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;', html)


if __name__ == '__main__':
    unittest.main()
