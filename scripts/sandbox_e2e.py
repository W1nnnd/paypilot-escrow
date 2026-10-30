"""End-to-end run against a running PayPilot server (default http://127.0.0.1:8080) in live sandbox mode.

Writes PayPal object IDs/statuses and the AI reviewer's verdicts (no credentials, no tokens) to
docs/sandbox_gemini_e2e_results.json.
Usage:  python scripts/sandbox_e2e.py [base_url]
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
CRITERIA = ["Provide FastAPI endpoint for PayPal authorization capture and invoice creation",
            "Include automated unit tests for escrow state transitions"]
ROOT = Path(__file__).resolve().parent.parent
GOOD = (ROOT / "samples" / "good_capture_endpoint.py").read_text()
STUB = (ROOT / "samples" / "stub_deliverable.py").read_text()
OUT_FILE = ROOT / "docs" / "sandbox_gemini_e2e_results.json"


def ai(out):
    """Keep the AI reviewer's verdict (model, reasons, risk flags) for the evidence file."""
    r = out["audit_report"]["llm_review"]
    return {k: r.get(k) for k in ("status", "model", "recommended_decision", "confidence", "summary", "criteria", "risk_flags",
                                  "latency_s", "fallback_attempts", "error", "attempts") if k in r}
BAD = 'API_SECRET = "sk-1234567890abcdefghijklmnop"\ndef broken(:\n    pass\n'

c = httpx.Client(base_url=BASE, timeout=90)
res: dict = {"run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "server": BASE}
st = c.get("/api/paypal/status").json()
res["paypal_status"] = {k: st.get(k) for k in ("mode", "connected", "label")}
res["llm_reviewer_config"] = st.get("llm_review")
if not st.get("connected"):
    print(json.dumps(res, indent=2)); sys.exit("PayPal sandbox not connected")

# A) Buyer-approval path: real order + approve link; authorize must be refused until the buyer approves.
a = c.post("/api/escrow/create", json={"project_name": "E2E buyer approval", "milestone_title": "Approve via PayPal", "amount": 15.0,
                                         "required_criteria": CRITERIA}).json()["milestone"]
early = c.post(f"/api/escrow/{a['milestone_id']}/authorize")
res["A_buyer_approval_path"] = {
    "milestone_id": a["milestone_id"], "paypal_order_id": a["paypal_order_id"], "escrow_status": a["escrow_status"],
    "approve_url": a["approve_url"],
    "authorize_before_approval": {"http": early.status_code,
                                  "paypal_issue": (early.json().get("detail", {}).get("paypal_error", {}).get("details") or [{}])[0].get("issue")},
}

# B) Sandbox test-card path: real authorization -> AI audit pass -> real capture -> real invoice.
b = c.post("/api/escrow/create", json={"project_name": "E2E capture", "milestone_title": "Audit pass releases funds", "amount": 25.0,
                                         "funding": "sandbox_test_card", "required_criteria": CRITERIA}).json()["milestone"]
out = c.post("/api/escrow/verify-and-settle", json={"milestone_id": b["milestone_id"], "artifact_content": GOOD, "test_pass_rate": 1.0,
                                                    "acceptance_evidence": "pytest samples/good_capture_endpoint.py: 3 passed"}).json()
res["B_capture_path"] = {
    "milestone_id": b["milestone_id"], "paypal_order_id": b["paypal_order_id"], "authorization_id": b["paypal_authorization_id"],
    "ai_decision": out["audit_report"]["decision"], "ai_confidence": out["audit_report"]["confidence_score"],
    "guardrail_decision": out["audit_report"]["guardrail_decision"], "ai_reviewer": ai(out),
    "capture_id": (out["paypal_capture"] or {}).get("capture_id"), "capture_status": (out["paypal_capture"] or {}).get("status"),
    "invoice_id": (out["paypal_invoice"] or {}).get("invoice_id"), "invoice_status": (out["paypal_invoice"] or {}).get("status"),
    "invoice_steps": [s["step"] for s in (out["paypal_invoice"] or {}).get("steps", [])],
    "invoice_error": out.get("paypal_invoice_error"), "final_escrow_status": out["milestone"]["escrow_status"],
}

# B2) Stubbed deliverable that fools the keyword guardrails: the AI reviewer must keep the hold.
e = c.post("/api/escrow/create", json={"project_name": "E2E stub", "milestone_title": "Stubbed deliverable", "amount": 12.0,
                                         "funding": "sandbox_test_card", "required_criteria": CRITERIA}).json()["milestone"]
out = c.post("/api/escrow/verify-and-settle", json={"milestone_id": e["milestone_id"], "artifact_content": STUB, "test_pass_rate": 0.98}).json()
auth_after = e["paypal_authorization_id"]
v2 = c.post(f"/api/escrow/{e['milestone_id']}/void").json()
res["B2_ai_blocks_stub_path"] = {
    "milestone_id": e["milestone_id"], "paypal_order_id": e["paypal_order_id"], "authorization_id": auth_after,
    "guardrail_decision": out["audit_report"]["guardrail_decision"], "final_decision": out["audit_report"]["decision"],
    "paypal_capture": out["paypal_capture"], "status_after_audit": out["milestone"]["escrow_status"], "ai_reviewer": ai(out),
    "void_status_after_test": (v2.get("paypal_void") or {}).get("status"),
}

# C) Dispute path: real authorization -> audit fails -> funds stay frozen -> void.
d = c.post("/api/escrow/create", json={"project_name": "E2E dispute", "milestone_title": "Audit fail keeps hold", "amount": 9.0,
                                         "funding": "sandbox_test_card", "required_criteria": CRITERIA}).json()["milestone"]
out = c.post("/api/escrow/verify-and-settle", json={"milestone_id": d["milestone_id"], "artifact_content": BAD, "test_pass_rate": 0.3}).json()
v = c.post(f"/api/escrow/{d['milestone_id']}/void").json()
res["C_dispute_void_path"] = {
    "milestone_id": d["milestone_id"], "paypal_order_id": d["paypal_order_id"], "authorization_id": d["paypal_authorization_id"],
    "guardrail_decision": out["audit_report"]["guardrail_decision"], "ai_decision": out["audit_report"]["decision"],
    "status_after_audit": out["milestone"]["escrow_status"], "ai_reviewer": ai(out), "void_status": v["paypal_void"]["status"],
}

OUT_FILE.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
print(json.dumps(res, indent=2))
