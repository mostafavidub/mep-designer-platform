import unittest

from fastapi.testclient import TestClient

from app.main_health import app


class TemporaryDomainNoindexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_railway_hostname_is_noindex_follow(self):
        response = self.client.get(
            '/',
            headers={'host': 'web-app-production-3d3b.up.railway.app'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('x-robots-tag'), 'noindex, follow')

    def test_future_custom_domain_remains_indexable(self):
        response = self.client.get('/', headers={'host': 'www.example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get('x-robots-tag'))

    def test_private_page_remains_noindex_nofollow_on_custom_domain(self):
        response = self.client.get('/login', headers={'host': 'www.example.com'})
        self.assertEqual(response.headers.get('x-robots-tag'), 'noindex, nofollow')

    def test_forwarded_host_is_used_behind_proxy(self):
        response = self.client.get(
            '/',
            headers={
                'host': 'internal-service',
                'x-forwarded-host': 'web-app-production-3d3b.up.railway.app',
            },
        )
        self.assertEqual(response.headers.get('x-robots-tag'), 'noindex, follow')


if __name__ == '__main__':
    unittest.main()
