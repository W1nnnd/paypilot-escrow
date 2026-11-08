"""Real PayPal Sandbox calls. Skipped unless sandbox credentials are present in the environment
(PAYPAL_CLIENT_ID/PAYPAL_CLIENT_SECRET or PAYPAL_SANDBOX_CLIENT_ID/PAYPAL_SANDBOX_CLIENT_SECRET)."""
import os

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.paypal_client import PayPalV2Client
from tests.conftest import BAD_DELIVERABLE, GOOD_DELIVERABLE

HAS_CREDS = bool(
    (os.environ.get("PAYPAL_CLIENT_ID") or os.environ.get("PAYPAL_SANDBOX_CLIENT_ID"))
    and (os.environ.get("PAYPAL_CLIENT_SECRET") or os.environ.get("PAYPAL_SANDBOX_CLIENT_SECRET"))
)
pytestmark = [pytest.mark.live, pytest.mark.skipif(not HAS_CREDS, reason="PayPal Sandbox credentials not set")]

client = TestClient(app)
CRITERIA = ["Provide FastAPI endpoint for PayPal authorization capture and invoice creation",
            "Include automated unit tests for escrow state transitions"]


@pytest.fixture
def live(use_client, monkeypatch):
    monkeypatch.delenv("PAYPAL_MODE", raising=False)
    c = use_client(PayPalV2Client())
    assert c.is_live
    return c


def test_live_status_connected(live):
    st = client.get("/api/paypal/status").json()
    assert st["connected"] is True and st["label"] == "PayPal Sandbox · live"


def test_live_buyer_approval_order_is_created_and_waits(live):
    ms = client.post("/api/escrow/create", json={"project_name": "Live approval", "milestone_title": "Approve link", "amount": 11.0}).json()["milestone"]
    assert ms["escrow_status"] == "AWAITING_BUYER_APPROVAL"
    assert ms["approve_url"].startswith("https://www.sandbox.paypal.com/")
    r = client.post(f"/api/escrow/{ms['milestone_id']}/authorize")
    assert r.status_code == 502
    assert r.json()["detail"]["paypal_error"]["details"][0]["issue"] == "ORDER_NOT_APPROVED"


def test_live_test_card_authorize_capture_invoice(live, mocked_llm_approval):
    body = client.post("/api/escrow/create", json={"project_name": "Live card", "milestone_title": "Capture path", "amount": 25.0,
                                                   "funding": "sandbox_test_card", "required_criteria": CRITERIA}).json()
    ms = body["milestone"]
    assert ms["paypal_mode"] == "LIVE_SANDBOX" and ms["escrow_status"] == "ESCROW_AUTHORIZED"
    assert ms["paypal_authorization_id"] and not ms["paypal_authorization_id"].startswith("SIM-")
    out = client.post("/api/escrow/verify-and-settle", json={"milestone_id": ms["milestone_id"], "artifact_content": GOOD_DELIVERABLE,
                                                              "test_pass_rate": 0.98}).json()
    assert out["paypal_capture"]["status"] == "COMPLETED" and out["paypal_capture"]["simulated"] is False
    assert out["paypal_invoice"]["invoice_id"].startswith("INV2-")
    assert out["paypal_invoice"]["status"] in {"MARKED_AS_PAID", "PAID", "SENT", "UNPAID"}
    assert out["paypal_invoice_error"] is None


def test_live_dispute_then_void(live):
    ms = client.post("/api/escrow/create", json={"project_name": "Live void", "milestone_title": "Dispute path", "amount": 9.0,
                                                 "funding": "sandbox_test_card", "required_criteria": CRITERIA}).json()["milestone"]
    out = client.post("/api/escrow/verify-and-settle", json={"milestone_id": ms["milestone_id"], "artifact_content": BAD_DELIVERABLE,
                                                              "test_pass_rate": 0.3}).json()
    assert out["milestone"]["escrow_status"] == "DISPUTE_FROZEN" and out["paypal_capture"] is None
    v = client.post(f"/api/escrow/{ms['milestone_id']}/void").json()
    assert v["paypal_void"]["status"] == "VOIDED" and v["paypal_void"]["simulated"] is False
