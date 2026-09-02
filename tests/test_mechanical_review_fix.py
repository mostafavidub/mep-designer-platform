import unittest

from app.mechanical_drawing_set import predict_drawing_set
from app.mechanical_review_fix import decorate_review_payload, review_question_html


class MechanicalReviewFixTests(unittest.TestCase):
    def drawing_set(self):
        levels = ['همکف', 'اول', 'دوم']
        return predict_drawing_set({
            'all_levels': levels + ['بام'],
            'conditioned_levels': levels,
            'heated_levels': levels,
            'wet_fixture_levels': levels,
            'sanitary_fixture_levels': levels,
            'ventilation_required_levels': levels,
            'gas_consumer_levels': levels,
            'roof_exists': True,
            'roof_level_name': 'بام',
            'vertical_systems': True,
            'typical_groups': [],
        })

    def test_review_is_rendered_as_modal_confirmation_step(self):
        ds = self.drawing_set()
        payload = decorate_review_payload({'status': 'drawing_set_review'}, ds)
        self.assertEqual(payload['status'], 'asking')
        self.assertEqual(payload['question_count'], 1)
        self.assertEqual(payload['question']['key'], '_drawing_set_approval')
        self.assertIn('تأیید و شروع طراحی', payload['question']['question'])
        self.assertIn(
            f"تعداد شیت‌های تحویلی مکانیک: {ds['deliverable_sheet_count']} شیت",
            payload['question']['question'],
        )

    def test_review_html_contains_authority_family_breakdown(self):
        ds = self.drawing_set()
        html = review_question_html(ds)
        self.assertIn('آب سرد و گرم', html)
        self.assertIn('فاضلاب و ونت', html)
        self.assertIn('گرمایش', html)
        self.assertIn('سرمایش / HVAC', html)
        self.assertIn('گاز', html)
        self.assertIn('تهویه و اگزاست', html)
        self.assertIn('بام / آب باران', html)
        self.assertIn('M-W', html)
        self.assertIn(str(ds['deliverable_sheet_count']), html)
        self.assertIn('#answerForm textarea', html)
        self.assertIn('requestSubmit()', html)

    def test_architecture_labels_are_escaped_before_modal_html(self):
        ds = self.drawing_set()
        ds['sheet_families']['water_supply']['sheets'][0]['pattern'] = '<script>alert(1)</script>'
        html = review_question_html(ds)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertNotIn('alert(1)', html)


if __name__ == '__main__':
    unittest.main()
