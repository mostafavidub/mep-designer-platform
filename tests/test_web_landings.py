import unittest

from fastapi.testclient import TestClient
from app.main_auto import app


class LandingSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _assert_brand_shell(self, r):
        self.assertEqual(r.status_code, 200)
        self.assertIn('/static/brand_v4.css', r.text)
        self.assertIn('/static/brand_v4.js', r.text)
        self.assertIn('rel="canonical"', r.text)
        self.assertEqual(r.text.count('<h1'), 1)
        self.assertNotIn('target="_blank"', r.text)

    def _assert_common_discipline_contract(self, r, discipline_label):
        self._assert_brand_shell(r)
        self.assertIn(discipline_label, r.text)
        self.assertIn('ARCHITECTURE-FIRST', r.text)
        self.assertIn('START DESIGN', r.text)
        self.assertIn('DYNAMIC QUESTIONS', r.text)
        self.assertIn('APPROVED PROJECTS', r.text)
        self.assertIn('DELIVERABLES', r.text)
        self.assertIn('COMPARISON', r.text)
        self.assertIn('REVISION FLOW', r.text)
        self.assertIn('TRANSPARENT LIMITS', r.text)
        self.assertIn('RELATED GUIDES', r.text)
        self.assertIn('FAQPage', r.text)
        self.assertIn('چه چیزی تحویل می‌گیرید؟', r.text)
        self.assertTrue(r.text.count('project-') >= 4)
        self.assertIn('data-sample-carousel', r.text)
        self.assertIn('sample-lightbox', r.text)
        self.assertIn('/static/landing_v3.css', r.text)

    def test_electrical_landing_renders_complete_contract(self):
        r = self.client.get('/electrical')
        self._assert_common_discipline_contract(r, 'همراه برق')
        self.assertIn('روشنایی', r.text)
        self.assertIn('SLD', r.text)
        self.assertIn('Panel Schedule', r.text)
        self.assertIn('project-1-electrical-before-after.svg', r.text)

    def test_mechanical_landing_renders_complete_contract(self):
        r = self.client.get('/mechanical')
        self._assert_common_discipline_contract(r, 'همراه مکانیک')
        self.assertIn('آب سرد و گرم', r.text)
        self.assertIn('فاضلاب', r.text)
        self.assertIn('HVAC', r.text)
        self.assertIn('project-1-mechanical-before-after.svg', r.text)

    def test_home_has_trust_comparison_limits_and_faq(self):
        r = self.client.get('/')
        self._assert_brand_shell(r)
        self.assertIn('ENGINEERING TRUST', r.text)
        self.assertIn('COMPARISON', r.text)
        self.assertIn('LIMITS & REVISION', r.text)
        self.assertIn('FAQPage', r.text)
        self.assertIn('۴ نمونه واقعی از پروژه‌های تأییدشده', r.text)
        self.assertIn('project-1-electrical-before-after.svg', r.text)
        self.assertIn('project-8-mechanical-before-after.svg', r.text)
        self.assertIn('data-sample-carousel', r.text)
        self.assertIn('sample-lightbox', r.text)

    def test_blog_and_articles_use_editorial_brand_shell(self):
        blog = self.client.get('/blog')
        self._assert_brand_shell(blog)
        self.assertIn('ENGITOOLS ENGINEERING BLOG', blog.text)
        for slug in ('mep-input-guide', 'electrical-plan-scope', 'mechanical-plan-scope'):
            article = self.client.get(f'/blog/{slug}')
            self._assert_brand_shell(article)
            self.assertIn('article-featured', article.text)
            self.assertIn('BreadcrumbList', article.text)

    def test_field_specific_hero_assets_exist(self):
        electrical = self.client.get('/static/hero-electrical.svg')
        mechanical = self.client.get('/static/hero-mechanical.svg')
        self.assertEqual(electrical.status_code, 200)
        self.assertEqual(mechanical.status_code, 200)
        self.assertIn('LIGHTING / POWER / FIRE / ELV', electrical.text)
        self.assertIn('WATER / SANITARY / VENT / GAS', mechanical.text)

    def test_architect_is_transparent_and_links_active_services(self):
        r = self.client.get('/architect')
        self._assert_brand_shell(r)
        self.assertIn('این سرویس فعلاً فعال نیست', r.text)
        self.assertIn('/electrical', r.text)
        self.assertIn('/mechanical', r.text)


if __name__ == '__main__':
    unittest.main()
