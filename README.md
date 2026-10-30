# PayPilot Escrow — AI-audited milestone escrow on PayPal

Built for the **PayPal AI Hackathon** (Devpost). Buyers lock a milestone payment with a PayPal
**authorization**; an auditor agent checks the freelancer's deliverable against the contract's acceptance
criteria; PayPal **captures** the funds and issues an **invoice** only when the audit passes. Otherwise the
authorization stays on hold, or is **voided** back to the buyer.

## How the PayPal flow works (live Sandbox mode)

| Step | PayPal API | What happens |
|---|---|---|
| 1. Lock funds | `POST /v2/checkout/orders` (`intent=AUTHORIZE`) | Order created; the response's `payer-action` link is shown as **Approve on PayPal Sandbox**. Status `AWAITING_BUYER_APPROVAL`. |
| 2. Buyer approves | PayPal checkout page → redirect to `/api/paypal/return` | The buyer logs in with a Sandbox personal account and approves. |
| 3. Authorize | `POST /v2/checkout/orders/{id}/authorize` | PayPal returns the real `authorization_id`. Status `ESCROW_AUTHORIZED`. |
| 4. Audit | Gemini (OpenAI-compatible API) | `DeliverableAuditorAgent`: deterministic guardrails (AST, secret & `eval()` scan, criteria matching, test pass rate), then a Gemini review with per-criterion reasons and risk flags. |
| 5a. Pass | `POST /v2/payments/authorizations/{id}/capture` | Funds released. Status `CAPTURED_SETTLED`. |
| 5b. Receipt | `POST /v2/invoicing/invoices` → `/send` → `/payments` | Invoice created, sent (no e-mail by default) and recorded as paid with the capture ID → `MARKED_AS_PAID`. |
| 5c. Fail | — / `POST /v2/payments/authorizations/{id}/void` | `HOLD_FOR_REVISION` or `DISPUTE_FROZEN` keeps the hold; **Void Hold** releases it to the buyer. |

Any PayPal error is returned as HTTP 502 with PayPal's error name and `debug_id`; nothing is ever faked.

**Sandbox test-card shortcut.** For demos without a Sandbox buyer login, choose *Sandbox test card* when
creating a hold. The order is paid with PayPal's public sandbox test card, so PayPal authorizes it immediately
and returns a real authorization ID. Steps 4–5 are then identical.

## The AI reviewer (Gemini)

`LLMReviewer` (`backend/auditor_agent.py`) sends the acceptance criteria, the deliverable and any acceptance
evidence (test output, demo notes) to Gemini through its OpenAI-compatible endpoint
(`https://generativelanguage.googleapis.com/v1beta/openai/`). It asks for strict JSON:
`criteria[{criterion, met, reason, evidence}]`, `risk_flags[{flag, severity, detail}]`,
`recommended_decision`, `confidence` and `summary`. The deliverable is treated as untrusted data, and the
reviewer is told to ignore instructions embedded in it.

**The AI can only make the decision stricter.** The final decision is the stricter of the guardrail decision and
the AI's recommendation (`AUTO_CAPTURE_APPROVED` < `HOLD_FOR_REVISION` < `ESCALATE_DISPUTE`). The AI's
"approve" only counts if every criterion is `met` and there is no `high` risk flag. Missing criteria count as
unmet, and an LLM error or invalid output blocks auto-capture. The dashboard's **AI Reviewer Reasoning**
panel shows the model, its decision, and the reason and evidence for each criterion, plus any risk flags.

Model choice: `gemini-2.5-flash` is tried first. Google now returns 404 for it on new API keys, so the reviewer
falls back to **`gemini-3.5-flash`** (the model used in all verified runs) and records the model it actually used,
along with any fallback attempts, in every verdict. Real-run evidence is in `docs/sandbox_gemini_e2e_results.json`.
In that run the keyword guardrails approved a stubbed deliverable, and Gemini caught it and escalated to dispute.

`samples/good_capture_endpoint.py` (real implementation and tests) and `samples/stub_deliverable.py` (keyword-stuffed stub) can be
loaded from the dashboard.

### Replay (simulated) mode

Without credentials (or with `PAYPAL_MODE=replay`) the app makes **no PayPal calls**. Every ID is prefixed
`SIM-`, payloads carry `"simulated": true`, and the UI shows **Replay (simulated)**. The four seeded demo rows
are always replay data, even in live mode. The UI shows **PayPal Sandbox · live** only after PayPal has issued
an OAuth token to this process.

## Configuration (environment variables only, never commit secrets)

| Variable | Purpose |
|---|---|
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` (or `PAYPAL_SANDBOX_CLIENT_ID`, `PAYPAL_SANDBOX_CLIENT_SECRET`) | Sandbox REST app credentials. Enables live Sandbox mode. |
| `PAYPAL_MODE=replay` | Force Replay (simulated) mode. |
| `PUBLIC_BASE_URL` | Optional base URL for PayPal's return/cancel redirects. Defaults to Render's automatic `RENDER_EXTERNAL_URL`, then to the request host. |
| `PAYPAL_INVOICE_NOTIFY_RECIPIENT=true` | Let PayPal e-mail the invoice to the buyer (default: off). |
| `GEMINI_API_KEY` (or `AUDITOR_LLM_API_KEY`, which takes precedence) | Enables the AI reviewer. Without it the auditor runs guardrails only and the UI says so. |
| `AUDITOR_LLM_MODEL` | Comma-separated models to try in order. Default `gemini-2.5-flash,gemini-3.5-flash,gemini-3.5-flash-lite`. |
| `AUDITOR_LLM_BASE_URL` | OpenAI-compatible base URL. Default: Gemini's `…/v1beta/openai`. |
| `AUDITOR_LLM_TIMEOUT` | Seconds per LLM call (default 45). |

## Run & test

```bash
pip install -r requirements.txt
uvicorn backend.app:app --host 0.0.0.0 --port 8080        # open http://localhost:8080
pytest -q                                                 # live Sandbox tests run only when credentials are set
python scripts/sandbox_e2e.py http://localhost:8080       # live PayPal Sandbox + Gemini run; writes docs/sandbox_gemini_e2e_results.json
```

Test suites: `tests/test_replay.py` (simulated mode), `tests/test_live_flow_mocked.py` (live code path against
a mocked PayPal API, incl. error handling), `tests/test_auditor_llm.py` (LLM reviewer with a mocked endpoint: fallback, strict-only merging, errors),
`tests/test_live_sandbox.py` (real Sandbox calls, skipped without PayPal credentials),
`tests/test_live_gemini.py` (real Gemini calls, skipped without a key). Apart from `test_live_gemini.py`, all
tests run guardrails-only, so they stay deterministic even when a key is set.

## Stack

FastAPI · Pydantic · httpx · PayPal Orders v2 / Payments v2 / Invoicing v2 · Google Gemini (`gemini-3.5-flash`, OpenAI-compatible API) · AG Grid Community 31 · Render (`render.yaml`).

## License

[MIT](LICENSE)
