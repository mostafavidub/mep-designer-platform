import unittest

from fastapi.testclient import TestClient

from app.main_health import app


class TemporaryDomainNoindexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_railway_hostname_redirects_to_canonical_host(self):
        response = self.client.get(
            '/blog?source=railway',
            headers={'host': 'web-app-production-3d3b.up.railway.app'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response.headers.get('location'),
            'https://planha.com/blog?source=railway',
        )

    def test_www_hostname_redirects_to_canonical_host(self):
        response = self.client.get(
            '/mechanical?utm_source=test',
            headers={'host': 'www.planha.com'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response.headers.get('location'),
            'https://planha.com/mechanical?utm_source=test',
        )

    def test_canonical_host_remains_indexable(self):
        response = self.client.get('/', headers={'host': 'planha.com'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get('x-robots-tag'))
        self.assertIn('rel="canonical" href="https://planha.com/"', response.text)
        self.assertIn('property="og:url" content="https://planha.com/"', response.text)
        self.assertIn('"url":"https://planha.com/"', response.text)

    def test_future_unlisted_custom_domain_remains_indexable_but_canonicalizes_to_planha(self):
        response = self.client.get('/', headers={'host': 'www.example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get('x-robots-tag'))
        self.assertIn('rel="canonical" href="https://planha.com/"', response.text)

    def test_private_page_remains_noindex_nofollow_on_canonical_domain(self):
        response = self.client.get('/login', headers={'host': 'planha.com'})
        self.assertEqual(response.headers.get('x-robots-tag'), 'noindex, nofollow')

    def test_health_probe_on_railway_hostname_is_not_redirected_and_stays_noindex(self):
        response = self.client.get(
            '/system_health',
            headers={'host': 'web-app-production-3d3b.up.railway.app'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('x-robots-tag'), 'noindex, follow')

    def test_forwarded_railway_host_redirects_behind_proxy(self):
        response = self.client.get(
            '/electrical',
            headers={
                'host': 'internal-service',
                'x-forwarded-host': 'web-app-production-3d3b.up.railway.app',
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers.get('location'), 'https://planha.com/electrical')

    def test_sitemap_and_robots_only_advertise_canonical_domain(self):
        sitemap = self.client.get('/sitemap.xml', headers={'host': 'planha.com'})
        self.assertEqual(sitemap.status_code, 200)
        self.assertIn('<loc>https://planha.com/</loc>', sitemap.text)
        self.assertNotIn('www.planha.com', sitemap.text)
        self.assertNotIn('up.railway.app', sitemap.text)

        robots = self.client.get('/robots.txt', headers={'host': 'planha.com'})
        self.assertEqual(robots.status_code, 200)
        self.assertIn('Sitemap: https://planha.com/sitemap.xml', robots.text)
        self.assertNotIn('www.planha.com', robots.text)
        self.assertNotIn('up.railway.app', robots.text)


if __name__ == '__main__':
    unittest.main()
