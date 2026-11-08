"""Replay (simulated) mode: no credentials, no PayPal calls. Always runs."""
from fastapi.testclient import TestClient

from backend.app import app
from backend.paypal_client import PayPalV2Client, REPLAY_MODE
from tests.conftest import BAD_DELIVERABLE, GOOD_DELIVERABLE

client = TestClient(app)


def _replay(use_client):
    return use_client(PayPalV2Client(client_id="", client_secret=""))


def test_replay_mode_selected_without_credentials_and_forced_by_env(monkeypatch):
    assert PayPalV2Client(client_id="", client_secret="").mode == REPLAY_MODE
    monkeypatch.setenv("PAYPAL_MODE", "replay")
    assert PayPalV2Client(client_id="x", client_secret="y").mode == REPLAY_MODE


def test_health_status_and_dashboard_are_labelled_replay(use_client):
    _replay(use_client)
    health = client.get("/api/health").json()
    assert health["paypal_mode"] == "REPLAY_SIMULATED"
    assert health["version"] == "1.3.0"
    assert "source_commit" in health
    st = client.get("/api/paypal/status").json()
    assert st["connected"] is False and "Replay (simulated)" in st["label"]
    html = client.get("/").text
    assert "ag-grid-community" in html and "PayPilot Escrow AI" in html
    assert "READY (v2 API)" not in html
    assert "Replay (simulated)" in html


def test_seeded_rows_are_marked_simulated(use_client):
    _replay(use_client)
    rows = client.get("/api/milestones").json()["milestones"]
    assert len(rows) >= 4
    for r in rows:
        assert r["paypal_mode"] == "REPLAY_SIMULATED"
        assert r["paypal_order_id"].startswith("SIM-")


def test_replay_create_verify_capture_invoice(use_client):
    _replay(use_client)
    res = client.post(
        "/api/escrow/create",
        json={"project_name": "Autonomous Tax Agent", "milestone_title": "Phase 1", "amount": 150.0,
              "required_criteria": ["Provide FastAPI endpoint for PayPal authorization capture and invoice creation",
                                    "Include automated unit tests for escrow state transitions"]},
    )
    assert res.status_code == 200
    body = res.json()
    tx = body["paypal_transaction"]
    assert tx["simulated"] is True and tx["mode"] == "REPLAY_SIMULATED"
    assert tx["authorization_id"].startswith("SIM-AUTH-")
    ms_id = body["milestone"]["milestone_id"]
    assert body["milestone"]["escrow_status"] == "ESCROW_AUTHORIZED"

    res = client.post("/api/escrow/verify-and-settle", json={"milestone_id": ms_id, "artifact_content": GOOD_DELIVERABLE, "test_pass_rate": 0.98})
    assert res.status_code == 200
    out = res.json()
    assert out["audit_report"]["decision"] == "AUTO_CAPTURE_APPROVED"
    assert out["audit_report"]["llm_review"]["status"] == "NOT_CONFIGURED"
    assert out["paypal_capture"]["simulated"] is True and out["paypal_capture"]["capture_id"].startswith("SIM-CAPTURE-")
    assert out["paypal_invoice"]["simulated"] is True and out["paypal_invoice"]["invoice_id"].startswith("SIM-INV-")
    assert out["milestone"]["escrow_status"] == "CAPTURED_SETTLED"

    # cannot settle twice
    again = client.post("/api/escrow/verify-and-settle", json={"milestone_id": ms_id, "artifact_content": GOOD_DELIVERABLE})
    assert again.status_code == 409


def test_replay_bad_deliverable_freezes_then_void(use_client):
    _replay(use_client)
    res = client.post("/api/escrow/verify-and-settle", json={"milestone_id": "MS-1004", "artifact_content": BAD_DELIVERABLE, "test_pass_rate": 0.4})
    out = res.json()
    assert out["audit_report"]["auto_release_eligible"] is False
    assert out["audit_report"]["decision"] == "ESCALATE_DISPUTE"
    assert out["paypal_capture"] is None
    assert out["milestone"]["escrow_status"] == "DISPUTE_FROZEN"
    v = client.post("/api/escrow/MS-1004/void")
    assert v.status_code == 200 and v.json()["milestone"]["escrow_status"] == "VOIDED"


def test_replay_records_cannot_be_authorized(use_client):
    _replay(use_client)
    assert client.post("/api/escrow/MS-1002/authorize").status_code == 409
