import unittest

from fastapi.testclient import TestClient
from app.main_auto import app


class LandingSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_electrical_landing_renders_architecture_first_flow(self):
        r = self.client.get('/electrical')
        self.assertEqual(r.status_code, 200)
        self.assertIn('همراه برق', r.text)
        self.assertIn('محاسبات قابل استخراج', r.text)
        self.assertIn('سؤال', r.text)
        self.assertIn('چه چیزی تحویل می‌گیرید؟', r.text)
        self.assertIn('FAQPage', r.text)
        self.assertIn('اصلاح خروجی چگونه انجام می‌شود؟', r.text)

    def test_mechanical_landing_renders_architecture_first_flow(self):
        r = self.client.get('/mechanical')
        self.assertEqual(r.status_code, 200)
        self.assertIn('همراه مکانیک', r.text)
        self.assertIn('محاسبات قابل استخراج', r.text)
        self.assertIn('سؤال', r.text)
        self.assertIn('چه چیزی تحویل می‌گیرید؟', r.text)
        self.assertIn('FAQPage', r.text)
        self.assertIn('اصلاح خروجی چگونه انجام می‌شود؟', r.text)

    def test_home_has_trust_comparison_limits_and_faq(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('چرا می‌توان به فرآیند EngiTools اعتماد کرد؟', r.text)
        self.assertIn('FAQPage', r.text)
        self.assertIn('شفافیت درباره محدودیت‌ها', r.text)

    def test_architect_is_transparent_and_links_active_services(self):
        r = self.client.get('/architect')
        self.assertEqual(r.status_code, 200)
        self.assertIn('این سرویس هنوز فعال نیست', r.text)
        self.assertIn('/electrical', r.text)
        self.assertIn('/mechanical', r.text)


if __name__ == '__main__':
    unittest.main()
