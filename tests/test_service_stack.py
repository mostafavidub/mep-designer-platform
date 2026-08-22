import unittest
from fastapi.testclient import TestClient
from app.main_auto import app


class ServiceStackRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_home_loads_service_stack_assets(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('/static/service-stack.css', r.text)
        self.assertIn('/static/service-stack.js', r.text)
        for path in ('/electrical', '/mechanical', '/blog', '/architect'):
            page = self.client.get(path)
            self.assertNotIn('/static/service-stack.css', page.text)
            self.assertNotIn('/static/service-stack.js', page.text)

    def test_service_stack_reorders_after_workflow_and_uses_pinned_scene(self):
        js = self.client.get('/static/service-stack.js')
        css = self.client.get('/static/service-stack.css')
        self.assertEqual(js.status_code, 200)
        self.assertEqual(css.status_code, 200)
        self.assertIn("workflow.insertAdjacentElement('afterend',section)", js.text)
        self.assertIn('خدماتی که ما به مهندسان ارائه می‌کنیم', js.text)
        self.assertIn("section.classList.add('service-stack-section')", js.text)
        self.assertIn('.service-stack-scene', css.text)
        self.assertIn('.service-stack-viewport', css.text)
        self.assertIn('position:sticky!important', css.text)
        self.assertIn('position:absolute!important', css.text)
        self.assertIn('--stack-enter', css.text)
        self.assertIn('--stack-scale', css.text)
        self.assertIn("scene.className='service-stack-scene'", js.text)
        self.assertIn("viewport.className='service-stack-viewport'", js.text)
        self.assertIn('requestAnimationFrame', js.text)
        self.assertIn("addEventListener('scroll'", js.text)
        self.assertIn('prefers-reduced-motion: reduce', css.text)

    def test_all_three_service_routes_remain_present(self):
        r = self.client.get('/')
        self.assertIn('href="/mechanical"', r.text)
        self.assertIn('href="/electrical"', r.text)
        self.assertIn('href="/architect"', r.text)


if __name__ == '__main__':
    unittest.main()
