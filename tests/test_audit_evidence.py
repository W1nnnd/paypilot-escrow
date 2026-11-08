"""Offline policy and evidence regressions; no PayPal or model traffic."""
import copy
import hashlib

import pytest
from fastapi.testclient import TestClient

import backend.app as module
from backend.paypal_client import PayPalV2Client
from tests.conftest import GOOD_DELIVERABLE


@pytest.fixture
def client(use_client):
    use_client(PayPalV2Client(mode="replay"))
    return TestClient(module.app)


def install_confidence(monkeypatch, confidence):
    def review(criteria, *_args):
        return {"status": "OK", "model": "offline-test", "overall_pass": True,
                "recommended_decision": "AUTO_CAPTURE_APPROVED", "confidence": confidence,
                "criteria": [{"criterion": c, "met": True, "reason": "mock", "evidence": "mock"} for c in criteria],
                "risk_flags": [], "summary": "Offline test double."}
    monkeypatch.setattr(module.auditor_agent.llm_reviewer, "review", review)


@pytest.mark.parametrize("requested, confidence, effective, expected", [
    (50, 75, 80, "HOLD_FOR_REVISION"),
    (80, 80, 80, "AUTO_CAPTURE_APPROVED"),
    (95, 90, 95, "HOLD_FOR_REVISION"),
])
def test_request_cannot_lower_server_minimum(client, monkeypatch, requested, confidence, effective, expected):
    install_confidence(monkeypatch, confidence)
    result = client.post('/api/escrow/verify-and-settle', json={
        'milestone_id':'MS-1002', 'artifact_content':GOOD_DELIVERABLE,
        'auto_capture_threshold':requested,
    })
    assert result.status_code == 200
    body=result.json()
    assert body['audit_report']['decision'] == expected
    if expected != 'AUTO_CAPTURE_APPROVED':
        assert body['paypal_capture'] is None and body['paypal_invoice'] is None
    snapshot=body['milestone']['last_audit_report']
    assert snapshot['effective_threshold'] == effective
    assert snapshot['requested_threshold'] == requested
    assert snapshot['server_minimum_threshold'] == 80


def test_report_binds_inputs_to_decision_and_separates_current_payment(client, monkeypatch):
    install_confidence(monkeypatch, 70)
    evidence='test output supplied by caller'
    client.post('/api/escrow/verify-and-settle', json={
        'milestone_id':'MS-1002', 'artifact_content':GOOD_DELIVERABLE, 'acceptance_evidence':evidence,
    })
    snapshot=copy.deepcopy(module.LEDGER['MS-1002']['last_audit_report'])
    client.post('/api/escrow/MS-1002/void')
    res=client.get('/api/escrow/MS-1002/audit-report?download=true')
    assert res.status_code == 200
    assert 'attachment;' in res.headers['content-disposition']
    report=res.json()
    assert report['evaluation'] == snapshot
    assert report['evaluation']['artifact_sha256'] == hashlib.sha256(GOOD_DELIVERABLE.encode()).hexdigest()
    assert report['evaluation']['acceptance_evidence_sha256'] == hashlib.sha256(evidence.encode()).hexdigest()
    assert report['evaluation']['code_executed'] is False
    assert report['evaluation']['audit']['decision'] == 'HOLD_FOR_REVISION'
    assert report['current_payment']['escrow_status'] == 'VOIDED'
    assert 'artifact_content' not in report['evaluation']
    assert 'buyer_email' not in report['current_payment']


def test_report_is_available_after_capture_failure(client, monkeypatch):
    import httpx
    async def unknown(*args, **kwargs):
        raise httpx.ReadTimeout('offline test')
    monkeypatch.setattr(module.replay_client, 'capture_authorization', unknown)
    result=client.post('/api/escrow/verify-and-settle',json={'milestone_id':'MS-1002','artifact_content':GOOD_DELIVERABLE})
    assert result.status_code == 502
    report=client.get('/api/escrow/MS-1002/audit-report').json()
    assert report['evaluation']['audit']['auto_release_eligible'] is True
    assert report['current_payment']['escrow_status'] == 'CAPTURE_UNKNOWN'
    assert report['current_payment']['paypal_capture_id'] is None


def test_absent_report_returns_404(client):
    assert client.get('/api/escrow/MS-1002/audit-report').status_code == 404
    assert client.get('/api/escrow/missing/audit-report').status_code == 404


def test_oversized_artifact_rejected_instead_of_silently_partial_review(client, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('must not review oversized input')
    monkeypatch.setattr(module.auditor_agent, 'evaluate_deliverable', forbidden)
    result=client.post('/api/escrow/verify-and-settle',json={'milestone_id':'MS-1002','artifact_content':'x'*30001})
    assert result.status_code == 422
