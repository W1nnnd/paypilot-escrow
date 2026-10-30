"""Live code path against a mocked PayPal API (no network). Checks the buyer-approval state machine and
that PayPal errors are surfaced instead of being turned into fake success."""
import json

import httpx
from fastapi.testclient import TestClient

from backend.app import app
from backend.paypal_client import PayPalV2Client
from tests.conftest import GOOD_DELIVERABLE

client = TestClient(app)


class FakePayPal:
    def __init__(self):
        self.approved = False
        self.calls = []
        self.fail_capture = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "fake", "expires_in": 3600})
        if path == "/v2/checkout/orders" and request.method == "POST":
            body = json.loads(request.content)
            assert body["intent"] == "AUTHORIZE"
            assert "return_url" in body["payment_source"]["paypal"]["experience_context"]
            return httpx.Response(200, json={"id": "ORDER123", "status": "PAYER_ACTION_REQUIRED", "purchase_units": [{}],
                                             "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER123"}]})
        if path == "/v2/checkout/orders/ORDER123/authorize":
            if not self.approved:
                return httpx.Response(422, json={"name": "UNPROCESSABLE_ENTITY", "debug_id": "dbg1", "details": [{"issue": "ORDER_NOT_APPROVED"}]})
            return httpx.Response(201, json={"id": "ORDER123", "status": "COMPLETED", "purchase_units": [
                {"payments": {"authorizations": [{"id": "AUTH999", "status": "CREATED", "expiration_time": "2026-11-29T00:00:00Z"}]}}]})
        if path == "/v2/payments/authorizations/AUTH999/capture":
            if self.fail_capture:
                return httpx.Response(422, json={"name": "UNPROCESSABLE_ENTITY", "debug_id": "dbg2", "details": [{"issue": "AUTHORIZATION_EXPIRED"}]})
            return httpx.Response(201, json={"id": "CAP777", "status": "COMPLETED", "final_capture": True})
        if path == "/v2/invoicing/invoices" and request.method == "POST":
            return httpx.Response(201, json={"id": "INV2-TEST", "status": "DRAFT"})
        if path == "/v2/invoicing/invoices/INV2-TEST/send":
            return httpx.Response(200, json={"href": "https://www.sandbox.paypal.com/invoice/p/#INV2-TEST"})
        if path == "/v2/invoicing/invoices/INV2-TEST/payments":
            return httpx.Response(200, json={"payment_id": "EXTR-1"})
        if path == "/v2/invoicing/invoices/INV2-TEST":
            return httpx.Response(200, json={"id": "INV2-TEST", "status": "MARKED_AS_PAID"})
        return httpx.Response(404, json={"name": "NOT_FOUND", "path": path})


def _live(use_client, fake):
    return use_client(PayPalV2Client(client_id="id", client_secret="secret", transport=httpx.MockTransport(fake)))


def _create():
    return client.post("/api/escrow/create", json={
        "project_name": "Mock Project", "milestone_title": "Mock milestone", "amount": 42.0,
        "required_criteria": ["Provide FastAPI endpoint for PayPal authorization capture and invoice creation",
                              "Include automated unit tests for escrow state transitions"]})


def test_live_buyer_approval_state_machine(use_client):
    fake = FakePayPal()
    _live(use_client, fake)
    assert client.get("/api/paypal/status").json()["label"] == "PayPal Sandbox · live"

    body = _create().json()
    ms = body["milestone"]
    assert ms["paypal_mode"] == "LIVE_SANDBOX"
    assert ms["escrow_status"] == "AWAITING_BUYER_APPROVAL"
    assert ms["paypal_authorization_id"] is None
    assert ms["approve_url"].endswith("token=ORDER123")
    ms_id = ms["milestone_id"]

    # Cannot capture before the buyer approves
    assert client.post("/api/escrow/verify-and-settle", json={"milestone_id": ms_id, "artifact_content": GOOD_DELIVERABLE}).status_code == 409
    # Authorize before approval -> PayPal error is surfaced (502), not faked
    r = client.post(f"/api/escrow/{ms_id}/authorize")
    assert r.status_code == 502 and r.json()["detail"]["paypal_error"]["details"][0]["issue"] == "ORDER_NOT_APPROVED"

    # Buyer approves on PayPal, PayPal redirects back to the return URL
    fake.approved = True
    r = client.get(f"/api/paypal/return?milestone_id={ms_id}&token=ORDER123", follow_redirects=False)
    assert r.status_code == 303 and "authorized=" in r.headers["location"]
    rows = {m["milestone_id"]: m for m in client.get("/api/milestones").json()["milestones"]}
    assert rows[ms_id]["paypal_authorization_id"] == "AUTH999"
    assert rows[ms_id]["escrow_status"] == "ESCROW_AUTHORIZED"

    out = client.post("/api/escrow/verify-and-settle", json={"milestone_id": ms_id, "artifact_content": GOOD_DELIVERABLE, "test_pass_rate": 0.98}).json()
    assert out["paypal_capture"]["capture_id"] == "CAP777" and out["paypal_capture"]["simulated"] is False
    assert out["paypal_invoice"]["invoice_id"] == "INV2-TEST" and out["paypal_invoice"]["status"] == "MARKED_AS_PAID"
    assert out["milestone"]["escrow_status"] == "CAPTURED_SETTLED"
    assert "POST /v2/invoicing/invoices/INV2-TEST/payments" in fake.calls


def test_live_capture_failure_is_not_reported_as_success(use_client):
    fake = FakePayPal()
    fake.approved = True
    fake.fail_capture = True
    _live(use_client, fake)
    ms_id = _create().json()["milestone"]["milestone_id"]
    assert client.post(f"/api/escrow/{ms_id}/authorize").status_code == 200
    r = client.post("/api/escrow/verify-and-settle", json={"milestone_id": ms_id, "artifact_content": GOOD_DELIVERABLE, "test_pass_rate": 0.98})
    assert r.status_code == 502
    rows = {m["milestone_id"]: m for m in client.get("/api/milestones").json()["milestones"]}
    assert rows[ms_id]["escrow_status"] == "HOLD_FOR_REVISION"
    assert rows[ms_id]["paypal_capture_id"] is None


def test_bad_credentials_show_error_not_live(use_client):
    def deny(request):
        return httpx.Response(401, json={"error": "invalid_client", "error_description": "Client Authentication failed"})
    _live(use_client, deny)
    st = client.get("/api/paypal/status").json()
    assert st["connected"] is False and "error" in st["label"]
    r = _create()
    assert r.status_code == 502


def test_client_repr_never_contains_secret():
    c = PayPalV2Client(client_id="ID-SHOULD-NOT-LEAK", client_secret="SECRET-SHOULD-NOT-LEAK")
    assert "LEAK" not in repr(c)
