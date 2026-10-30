"""
PayPal REST client for PayPilot Escrow.

Two clearly separated modes:

* ``LIVE_SANDBOX`` – real HTTPS calls to ``https://api-m.sandbox.paypal.com``:
    - ``POST /v1/oauth2/token``                                  (client-credentials token)
    - ``POST /v2/checkout/orders`` with ``intent=AUTHORIZE``      (returns the buyer ``payer-action`` approve link)
    - ``POST /v2/checkout/orders/{id}/authorize``                 (after buyer approval -> real authorization id)
    - ``POST /v2/payments/authorizations/{id}/capture``           (AI audit passed -> release funds)
    - ``POST /v2/payments/authorizations/{id}/void``              (dispute / cancellation -> release hold back to buyer)
    - ``POST /v2/invoicing/invoices`` + ``/send`` + ``/payments`` (receipt invoice, recorded as paid by the capture)
  Every result returned in this mode comes from a PayPal response. If PayPal returns an error,
  :class:`PayPalAPIError` is raised; nothing is ever made up and labelled "live".

* ``REPLAY_SIMULATED`` – zero-config judge/demo mode. **No PayPal calls are made.** Payloads mimic the
  PayPal v2 response shape, but all IDs are prefixed with ``SIM-`` and every payload carries
  ``"simulated": True`` so nobody can mistake them for real PayPal objects.

Credentials are read only from the environment (``PAYPAL_CLIENT_ID`` / ``PAYPAL_CLIENT_SECRET``, or
``PAYPAL_SANDBOX_CLIENT_ID`` / ``PAYPAL_SANDBOX_CLIENT_SECRET``). They are never logged or returned.
Set ``PAYPAL_MODE=replay`` to force Replay mode even when credentials are present.
"""
from __future__ import annotations

import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
LIVE_MODE = "LIVE_SANDBOX"
REPLAY_MODE = "REPLAY_SIMULATED"

# Public PayPal sandbox test card (developer.paypal.com "Card testing"). Only ever used against the sandbox.
SANDBOX_TEST_CARD = {"number": "4032039317984658", "expiry": "2030-12", "security_code": "123", "name": "PayPilot Sandbox Tester"}


class PayPalAPIError(RuntimeError):
    """A PayPal REST call failed. Carries PayPal's error name/debug_id, never credentials."""

    def __init__(self, operation: str, status_code: int, body: Any) -> None:
        self.operation = operation
        self.status_code = status_code
        body = body if isinstance(body, dict) else {"raw": str(body)[:500]}
        self.name = body.get("name") or body.get("error") or "PAYPAL_ERROR"
        self.debug_id = body.get("debug_id")
        self.details = body.get("details") or body.get("error_description") or body.get("message")
        super().__init__(f"{operation} failed: HTTP {status_code} {self.name} (debug_id={self.debug_id}) {self.details}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "http_status": self.status_code,
            "paypal_error": self.name,
            "debug_id": self.debug_id,
            "details": self.details,
        }


