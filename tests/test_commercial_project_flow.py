import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main_health import app
from app import main as legacy


class CommercialProjectFlowTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.get('/panel')
        commercial = app.state.commercial
        db = legacy.Session()
        for key in ('mechanical', 'electrical'):
            row = db.query(commercial['ServicePricing']).filter(commercial['ServicePricing'].discipline == key).first()
            if row: row.enabled = True
        db.commit(); db.close()

    def _ready_project(self, discipline='electrical'):
        init = self.client.post(f'/api/upload/init/{discipline}', json={'name': 'پروژه تست پرداخت'})
        pid = init.json()['project_id']
        db = legacy.Session()
        project = db.get(legacy.Project, pid)
        project.status = 'ready_to_design'
        project.answers = {'discipline': discipline}
        project.analysis = {'discipline': discipline, 'file_count': 1}
        db.commit(); db.close()
        return pid

    def test_panel_and_new_project_surface(self):
        panel = self.client.get('/panel')
        self.assertEqual(panel.status_code, 200)
        self.assertIn('پروژه جدید', panel.text)
        self.assertIn('موجودی کیف پول', panel.text)
        new = self.client.get('/panel/projects/new')
        self.assertIn('نام پروژه', new.text)
        self.assertIn('DXF یا ZIP', new.text)

    def test_get_start_project_recovers_to_upload_page(self):
        response = self.client.get('/start-project/mechanical', follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/mechanical#start')
        page = self.client.get(response.headers['location'])
        self.assertEqual(page.status_code, 200)
        self.assertIn('آپلود و تحلیل', page.text)

        missing = self.client.get('/start-project', follow_redirects=False)
        self.assertEqual(missing.status_code, 303)
        self.assertEqual(missing.headers['location'], '/panel/projects/new')

        unknown = self.client.get('/start-project/unknown', follow_redirects=False)
        self.assertEqual(unknown.status_code, 404)

    def test_quote_appears_and_design_is_payment_gated(self):
        pid = self._ready_project()
        page = self.client.get(f'/projects/{pid}')
        self.assertIn('قیمت طراحی پروژه', page.text)
        self.assertIn('پرداخت آزمایشی Staging', page.text)
        self.assertIn('پرداخت از کیف پول', page.text)
        blocked = self.client.post(f'/projects/{pid}/design-json')
        self.assertEqual(blocked.status_code, 402)
        self.assertEqual(blocked.json()['error'], 'payment_required')

    def test_insufficient_wallet_is_disabled_and_rejected_server_side(self):
        pid = self._ready_project('mechanical')
        commercial = app.state.commercial
        db = legacy.Session()
        project = db.get(legacy.Project, pid)
        commercial['quote_for'](project)
        wallet = db.query(commercial['Wallet']).filter(commercial['Wallet'].user_id == project.user_id).first()
        wallet.balance = 0
        db.commit(); db.close()
        page = self.client.get(f'/projects/{pid}')
        self.assertIn('موجودی کیف پول کافی نیست', page.text)
        self.assertIn('disabled aria-disabled="true"', page.text)
        rejected = self.client.post(f'/projects/{pid}/pay/wallet')
        self.assertEqual(rejected.status_code, 409)

    def test_mechanical_runtime_preflight_blocks_payment_without_marking_quote_paid(self):
        pid = self._ready_project('mechanical')
        with patch('app.commercial_flow.assert_runtime_contract_synchronized', side_effect=RuntimeError('mismatch')):
            rejected = self.client.post(
                f'/projects/{pid}/pay/gateway',
                headers={'host': 'web-app-staging-production.up.railway.app'},
            )
        self.assertEqual(rejected.status_code, 503)
        commercial = app.state.commercial
        db = legacy.Session()
        quote = db.query(commercial['ProjectQuote']).filter(commercial['ProjectQuote'].project_id == pid).first()
        self.assertTrue(quote is None or not quote.paid)
        db.close()

    def test_staging_demo_gateway_marks_paid_and_starts_design(self):
        pid = self._ready_project('electrical')
        queued = []
        original = app.state.enqueue_design_if_ready
        app.state.enqueue_design_if_ready = lambda project_id: queued.append(project_id) or True
        try:
            response = self.client.post(
                f'/projects/{pid}/pay/gateway',
                headers={'host': 'web-app-staging-production.up.railway.app'},
                follow_redirects=False,
            )
        finally:
            app.state.enqueue_design_if_ready = original
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], f'/projects/{pid}?payment=success&design=queued')
        self.assertEqual(queued, [pid])
        commercial = app.state.commercial
        db = legacy.Session()
        quote = db.query(commercial['ProjectQuote']).filter(commercial['ProjectQuote'].project_id == pid).one()
        self.assertTrue(quote.paid)
        self.assertEqual(quote.payment_method, 'staging_demo_gateway')
        db.close()

    def test_demo_gateway_is_closed_outside_staging(self):
        pid = self._ready_project('electrical')
        rejected = self.client.post(f'/projects/{pid}/pay/gateway')
        self.assertEqual(rejected.status_code, 503)
        commercial = app.state.commercial
        db = legacy.Session()
        quote = db.query(commercial['ProjectQuote']).filter(commercial['ProjectQuote'].project_id == pid).first()
        self.assertTrue(quote is None or not quote.paid)
        db.close()

    def test_staging_gateway_missing_basis_redirects_without_internal_error_or_payment(self):
        pid = self._ready_project('mechanical')
        response = self.client.post(
            f'/projects/{pid}/pay/gateway',
            headers={'host': 'web-app-staging-production.up.railway.app'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], f'/projects/{pid}?payment=input-required')
        commercial = app.state.commercial
        db = legacy.Session()
        project = db.get(legacy.Project, pid)
        quote = db.query(commercial['ProjectQuote']).filter(commercial['ProjectQuote'].project_id == pid).one()
        self.assertEqual(project.status, 'asking')
        self.assertFalse(quote.paid)
        db.close()

    def test_admin_pricing_controls_area_formula(self):
        saved = self.client.post('/admin/pricing/electrical', data={
            'enabled': 'on', 'minimum_price': 3_000_000, 'price_per_m2': 20_000,
        })
        self.assertEqual(saved.status_code, 200)
        pid = self._ready_project('electrical')
        db = legacy.Session(); project = db.get(legacy.Project, pid)
        project.analysis = {'discipline': 'electrical', 'architectural_auto': {'geometry_area_m2': 250}}
        db.commit(); db.close()
        page = self.client.get(f'/projects/{pid}')
        self.assertIn('5٬000٬000', page.text)

    def test_disabled_service_is_hidden_and_rejected(self):
        self.client.post('/admin/pricing/mechanical', data={
            'minimum_price': 4_900_000, 'price_per_m2': 28_000,
        })
        new = self.client.get('/panel/projects/new')
        self.assertIn('این سرویس موقتاً غیرفعال است', new.text)
        blocked = self.client.post('/api/upload/init/mechanical', json={'name': 'blocked'})
        self.assertEqual(blocked.status_code, 503)
        self.assertEqual(blocked.json()['error'], 'service_disabled')


if __name__ == '__main__':
    unittest.main()
