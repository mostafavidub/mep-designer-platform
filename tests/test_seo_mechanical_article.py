import unittest
from fastapi.testclient import TestClient

from app.main_health import app


class MechanicalSeoArticleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_mechanical_building_plan_article_is_published(self):
        response = self.client.get('/blog/mechanical-building-plan')
        self.assertEqual(response.status_code, 200)
        self.assertIn('نقشه تأسیسات مکانیکی ساختمان', response.text)
        self.assertIn('href="/mechanical"', response.text)
        self.assertEqual(response.text.count('<h1'), 1)
        self.assertIn('application/ld+json', response.text)
        self.assertIn('rel="canonical"', response.text)

    def test_article_is_discoverable_in_blog_and_sitemap(self):
        blog = self.client.get('/blog')
        sitemap = self.client.get('/sitemap.xml')
        self.assertEqual(blog.status_code, 200)
        self.assertEqual(sitemap.status_code, 200)
        self.assertIn('/blog/mechanical-building-plan', blog.text)
        self.assertIn('/blog/mechanical-building-plan', sitemap.text)

    def test_system_health_remains_available(self):
        response = self.client.get('/system_health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('status'), 'ok')


if __name__ == '__main__':
    unittest.main()
