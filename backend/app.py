"""
FastAPI backend for PayPilot Escrow — AI-audited milestone escrow on PayPal authorize/capture.

Each ledger record carries ``paypal_mode``:
* ``LIVE_SANDBOX``      – created through real PayPal Sandbox calls; every PayPal ID on the record came from PayPal.
* ``REPLAY_SIMULATED``  – seeded or replay-mode demo data; IDs are ``SIM-…`` and no PayPal call was made.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import os
import itertools
import uuid
from contextlib import contextmanager
from decimal import Decimal
from datetime import datetime, timezone

import httpx
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from .auditor_agent import DeliverableAuditorAgent
from .paypal_client import LIVE_MODE, REPLAY_MODE, PayPalAPIError, PayPalV2Client

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
SAMPLES = {"good": "good_capture_endpoint.py", "stub": "stub_deliverable.py"}

app = FastAPI(
    title="PayPilot Escrow — AI-audited milestone escrow on PayPal",
    version="1.3.1",
    description=(
        "Locks milestone funds with a PayPal Orders v2 AUTHORIZE order the buyer approves, audits the deliverable, "
        "then captures (or keeps on hold / voids) the authorization and issues a PayPal invoice."
    ),
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

paypal_client = PayPalV2Client()                 # live sandbox if credentials are in the environment
replay_client = PayPalV2Client(mode="replay")    # always simulated; used for seeded demo rows
auditor_agent = DeliverableAuditorAgent()

LOCKED_STATES = {"ESCROW_AUTHORIZED", "HOLD_FOR_REVISION", "DISPUTE_FROZEN"}
SETTLEABLE_STATES = {"ESCROW_AUTHORIZED", "HOLD_FOR_REVISION"}
# Server-owned minimum policy, not an assertion about a negotiated contract.
MIN_AUTO_CAPTURE_THRESHOLD = 80.0

# Seeded demo rows (always REPLAY_SIMULATED, clearly labelled in the UI)
SEED_LEDGER: dict[str, dict[str, Any]] = {
    "MS-1001": {
        "milestone_id": "MS-1001",
        "contract_id": "CTR-2026-089",
        "project_name": "Stripe-to-PayPal v2 Checkout Migration",
        "milestone_title": "Phase 1: OAuth2 + Orders v2 Authorize Webhook Engine",
        "buyer_email": "treasury@acme-saas.io",
        "freelancer_email": "elena.dev@studio-x.dev",
        "amount": 2400.00,
        "currency": "USD",
        "start_date": "2026-10-18",
        "due_date": "2026-10-28",
        "progress_pct": 100,
        "paypal_mode": "REPLAY_SIMULATED",
        "approve_url": None,
        "escrow_status": "CAPTURED_SETTLED",
        "paypal_order_id": "SIM-ORDER-88412A90C11B2",
        "paypal_authorization_id": "SIM-AUTH-A19C4402E81F0",
        "paypal_capture_id": "SIM-CAPTURE-C9910B23E77A1",
        "paypal_invoice_id": "SIM-INV-77310D91B22C8",
        "ai_confidence": 96.5,
        "risk_score": 3.5,
        "ai_decision": "AUTO_CAPTURE_APPROVED",
        "required_criteria": [
            "Implement OAuth2 token caching and PayPal Orders v2 AUTHORIZE intent",
            "Verify webhook signature headers and idempotency keys",
        ],
        "last_audit_summary": "Seed example: approved and settled (simulated Replay data). No audit was run for this record in the current session.",
    },
    "MS-1002": {
        "milestone_id": "MS-1002",
        "contract_id": "CTR-2026-089",
        "project_name": "Stripe-to-PayPal v2 Checkout Migration",
        "milestone_title": "Phase 2: Multi-Currency Payouts & AG Grid Reconciliation Portal",
        "buyer_email": "treasury@acme-saas.io",
        "freelancer_email": "elena.dev@studio-x.dev",
        "amount": 3200.00,
        "currency": "USD",
        "start_date": "2026-10-25",
        "due_date": "2026-11-05",
        "progress_pct": 75,
        "paypal_mode": "REPLAY_SIMULATED",
        "approve_url": None,
        "escrow_status": "ESCROW_AUTHORIZED",
        "paypal_order_id": "SIM-ORDER-33910F48B21D9",
        "paypal_authorization_id": "SIM-AUTH-F0218D73A94E1",
        "paypal_capture_id": None,
        "paypal_invoice_id": None,
        "ai_confidence": 0.0,
        "risk_score": 15.0,
        "ai_decision": "PENDING_DELIVERABLE",
        "required_criteria": [
            "Provide FastAPI endpoint for PayPal authorization capture and invoice creation",
            "Include automated unit tests for escrow state transitions",
        ],
        "last_audit_summary": "Simulated authorization SIM-AUTH-F0218D73A94E1 (replay data, no PayPal call). Awaiting deliverable submission for AI audit.",
    },
    "MS-1003": {
        "milestone_id": "MS-1003",
        "contract_id": "CTR-2026-104",
        "project_name": "AI Customer Support Triage Microservice",
        "milestone_title": "Milestone 1: LLM Classification Pipeline & Latency SLA Benchmark",
        "buyer_email": "ops@globalretail.co",
        "freelancer_email": "marco.ai@neuralforge.io",
        "amount": 1850.00,
        "currency": "EUR",
        "start_date": "2026-10-22",
        "due_date": "2026-11-02",
        "progress_pct": 60,
        "paypal_mode": "REPLAY_SIMULATED",
        "approve_url": None,
        "escrow_status": "HOLD_FOR_REVISION",
        "paypal_order_id": "SIM-ORDER-66120C84D19E4",
        "paypal_authorization_id": "SIM-AUTH-D8812C09B11A3",
        "paypal_capture_id": None,
        "paypal_invoice_id": None,
        "ai_confidence": 64.2,
        "risk_score": 35.8,
        "ai_decision": "HOLD_FOR_REVISION",
        "required_criteria": [
            "Implement ticket classifier with structured JSON schema output",
            "Include fallback retry handler and unit tests",
        ],
        "last_audit_summary": "Seed example: held for revision while retry tests are missing (simulated Replay data). No audit was run for this record in the current session.",
    },
    "MS-1004": {
        "milestone_id": "MS-1004",
        "contract_id": "CTR-2026-112",
        "project_name": "Cross-Border B2B Supplier API Gateway",
        "milestone_title": "Milestone 1: PayPal Invoicing v2 Automated Tax & Customs Sync",
        "buyer_email": "procurement@nordicparts.se",
        "freelancer_email": "kenji@tokyocloud.jp",
        "amount": 4100.00,
        "currency": "USD",
        "start_date": "2026-10-26",
        "due_date": "2026-11-10",
        "progress_pct": 40,
        "paypal_mode": "REPLAY_SIMULATED",
        "approve_url": None,
        "escrow_status": "ESCROW_AUTHORIZED",
        "paypal_order_id": "SIM-ORDER-99201E77C43A8",
        "paypal_authorization_id": "SIM-AUTH-E7741A20C85B6",
        "paypal_capture_id": None,
        "paypal_invoice_id": None,
        "ai_confidence": 0.0,
        "risk_score": 10.0,
        "ai_decision": "PENDING_DELIVERABLE",
        "required_criteria": [
            "Generate PayPal v2 invoice payload with line-item tax breakdown",
            "Validate webhook reconciliation and currency formatting",
        ],
        "last_audit_summary": "Simulated authorization ($4,100.00 USD, replay data). Ready for autonomous verification.",
    },
}

LEDGER: dict[str, dict[str, Any]] = {}
# Single-process demo storage only. Multiple workers require a shared transactional store.
_milestone_ids = itertools.count(1005)
_busy_milestones: set[str] = set()


def _next_milestone_id() -> str:
    # Reserve before the first await, including failed creations; never reuse an ID.
    while True:
        candidate = f"MS-{next(_milestone_ids)}"
        if candidate not in LEDGER:
            return candidate


@contextmanager
def _milestone_operation(milestone_id: str):
    # No await between check and reservation on this process's event loop.
    if milestone_id in _busy_milestones:
        raise HTTPException(status_code=409, detail="Milestone operation already in progress; refresh before trying again.")
    _busy_milestones.add(milestone_id)
    try:
        yield
    finally:
        _busy_milestones.discard(milestone_id)



def reset_ledger() -> None:
    LEDGER.clear()
    LEDGER.update(copy.deepcopy(SEED_LEDGER))


reset_ledger()


def client_for(record: dict[str, Any]) -> PayPalV2Client:
    return paypal_client if record.get("paypal_mode") == LIVE_MODE else replay_client


def _paypal_error(exc: PayPalAPIError) -> HTTPException:
    return HTTPException(status_code=502, detail={"paypal_error": exc.to_dict()})


def _public_base_url(request: Request) -> str:
    # PUBLIC_BASE_URL wins; on Render, RENDER_EXTERNAL_URL (https://<service>.onrender.com) is set automatically.
    return (os.environ.get("PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or str(request.base_url)).rstrip("/")


class CreateEscrowRequest(BaseModel):
    contract_id: str = Field(default="CTR-2026-205")
    project_name: str = Field(..., min_length=3)
    milestone_title: str = Field(..., min_length=3)
    buyer_email: str = Field(default="buyer@example.com")
    freelancer_email: str = Field(default="builder@example.com")
    amount: float = Field(..., gt=0, le=10000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    start_date: str = Field(default="2026-10-26")
    due_date: str = Field(default="2026-11-08")
    funding: str = Field(default="paypal_buyer_approval", pattern="^(paypal_buyer_approval|sandbox_test_card)$")
    required_criteria: list[str] = Field(
        default_factory=lambda: [
            "Implement FastAPI PayPal escrow handler and error recovery",
            "Provide unit test assertions verifying output schema",
        ]
    )


class VerifyDeliverableRequest(BaseModel):
    milestone_id: str
    artifact_type: str = Field(default="python_code")
    artifact_content: str = Field(..., min_length=10, max_length=30000)
    test_pass_rate: float = Field(default=0.96, ge=0.0, le=1.0)
    auto_capture_threshold: float = Field(default=80.0, ge=50.0, le=100.0)
    acceptance_evidence: str = Field(default="", max_length=8000, description="Test output, demo URL notes, etc. given to the AI reviewer")


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.is_file():
        return HTMLResponse("<h1>PayPilot Escrow Backend Running</h1>")
    return FileResponse(index_file)


@app.get("/api/samples/{name}")
async def get_sample(name: str) -> dict[str, str]:
    if name not in SAMPLES:
        raise HTTPException(status_code=404, detail="Unknown sample")
    return {"name": name, "content": (SAMPLES_DIR / SAMPLES[name]).read_text()}


@app.get("/api/health")
async def health_check() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "paypilot-escrow-ai",
        "version": app.version,
        "source_commit": os.environ.get("RENDER_GIT_COMMIT"),
        "paypal_mode": paypal_client.mode,
        "llm_review_configured": auditor_agent.llm_reviewer.configured,
        "llm_review": auditor_agent.llm_reviewer.describe(),
        "milestones_count": len(LEDGER),
    }


@app.get("/api/paypal/status")
async def paypal_status() -> dict[str, Any]:
    """Live label is only returned after PayPal actually issued a token in this process."""
    status = await paypal_client.check_connection()
    status["llm_review_configured"] = auditor_agent.llm_reviewer.configured
    status["llm_review"] = auditor_agent.llm_reviewer.describe()
    return status


@app.get("/api/milestones")
async def list_milestones() -> dict[str, Any]:
    items = list(LEDGER.values())
    def totals(states):
        grouped: dict[str, Decimal] = {}
        for milestone in items:
            if milestone["escrow_status"] in states:
                currency = milestone["currency"]
                grouped[currency] = grouped.get(currency, Decimal("0")) + Decimal(str(milestone["amount"]))
        return {currency: float(amount.quantize(Decimal("0.01"))) for currency, amount in sorted(grouped.items())}

    locked = totals(LOCKED_STATES)
    settled = totals({"CAPTURED_SETTLED"})
    return {
        "milestones": items,
        "score_interpretation": "Legacy ai_confidence and risk_score are diagnostics, not delivery quality or actual risk. Use ai_decision and last_audit_report.audit.score_details. Seed examples have no current audit evidence.",
        "metrics": {
            "total_milestones": len(items),
            "escrow_locked_amount": next(iter(locked.values()), 0.0) if len(locked) <= 1 else None,
            "settled_captured_amount": next(iter(settled.values()), 0.0) if len(settled) <= 1 else None,
            "escrow_locked_by_currency": locked,
            "settled_captured_by_currency": settled,
            "awaiting_buyer_approval": sum(1 for m in items if m["escrow_status"] == "AWAITING_BUYER_APPROVAL"),
            "auto_settled_count": sum(1 for m in items if m["escrow_status"] == "CAPTURED_SETTLED"),
            "live_sandbox_records": sum(1 for m in items if m.get("paypal_mode") == LIVE_MODE),
        },
    }


@app.get("/api/escrow/{milestone_id}/audit-report")
async def get_audit_report(milestone_id: str, download: bool = False):
    ms = LEDGER.get(milestone_id)
    if not ms:
        raise HTTPException(status_code=404, detail="Milestone not found")
    if not ms.get("last_audit_report"):
        raise HTTPException(status_code=404, detail="No audit has been run for this milestone in this process")
    report = {
        "schema_version": "1.1",
        "milestone_id": milestone_id,
        "project_name": ms["project_name"],
        "paypal_mode": ms["paypal_mode"],
        "evaluation": copy.deepcopy(ms["last_audit_report"]),
        "current_payment": {key: ms.get(key) for key in (
            "escrow_status", "amount", "currency", "paypal_order_id", "paypal_authorization_id",
            "paypal_capture_id", "paypal_invoice_id", "last_audit_summary")},
        "limitations": [
            "Sandbox or Replay prototype, not a production escrow guarantee.",
            "In-memory demo record; not signed, tamper-proof or durable across restarts.",
            "Code is inspected, not executed. The test pass rate is supplied by the submitter.",
            "Raw source is not separately included; review reasons and evidence may quote input text.",
            "The evaluation is a snapshot; current_payment reflects the latest ledger state.",
            "Scores are policy diagnostics, not delivery quality or calibrated probabilities. Read audit.score_details; the final decision takes precedence.",
        ],
    }
    headers = {"Content-Disposition": f'attachment; filename="PayPilot-{milestone_id}-audit.json"'} if download else None
    return JSONResponse(content=report, headers=headers)


@app.post("/api/demo/replay")
async def create_replay_demo() -> dict[str, Any]:
    record = copy.deepcopy(SEED_LEDGER["MS-1002"])
    record.update({
        "milestone_id": _next_milestone_id(),
        "paypal_order_id": f"SIM-ORDER-{uuid.uuid4().hex.upper()}",
        "paypal_authorization_id": f"SIM-AUTH-{uuid.uuid4().hex.upper()}",
        "ai_confidence": 0.0,
        "risk_score": 0.0,
        "ai_decision": "PENDING_DELIVERABLE",
        "progress_pct": 25,
        "last_audit_summary": "Fresh Replay demo: simulated authorization ready for audit; no PayPal call was made.",
    })
    LEDGER[record["milestone_id"]] = record
    return {"status": "ok", "milestone": record}


@app.post("/api/escrow/create")
async def create_escrow_milestone(req: CreateEscrowRequest, request: Request) -> dict[str, Any]:
    milestone_id = _next_milestone_id()
    base = _public_base_url(request)
    try:
        pp = await paypal_client.create_authorize_order(
            contract_id=req.contract_id,
            milestone_id=milestone_id,
            title=req.milestone_title,
            amount=req.amount,
            currency=req.currency.upper(),
            return_url=f"{base}/api/paypal/return?milestone_id={milestone_id}",
            cancel_url=f"{base}/api/paypal/cancel?milestone_id={milestone_id}",
            funding=req.funding,
        )
    except PayPalAPIError as exc:
        raise _paypal_error(exc)

    authorized = bool(pp.get("authorization_id"))
    if pp["mode"] == LIVE_MODE and not authorized:
        status = "AWAITING_BUYER_APPROVAL"
        summary = f"PayPal Sandbox order {pp['order_id']} created (intent=AUTHORIZE). Waiting for the buyer to approve it on PayPal."
    elif pp["mode"] == LIVE_MODE:
        status = "ESCROW_AUTHORIZED"
        summary = f"PayPal Sandbox authorization {pp['authorization_id']} created (sandbox test card). Funds on hold."
    else:
        status = "ESCROW_AUTHORIZED"
        summary = f"Replay (simulated): authorization {pp['authorization_id']} — no PayPal call was made."

    record = {
        "milestone_id": milestone_id,
        "contract_id": req.contract_id,
        "project_name": req.project_name,
        "milestone_title": req.milestone_title,
        "buyer_email": req.buyer_email,
        "freelancer_email": req.freelancer_email,
        "amount": round(req.amount, 2),
        "currency": req.currency.upper(),
        "start_date": req.start_date,
        "due_date": req.due_date,
        "progress_pct": 25 if authorized else 10,
        "paypal_mode": pp["mode"],
        "approve_url": pp.get("approve_url"),
        "escrow_status": status,
        "paypal_order_id": pp["order_id"],
        "paypal_authorization_id": pp.get("authorization_id"),
        "paypal_capture_id": None,
        "paypal_invoice_id": None,
        "ai_confidence": 0.0,
        "risk_score": 10.0,
        "ai_decision": "PENDING_DELIVERABLE",
        "required_criteria": req.required_criteria,
        "last_audit_summary": summary,
    }
    LEDGER[milestone_id] = record
    return {"status": "ok", "milestone": record, "paypal_transaction": pp}


async def _authorize_record(ms: dict[str, Any]) -> dict[str, Any]:
    with _milestone_operation(ms["milestone_id"]):
        if ms.get("paypal_mode") != LIVE_MODE:
            raise HTTPException(status_code=409, detail="Replay (simulated) records are already authorized; nothing to call.")
        if ms["escrow_status"] != "AWAITING_BUYER_APPROVAL":
            raise HTTPException(status_code=409, detail=f"Milestone is {ms['escrow_status']}, not AWAITING_BUYER_APPROVAL.")
        try:
            auth = await paypal_client.authorize_order(ms["paypal_order_id"])
        except PayPalAPIError as exc:
            raise _paypal_error(exc)
        ms["paypal_authorization_id"] = auth["authorization_id"]
        ms["escrow_status"] = "ESCROW_AUTHORIZED"
        ms["progress_pct"] = 25
        ms["approve_url"] = None
        ms["last_audit_summary"] = (
            f"Buyer approved; PayPal Sandbox authorization {auth['authorization_id']} ({auth['authorization_status']}) holds the funds."
        )
        return auth


@app.get("/api/paypal/return")
async def paypal_return(milestone_id: str, token: str | None = None):
    """PayPal redirects the buyer here after approval (``token`` = order id)."""
    ms = LEDGER.get(milestone_id)
    if not ms or (token and token != ms.get("paypal_order_id")):
        raise HTTPException(status_code=404, detail="Unknown milestone/order")
    if ms.get("paypal_authorization_id") and ms.get("paypal_mode") == LIVE_MODE:
        return RedirectResponse(url=f"/?authorized={milestone_id}", status_code=303)
    try:
        await _authorize_record(ms)
        return RedirectResponse(url=f"/?authorized={milestone_id}", status_code=303)
    except HTTPException as exc:
        if exc.status_code != 409:
            ms["last_audit_summary"] = f"Authorization after buyer approval failed: {exc.detail}"
        return RedirectResponse(url=f"/?authorize_failed={milestone_id}", status_code=303)


@app.get("/api/paypal/cancel")
async def paypal_cancel(milestone_id: str):
    with _milestone_operation(milestone_id):
        ms = LEDGER.get(milestone_id)
        if ms and ms["escrow_status"] == "AWAITING_BUYER_APPROVAL":
            ms["escrow_status"] = "BUYER_CANCELLED"
            ms["last_audit_summary"] = "Buyer cancelled on the PayPal approval page. No funds were authorized."
        return RedirectResponse(url=f"/?cancelled={milestone_id}", status_code=303)


@app.post("/api/escrow/{milestone_id}/authorize")
async def authorize_milestone(milestone_id: str) -> dict[str, Any]:
    ms = LEDGER.get(milestone_id)
    if not ms:
        raise HTTPException(status_code=404, detail=f"Milestone {milestone_id} not found")
    auth = await _authorize_record(ms)
    return {"status": "ok", "milestone": ms, "paypal_authorization": auth}


@app.post("/api/escrow/{milestone_id}/void")
async def void_milestone(milestone_id: str) -> dict[str, Any]:
    with _milestone_operation(milestone_id):
        ms = LEDGER.get(milestone_id)
        if not ms:
            raise HTTPException(status_code=404, detail=f"Milestone {milestone_id} not found")
        if ms["escrow_status"] not in LOCKED_STATES:
            raise HTTPException(status_code=409, detail=f"Milestone is {ms['escrow_status']}; only held authorizations can be voided.")
        try:
            res = await client_for(ms).void_authorization(ms["paypal_authorization_id"])
        except httpx.HTTPError as exc:
            ms["escrow_status"] = "VOID_UNKNOWN"
            ms["last_audit_summary"] = "PayPal void outcome is unknown after a network failure. Reconcile with PayPal before any further payment action."
            raise HTTPException(status_code=502, detail="Void outcome unknown; do not retry payment. Reconciliation required.") from exc
        except PayPalAPIError as exc:
            # A successful void POST may be followed by a failed status GET.
            # Neither a server error nor that failed confirmation proves the hold remains.
            if exc.status_code >= 500 or exc.operation.startswith("GET "):
                ms["escrow_status"] = "VOID_UNKNOWN"
                ms["last_audit_summary"] = f"PayPal void outcome is unconfirmed ({exc.name}). Reconcile with PayPal before any further payment action."
            raise _paypal_error(exc)
        ms["escrow_status"] = "VOIDED"
        ms["last_audit_summary"] = f"Authorization {ms['paypal_authorization_id']} voided ({res['status']}); hold released back to the buyer."
        return {"status": "ok", "milestone": ms, "paypal_void": res}


@app.post("/api/escrow/verify-and-settle")
async def verify_and_settle_milestone(req: VerifyDeliverableRequest) -> dict[str, Any]:
    with _milestone_operation(req.milestone_id):
        ms = LEDGER.get(req.milestone_id)
        if not ms:
            raise HTTPException(status_code=404, detail=f"Milestone {req.milestone_id} not found")
        if ms["escrow_status"] == "AWAITING_BUYER_APPROVAL":
            raise HTTPException(status_code=409, detail="Buyer has not approved the PayPal order yet; nothing is on hold to capture.")
        if ms["escrow_status"] not in SETTLEABLE_STATES:
            raise HTTPException(status_code=409, detail=f"Milestone is {ms['escrow_status']}; it cannot be settled.")

        audit = await asyncio.to_thread(
            auditor_agent.evaluate_deliverable,
            milestone_id=req.milestone_id,
            required_criteria=ms["required_criteria"],
            artifact_type=req.artifact_type,
            artifact_content=req.artifact_content,
            test_pass_rate=req.test_pass_rate,
            threshold=max(MIN_AUTO_CAPTURE_THRESHOLD, req.auto_capture_threshold),
            evidence=req.acceptance_evidence,
            # This policy comes from the server-owned record, never from the request body.
            require_llm=ms.get("paypal_mode") != REPLAY_MODE,
        )
        # Preserve what was evaluated separately from the later payment outcome.
        # This is a demo record, not a signed or durable audit trail.
        ms["last_audit_report"] = {
            "audit_id": f"AUD-{uuid.uuid4().hex}",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "app_version": app.version,
            "source_commit": os.environ.get("RENDER_GIT_COMMIT"),
            "artifact_type": req.artifact_type,
            "artifact_sha256": hashlib.sha256(req.artifact_content.encode("utf-8")).hexdigest(),
            "acceptance_evidence_sha256": hashlib.sha256(req.acceptance_evidence.encode("utf-8")).hexdigest(),
            "reported_test_pass_rate": req.test_pass_rate,
            "code_executed": False,
            "requested_threshold": req.auto_capture_threshold,
            "server_minimum_threshold": MIN_AUTO_CAPTURE_THRESHOLD,
            "effective_threshold": max(MIN_AUTO_CAPTURE_THRESHOLD, req.auto_capture_threshold),
            "required_criteria": list(ms["required_criteria"]),
            "audit": asdict(audit),
        }
        ms["ai_confidence"] = audit.confidence_score
        ms["risk_score"] = audit.risk_score
        ms["ai_decision"] = audit.decision
        ms["last_audit_summary"] = audit.summary
        llm = audit.llm_review
        ms["ai_reviewer"] = {
            "status": llm.get("status"),
            "model": llm.get("model"),
            "recommended_decision": llm.get("recommended_decision"),
            "model_recommended_decision": llm.get("model_recommended_decision"),
            "confidence": llm.get("confidence"),
            "confidence_basis": llm.get("confidence_basis"),
            "summary": llm.get("summary"),
            "criteria": llm.get("criteria", []),
            "risk_flags": llm.get("risk_flags", []),
            "guardrail_decision": audit.guardrail_decision,
        }

        pp = client_for(ms)
        capture: dict[str, Any] | None = None
        invoice: dict[str, Any] | None = None
        invoice_error: dict[str, Any] | None = None

        if audit.auto_release_eligible:
            try:
                capture = await pp.capture_authorization(
                    ms["paypal_authorization_id"], ms["amount"], ms["currency"], note_to_payer="PayPilot AI audit passed; milestone released."
                )
            except httpx.HTTPError as exc:
                ms["escrow_status"] = "CAPTURE_UNKNOWN"
                ms["last_audit_summary"] = "PayPal capture outcome is unknown after a network failure. Reconcile with PayPal before any further payment action."
                raise HTTPException(status_code=502, detail="Capture outcome unknown; do not retry payment. Reconciliation required.") from exc
            except PayPalAPIError as exc:
                if exc.status_code >= 500:
                    ms["escrow_status"] = "CAPTURE_UNKNOWN"
                    ms["last_audit_summary"] = f"PayPal capture outcome is unknown after server error ({exc.name}). Reconciliation required before any further payment action."
                else:
                    ms["escrow_status"] = "HOLD_FOR_REVISION"
                    ms["last_audit_summary"] = f"AI audit passed but PayPal capture failed ({exc.name}); authorization still on hold."
                raise _paypal_error(exc)
            if capture.get("status") != "COMPLETED" or not capture.get("capture_id"):
                ms["paypal_capture_id"] = capture.get("capture_id")
                ms["escrow_status"] = "CAPTURE_PENDING" if capture.get("status") == "PENDING" else "CAPTURE_UNKNOWN"
                ms["last_audit_summary"] = f"Capture returned {capture.get('status') or 'unknown status'}{' without a capture ID' if not capture.get('capture_id') else ''}; payment reconciliation required. No paid invoice issued."
                return {"status": "pending", "paypal_mode": ms["paypal_mode"], "milestone": ms,
                        "audit_report": asdict(audit), "paypal_capture": capture,
                        "paypal_invoice": None, "paypal_invoice_error": None}
            ms["escrow_status"] = "CAPTURED_SETTLED"
            ms["progress_pct"] = 100
            ms["paypal_capture_id"] = capture["capture_id"]
            try:
                invoice = await pp.create_milestone_invoice(
                    contract_id=ms["contract_id"],
                    milestone_id=ms["milestone_id"],
                    milestone_title=ms["milestone_title"],
                    amount=ms["amount"],
                    currency=ms["currency"],
                    recipient_email=ms["buyer_email"],
                    audit_summary=audit.summary,
                    capture_id=capture["capture_id"],
                )
                ms["paypal_invoice_id"] = invoice["invoice_id"]
            except httpx.HTTPError:
                invoice_error = {
                    "operation": "create_milestone_invoice",
                    "paypal_error": "INVOICE_OUTCOME_UNKNOWN",
                    "details": "Capture completed, but the invoice workflow outcome is unconfirmed after a network failure. Reconcile before retrying invoice creation.",
                }
                ms["last_audit_summary"] += " Capture succeeded; invoice workflow outcome is unknown after a network failure. Reconciliation required."
            except PayPalAPIError as exc:
                invoice_error = exc.to_dict()
                ms["last_audit_summary"] += f" Capture succeeded; invoice creation failed ({exc.name})."
        elif audit.decision == "HOLD_FOR_REVISION":
            ms["escrow_status"] = "HOLD_FOR_REVISION"
            ms["progress_pct"] = 65
        else:
            # Dispute: keep the authorization frozen; the buyer/mediator can void it via /api/escrow/{id}/void.
            ms["escrow_status"] = "DISPUTE_FROZEN"
            ms["progress_pct"] = 50

        return {
            "status": "ok",
            "paypal_mode": ms["paypal_mode"],
            "milestone": ms,
            "audit_report": asdict(audit),
            "paypal_capture": capture,
            "paypal_invoice": invoice,
            "paypal_invoice_error": invoice_error,
        }
