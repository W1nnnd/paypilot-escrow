"""Offline demo lifecycle and concurrency regressions. Never call PayPal or Gemini."""
import asyncio
import copy

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.app as module
from backend.paypal_client import PayPalV2Client, PayPalAPIError, LIVE_MODE
from tests.conftest import GOOD_DELIVERABLE


@pytest.fixture
def replay(use_client):
    use_client(PayPalV2Client(mode="replay"))
    return TestClient(module.app)


def test_metrics_keep_currencies_separate(replay):
    metrics = replay.get('/api/milestones').json()['metrics']
    assert metrics['escrow_locked_by_currency'] == {'EUR': 1850.0, 'USD': 7300.0}
    assert metrics['escrow_locked_amount'] is None
    assert metrics['settled_captured_by_currency'] == {'USD': 2400.0}
    assert metrics['settled_captured_amount'] == 2400.0
    module.LEDGER['MS-1003']['escrow_status'] = 'CAPTURED_SETTLED'
    metrics = replay.get('/api/milestones').json()['metrics']
    assert metrics['settled_captured_amount'] is None
    assert metrics['escrow_locked_amount'] == 7300.0
    module.LEDGER.clear()
    metrics = replay.get('/api/milestones').json()['metrics']
    assert metrics['escrow_locked_by_currency'] == {}
    assert metrics['escrow_locked_amount'] == 0.0


def test_fresh_demo_never_calls_live_client_or_resets_existing_rows(replay, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError('No payment API permitted')
    monkeypatch.setattr(module.paypal_client, 'create_authorize_order', forbidden)
    monkeypatch.setattr(module.paypal_client, 'mode', LIVE_MODE)
    existing = copy.deepcopy(module.LEDGER)
    first = replay.post('/api/demo/replay').json()['milestone']
    replay.post(f"/api/escrow/{first['milestone_id']}/void")
    second = replay.post('/api/demo/replay').json()['milestone']
    for field in ('milestone_id', 'paypal_order_id', 'paypal_authorization_id'):
        assert first[field] != second[field]
    assert second['paypal_mode'] == 'REPLAY_SIMULATED'
    assert second['escrow_status'] == 'ESCROW_AUTHORIZED'
    assert second['ai_decision'] == 'PENDING_DELIVERABLE'
    assert second['paypal_capture_id'] is second['paypal_invoice_id'] is None
    assert second['paypal_authorization_id'].startswith('SIM-')
    assert all(module.LEDGER[key] == value for key, value in existing.items())


def test_concurrent_creates_reserve_distinct_ids(replay, monkeypatch):
    async def scenario():
        entered = 0
        both = asyncio.Event()
        original = module.paypal_client.create_authorize_order
        async def delayed(**kwargs):
            nonlocal entered
            entered += 1
            if entered == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 2)
            return await original(**kwargs)
        monkeypatch.setattr(module.paypal_client, 'create_authorize_order', delayed)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app), base_url='http://test') as client:
            payload = {'project_name': 'Concurrent', 'milestone_title': 'Test hold', 'amount': 1}
            responses = await asyncio.gather(*(client.post('/api/escrow/create', json=payload) for _ in range(2)))
        ids = [response.json()['milestone']['milestone_id'] for response in responses]
        assert len(set(ids)) == 2
        assert all(value in module.LEDGER for value in ids)
    asyncio.run(scenario())


