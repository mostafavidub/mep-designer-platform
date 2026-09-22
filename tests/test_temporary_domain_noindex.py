import unittest

from fastapi.testclient import TestClient

from app.main_health import app


class TemporaryDomainRedirectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_railway_hostname_redirects_to_planha(self):
        response = self.client.get(
            '/',
            headers={'host': 'web-app-production-3d3b.up.railway.app'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers.get('location'), 'https://planha.com/')

    def test_railway_redirect_preserves_path_and_query(self):
        response = self.client.get(
            '/blog/electrical-building-plan?utm_source=legacy',
            headers={'host': 'web-app-production-3d3b.up.railway.app'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response.headers.get('location'),
            'https://planha.com/blog/electrical-building-plan?utm_source=legacy',
        )

    def test_future_custom_domain_remains_indexable(self):
        response = self.client.get('/', headers={'host': 'www.example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get('x-robots-tag'))

    def test_private_page_remains_noindex_nofollow_on_custom_domain(self):
        response = self.client.get('/login', headers={'host': 'www.example.com'})
        self.assertEqual(response.headers.get('x-robots-tag'), 'noindex, nofollow')

    def test_planha_robots_is_canonical_and_not_shadowed_by_indexnow(self):
        response = self.client.get('/robots.txt', headers={'host': 'planha.com'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('User-agent: *', response.text)
        self.assertIn('Sitemap: https://planha.com/sitemap.xml', response.text)

    def test_unknown_root_txt_still_returns_404(self):
        response = self.client.get('/not-an-indexnow-key.txt', headers={'host': 'planha.com'})
        self.assertEqual(response.status_code, 404)

    def test_private_panel_and_admin_pages_send_noindex_header(self):
        for path in ('/panel', '/panel/projects/new', '/admin/pricing'):
            with self.subTest(path=path):
                response = self.client.get(path, headers={'host': 'planha.com'})
                self.assertEqual(
                    response.headers.get('x-robots-tag'),
                    'noindex, nofollow',
                )

    def test_forwarded_railway_host_redirects_behind_proxy(self):
        response = self.client.get(
            '/mechanical',
            headers={
                'host': 'internal-service',
                'x-forwarded-host': 'web-app-production-3d3b.up.railway.app',
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers.get('location'), 'https://planha.com/mechanical')


if __name__ == '__main__':
    unittest.main()
