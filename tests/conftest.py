import pytest

import backend.app as app_module
from backend.paypal_client import PayPalV2Client


GOOD_DELIVERABLE = '''
from fastapi import APIRouter

router = APIRouter()

async def capture_paypal_authorization_and_create_invoice(auth_id: str) -> dict:
    """Provide FastAPI endpoint for PayPal authorization capture and invoice creation."""
    return {"authorization_id": auth_id, "captured": True, "invoice_created": True}

def test_escrow_state_transitions():
    """Include automated unit tests for escrow state transitions."""
    assert True
'''

BAD_DELIVERABLE = '''
API_SECRET = "sk-1234567890abcdefghijklmnop"
def broken_func(:
    pass
'''


@pytest.fixture
def use_client(monkeypatch):
    """Swap the app's PayPal client and reset the ledger for each test."""

    def _use(client: PayPalV2Client):
        monkeypatch.setattr(app_module, "paypal_client", client)
        app_module.reset_ledger()
        return client

    yield _use
    app_module.reset_ledger()


@pytest.fixture(autouse=True)
def unconfigured_llm_by_default(request, monkeypatch):
    """Unless a test is marked ``live_llm``, disable the real LLM. Tests may explicitly install
    a mock verdict; the default never spends API quota (even when GEMINI_API_KEY is set)."""
    if request.node.get_closest_marker("live_llm"):
        yield
        return
    from backend.auditor_agent import LLMReviewer

    reviewer = LLMReviewer()
    reviewer.api_key = ""
    monkeypatch.setattr(app_module.auditor_agent, "llm_reviewer", reviewer)
    yield


@pytest.fixture
def mocked_llm_approval(monkeypatch):
    """Explicit successful LLM test double; never calls a model or spends API quota."""
    def review(required_criteria, artifact_type, artifact_content, evidence=""):
        return {
            "status": "OK", "model": "mock-reviewer", "overall_pass": True,
            "recommended_decision": "AUTO_CAPTURE_APPROVED", "confidence": 98.0,
            "criteria": [{"criterion": c, "met": True, "reason": "Test double", "evidence": "Test double"}
                         for c in required_criteria],
            "risk_flags": [], "summary": "Mock approval for payment-path isolation.",
        }
    monkeypatch.setattr(app_module.auditor_agent.llm_reviewer, "review", review)
