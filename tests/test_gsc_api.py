import os
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gsc_api import register_gsc_routes


class GscApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        register_gsc_routes(app)
        self.client = TestClient(app)
        self.env = patch.dict(os.environ, {
            "SEO_REPORT_API_KEY": "test-secret",
            "GSC_SITE_URL": "sc-domain:example.com",
            "PUBLIC_SITE_URL": "https://example.com",
            "GSC_SERVICE_ACCOUNT_JSON": '{"type":"service_account"}',
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_requires_internal_key(self):
        self.assertEqual(self.client.get("/internal/seo/report").status_code, 401)

    @patch("app.gsc_api._inspect", return_value=[{"url": "https://example.com/b", "verdict": "PASS"}])
    @patch("app.gsc_api._fetch_sitemap_urls", return_value=["https://example.com/a", "https://example.com/b"])
    @patch("app.gsc_api._search_analytics", return_value=[{
        "keys": ["example", "https://example.com/a"], "clicks": 2, "impressions": 10, "ctr": .2, "position": 3
    }])
    @patch("app.gsc_api._authorized_session", return_value=Mock())
    def test_combines_analytics_sitemap_and_inspection(self, *_mocks):
        response = self.client.get("/internal/seo/report?inspect_limit=10", headers={"Authorization": "Bearer test-secret"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["totals"]["clicks"], 2)
        self.assertEqual(data["sitemap"]["urlsWithoutPerformanceRows"], ["https://example.com/b"])
        self.assertEqual(data["urlInspection"]["results"][0]["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
