import unittest

from fastapi.testclient import TestClient

from app.main_health import app


class GeneratedSeoArticleRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_generated_article_is_listed_in_blog(self):
        response = self.client.get('/blog')

        self.assertEqual(response.status_code, 200)
        self.assertIn('seo-engine-publish-test', response.text)
        self.assertIn(
            'تست انتشار خودکار مقاله با SEO Engine',
            response.text,
        )

    def test_generated_article_renders_with_dynamic_template(self):
        response = self.client.get('/blog/seo-engine-publish-test')

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            'تست انتشار خودکار مقاله با SEO Engine',
            response.text,
        )

        self.assertIn(
            'تست اتصال SEO Engine به سایت',
            response.text,
        )

        self.assertIn(
            'href="/electrical"',
            response.text,
        )

        self.assertIn(
            'href="/mechanical"',
            response.text,
        )

        self.assertEqual(
            response.text.count('<h1'),
            1,
        )

        self.assertIn(
            'application/ld+json',
            response.text,
        )

    def test_generated_article_is_in_sitemap(self):
        response = self.client.get('/sitemap.xml')

        self.assertEqual(response.status_code, 200)

        self.assertIn(
            'https://planha.com/blog/seo-engine-publish-test',
            response.text,
        )

    def test_unknown_generated_article_returns_404(self):
        response = self.client.get(
            '/blog/this-generated-article-does-not-exist'
        )

        self.assertEqual(
            response.status_code,
            404,
        )


if __name__ == '__main__':
    unittest.main()
