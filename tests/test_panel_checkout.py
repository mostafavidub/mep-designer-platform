"""HTTP + real SQLite tests; no customer drawings, payments or CAD jobs run."""
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.main_health import app, main_auto, DesignJob
from app.panel_checkout import digest

legacy = main_auto.legacy


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setenv("PANEL_BRIDGE_TOKEN", "checkout-test-only-secret")
    browser = TestClient(app, raise_server_exceptions=False)
    headers = {"x-panel-token": "checkout-test-only-secret"}
    phone = "09" + str(int(uuid4().hex[:10], 16)).zfill(9)[-9:]
    session = browser.post('/internal/panel/customer/session', headers=headers, json={"phone": phone})
    assert session.status_code == 200, session.text
    auth = {**headers, 'x-customer-session': session.json()['session']}
    uid = int(session.json()['userId'].split('-')[1])
    result = browser.post('/api/upload/init/electrical', json={'name': 'checkout fixture'})
    pid = result.json()['project_id']
    with legacy.Session() as db:
        project = db.get(legacy.Project, pid)
        project.status = 'ready_to_design'
        project.questions = [{'key': 'location', 'question': 'شهر پروژه'}]
        project.answers = {'discipline': 'electrical', 'location': 'گنبد', 'water_inlet_pressure': '2.5', 'gas_pressure': '17.8'}
        project.analysis = {'geometry_area_m2': 100, 'architectural_auto': {'geometry_area_m2': 100}}
        db.commit()
    handoff = browser.post(f'/projects/{pid}/panel-handoff')
    assert handoff.status_code == 200, handoff.text
    token = parse_qs(urlparse(handoff.json()['url']).fragment)['handoff'][0]
    claim = browser.post('/internal/panel/customer/claim', headers=auth, json={'token': token})
    assert claim.status_code == 200, claim.text
    quote = browser.post('/internal/panel/customer/quote', headers=auth, json={'engineProjectId': pid, 'area': 100})
    assert quote.status_code == 200, quote.text
    order = quote.json()['project']
    return browser, auth, uid, pid, token, order


def fund(uid, amount):
    with legacy.Session() as db:
        wallet = db.query(app.state.commercial['Wallet']).filter_by(user_id=uid).one()
        wallet.balance = amount
        db.commit()


def pay(browser, auth, pid, order, **extra):
    return browser.post('/internal/panel/customer/pay', headers=auth,
                        json={'engineProjectId': pid, 'quoteToken': order['quoteToken'], 'method': 'wallet', **extra})


def test_phone_login_starts_with_zero_not_demo_credit(flow):
    browser, auth, uid, pid, token, order = flow
    assert browser.post('/internal/panel/customer/state', headers=auth, json={}).json()['balance'] == 0


def test_admin_adjustment_syncs_with_customer_and_is_idempotent(flow):
    browser, auth, uid, pid, token, order = flow
    body = {'action': 'wallet_adjustment', 'userId': f'CUST-{uid}', 'amount': 10000,
            'kind': 'credit', 'reason': 'Approved support credit', 'requestId': str(uuid4())}
    for _ in range(2):
        result = browser.post('/internal/panel/admin/accounts', headers=auth, json=body)
        assert result.status_code == 200, result.text
    account = browser.post('/internal/panel/customer/state', headers=auth, json={}).json()
    assert account['balance'] == 10000
    assert len(account['transactions']) == 1
    assert next(u for u in result.json()['users'] if u['id'] == f'CUST-{uid}')['wallet'] == 10000
    assert browser.post('/internal/panel/admin/accounts', headers=auth, json={**body, 'amount': 20000}).status_code == 409
    assert browser.post('/internal/panel/admin/accounts', json=body).status_code == 404
    assert browser.post('/internal/panel/customer/wallet_adjustment', headers=auth, json=body).status_code == 404


def test_admin_debit_cannot_overdraw(flow):
    browser, auth, uid, *_ = flow
    fund(uid, 100)
    body = {'action': 'wallet_adjustment', 'userId': f'CUST-{uid}', 'amount': 101,
            'kind': 'debit', 'reason': 'Correction', 'requestId': str(uuid4())}
    assert browser.post('/internal/panel/admin/accounts', headers=auth, json=body).status_code == 409
    assert browser.post('/internal/panel/customer/state', headers=auth, json={}).json()['balance'] == 100


def test_concurrent_admin_debits_do_not_lose_updates(flow):
    browser, auth, uid, *_ = flow
    fund(uid, 100)
    def debit(_):
        return browser.post('/internal/panel/admin/accounts', headers=auth, json={
            'action':'wallet_adjustment', 'userId':f'CUST-{uid}', 'amount':80,
            'kind':'debit', 'reason':'concurrent debit fixture', 'requestId':str(uuid4())})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(debit, range(2)))
    assert sorted(r.status_code for r in results) == [200, 409]
    state = browser.post('/internal/panel/customer/state', headers=auth, json={}).json()
    assert state['balance'] == 20
    assert len(state['transactions']) == 1