def test_audit_blocks_second_audit_and_void_then_releases_guard(replay, monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed_evaluation(fn, **kwargs):
            entered.set()
            await release.wait()
            return fn(**kwargs)
        monkeypatch.setattr(module.asyncio, 'to_thread', delayed_evaluation)
        captures = []
        original = module.replay_client.capture_authorization
        async def capture(*args, **kwargs):
            captures.append(args)
            return await original(*args, **kwargs)
        monkeypatch.setattr(module.replay_client, 'capture_authorization', capture)
        request = module.VerifyDeliverableRequest(milestone_id='MS-1002', artifact_content=GOOD_DELIVERABLE)
        pending = asyncio.create_task(module.verify_and_settle_milestone(request))
        await entered.wait()
        for action in (module.verify_and_settle_milestone(request), module.void_milestone('MS-1002')):
            with pytest.raises(HTTPException) as exc:
                await action
            assert exc.value.status_code == 409
        release.set()
        await pending
        assert len(captures) == 1
        assert module.LEDGER['MS-1002']['escrow_status'] == 'CAPTURED_SETTLED'
        assert not module._busy_milestones
    asyncio.run(scenario())


@pytest.mark.parametrize('outcome, expected', [('PENDING', 'CAPTURE_PENDING'), ('timeout', 'CAPTURE_UNKNOWN'), ('server_error', 'CAPTURE_UNKNOWN'), ('missing_id', 'CAPTURE_UNKNOWN')])
def test_uncertain_capture_never_invoices_or_retries(replay, monkeypatch, outcome, expected):
    calls = []
    async def capture(*args, **kwargs):
        calls.append('capture')
        if outcome == 'timeout':
            raise httpx.ReadTimeout('mock timeout')
        if outcome == 'server_error':
            raise PayPalAPIError('capture', 503, {'name': 'SERVICE_UNAVAILABLE'})
        if outcome == 'missing_id':
            return {'status': 'COMPLETED'}
        return {'status': outcome, 'capture_id': 'SIM-PENDING'}
    async def forbidden(*args, **kwargs):
        raise AssertionError('No paid invoice for uncertain capture')
    monkeypatch.setattr(module.replay_client, 'capture_authorization', capture)
    monkeypatch.setattr(module.replay_client, 'create_milestone_invoice', forbidden)
    payload = {'milestone_id': 'MS-1002', 'artifact_content': GOOD_DELIVERABLE}
    result = replay.post('/api/escrow/verify-and-settle', json=payload)
    assert result.status_code == (502 if outcome in {'timeout', 'server_error'} else 200)
    assert module.LEDGER['MS-1002']['escrow_status'] == expected
    assert module.LEDGER['MS-1002']['paypal_invoice_id'] is None
    assert replay.post('/api/escrow/verify-and-settle', json=payload).status_code == 409
    assert replay.post('/api/escrow/MS-1002/void').status_code == 409
    assert calls == ['capture']
    assert not module._busy_milestones


def test_authorize_cancel_race_and_callback_retry(replay, monkeypatch):
    async def scenario():
        ms = module.LEDGER['MS-1002']
        ms.update(paypal_mode=LIVE_MODE, escrow_status='AWAITING_BUYER_APPROVAL', paypal_authorization_id=None)
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def authorize(order_id):
            calls.append(order_id)
            entered.set()
            await release.wait()
            return {'authorization_id': 'AUTH-TEST', 'authorization_status': 'CREATED'}
        monkeypatch.setattr(module.paypal_client, 'authorize_order', authorize)
        pending = asyncio.create_task(module.authorize_milestone('MS-1002'))
        await entered.wait()
        for action in (module.paypal_cancel('MS-1002'), module.authorize_milestone('MS-1002')):
            with pytest.raises(HTTPException) as exc:
                await action
            assert exc.value.status_code == 409
        release.set()
        await pending
        summary = ms['last_audit_summary']
        result = await module.paypal_return('MS-1002', token=ms['paypal_order_id'])
        assert result.status_code == 303
        assert result.headers['location'] == '/?authorized=MS-1002'
        assert ms['last_audit_summary'] == summary
        assert len(calls) == 1
    asyncio.run(scenario())


def test_failed_operation_releases_busy_guard(replay, monkeypatch):
    async def fail(*args, **kwargs):
        raise httpx.ReadTimeout('mock timeout')
    monkeypatch.setattr(module.replay_client, 'void_authorization', fail)
    response = replay.post('/api/escrow/MS-1002/void')
    assert response.status_code == 502
    assert 'unknown' in response.json()['detail']
    assert module.LEDGER['MS-1002']['escrow_status'] == 'VOID_UNKNOWN'
    assert replay.post('/api/escrow/MS-1002/void').status_code == 409
    assert replay.post('/api/escrow/verify-and-settle', json={
        'milestone_id': 'MS-1002', 'artifact_content': GOOD_DELIVERABLE,
    }).status_code == 409
    assert not module._busy_milestones


def test_invoice_timeout_preserves_confirmed_capture(replay, monkeypatch):
    async def fail(*args, **kwargs):
        raise httpx.ReadTimeout('mock invoice timeout')
    monkeypatch.setattr(module.replay_client, 'create_milestone_invoice', fail)
    response = replay.post('/api/escrow/verify-and-settle', json={
        'milestone_id': 'MS-1002', 'artifact_content': GOOD_DELIVERABLE,
    })
    assert response.status_code == 200
    result = response.json()
    assert result['milestone']['escrow_status'] == 'CAPTURED_SETTLED'
    assert result['milestone']['paypal_capture_id']
    assert result['paypal_invoice'] is None
    assert result['paypal_invoice_error']['paypal_error'] == 'INVOICE_OUTCOME_UNKNOWN'
    assert 'unconfirmed' in result['paypal_invoice_error']['details']
    assert replay.post('/api/escrow/verify-and-settle', json={
        'milestone_id': 'MS-1002', 'artifact_content': GOOD_DELIVERABLE,
    }).status_code == 409
    assert not module._busy_milestones


@pytest.mark.parametrize('confirmation_status', [404, 500])
def test_void_success_then_failed_confirmation_blocks_capture(replay, monkeypatch, confirmation_status):
    calls = []
    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.path == '/v1/oauth2/token':
            return httpx.Response(200, json={'access_token': 'mock', 'expires_in': 3600})
        if request.method == 'POST' and request.url.path.endswith('/void'):
            return httpx.Response(204)
        if request.method == 'GET':
            return httpx.Response(confirmation_status, json={'name': 'CONFIRMATION_FAILED'})
        raise AssertionError('Unexpected payment request')
    payment_client = PayPalV2Client(client_id='mock', client_secret='mock', mode='sandbox', transport=httpx.MockTransport(handle))
    monkeypatch.setattr(module, 'paypal_client', payment_client)
    module.LEDGER['MS-1002']['paypal_mode'] = LIVE_MODE
    response = replay.post('/api/escrow/MS-1002/void')
    assert response.status_code == 502
    assert module.LEDGER['MS-1002']['escrow_status'] == 'VOID_UNKNOWN'
    assert replay.post('/api/escrow/verify-and-settle', json={
        'milestone_id': 'MS-1002', 'artifact_content': GOOD_DELIVERABLE,
    }).status_code == 409
    assert replay.post('/api/escrow/MS-1002/void').status_code == 409
    assert [method for method, path in calls if '/authorizations/' in path] == ['POST', 'GET']
    assert not module._busy_milestones


def test_void_server_error_blocks_followup_payment(replay, monkeypatch):
    async def fail(*args, **kwargs):
        raise PayPalAPIError('POST /v2/payments/authorizations/mock/void', 503, {'name': 'SERVICE_UNAVAILABLE'})
    monkeypatch.setattr(module.replay_client, 'void_authorization', fail)
    assert replay.post('/api/escrow/MS-1002/void').status_code == 502
    assert module.LEDGER['MS-1002']['escrow_status'] == 'VOID_UNKNOWN'
    assert replay.post('/api/escrow/verify-and-settle', json={
        'milestone_id': 'MS-1002', 'artifact_content': GOOD_DELIVERABLE,
    }).status_code == 409
