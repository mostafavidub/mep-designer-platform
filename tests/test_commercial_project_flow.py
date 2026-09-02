import unittest

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

    def test_quote_appears_and_design_is_payment_gated(self):
        pid = self._ready_project()
        page = self.client.get(f'/projects/{pid}')
        self.assertIn('قیمت طراحی پروژه', page.text)
        self.assertIn('پرداخت از درگاه بانکی', page.text)
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
