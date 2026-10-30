"""Sample milestone deliverable: FastAPI endpoint that captures a PayPal authorization and creates an invoice,
plus unit tests for the escrow state transitions. Used by the demo UI and the end-to-end script."""
from enum import Enum

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter()
PAYPAL_BASE = "https://api-m.sandbox.paypal.com"


class EscrowState(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"


ALLOWED = {EscrowState.AUTHORIZED: {EscrowState.CAPTURED, EscrowState.VOIDED}}


def transition(current: EscrowState, target: EscrowState) -> EscrowState:
    if target not in ALLOWED.get(current, set()):
        raise ValueError(f"illegal escrow transition {current} -> {target}")
    return target


@router.post("/escrow/{authorization_id}/capture")
async def capture_and_invoice(authorization_id: str, amount: str, currency: str, buyer_email: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        cap = await client.post(
            f"{PAYPAL_BASE}/v2/payments/authorizations/{authorization_id}/capture",
            json={"amount": {"currency_code": currency, "value": amount}, "final_capture": True},
            headers=headers,
        )
        if cap.status_code >= 300:
            raise HTTPException(status_code=502, detail={"step": "capture", "paypal": cap.json()})
        inv = await client.post(
            f"{PAYPAL_BASE}/v2/invoicing/invoices",
            json={
                "detail": {"currency_code": currency, "note": f"Capture {cap.json()['id']}"},
                "primary_recipients": [{"billing_info": {"email_address": buyer_email}}],
                "items": [{"name": "Milestone", "quantity": "1", "unit_amount": {"currency_code": currency, "value": amount}}],
            },
            headers=headers,
        )
        if inv.status_code >= 300:
            raise HTTPException(status_code=502, detail={"step": "invoice", "paypal": inv.json()})
    return {"capture_id": cap.json()["id"], "invoice_id": inv.json().get("id"), "state": EscrowState.CAPTURED}


# ---- unit tests for escrow state transitions ----
def test_authorized_can_be_captured():
    assert transition(EscrowState.AUTHORIZED, EscrowState.CAPTURED) is EscrowState.CAPTURED


def test_authorized_can_be_voided():
    assert transition(EscrowState.AUTHORIZED, EscrowState.VOIDED) is EscrowState.VOIDED


def test_captured_cannot_be_voided():
    try:
        transition(EscrowState.CAPTURED, EscrowState.VOIDED)
    except ValueError:
        return
    raise AssertionError("captured escrow must not be voidable")
