import unittest

from fastapi.testclient import TestClient
from app.main_auto import app


class LandingSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _assert_common_discipline_contract(self, r, discipline_label, sample_title):
        self.assertEqual(r.status_code, 200)
        self.assertIn(discipline_label, r.text)
        self.assertIn('محاسبات قابل استخراج', r.text)
        self.assertIn('سؤال', r.text)
        self.assertIn('چه چیزی تحویل می‌گیرید؟', r.text)
        self.assertIn('FAQPage', r.text)
        self.assertIn('اصلاح خروجی چگونه انجام می‌شود؟', r.text)
        self.assertIn('EngiTools در مقایسه با شروع دستی طراحی', r.text)
        self.assertIn('چه چیزهایی را از پلان معماری حدس نمی‌زنیم؟', r.text)
        self.assertIn(sample_title, r.text)
        self.assertTrue(r.text.count('project-') >= 4)
        self.assertIn('data-sample-carousel', r.text)
        self.assertIn('sample-lightbox', r.text)
        self.assertNotIn('target="_blank"', r.text)
        self.assertEqual(r.text.count('<h1'), 1)
        self.assertIn('/static/landing_v3.css', r.text)
        self.assertIn('rel="canonical"', r.text)

    def test_electrical_landing_renders_complete_contract(self):
        r = self.client.get('/electrical')
        self._assert_common_discipline_contract(
            r,
            'همراه برق',
            '۴ نمونه واقعی تبدیل پلان معماری به نقشه برق',
        )
        self.assertIn('پلان روشنایی', r.text)
        self.assertIn('SLD', r.text)
        self.assertIn('Panel Schedule', r.text)

    def test_mechanical_landing_renders_complete_contract(self):
        r = self.client.get('/mechanical')
        self._assert_common_discipline_contract(
            r,
            'همراه مکانیک',
            '۴ نمونه واقعی تبدیل پلان معماری به نقشه مکانیک',
        )
        self.assertIn('آب سرد و گرم', r.text)
        self.assertIn('فاضلاب', r.text)
        self.assertIn('HVAC', r.text)

    def test_home_has_trust_comparison_limits_and_faq(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('چرا می‌توان به فرآیند EngiTools اعتماد کرد؟', r.text)
        self.assertIn('FAQPage', r.text)
        self.assertIn('شفافیت درباره محدودیت‌ها', r.text)
        self.assertIn('۴ نمونه واقعی از پروژه‌های تأییدشده', r.text)
        self.assertIn('project-1-electrical-before-after.svg', r.text)
        self.assertIn('project-8-mechanical-before-after.svg', r.text)
        self.assertIn('data-sample-carousel', r.text)
        self.assertIn('sample-lightbox', r.text)
        self.assertNotIn('target="_blank"', r.text)
        self.assertEqual(r.text.count('<h1'), 1)
        self.assertIn('/static/landing_v3.css', r.text)

    def test_field_specific_hero_assets_exist(self):
        electrical = self.client.get('/static/hero-electrical.svg')
        mechanical = self.client.get('/static/hero-mechanical.svg')
        self.assertEqual(electrical.status_code, 200)
        self.assertEqual(mechanical.status_code, 200)
        self.assertIn('LIGHTING / POWER / FIRE / ELV', electrical.text)
        self.assertIn('WATER / SANITARY / VENT / GAS', mechanical.text)

    def test_architect_is_transparent_and_links_active_services(self):
        r = self.client.get('/architect')
        self.assertEqual(r.status_code, 200)
        self.assertIn('این سرویس هنوز فعال نیست', r.text)
        self.assertIn('/electrical', r.text)
        self.assertIn('/mechanical', r.text)


if __name__ == '__main__':
    unittest.main()
