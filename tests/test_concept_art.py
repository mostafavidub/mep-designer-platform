import unittest
from fastapi.testclient import TestClient
from app.main_auto import app


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
