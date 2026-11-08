# Devpost paste-ready copy: PayPilot Escrow

Repository draft updated for the current prototype. The text already submitted to Devpost has not been verified or changed by this update. Review before copying each block into the matching Devpost field. The text between the `----- BEGIN` / `----- END` markers is the exact content; the markers themselves are not part of it.

## Project name

```
PayPilot Escrow
```

## Elevator pitch / tagline (≤200 chars)

```
PayPal Sandbox milestone payments: Gemini reviews code against acceptance criteria, with bounded decisions, payment-state tracking and downloadable audit evidence.
```

## "Try it out" links

```
https://paypilot-escrow-ai.onrender.com
https://github.com/W1nnnd/paypilot-escrow
```

## Video demo link

```
https://youtu.be/kL-quH7Iu8U
```

## Built with

```
python, fastapi, pydantic, httpx, paypal-orders-v2, paypal-payments-v2, paypal-invoicing-v2, google-gemini, ag-grid, render
```

## About the project (Markdown)

----- BEGIN ABOUT -----
## Inspiration
Freelance and micro-SaaS work stalls on trust. Buyers won't pay before the code works, and freelancers wait weeks for milestone sign-off. PayPal already offers a two-step payment: authorize now, capture later. We put an AI auditor between those two steps, to explore whether an explainable review can reduce manual milestone sign-off. This is a Sandbox prototype, and an AI review is not a guarantee that work is correct.

## What it does
- **Lock funds on PayPal.** Each milestone is a PayPal Orders v2 order with `intent=AUTHORIZE`. The buyer approves on PayPal; PayPilot calls `/authorize`, and the money is held, not captured.
- **AI audit.** The freelancer submits code and evidence. Deterministic guardrails (Python AST, leaked-secret and `eval()` scans, criteria matching, submitter-reported test pass rate) run first, then **Google Gemini** checks every acceptance criterion and returns a reasoned verdict with evidence and risk flags.
- **Settle automatically.** If both agree and the merged score meets the server-enforced minimum of 80% (requests may raise, not lower, it), PayPilot calls **Payments v2 capture**, then creates a **PayPal invoice** with the audit summary and records it as paid against the capture.
- **Hold or void.** Otherwise the hold stays for revision or dispute, and the operator can request **void** of the authorization. Voiding an uncaptured hold is not a refund of a completed capture.
- **Reconcile in AG Grid.** One grid shows every escrow with its full PayPal ID chain (order → authorization → capture → invoice), lifecycle state, AI score and data source, with quick filter and CSV export.

## How we built it
FastAPI + Pydantic + httpx on **Render** (`render.yaml` Blueprint). PayPal REST: OAuth2 client credentials, Orders v2 (authorize intent + buyer approval redirect), Payments v2 capture/void, Invoicing v2 (create, send, record payment). The auditor merges Python `ast` and rule checks with a Gemini verdict over the Gemini API's OpenAI-compatible endpoint (strict JSON with exact criterion coverage checks and instructions to treat input as untrusted, model fallback `gemini-3.5-flash` → `gemini-3.5-flash-lite`, recorded in every verdict). The front end is a single page built on **AG Grid Community 31**.

## Prize tracks

**Best Use of PayPal + AI.** The AI review gates capture or a hold/dispute state; void is a separate operator action. This Sandbox design uses conservative decision rules, but it is not validated for real-money production: the final decision is the *stricter* of the guardrails and Gemini, so the AI can block a payout but never force one. Gemini's approval only counts if every criterion is met with no high-risk flag, and an LLM error blocks capture. Verified live: a Sandbox buyer logged in and approved a $275 milestone → authorization → Gemini approved at 98.6% → capture `COMPLETED` → invoice `MARKED_AS_PAID`. In another run, a keyword-stuffed stub fooled the keyword guardrails, but **Gemini flagged the fake tests and escalated**, so nothing was captured and the hold was voided. Evidence JSON with real PayPal IDs is in the repo's `docs/` folder.

**Best Use of AG Grid.** AG Grid is the operator's workbench, not a decorative table. Each row is one PayPal escrow, with pinned milestone ID and Order / Authorization / Capture / Invoice ID columns. `cellStyle` colours the lifecycle (authorized, settled, held, voided), and `valueFormatter` renders amounts and AI confidence. A *Data Source* column labels every row as **PayPal Sandbox (live)** or *Replay (simulated)*. Sort, filter and resize work on every column, with a quick filter across IDs, contracts and statuses. Clicking a row selects that milestone for authorize / audit / void. The grid refreshes after every PayPal call, the KPI totals (locked vs settled) are computed from the same rows, and `exportDataAsCsv` produces a reconciliation file with all PayPal IDs.

