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


@pytest.mark.parametrize('decision', ['HOLD_FOR_REVISION', 'ESCALATE_DISPUTE'])
def test_confident_rejection_metadata_matches_response_ledger_and_download(client, monkeypatch, decision):
    from backend.auditor_agent import _normalise_verdict
    def review(criteria, *_args):
        verdict = _normalise_verdict({
            'criteria': [{'criterion': c, 'met': False, 'reason': 'stub', 'evidence': 'return True'} for c in criteria],
            'risk_flags': [], 'recommended_decision': decision, 'confidence': 100, 'summary': 'Reject stub.'}, criteria)
        return dict(verdict, status='OK', model='offline-test')
    monkeypatch.setattr(module.auditor_agent.llm_reviewer, 'review', review)
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Rejected review must not call PayPal')
    monkeypatch.setattr(module.replay_client, 'capture_authorization', forbidden)
    monkeypatch.setattr(module.replay_client, 'create_milestone_invoice', forbidden)
    body = client.post('/api/escrow/verify-and-settle', json={
        'milestone_id':'MS-1002', 'artifact_content':GOOD_DELIVERABLE, 'test_pass_rate':0.98}).json()
    assert body['paypal_capture'] is None and body['paypal_invoice'] is None
    audit = body['audit_report']
    assert audit['confidence_score'] == 99.6
    assert audit['score_details']['approval_gate_score'] is None
    assert audit['score_details']['model_confidence_for'] == decision
    assert audit['decision'] == decision and audit['auto_release_eligible'] is False
    ledger = client.get('/api/milestones').json()
    milestone = next(m for m in ledger['milestones'] if m['milestone_id'] == 'MS-1002')
    assert milestone['last_audit_report']['audit'] == audit
    assert milestone['ai_reviewer']['confidence'] == 100
    assert milestone['ai_reviewer']['confidence_basis'] == 'MODEL_RECOMMENDED_DECISION'
    assert milestone['ai_reviewer']['model_recommended_decision'] == decision
    assert 'not delivery quality' in ledger['score_interpretation']
    report = client.get('/api/escrow/MS-1002/audit-report?download=true').json()
    assert report['schema_version'] == '1.1'
    assert report['evaluation']['app_version'] == '1.3.1'
    assert report['evaluation']['audit'] == audit
    assert any('not delivery quality' in text for text in report['limitations'])
