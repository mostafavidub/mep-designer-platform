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
        self.assertIn('.service-stack-stage', css.text)
        self.assertIn('position:sticky!important', css.text)
        self.assertIn('position:absolute!important', css.text)
        self.assertIn('--stack-enter', css.text)
        self.assertIn('--stack-scale', css.text)
        self.assertNotIn('filter:brightness', css.text)
        self.assertNotIn('--stack-opacity', css.text)
        self.assertIn("stage.appendChild(head)", js.text)
        self.assertIn("stage.appendChild(grid)", js.text)
        self.assertIn("const layers=[head,...cards]", js.text)
        self.assertIn('requestAnimationFrame', js.text)
        self.assertIn("addEventListener('scroll'", js.text)
        self.assertIn('prefers-reduced-motion: reduce', css.text)

    def test_service_cards_have_accessible_contrast_and_full_card_navigation(self):
        js = self.client.get('/static/service-stack.js')
        css = self.client.get('/static/service-stack.css')
        self.assertEqual(js.status_code, 200)
        self.assertEqual(css.status_code, 200)
        self.assertIn("card.classList.add('service-card-dark')", js.text)
        self.assertIn("card.classList.add('service-card-clickable')", js.text)
        self.assertIn("card.addEventListener('click'", js.text)
        self.assertIn("card.addEventListener('keydown'", js.text)
        self.assertIn('location.assign(targetHref)', js.text)
        self.assertIn("card.setAttribute('role','link')", js.text)
        self.assertIn('card.tabIndex=0', js.text)
        self.assertIn('.service-card-dark', css.text)
        self.assertIn('color:#fff!important', css.text)
        self.assertIn('.service-card-dark .cta-body p{color:#e2e2dc!important}', css.text)
        self.assertIn('.service-card-clickable{cursor:pointer!important}', css.text)
        self.assertIn('.service-card-clickable:focus-visible', css.text)

    def test_all_three_service_routes_remain_present(self):
        r = self.client.get('/')
        self.assertIn('href="/mechanical"', r.text)
        self.assertIn('href="/electrical"', r.text)
        self.assertIn('href="/architect"', r.text)


if __name__ == '__main__':
    unittest.main()
