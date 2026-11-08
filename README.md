# PayPilot Escrow — AI-audited milestone escrow on PayPal

Built for the **PayPal AI Hackathon** (Devpost).

**Live demo:** https://paypilot-escrow-ai.onrender.com · **Demo video (2:50):** https://youtu.be/kL-quH7Iu8U (PayPal Sandbox + Gemini, Render free tier; the first request after idle can take ~30–60 s). Evidence from a hosted run: [`docs/render_live_e2e_results.json`](docs/render_live_e2e_results.json). Buyers lock a milestone payment with a PayPal
**authorization**; an auditor agent checks the freelancer's deliverable against the contract's acceptance
criteria; PayPal **captures** the funds and issues an **invoice** only when the audit passes. Otherwise the
authorization stays on hold, or is **voided** back to the buyer.

## Quick judge walkthrough

1. Open the hosted demo and click **Run a Fresh Replay Demo**. Each run creates an independent,
   clearly labelled simulated milestone, loads the implementation sample, and audits it. It never
   calls PayPal; a configured AI reviewer may still be used. **Compare a Stub in Replay** starts a separate example so
   you can compare the actual verdicts. Without a configured reviewer, guardrail-only Replay may miss
   a keyword-heavy stub; the demo shows that result rather than forcing a rejection. You can repeat this without resetting
   anyone else's records.
2. To compare artifacts manually, select an authorized milestone, load a real or stubbed deliverable,
   and review the contract criteria shown above the editor. The test pass rate is a **reported input**,
   not measured execution: this prototype inspects submitted code but does not run it.
3. For the actual integration, create a new **PayPal Sandbox** hold with buyer approval or the sandbox
   test-card option, then audit its deliverable. The state, IDs and AI reasons are visible in the ledger.

The dashboard disables conflicting actions while a request is active and offers a read-only refresh
if a request fails. An uncertain network response is never retried automatically. If AG Grid's CDN
is unavailable, a basic selectable ledger remains usable (CSV export requires AG Grid).
The **Decision & Evidence** panel shows the final decision separately from the model recommendation and
payment state. Its downloadable JSON report includes source/evidence SHA-256 fingerprints, criteria,
reviewer results and the effective server policy. It does not separately embed the complete source, but
review excerpts may quote input text. Reports are in-memory demo records, not signed or durable logs.
The ledger and CSV show the **Audit Decision**, not a quality percentage. A model can be highly confident
that work should be rejected. Its self-reported confidence is labelled with its original recommendation;
the validated recommendation may be stricter. A rejected or unavailable required review has **no applicable
approval gate score**. Old seed/snapshot values are not reinterpreted as decision confidence.

Amounts are grouped by currency without conversion; totals explicitly include both Sandbox and Replay rows.

### Prototype limits and payment recovery