def _env_first(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sim_id(prefix: str) -> str:
    return f"SIM-{prefix}-{secrets.token_hex(6).upper()}"


def _link(data: dict[str, Any], rel: str) -> str | None:
    for l in data.get("links", []) or []:
        if l.get("rel") == rel:
            return l.get("href")
    return None


class PayPalV2Client:
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        base_url: str | None = None,
        mode: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client_id = client_id if client_id is not None else _env_first("PAYPAL_CLIENT_ID", "PAYPAL_SANDBOX_CLIENT_ID")
        self._client_secret = (
            client_secret if client_secret is not None else _env_first("PAYPAL_CLIENT_SECRET", "PAYPAL_SANDBOX_CLIENT_SECRET")
        )
        self.base_url = (base_url or os.environ.get("PAYPAL_BASE_URL") or SANDBOX_BASE_URL).rstrip("/")
        if "sandbox" not in self.base_url:
            # This hackathon build only targets the PayPal Sandbox.
            raise ValueError("PayPilot Escrow only supports the PayPal Sandbox base URL")
        forced = (mode or os.environ.get("PAYPAL_MODE", "")).strip().lower()
        has_creds = bool(self._client_id and self._client_secret)
        self.mode = REPLAY_MODE if forced == "replay" or not has_creds else LIVE_MODE
        self._transport = transport
        self._access_token: str | None = None
        self._token_expiry = 0.0
        self.last_live_success_at: str | None = None
        self.last_error: dict[str, Any] | None = None

    def __repr__(self) -> str:  # never leak credentials through repr/logging
        return f"PayPalV2Client(mode={self.mode!r}, base_url={self.base_url!r})"

    @property
    def is_live(self) -> bool:
        return self.mode == LIVE_MODE

    # Backwards-compatible alias
    @property
    def is_live_sandbox_configured(self) -> bool:
        return self.is_live

    # ------------------------------------------------------------------ HTTP helpers
    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=30.0, transport=self._transport)

    async def get_access_token(self) -> str:
        if not self.is_live:
            raise RuntimeError("Replay mode has no PayPal access token")
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token
        async with self._http() as client:
            resp = await client.post(
                f"{self.base_url}/v1/oauth2/token",
                auth=(self._client_id, self._client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
            )
        if resp.status_code != 200:
            err = PayPalAPIError("POST /v1/oauth2/token", resp.status_code, _safe_json(resp))
            self.last_error = err.to_dict()
            raise err
        payload = resp.json()
        self._access_token = payload["access_token"]
        self._token_expiry = time.time() + int(payload.get("expires_in", 3600)) - 60
        self.last_live_success_at = _now_iso()
        return self._access_token

    async def _request(self, method: str, path: str, operation: str, json_body: Any = None, idempotency_key: str | None = None) -> dict[str, Any]:
        token = await self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        if idempotency_key:
            headers["PayPal-Request-Id"] = idempotency_key
        async with self._http() as client:
            resp = await client.request(method, f"{self.base_url}{path}", json=json_body, headers=headers)
        if resp.status_code >= 300:
            err = PayPalAPIError(operation, resp.status_code, _safe_json(resp))
            self.last_error = err.to_dict()
            raise err
        self.last_live_success_at = _now_iso()
        self.last_error = None
        return _safe_json(resp) if resp.content else {}

    async def check_connection(self) -> dict[str, Any]:
        """Verifies credentials by fetching a token. Returns status only, never the token."""
        if not self.is_live:
            return {"mode": REPLAY_MODE, "connected": False, "label": "Replay (simulated) — no PayPal calls"}
        try:
            await self.get_access_token()
            return {"mode": LIVE_MODE, "connected": True, "label": "PayPal Sandbox · live", "verified_at": self.last_live_success_at}
        except PayPalAPIError as exc:
            return {"mode": LIVE_MODE, "connected": False, "label": "PayPal Sandbox · credential error", "error": exc.to_dict()}
        except httpx.HTTPError as exc:
            return {"mode": LIVE_MODE, "connected": False, "label": "PayPal Sandbox · network error", "error": {"details": type(exc).__name__}}

    # ------------------------------------------------------------------ Orders v2
    async def create_authorize_order(
        self,
        contract_id: str,
        milestone_id: str,
        title: str,
        amount: float,
        currency: str = "USD",
        return_url: str = "http://localhost:8080/api/paypal/return",
        cancel_url: str = "http://localhost:8080/api/paypal/cancel",
        funding: str = "paypal_buyer_approval",
    ) -> dict[str, Any]:
        """Creates an ``intent=AUTHORIZE`` order.

        ``funding="paypal_buyer_approval"`` (default): returns ``status=PAYER_ACTION_REQUIRED`` and an
        ``approve_url``; the buyer must log in to PayPal and approve, then :meth:`authorize_order` is called.

        ``funding="sandbox_test_card"``: sandbox-only shortcut that pays with PayPal's public sandbox
        test card, so PayPal authorizes immediately and returns a real authorization id.
        """
        amt = f"{amount:.2f}"
        if not self.is_live:
            order_id = _sim_id("ORDER")
            auth_id = _sim_id("AUTH")
            return {
                "mode": REPLAY_MODE,
                "simulated": True,
                "order_id": order_id,
                "order_status": "COMPLETED",
                "authorization_id": auth_id,
                "authorization_status": "CREATED",
                "approve_url": None,
                "amount": {"currency_code": currency, "value": amt},
                "created_at": _now_iso(),
                "note": "Replay mode: no PayPal API call was made; IDs are simulated.",
            }

        purchase_unit = {
            "reference_id": f"{contract_id}:{milestone_id}"[:256],
            "custom_id": milestone_id,
            "description": f"PayPilot escrow milestone: {title}"[:127],
            "amount": {"currency_code": currency, "value": amt},
        }
        body: dict[str, Any] = {"intent": "AUTHORIZE", "purchase_units": [purchase_unit]}
        if funding == "sandbox_test_card":
            body["payment_source"] = {"card": dict(SANDBOX_TEST_CARD)}
        else:
            body["payment_source"] = {
                "paypal": {
                    "experience_context": {
                        "brand_name": "PayPilot Escrow",
                        "user_action": "CONTINUE",
                        "shipping_preference": "NO_SHIPPING",
                        "return_url": return_url,
                        "cancel_url": cancel_url,
                    }
                }
            }
        data = await self._request("POST", "/v2/checkout/orders", "POST /v2/checkout/orders (intent=AUTHORIZE)", body, str(uuid.uuid4()))
        result = {
            "mode": LIVE_MODE,
            "simulated": False,
            "funding": funding,
            "order_id": data["id"],
            "order_status": data.get("status"),
            "approve_url": _link(data, "payer-action") or _link(data, "approve"),
            "authorization_id": None,
            "authorization_status": None,
            "amount": {"currency_code": currency, "value": amt},
            "payee": (data.get("purchase_units") or [{}])[0].get("payee"),
            "created_at": _now_iso(),
        }
        auth = _first_authorization(data)
        if auth:
            result["authorization_id"] = auth.get("id")
            result["authorization_status"] = auth.get("status")
            result["authorization_expires"] = auth.get("expiration_time")
        return result

    async def get_order(self, order_id: str) -> dict[str, Any]:
        if not self.is_live:
            raise RuntimeError("get_order is only available in live sandbox mode")
        data = await self._request("GET", f"/v2/checkout/orders/{order_id}", f"GET /v2/checkout/orders/{order_id}")
        return {"mode": LIVE_MODE, "order_id": data.get("id"), "order_status": data.get("status"), "payer": data.get("payer"), "raw": data}

    async def authorize_order(self, order_id: str) -> dict[str, Any]:
        """Call after the buyer approved the order. Returns PayPal's real authorization id."""
        if not self.is_live:
            raise RuntimeError("authorize_order is only available in live sandbox mode")
        data = await self._request(
            "POST", f"/v2/checkout/orders/{order_id}/authorize", f"POST /v2/checkout/orders/{order_id}/authorize", {}, str(uuid.uuid4())
        )
        auth = _first_authorization(data)
        if not auth:
            raise PayPalAPIError(f"POST /v2/checkout/orders/{order_id}/authorize", 200, {"name": "NO_AUTHORIZATION_IN_RESPONSE"})
        return {
            "mode": LIVE_MODE,
            "simulated": False,
            "order_id": data.get("id"),
            "order_status": data.get("status"),
            "authorization_id": auth.get("id"),
            "authorization_status": auth.get("status"),
            "authorization_expires": auth.get("expiration_time"),
            "payer_email": (data.get("payer") or {}).get("email_address"),
        }

    # ------------------------------------------------------------------ Payments v2
    async def capture_authorization(
        self, authorization_id: str, amount: float, currency: str = "USD", note_to_payer: str = "AI milestone verification passed"
    ) -> dict[str, Any]:
        amt = f"{amount:.2f}"
        if not self.is_live:
            return {
                "mode": REPLAY_MODE,
                "simulated": True,
                "capture_id": _sim_id("CAPTURE"),
                "authorization_id": authorization_id,
                "status": "COMPLETED",
                "amount": {"currency_code": currency, "value": amt},
                "captured_at": _now_iso(),
                "note": "Replay mode: no PayPal API call was made.",
            }
        data = await self._request(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/capture",
            f"POST /v2/payments/authorizations/{authorization_id}/capture",
            {"amount": {"currency_code": currency, "value": amt}, "final_capture": True, "note_to_payer": note_to_payer[:255]},
            str(uuid.uuid4()),
        )
        return {
            "mode": LIVE_MODE,
            "simulated": False,
            "capture_id": data.get("id"),
            "authorization_id": authorization_id,
            "status": data.get("status"),
            "amount": data.get("amount") or {"currency_code": currency, "value": amt},
            "final_capture": data.get("final_capture"),
            "captured_at": data.get("create_time") or _now_iso(),
        }

    async def void_authorization(self, authorization_id: str) -> dict[str, Any]:
        if not self.is_live:
            return {"mode": REPLAY_MODE, "simulated": True, "authorization_id": authorization_id, "status": "VOIDED"}
        await self._request(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/void",
            f"POST /v2/payments/authorizations/{authorization_id}/void",
            None,
            str(uuid.uuid4()),
        )
        data = await self._request("GET", f"/v2/payments/authorizations/{authorization_id}", f"GET /v2/payments/authorizations/{authorization_id}")
        return {"mode": LIVE_MODE, "simulated": False, "authorization_id": authorization_id, "status": data.get("status")}

    async def get_authorization(self, authorization_id: str) -> dict[str, Any]:
        data = await self._request("GET", f"/v2/payments/authorizations/{authorization_id}", f"GET /v2/payments/authorizations/{authorization_id}")
        return {"mode": LIVE_MODE, "authorization_id": data.get("id"), "status": data.get("status"), "expiration_time": data.get("expiration_time")}

    # ------------------------------------------------------------------ Invoicing v2
    async def create_milestone_invoice(
        self,
        contract_id: str,
        milestone_id: str,
        milestone_title: str,
        amount: float,
        currency: str = "USD",
        recipient_email: str = "buyer@example.com",
        audit_summary: str = "",
        capture_id: str | None = None,
        notify_recipient: bool | None = None,
    ) -> dict[str, Any]:
        """Creates a receipt invoice, sends it, and records the escrow capture as the payment.

        By default ``send_to_recipient`` is false (no e-mail; PayPal still moves the invoice out of DRAFT and
        returns a payer view link). Set ``PAYPAL_INVOICE_NOTIFY_RECIPIENT=true`` to have PayPal e-mail the buyer.
        """
        amt = f"{amount:.2f}"
        if not self.is_live:
            return {
                "mode": REPLAY_MODE,
                "simulated": True,
                "invoice_id": _sim_id("INV"),
                "status": "MARKED_AS_PAID",
                "amount": {"currency_code": currency, "value": amt},
                "recipient_email": recipient_email,
                "steps": ["create (simulated)", "send (simulated)", "record payment (simulated)"],
                "note": "Replay mode: no PayPal API call was made.",
            }
        if notify_recipient is None:
            notify_recipient = os.environ.get("PAYPAL_INVOICE_NOTIFY_RECIPIENT", "").lower() == "true"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        steps: list[dict[str, Any]] = []
        body = {
            "detail": {
                "invoice_number": f"PP-{milestone_id}-{secrets.token_hex(3).upper()}",
                "currency_code": currency,
                "invoice_date": today,
                "reference": contract_id[:120],
                "note": f"PayPilot AI audit: {audit_summary}"[:4000],
                "memo": f"Escrow capture {capture_id}" if capture_id else "PayPilot escrow milestone",
                "payment_term": {"term_type": "DUE_ON_RECEIPT"},
            },
            "primary_recipients": [{"billing_info": {"email_address": recipient_email}}],
            "items": [
                {
                    "name": f"Milestone {milestone_id}"[:200],
                    "description": milestone_title[:1000],
                    "quantity": "1",
                    "unit_amount": {"currency_code": currency, "value": amt},
                    "unit_of_measure": "AMOUNT",
                }
            ],
        }
        created = await self._request("POST", "/v2/invoicing/invoices", "POST /v2/invoicing/invoices", body, str(uuid.uuid4()))
        invoice_id = created.get("id") or (_link(created, "self") or "").rstrip("/").split("/")[-1]
        steps.append({"step": "create", "status": created.get("status", "DRAFT")})
        result: dict[str, Any] = {
            "mode": LIVE_MODE,
            "simulated": False,
            "invoice_id": invoice_id,
            "invoice_number": body["detail"]["invoice_number"],
            "amount": {"currency_code": currency, "value": amt},
            "recipient_email": recipient_email,
            "steps": steps,
        }
        try:
            sent = await self._request(
                "POST",
                f"/v2/invoicing/invoices/{invoice_id}/send",
                f"POST /v2/invoicing/invoices/{invoice_id}/send",
                {"send_to_invoicer": False, "send_to_recipient": bool(notify_recipient)},
                str(uuid.uuid4()),
            )
            steps.append({"step": "send", "send_to_recipient": bool(notify_recipient), "payer_view_url": sent.get("href")})
            result["payer_view_url"] = sent.get("href")
            if capture_id:
                await self._request(
                    "POST",
                    f"/v2/invoicing/invoices/{invoice_id}/payments",
                    f"POST /v2/invoicing/invoices/{invoice_id}/payments",
                    {
                        "method": "PAYPAL",
                        "payment_date": today,
                        "amount": {"currency_code": currency, "value": amt},
                        "note": f"Settled by PayPal escrow capture {capture_id}",
                    },
                )
                steps.append({"step": "record_payment", "capture_id": capture_id})
        except PayPalAPIError as exc:
            # The invoice exists in PayPal; report exactly which follow-up step failed.
            result["follow_up_error"] = exc.to_dict()
        final = await self._request("GET", f"/v2/invoicing/invoices/{invoice_id}", f"GET /v2/invoicing/invoices/{invoice_id}")
        result["status"] = final.get("status")
        return result


def _first_authorization(order: dict[str, Any]) -> dict[str, Any] | None:
    for pu in order.get("purchase_units", []) or []:
        auths = ((pu.get("payments") or {}).get("authorizations")) or []
        if auths:
            return auths[0]
    return None


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text[:500]}
