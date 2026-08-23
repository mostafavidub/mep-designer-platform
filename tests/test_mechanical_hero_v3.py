import unittest

from fastapi.testclient import TestClient

from app.main_health import app


class MechanicalHeroV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_mechanical_page_loads_isolated_static_hero(self):
        r = self.client.get('/mechanical')
        self.assertEqual(r.status_code, 200)
        self.assertIn('/static/mechanical-hero-v3.css?v=20260823-0915', r.text)
        self.assertIn('/static/mechanical-hero-v3.js?v=20260823-0915', r.text)
        self.assertIn('rel="preload" as="image" href="/service-art/mechanical.jpg?v=20260823-0915"', r.text)
        self.assertNotIn('/static/mechanical-hero-static.css', r.text)
        self.assertNotIn('/static/hero-scroll-v1.js', r.text)
        self.assertNotIn('/static/workflow-road.js', r.text)

    def test_mechanical_hero_css_is_static_scoped_and_split(self):
        css = self.client.get('/static/mechanical-hero-v3.css')
        self.assertEqual(css.status_code, 200)
        for expected in (
            '.mechanical .discipline-hero.mechanical-landing-hero',
            "grid-template-areas:'art copy' 'meta meta'",
            'object-fit:contain',
            'animation:none!important',
            'transition:none!important',
            'transform:none!important',
            '@media(max-width:1024px)',
            '@media(max-width:640px)',
        ):
            self.assertIn(expected, css.text)
        self.assertNotIn('hero-integrated-mep-v1.jpg', css.text)
        self.assertNotIn('hero-electrical', css.text)

    def test_mechanical_hero_script_uses_only_mechanical_asset(self):
        js = self.client.get('/static/mechanical-hero-v3.js')
        self.assertEqual(js.status_code, 200)
        self.assertIn("document.querySelector('.discipline-page.mechanical')", js.text)
        self.assertIn('/service-art/mechanical.jpg?v=20260823-0915', js.text)
        self.assertIn('mechanical-hero-v3-art', js.text)
        self.assertNotIn('hero-integrated-mep-v1', js.text)
        self.assertNotIn('hero-electrical', js.text)
        self.assertNotIn('requestAnimationFrame', js.text)
        self.assertNotIn("addEventListener('scroll'", js.text)

    def test_mechanical_asset_route_is_real_webp(self):
        art = self.client.get('/service-art/mechanical.jpg?v=20260823-0915')
        self.assertEqual(art.status_code, 200)
        self.assertEqual(art.headers.get('content-type'), 'image/webp')
        self.assertEqual(art.headers.get('x-engitools-art'), 'mechanical-approved-1920x1080')
        self.assertGreater(len(art.content), 30_000)
        self.assertTrue(art.content.startswith(b'RIFF'))
        self.assertEqual(art.content[8:12], b'WEBP')

    def test_home_and_electrical_are_not_given_mechanical_v3_runtime(self):
        home = self.client.get('/')
        electrical = self.client.get('/electrical')
        self.assertEqual(home.status_code, 200)
        self.assertEqual(electrical.status_code, 200)
        self.assertNotIn('/static/mechanical-hero-v3.js', home.text)
        self.assertNotIn('/static/mechanical-hero-v3.css', home.text)
        self.assertNotIn('/static/mechanical-hero-v3.js', electrical.text)
        self.assertNotIn('/static/mechanical-hero-v3.css', electrical.text)
        self.assertIn('/static/hero-scroll-v1.js', home.text)


if __name__ == '__main__':
    unittest.main()