**Best Demo Delivery.** The 2:50 video (https://youtu.be/kL-quH7Iu8U) was recorded on the live Render app against the real PayPal Sandbox, with Sandbox transaction IDs and explicitly labelled simulated seed rows. It shows PayPal refusing to authorize before buyer approval, a successful AI-approved capture and paid invoice, and an AI-blocked stub being voided. It also says what is a test card and what is replay data. Judges can try a fresh Replay example or the Sandbox flow at https://paypilot-escrow-ai.onrender.com with the Sandbox test-card option. Replay needs no PayPal login. Buyer-approval checkout requires a Sandbox buyer account; the separate Sandbox test-card route avoids that login. Model and hosting response times vary.

## Challenges we ran into
Modelling escrow on PayPal's authorize/capture lifecycle (authorization validity and honor periods), handling buyer approval redirects on a hosted service, and keeping the AI's power bounded and explainable per criterion.

## Accomplishments that we're proud of
Real end-to-end runs on PayPal Sandbox, including a real buyer login. An AI reviewer that caught a fake deliverable the rule checks missed. Nothing faked in live mode: PayPal errors are shown with their `debug_id`, and simulated rows are always labelled.

## What we learned
Authorize/capture can support short-cycle milestone payment experiments. PayPal authorizations last up to 29 days, with capture recommended within the first 3 days; this is not indefinite escrow. AI review needs conservative policy checks and human review when outcomes are uncertain.

## Limits
Sandbox only. The shared ledger resets on restart. Submitted code is inspected, not executed; the test pass rate is an input, not measured coverage. The downloadable evidence is an in-memory demo record, not a signed or tamper-proof audit trail. Authentication, durable storage, automatic reconciliation, authorization renewal and production compliance remain unimplemented. No measured customer-impact or real-money safety claim is made.

## What's next for PayPilot Escrow
Partial captures for multi-part milestones, automatic void on dispute timeout, re-authorization before the honor period ends, webhook-driven state (`PAYMENT.CAPTURE.COMPLETED`), and separate buyer and freelancer views.
----- END ABOUT -----

## AI tools used (required field)

----- BEGIN AI TOOLS -----
Google Gemini (gemini-3.5-flash, fallback gemini-3.5-flash-lite) via the Gemini API's OpenAI-compatible endpoint is the product's deliverable reviewer. It reads the acceptance criteria, the freelancer's deliverable and evidence, and returns strict JSON: per-criterion met / reason / evidence, risk flags, a recommended decision and confidence. PayPilot merges this with deterministic Python AST and security checks and always keeps the stricter decision. The result gates capture or a hold/dispute state. Void is a separate operator action, and an invoice is attempted only after a confirmed completed capture. The model actually used is recorded in every verdict. During development, an AI coding assistant helped write code, tests and documentation.
----- END AI TOOLS -----

## Testing instructions for judges (if the form asks)

----- BEGIN TESTING -----
1. Open https://paypilot-escrow-ai.onrender.com (free Render tier; startup and model responses can take time). Try "Run a Fresh Replay Demo" and "Compare a Stub in Replay" for separate simulated records. Inspect Decision & Evidence and download the report. Replay uses the configured reviewer when available; without it the clearly labelled guardrail-only result can miss a stub.
2. Under "New Escrow Funding", pick "Sandbox test card" and click "+ New AUTHORIZE Hold". PayPal returns a real authorization.
3. Click "Load real deliverable", then "Run AI Audit & Trigger PayPal Capture". Gemini's reasoning appears, and the grid row shows the capture and invoice IDs.
4. Create another hold, click "Load stubbed deliverable" and run the audit. Inspect the actual verdict; it is not predetermined. "Void Hold" is a separate operator action when a hold remains.
5. Use the grid's quick filter and "Export Ledger CSV".
Run locally: see README "Run & test" (pip install -r requirements.txt; uvicorn backend.app:app). Without credentials the app runs in a clearly labelled Replay mode.
----- END TESTING -----

## Gallery images (upload in this order)

1. `docs/screenshots/01_dashboard_initial.png`
2. `docs/screenshots/03_ai_audit_auto_capture.png`
3. `docs/screenshots/live_03_released.png`
4. `docs/screenshots/02_ledger_after_e2e.png`
5. `docs/screenshots/04_grid_filter_dispute_frozen.png`
6. `docs/screenshots/05_new_authorize_hold.png`
