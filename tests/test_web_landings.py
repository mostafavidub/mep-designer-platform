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
        self.assertIn('/static/electrical-hero-v1.css', r.text)
        self.assertIn('electrical-landing-hero', r.text)
        self.assertIn('electrical-hero-art', r.text)
        self.assertIn('طراحی سیستم‌های', r.text)
        self.assertIn('الکتریکی ساختمان', r.text)
        self.assertIn('از پلان تا مدارک اجرایی', r.text)
        self.assertIn('شروع تحلیل پلان', r.text)
        self.assertIn('مشاهده نمونه خروجی‌ها', r.text)
        self.assertEqual(r.text.count('electrical-hero-feature'), 5)
        self.assertNotIn('/static/hero-scroll-v1.js', r.text)
        self.assertNotIn('/static/workflow-road.js', r.text)

    def test_electrical_hero_css_locks_approved_composition(self):
        css = self.client.get('/static/electrical-hero-v1.css')
        self.assertEqual(css.status_code, 200)
        self.assertIn("grid-template-areas:'. copy'", css.text)
        self.assertIn('direction:ltr', css.text)
        self.assertIn('grid-area:art', css.text)
        self.assertIn('grid-area:copy', css.text)
        self.assertIn('electrical-hero-final-20260822.webp', css.text)
        self.assertIn('background-size:cover!important', css.text)
        self.assertIn('display:none!important;grid-area:art', css.text)
        self.assertIn('@media(max-width:860px)', css.text)
        self.assertIn('@media(max-width:640px)', css.text)
        self.assertIn('prefers-reduced-motion:reduce', css.text)

    def test_mechanical_landing_renders_complete_contract(self):
        r = self.client.get('/mechanical')
        self._assert_common_discipline_contract(r, 'همراه مکانیک')
        self.assertIn('آب سرد و گرم', r.text)
        self.assertIn('فاضلاب', r.text)
        self.assertIn('HVAC', r.text)
        self.assertIn('project-1-mechanical-before-after.svg', r.text)
        self.assertNotIn('/static/electrical-hero-v1.css', r.text)
        self.assertNotIn('electrical-landing-hero', r.text)
        self.assertNotIn('/static/hero-scroll-v1.js', r.text)
        self.assertNotIn('/static/workflow-road.js', r.text)

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

    def test_home_has_scroll_driven_curved_workflow_road(self):
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertIn('data-workflow-road', home.text)
        self.assertIn('workflow-road-svg-desktop', home.text)
        self.assertIn('workflow-road-svg-mobile', home.text)
        self.assertEqual(home.text.count('data-workflow-stop='), 4)
        self.assertIn('ARCHITECTURE → READ → INFER → ENGINEERING OUTPUT', home.text)
        self.assertIn('/static/workflow-road.css', home.text)
        self.assertIn('/static/workflow-road.js', home.text)

        css = self.client.get('/static/workflow-road.css')
        js = self.client.get('/static/workflow-road.js')
        self.assertEqual(css.status_code, 200)
        self.assertEqual(js.status_code, 200)
        self.assertIn('.workflow-road-progress', css.text)
        self.assertIn('.workflow-stop.is-active', css.text)
        self.assertIn('@media(max-width:760px)', css.text)
        self.assertIn('prefers-reduced-motion:reduce', css.text)
        self.assertIn('getTotalLength', js.text)
        self.assertIn('strokeDashoffset', js.text)
        self.assertIn('getPointAtLength', js.text)
        self.assertIn('requestAnimationFrame', js.text)
        self.assertIn("addEventListener('scroll'", js.text)

    def test_workflow_step_three_copy_is_forced_left_of_marker_on_desktop(self):
        css = self.client.get('/static/workflow-road.css')
        self.assertEqual(css.status_code, 200)
        self.assertIn('.workflow-stop-3 .workflow-stop-copy', css.text)
        self.assertIn('position:absolute', css.text)
        self.assertIn('right:calc(100% + 28px)', css.text)
        self.assertIn('width:330px', css.text)
        self.assertIn('right:calc(100% + 22px)', css.text)
        self.assertIn('width:min(270px,25vw)', css.text)
        self.assertIn('position:static', css.text)

    def test_home_loads_layered_hero_scene_only_on_home(self):
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertIn('/static/hero-scroll-v1.css', home.text)
        self.assertIn('/static/hero-scroll-v1.js', home.text)
        self.assertIn('home-hero', home.text)
        for path in ('/electrical', '/mechanical', '/blog', '/architect'):
            page = self.client.get(path)
            self.assertNotIn('/static/hero-scroll-v1.css', page.text)
            self.assertNotIn('/static/hero-scroll-v1.js', page.text)
            self.assertNotIn('/static/workflow-road.css', page.text)
            self.assertNotIn('/static/workflow-road.js', page.text)

    def test_layered_hero_assets_pin_until_full_cover(self):
        css = self.client.get('/static/hero-scroll-v1.css')
        js = self.client.get('/static/hero-scroll-v1.js')
        self.assertEqual(css.status_code, 200)
        self.assertEqual(js.status_code, 200)
        self.assertIn('.hero-scroll-scene', css.text)
        self.assertIn('.hero-overlap-next', css.text)
        self.assertIn('position:sticky', css.text)
        self.assertIn('min-height:100svh', css.text)
        self.assertIn('--hero-cover-gap', css.text)
        self.assertIn('@media(max-width:640px)', css.text)
        self.assertIn('prefers-reduced-motion:reduce', css.text)
        self.assertIn("scene.className='hero-scroll-scene'", js.text)
        self.assertIn('scene.appendChild(next)', js.text)
        self.assertIn("classList.add('hero-overlap-next')", js.text)
        self.assertIn('shrinkDistance', js.text)
        self.assertIn('requestAnimationFrame', js.text)
        self.assertIn("addEventListener('resize'", js.text)
        self.assertIn("addEventListener('scroll'", js.text)

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
        self.assertIn('در دست ساخت', r.text)
        self.assertIn('نقشه زمین', r.text)
        self.assertIn('مجموعه پلان‌های معماری', r.text)
        self.assertIn('/electrical', r.text)
        self.assertIn('/mechanical', r.text)


if __name__ == '__main__':
    unittest.main()
