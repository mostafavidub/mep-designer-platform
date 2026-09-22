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


    def test_historical_article_paths_redirect_to_current_equivalents(self):
        redirects = {
            '/blog/dxf-guide': 'https://planha.com/blog/mep-input-guide',
            '/blog/electrical-drawings': 'https://planha.com/blog/electrical-plan-scope',
            '/blog/mechanical-drawings': 'https://planha.com/blog/mechanical-plan-scope',
        }
        for source, target in redirects.items():
            with self.subTest(source=source):
                response = self.client.get(
                    source,
                    headers={'host': 'planha.com'},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 301)
                self.assertEqual(response.headers.get('location'), target)


    def test_historical_sitemap_index_remains_fetchable(self):
        response = self.client.get(
            '/sitemap_index.xml',
            headers={'host': 'planha.com'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            '<loc>https://planha.com/sitemap.xml</loc>',
            response.text,
        )

    def test_historical_redirect_preserves_query(self):
        response = self.client.get(
            '/blog/dxf-guide?utm_source=old-sitemap',
            headers={'host': 'planha.com'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response.headers.get('location'),
            'https://planha.com/blog/mep-input-guide?utm_source=old-sitemap',
        )

    def test_railway_historical_path_redirects_in_one_hop(self):
        response = self.client.get(
            '/blog/electrical-drawings',
            headers={'host': 'web-app-production-3d3b.up.railway.app'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response.headers.get('location'),
            'https://planha.com/blog/electrical-plan-scope',
        )


if __name__ == '__main__':
    unittest.main()
