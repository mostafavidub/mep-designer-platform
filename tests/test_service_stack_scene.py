import unittest

from fastapi.testclient import TestClient
from app.main_auto import app


class ServiceStackSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_home_loads_services_stack_assets_only_on_home(self):
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertIn('/static/service-stack.css', home.text)
        self.assertIn('/static/service-stack.js', home.text)
        for path in ('/mechanical', '/electrical', '/blog', '/architect'):
            page = self.client.get(path)
            self.assertNotIn('/static/service-stack.css', page.text)
            self.assertNotIn('/static/service-stack.js', page.text)

    def test_services_scene_uses_pinned_viewport_and_absolute_layers(self):
        css = self.client.get('/static/service-stack.css')
        js = self.client.get('/static/service-stack.js')
        self.assertEqual(css.status_code, 200)
        self.assertEqual(js.status_code, 200)
        self.assertIn('.service-stack-scene', css.text)
        self.assertIn('.service-stack-viewport', css.text)
        self.assertIn('.service-stack-stage', css.text)
        self.assertIn('position:sticky!important', css.text)
        self.assertIn('height:100svh', css.text)
        self.assertIn('position:absolute!important', css.text)
        self.assertIn('translate3d', css.text)
        self.assertIn("scene.className='service-stack-scene'", js.text)
        self.assertIn("viewport.className='service-stack-viewport'", js.text)
        self.assertIn("stage.className='service-stack-stage'", js.text)
        self.assertIn("stage.appendChild(head)", js.text)
        self.assertIn("stage.appendChild(grid)", js.text)
        self.assertIn("const layers=[head,...cards]", js.text)
        self.assertIn('scene.offsetHeight-vh', js.text)
        self.assertIn('requestAnimationFrame', js.text)
        self.assertIn("addEventListener('scroll'", js.text)
        self.assertIn('prefers-reduced-motion: reduce', css.text)

    def test_reverse_scroll_is_derived_from_current_scene_progress(self):
        js = self.client.get('/static/service-stack.js')
        self.assertEqual(js.status_code, 200)
        self.assertIn('const overall=clamp((-rect.top)/travel,0,1)', js.text)
        self.assertIn('const enter=i===0?1:clamp(segment-(i-1),0,1)', js.text)
        self.assertIn('const enterY=(1-ease(enter))*108', js.text)
        self.assertNotIn('scrollDirection', js.text)
        self.assertNotIn('lastScroll', js.text)

    def test_services_keep_three_destinations(self):
        home = self.client.get('/')
        self.assertIn('href="/mechanical"', home.text)
        self.assertIn('href="/electrical"', home.text)
        self.assertIn('href="/architect"', home.text)


if __name__ == '__main__':
    unittest.main()
