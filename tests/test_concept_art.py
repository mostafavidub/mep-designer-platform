import unittest

from fastapi.testclient import TestClient

from app.main_health import app


class ConceptArtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_home_loads_concept_art_and_all_three_assets_exist(self):
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertIn('/static/concept-art.css', home.text)
        for asset in (
            '/static/service-art-mechanical.svg',
            '/static/service-art-electrical.svg',
            '/static/service-art-architect.svg',
        ):
            r = self.client.get(asset)
            self.assertEqual(r.status_code, 200)
            self.assertIn('<svg', r.text)

    def test_mechanical_card_art_is_browser_safe_nonblank_svg(self):
        r = self.client.get('/static/hero-mechanical.svg?v=20260822-1618')
        self.assertEqual(r.status_code, 200)
        self.assertIn('image/svg+xml', r.headers.get('content-type', ''))
        self.assertGreater(len(r.content), 1000)
        self.assertIn('<svg', r.text)
        self.assertIn('WATER / SANITARY / VENT / GAS', r.text)
        self.assertIn('<path', r.text)

    def test_native_img_rendering_is_wired_and_visible(self):
        js = self.client.get('/static/service-stack.js')
        css = self.client.get('/static/concept-art.css')
        self.assertEqual(js.status_code, 200)
        self.assertEqual(css.status_code, 200)
        self.assertIn("art.className='service-stack-art'", js.text)
        self.assertIn("'/service-art/mechanical.jpg?v=20260822-2015'", js.text)
        self.assertIn('.service-stack-section .service-stack-art{', css.text)
        self.assertIn('display:block!important', css.text)
        self.assertIn('width:56%!important', css.text)
        self.assertIn('height:100%!important', css.text)
        self.assertIn('object-fit:contain!important', css.text)
        self.assertIn('.service-stack-section .service-cta::after{display:none!important;content:none!important}', css.text)

        art = self.client.get('/service-art/mechanical.jpg?v=20260822-2015')
        self.assertEqual(art.status_code, 200)
        self.assertGreater(len(art.content), 30_000)
        self.assertEqual(art.headers.get('content-type'), 'image/webp')
        self.assertEqual(art.headers.get('x-engitools-art'), 'mechanical-approved-1920x1080')
        self.assertTrue(art.content.startswith(b'RIFF'))
        self.assertEqual(art.content[8:12], b'WEBP')
        sync = art.content.find(b'\x9d\x01\x2a')
        self.assertGreaterEqual(sync, 0)
        width = int.from_bytes(art.content[sync + 3:sync + 5], 'little') & 0x3FFF
        height = int.from_bytes(art.content[sync + 5:sync + 7], 'little') & 0x3FFF
        self.assertEqual((width, height), (1920, 1080))

    def test_mechanical_and_electrical_landings_reuse_service_art(self):
        css = self.client.get('/static/concept-art.css')
        self.assertEqual(css.status_code, 200)
        self.assertIn(".discipline-page.mechanical .discipline-visual", css.text)
        self.assertIn("background-image:var(--et-art-mechanical)!important", css.text)
        self.assertIn(".discipline-page.electrical .discipline-visual", css.text)
        self.assertIn("background-image:var(--et-art-electrical)!important", css.text)
        mech = self.client.get('/mechanical')
        elec = self.client.get('/electrical')
        self.assertIn('/static/concept-art.css', mech.text)
        self.assertIn('/static/concept-art.css', elec.text)

    def test_service_stack_maps_each_art_to_its_own_card(self):
        css = self.client.get('/static/concept-art.css')
        self.assertIn('.service-card-1::after{background-image:var(--et-art-mechanical)}', css.text)
        self.assertIn('.service-card-dark::after{background-image:var(--et-art-electrical)}', css.text)
        self.assertIn('.service-card-muted::after{background-image:var(--et-art-architect)}', css.text)
        self.assertIn('pointer-events:none', css.text)

    def test_architect_scope_matches_planned_product(self):
        page = self.client.get('/architect')
        self.assertEqual(page.status_code, 200)
        self.assertIn('نقشه زمین', page.text)
        self.assertIn('مجموعه پلان‌های معماری', page.text)
        self.assertIn('/static/service-art-architect.svg', page.text)


if __name__ == '__main__':
    unittest.main()
