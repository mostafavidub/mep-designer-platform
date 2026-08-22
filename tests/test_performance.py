import unittest

from fastapi.testclient import TestClient
from app.main_health import app


class PerformanceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_versioned_static_assets_are_immutable(self):
        r = self.client.get('/static/brand_v4.css?v=20260821-2040')
        self.assertEqual(r.status_code, 200)
        self.assertIn('max-age=31536000', r.headers.get('cache-control', ''))
        self.assertIn('immutable', r.headers.get('cache-control', ''))

    def test_html_revalidates_instead_of_stale_caching(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get('cache-control'), 'no-cache')

    def test_discipline_hero_is_preloaded(self):
        electrical = self.client.get('/electrical')
        mechanical = self.client.get('/mechanical')
        self.assertTrue(
            'rel="preload" as="image" href="https://res.cloudinary.com/' in electrical.text
            or 'rel="preload" as="image" href="/static/service-art-electrical.svg' in electrical.text
        )
        self.assertTrue(
            'rel="preload" as="image" href="/static/service-art-mechanical.svg' in mechanical.text
            or 'rel="preload" as="image" href="/service-art/mechanical.jpg' in mechanical.text
            or 'rel="preload" as="image" href="/static/service-art-mechanical.jpg' in mechanical.text
            or 'rel="preload" as="image" href="/static/hero-mechanical.svg' in mechanical.text
        )

    def test_non_landing_pages_do_not_load_landing_runtime(self):
        r = self.client.get('/blog')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('/static/modal.css', r.text)
        self.assertNotIn('/static/landing_v3.css', r.text)
        self.assertNotIn('/static/sample-carousel.js', r.text)
        self.assertNotIn('/static/motion.js', r.text)
        self.assertIn('/static/brand_v4.js', r.text)


if __name__ == '__main__':
    unittest.main()
