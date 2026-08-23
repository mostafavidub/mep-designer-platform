import unittest
from fastapi.testclient import TestClient
from app.main_health import app

class MechanicalHeroV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.client = TestClient(app)

    def test_mechanical_page_loads_isolated_static_hero(self):
        r=self.client.get('/mechanical'); self.assertEqual(r.status_code,200)
        self.assertIn('/static/mechanical-hero-v3.css?v=20260823-0928',r.text)
        self.assertIn('/static/mechanical-hero-v3.js?v=20260823-0928',r.text)
        self.assertNotIn('/static/mechanical-hero-static.css',r.text)
        self.assertNotIn('/static/hero-scroll-v1.js',r.text)

    def test_mechanical_hero_css_is_static_scoped_and_split(self):
        css=self.client.get('/static/mechanical-hero-v3.css'); self.assertEqual(css.status_code,200)
        for expected in ('.mechanical .discipline-hero.mechanical-landing-hero',"grid-template-areas:'art copy' 'meta meta'",'object-fit:contain','animation:none!important','transition:none!important','transform:none!important','@media(max-width:1024px)','@media(max-width:640px)'):
            self.assertIn(expected,css.text)

    def test_mechanical_hero_script_uses_browser_safe_mechanical_asset(self):
        js=self.client.get('/static/mechanical-hero-v3.js'); self.assertEqual(js.status_code,200)
        self.assertIn("document.querySelector('.discipline-page.mechanical')",js.text)
        self.assertIn('/static/hero-mechanical.svg?v=20260823-1049',js.text)
        self.assertIn('mechanical-hero-v3-art',js.text)
        self.assertNotIn('hero-integrated-mep-v1',js.text)
        self.assertNotIn('hero-electrical',js.text)
        self.assertNotIn('requestAnimationFrame',js.text)
        self.assertNotIn("addEventListener('scroll'",js.text)

    def test_browser_safe_asset_route_exists(self):
        art=self.client.get('/static/hero-mechanical.svg?v=20260823-1049')
        self.assertEqual(art.status_code,200)
        self.assertIn('image/svg+xml',art.headers.get('content-type',''))
        self.assertGreater(len(art.content),2000)

    def test_home_and_electrical_are_not_given_mechanical_v3_runtime(self):
        home=self.client.get('/'); electrical=self.client.get('/electrical')
        self.assertEqual(home.status_code,200); self.assertEqual(electrical.status_code,200)
        self.assertNotIn('/static/mechanical-hero-v3.js',home.text)
        self.assertNotIn('/static/mechanical-hero-v3.js',electrical.text)
        self.assertIn('/static/hero-scroll-v1.js',home.text)

if __name__=='__main__': unittest.main()