This is a public **Sandbox-only demonstration**, not a production escrow service. Its shared ledger is
in memory and resets on restart. Run a single backend process; production use needs durable storage,
authentication, per-user isolation, reconciliation and operational controls. PayPal authorizations last up to 29 days,
with capture recommended within the first 3-day honor period. Later capture depends on risk checks
and funds availability. Authorization renewal is not implemented, so this targets short-cycle
milestones rather than indefinite escrow. [PayPal authorization timing](https://developer.paypal.com/payment-methods/auth-honor/). Per-record guards prevent
concurrent audit/authorization/void operations within this single process.

Only a `COMPLETED` capture with a capture ID is shown as settled and followed by an invoice.
`CAPTURE_PENDING`, `CAPTURE_UNKNOWN` and `VOID_UNKNOWN` block further payment actions and require manual
PayPal reconciliation. A network failure or server error can leave the outcome uncertain; do not blindly
retry. There is no automatic reconciliation endpoint in this prototype. A confirmed capture remains
settled if invoice creation fails; the invoice error is reported separately.

## Prize tracks

Entered for the overall prizes, with these special prizes in mind (details and evidence: [`docs/DEVPOST_SUBMISSION.md`](docs/DEVPOST_SUBMISSION.md#prize-tracks-we-are-targeting)):

| Prize | What to look at |
|---|---|
| **Best Use of PayPal + AI** | Gemini gates capture or a hold/dispute state; void is a separate operator action. Orders v2 `AUTHORIZE` → buyer approval → `/authorize`; Payments v2 capture/void; Invoicing v2 create/send/record-payment. The AI can only make the decision stricter. Real Sandbox evidence: `docs/render_live_buyer_approval_results.json`, `docs/sandbox_gemini_e2e_results.json`. |
| **Best Use of AG Grid** | The escrow and reconciliation ledger (`frontend/index.html`): one row per escrow with the full PayPal ID chain, lifecycle-coloured state cells, live/replay data-source column, pinned ID, quick filter, row click → action panel, live refresh after each PayPal call, CSV export. |
| **Best Demo Delivery** | [2:50 video](https://youtu.be/kL-quH7Iu8U) recorded on the live Render app against the real Sandbox, and the [hosted demo](https://paypilot-escrow-ai.onrender.com): judges can repeat a Replay example or use the Sandbox test-card option; hosting and model latency varies. |
| Best Use of Render | Runs as a Render web service from `render.yaml` (health check, secrets in env vars only). |

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

PayPal API errors are returned as HTTP 502 with the available error name and `debug_id`.
Uncertain capture/void outcomes are labelled explicitly and block further payment actions.

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
unmet. In live Sandbox mode a missing, failed or invalid LLM verdict blocks auto-capture.
Each model verdict must cover the actual contract criteria, with no duplicate or unknown criterion;
missing criteria are unmet. Malformed verdicts and non-finite confidence fail closed.
For an approving review, the approval gate (the lower of the guardrail heuristic and model decision confidence)
must meet the server-owned minimum of 80 on a 0–100 scale;
a request can raise this threshold but cannot lower it. This minimum is application policy, not an
assertion that a negotiated contract threshold has been stored. Since 1.3.1, the prompt explicitly asks for
confidence in the model's own recommendation, not completeness. The report's versioned `score_details`
separates guardrail heuristics, model decision confidence and the applicable approval gate. A high rejection
confidence never overrides a hold/dispute. Scores are neither delivery-quality percentages nor calibrated
probabilities. Legacy `confidence_score` / ledger `ai_confidence` and complementary `risk_score` remain for
API compatibility only; they are diagnostic numbers, not measured quality or actual risk. Historical evidence
and video preserve their original values and labels. Deliverables over 30,000 characters are rejected instead
of silently reviewing a prefix.
The dashboard's **AI Reviewer Reasoning**
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
an OAuth token to this process. Only Replay records may use guardrail-only simulated settlement
when the AI reviewer is not configured; this exception cannot enable a live Sandbox capture.

## Configuration (environment variables only, never commit secrets)

| Variable | Purpose |
|---|---|
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` (or `PAYPAL_SANDBOX_CLIENT_ID`, `PAYPAL_SANDBOX_CLIENT_SECRET`) | Sandbox REST app credentials. Enables live Sandbox mode. |
| `PAYPAL_MODE=replay` | Force Replay (simulated) mode. |
| `PUBLIC_BASE_URL` | Optional base URL for PayPal's return/cancel redirects. Defaults to Render's automatic `RENDER_EXTERNAL_URL`, then to the request host. |
| `PAYPAL_INVOICE_NOTIFY_RECIPIENT=true` | Let PayPal e-mail the invoice to the buyer (default: off). |
| `GEMINI_API_KEY` (or `AUDITOR_LLM_API_KEY`, which takes precedence) | Enables the AI reviewer. Without it live Sandbox auto-capture is blocked; only Replay records may simulate settlement with guardrails alone. |
| `AUDITOR_LLM_MODEL` | Comma-separated models to try in order. Default `gemini-2.5-flash,gemini-3.5-flash,gemini-3.5-flash-lite`. |
| `AUDITOR_LLM_BASE_URL` | OpenAI-compatible base URL. Default: Gemini's `…/v1beta/openai`. |
| `AUDITOR_LLM_TIMEOUT` | Seconds per LLM call (default 45). |

## Run & test

```bash
pip install -r requirements.txt
uvicorn backend.app:app --host 0.0.0.0 --port 8080        # open http://localhost:8080
pytest -q -m "not live and not live_llm"                   # offline suite only
npm ci && npm test                                        # dashboard DOM unit regressions (Node 18+)
python scripts/sandbox_e2e.py http://localhost:8080       # live PayPal Sandbox + Gemini run; writes docs/sandbox_gemini_e2e_results.json
```

Test suites: `tests/test_replay.py` (simulated mode), `tests/test_live_flow_mocked.py` (live code path against
a mocked PayPal API, incl. error handling), `tests/test_auditor_llm.py` (LLM reviewer with a mocked endpoint: fallback, strict-only merging, errors),
`tests/test_live_sandbox.py` (real Sandbox calls, skipped without PayPal credentials),
`tests/test_live_gemini.py` (real Gemini calls, skipped without a key). Other tests default to an
unconfigured reviewer or explicitly mock its approval to isolate the payment path; they never call Gemini.
Run `pytest -q -m "not live and not live_llm"` for the offline suite, including missing-reviewer,
approval-gate threshold and decision-confidence semantics, no-capture/no-invoice, concurrency, currency grouping, repeatable Replay,
and uncertain-payment regression checks. Dashboard DOM tests cover loading failures, busy controls,
repeat runs, safe text rendering, and partial-success recovery; they are not visual browser tests. Real Sandbox tests create
test transactions and should only be run when that is intended.

## Stack

FastAPI · Pydantic · httpx · PayPal Orders v2 / Payments v2 / Invoicing v2 · Google Gemini (`gemini-3.5-flash`, OpenAI-compatible API) · AG Grid Community 31 · Render (`render.yaml`).

## License

[MIT](LICENSE)
