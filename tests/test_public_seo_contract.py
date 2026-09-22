import re
import unittest
from xml.etree import ElementTree

from fastapi.testclient import TestClient

from app.main_health import app


INDEXABLE_PATHS = [
    "/",
    "/electrical",
    "/mechanical",
    "/blog",
    "/blog/electrical-building-plan",
    "/blog/mep-input-guide",
    "/blog/electrical-plan-scope",
    "/blog/mechanical-plan-scope",
    "/blog/mechanical-building-plan",
    "/blog/sanitary-drainage-plan",
    "/blog/electrical-execution-drawing-building",
]


class PublicSEOContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_all_indexable_pages_have_consistent_planha_metadata(self):
        for path in INDEXABLE_PATHS:
            with self.subTest(path=path):
                response = self.client.get(path, headers={"host": "planha.com"})
                self.assertEqual(response.status_code, 200)

                html = response.text
                expected_url = f"https://planha.com{path}"

                self.assertEqual(html.count("<h1"), 1)
                self.assertIn(
                    f'<link rel="canonical" href="{expected_url}">',
                    html,
                )
                self.assertIn(
                    f'<meta property="og:url" content="{expected_url}">',
                    html,
                )
                self.assertIn(
                    '<meta property="og:site_name" content="Planha">',
                    html,
                )
                self.assertRegex(
                    html,
                    r'<meta name="robots" content="index,follow[^"]*">',
                )

                title = re.search(r"<title>(.*?)</title>", html, re.S)
                self.assertIsNotNone(title)
                self.assertIn("Planha", title.group(1))
                self.assertNotIn("EngiTools", title.group(1))

                description = re.search(
                    r'<meta name="description" content="([^"]+)">',
                    html,
                )
                self.assertIsNotNone(description)
                self.assertGreater(len(description.group(1).strip()), 40)

                self.assertNotIn("EngiTools", html)
                self.assertNotIn("ENGITOOLS", html)

    def test_public_shell_exposes_square_png_favicon(self):
        response = self.client.get("/", headers={"host": "planha.com"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            '<link rel="icon" type="image/png" sizes="96x96" href="/static/favicon-96.png">',
            response.text,
        )

        favicon = self.client.get("/static/favicon-96.png")
        self.assertEqual(favicon.status_code, 200)
        self.assertTrue(
            favicon.headers.get("content-type", "").startswith("image/png")
        )

    def test_home_uses_clean_supported_structured_data(self):
        response = self.client.get("/", headers={"host": "planha.com"})
        self.assertEqual(response.status_code, 200)
        self.assertIn('"@type":"Organization"', response.text)
        self.assertIn('"@type":"WebSite"', response.text)
        self.assertIn('"name":"Planha"', response.text)
        self.assertIn('"alternateName":"پلان‌ها"', response.text)
        self.assertIn('"logo":"https://planha.com/static/logo-192.png"', response.text)
        logo = self.client.get("/static/logo-192.png")
        self.assertEqual(logo.status_code, 200)
        self.assertTrue(logo.headers.get("content-type", "").startswith("image/png"))
        self.assertNotIn('"@type":"SoftwareApplication"', response.text)

    def test_sitemap_matches_indexable_public_contract(self):
        response = self.client.get("/sitemap.xml", headers={"host": "planha.com"})
        self.assertEqual(response.status_code, 200)

        root = ElementTree.fromstring(response.content)
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        urls = [
            loc.text
            for loc in root.findall(f"{ns}url/{ns}loc")
            if loc.text
        ]

        self.assertEqual(
            set(urls),
            {f"https://planha.com{path}" for path in INDEXABLE_PATHS},
        )
        self.assertEqual(len(urls), len(set(urls)))
        self.assertNotIn("https://planha.com/architect", urls)

    def test_architect_remains_noindex_until_service_is_live(self):
        response = self.client.get("/architect", headers={"host": "planha.com"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            '<meta name="robots" content="noindex,follow">',
            response.text,
        )
        self.assertIn(
            '<link rel="canonical" href="https://planha.com/architect">',
            response.text,
        )

    def test_robots_points_to_canonical_sitemap(self):
        response = self.client.get("/robots.txt", headers={"host": "planha.com"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("User-agent: *", response.text)
        self.assertIn("Allow: /", response.text)
        self.assertIn(
            "Sitemap: https://planha.com/sitemap.xml",
            response.text,
        )


if __name__ == "__main__":
    unittest.main()
