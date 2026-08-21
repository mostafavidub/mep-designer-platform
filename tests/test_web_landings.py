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

    def test_mechanical_landing_renders_architecture_first_flow(self):
        r = self.client.get('/mechanical')
        self.assertEqual(r.status_code, 200)
        self.assertIn('همراه مکانیک', r.text)
        self.assertIn('محاسبات قابل استخراج', r.text)
        self.assertIn('سؤال', r.text)


if __name__ == '__main__':
    unittest.main()
