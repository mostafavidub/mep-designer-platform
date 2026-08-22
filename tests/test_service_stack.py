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
        self.assertIn('/static/service-stack-contrast-fix.css', r.text)
        for path in ('/electrical', '/mechanical', '/blog', '/architect'):
            page = self.client.get(path)
            self.assertNotIn('/static/service-stack.css', page.text)
            self.assertNotIn('/static/service-stack.js', page.text)
            self.assertNotIn('/static/service-stack-contrast-fix.css', page.text)

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

    def test_card_routes_stay_native_distinct_and_full_surface_clickable(self):
        home = self.client.get('/')
        self.assertIn('<a class="companion-card service-cta mechanical-card" href="/mechanical">', home.text)
        self.assertIn('<a class="companion-card service-cta electrical-card" href="/electrical">', home.text)
        self.assertIn('<a class="companion-card service-cta architect-card" href="/architect">', home.text)
        js = self.client.get('/static/service-stack.js')
        self.assertIn("card.dataset.serviceHref=card.getAttribute('href')||''", js.text)
        self.assertNotIn('location.assign(', js.text)
        self.assertNotIn('layer.style.pointerEvents', js.text)
        self.assertIn('card.style.zIndex=String(30+i)', js.text)

    def test_dark_card_title_and_copy_have_explicit_high_contrast(self):
        css = self.client.get('/static/service-stack-contrast-fix.css')
        self.assertEqual(css.status_code, 200)
        self.assertIn('.service-card-dark .cta-body h3', css.text)
        self.assertIn('color:#ffffff!important', css.text)
        self.assertIn('.service-card-dark .cta-body p', css.text)
        self.assertIn('color:#f0f0eb!important', css.text)
        self.assertIn('opacity:1!important', css.text)
        self.assertIn('visibility:visible!important', css.text)
        self.assertIn('a.service-card-clickable', css.text)
        self.assertIn('pointer-events:auto!important', css.text)

    def test_hover_cannot_freeze_scroll_driven_card_transform(self):
        css = self.client.get('/static/service-stack-contrast-fix.css')
        self.assertEqual(css.status_code, 200)
        self.assertIn('.service-cta:hover', css.text)
        self.assertIn('transform:translate3d(0,var(--stack-enter),0) scale(var(--stack-scale))!important', css.text)
        self.assertIn('transition:none!important', css.text)
        # The hover state may animate the arrow, but never the card transform itself.
        self.assertIn('a.service-card-clickable:hover .cta-arrow', css.text)

    def test_all_three_service_routes_remain_present(self):
        r = self.client.get('/')
        self.assertIn('href="/mechanical"', r.text)
        self.assertIn('href="/electrical"', r.text)
        self.assertIn('href="/architect"', r.text)


if __name__ == '__main__':
    unittest.main()