def test_demo_topup_explicit_flag_replay_and_ledger(flow, monkeypatch):
    browser, auth, uid, *_ = flow
    body = {'amount': 12345, 'requestId': str(uuid4())}
    monkeypatch.delenv('PANEL_DEMO_PAYMENTS', raising=False)
    assert browser.post('/internal/panel/customer/topup', headers=auth, json=body).status_code == 409
    monkeypatch.setenv('PANEL_DEMO_PAYMENTS', '1')
    for _ in range(2):
        result = browser.post('/internal/panel/customer/topup', headers=auth, json=body)
        assert result.status_code == 200, result.text
    assert result.json()['balance'] == 12345
    assert len(result.json()['transactions']) == 1
    assert result.json()['transactions'][0]['status'] == 'آزمایشی'


def test_demo_bank_queues_once_without_wallet_debit(flow, monkeypatch):
    browser, auth, uid, pid, token, order = flow
    monkeypatch.setenv('PANEL_DEMO_PAYMENTS', '1')
    for _ in range(2):
        response = pay(browser, auth, pid, order, method='gateway')
        assert response.status_code == 200, response.text
    assert response.json()['balance'] == 0
    assert len(response.json()['transactions']) == 1
    assert response.json()['transactions'][0]['category'] == 'demo_payment'
    with legacy.Session() as db:
        assert db.query(DesignJob).filter_by(project_id=pid).count() == 1
        assert db.query(app.state.panel_checkout.Ledger).filter_by(project_id=pid).count() == 0


def test_handoff_preserves_answers_and_replay_same_account(flow):
    browser, auth, uid, pid, token, order = flow
    claim = browser.post('/internal/panel/customer/claim', headers=auth, json={'token': token})
    assert claim.status_code == 200
    assert claim.json()['id'] == order['id']
    assert claim.json()['answers']['gas_pressure'] == '17.8'
    assert claim.json()['answers']['location'] == 'گنبد'
    with legacy.Session() as db:
        assert db.query(DesignJob).filter_by(project_id=pid).count() == 0


def test_cross_account_claim_and_payment_forbidden(flow):
    browser, auth, uid, pid, token, order = flow
    other = browser.post('/internal/panel/customer/session', headers={'x-panel-token': 'checkout-test-only-secret'}, json={'phone': '09000000000'}).json()
    other_auth = {**auth, 'x-customer-session': other['session']}
    assert browser.post('/internal/panel/customer/claim', headers=other_auth, json={'token': token}).status_code == 404
    assert pay(browser, other_auth, pid, order).status_code == 404


def test_insufficient_funds_has_no_ledger_or_job(flow):
    browser, auth, uid, pid, token, order = flow
    assert pay(browser, auth, pid, order).status_code == 409
    with legacy.Session() as db:
        assert db.query(app.state.panel_checkout.Ledger).filter_by(project_id=pid).count() == 0
        assert db.query(DesignJob).filter_by(project_id=pid).count() == 0


def test_double_click_is_one_debit_one_ledger_one_job(flow):
    browser, auth, uid, pid, token, order = flow
    fund(uid, order['amount'] + 1000)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: pay(browser, auth, pid, order), range(2)))
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    with legacy.Session() as db:
        assert db.query(app.state.commercial['Wallet']).filter_by(user_id=uid).one().balance == 1000
        assert db.query(app.state.panel_checkout.Ledger).filter_by(project_id=pid).count() == 1
        assert db.query(DesignJob).filter_by(project_id=pid).count() == 1
    state = browser.post('/internal/panel/customer/state', headers=auth, json={}).json()
    assert state['transactions'][0]['amount'] == -order['amount']


def test_transaction_rolls_back_when_job_insert_fails(flow):
    browser, auth, uid, pid, token, order = flow
    fund(uid, order['amount'] + 1000)
    def fail(mapper, connection, target):
        if target.project_id == pid:
            raise RuntimeError('test injected queue persistence failure')
    event.listen(DesignJob, 'before_insert', fail)
    try:
        assert pay(browser, auth, pid, order).status_code == 500
    finally:
        event.remove(DesignJob, 'before_insert', fail)
    with legacy.Session() as db:
        assert db.query(app.state.commercial['Wallet']).filter_by(user_id=uid).one().balance == order['amount'] + 1000
        assert db.query(app.state.panel_checkout.Ledger).filter_by(project_id=pid).count() == 0
        assert not db.get(app.state.panel_checkout.Checkout, pid).paid


def test_tampered_price_stale_quote_and_gateway_do_not_pay(flow):
    browser, auth, uid, pid, token, order = flow
    fund(uid, order['amount'] + 1000)
    assert pay(browser, auth, pid, order, quoteToken='wrong').status_code == 409
    assert pay(browser, auth, pid, order, method='gateway').status_code == 503
    assert pay(browser, auth, pid, order, amount=1).status_code == 200
    state = browser.post('/internal/panel/customer/state', headers=auth, json={}).json()
    assert state['balance'] == 1000


def test_expired_handoff_and_forged_session_fail(flow):
    browser, auth, uid, pid, token, order = flow
    with legacy.Session() as db:
        db.get(app.state.panel_checkout.Handoff, digest(token)).expires = 1
        db.commit()
    assert browser.post('/internal/panel/customer/claim', headers=auth, json={'token': token}).status_code == 404
    assert browser.post('/internal/panel/customer/state', headers={**auth, 'x-customer-session': '1.9999999999.fake'}, json={}).status_code == 401
