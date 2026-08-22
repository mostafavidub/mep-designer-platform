import unittest

from fastapi.testclient import TestClient
from app.main_auto import app


class HeroPinRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_home_runs_service_reorder_before_hero_scene(self):
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        service_pos = home.text.find('/static/service-stack.js?v=20260822-1048')
        hero_pos = home.text.find('/static/hero-scroll-v1.js?v=20260822-1048')
        self.assertGreaterEqual(service_pos, 0)
        self.assertGreaterEqual(hero_pos, 0)
        self.assertLess(service_pos, hero_pos)

    def test_hero_scene_targets_workflow_and_keeps_it_in_same_scene(self):
        js = self.client.get('/static/hero-scroll-v1.js')
        css = self.client.get('/static/hero-scroll-v1.css')
        self.assertEqual(js.status_code, 200)
        self.assertEqual(css.status_code, 200)
        self.assertIn("document.querySelector('[data-workflow-road]')", js.text)
        self.assertIn('scene.appendChild(hero)', js.text)
        self.assertIn('scene.appendChild(next)', js.text)
        self.assertIn("next.classList.add('hero-overlap-next')", js.text)
        self.assertIn('position:sticky!important', css.text)
        self.assertIn('height:100svh!important', css.text)
        self.assertIn('--hero-cover-gap:0px', css.text)
        self.assertIn('margin-top:var(--hero-cover-gap)!important', css.text)
        self.assertIn('min-height:100svh', css.text)
        self.assertIn('requestAnimationFrame', js.text)
        self.assertIn('prefers-reduced-motion:reduce', css.text)


if __name__ == '__main__':
    unittest.main()
