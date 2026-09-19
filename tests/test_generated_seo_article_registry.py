import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main_health import app
from app import main_auto, seo_articles


TEST_SLUG = "seo-engine-publish-test"

TEST_POST = {
    "slug": TEST_SLUG,
    "title": "تست انتشار خودکار مقاله با SEO Engine",
    "excerpt": "تست مسیر انتشار خودکار مقاله.",
    "tag": "راهنما",
    "body": [],
    "generated": True,
    "html": (
        "<h2>تست اتصال SEO Engine به سایت</h2>"
        "<p>مسیر تولید و نمایش مقاله با موفقیت اجرا شده است.</p>"
        "<p><a href=\"/electrical\">طراحی برق ساختمان</a></p>"
        "<p><a href=\"/mechanical\">طراحی مکانیک ساختمان</a></p>"
    ),
    "markdown": "",
    "primary_keyword": "تست انتشار خودکار مقاله",
    "secondary_keywords": "",
    "created_date": "2026-09-19",
    "machine_score": 100,
    "business_case": "Automated publishing regression test.",
    "engine_version": "1.1",
    "run_id": "test-generated-article-001",
}


class GeneratedSeoArticleRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

        cls.original_blog = list(main_auto.legacy.BLOG)

        main_auto.legacy.BLOG[:] = [
            post
            for post in main_auto.legacy.BLOG
            if post.get("slug") != TEST_SLUG
        ]

        main_auto.legacy.BLOG.append(TEST_POST.copy())

    @classmethod
    def tearDownClass(cls):
        main_auto.legacy.BLOG[:] = cls.original_blog

    def test_loader_reads_only_published_articles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir) / "articles.json"

            registry.write_text(
                json.dumps(
                    [
                        {
                            "slug": TEST_SLUG,
                            "title": TEST_POST["title"],
                            "status": "published",
                            "meta_description": TEST_POST["excerpt"],
                            "html": TEST_POST["html"],
                        },
                        {
                            "slug": "ready-but-not-published",
                            "title": "Should not publish",
                            "status": "ready",
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            original_path = seo_articles.ARTICLES_PATH

            try:
                seo_articles.ARTICLES_PATH = registry
                posts = seo_articles.load_generated_articles()
            finally:
                seo_articles.ARTICLES_PATH = original_path

            slugs = {post["slug"] for post in posts}

            self.assertIn(TEST_SLUG, slugs)
            self.assertNotIn("ready-but-not-published", slugs)

    def test_generated_article_is_listed_in_blog(self):
        response = self.client.get("/blog")

        self.assertEqual(response.status_code, 200)
        self.assertIn(TEST_SLUG, response.text)
        self.assertIn(TEST_POST["title"], response.text)

    def test_generated_article_renders_with_dynamic_template(self):
        response = self.client.get(f"/blog/{TEST_SLUG}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(TEST_POST["title"], response.text)
        self.assertIn("تست اتصال SEO Engine به سایت", response.text)
        self.assertIn('href="/electrical"', response.text)
        self.assertIn('href="/mechanical"', response.text)
        self.assertEqual(response.text.count("<h1"), 1)
        self.assertIn("application/ld+json", response.text)

    def test_generated_article_is_in_sitemap(self):
        response = self.client.get("/sitemap.xml")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f"https://planha.com/blog/{TEST_SLUG}",
            response.text,
        )

    def test_unknown_generated_article_returns_404(self):
        response = self.client.get(
            "/blog/this-generated-article-does-not-exist"
        )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
