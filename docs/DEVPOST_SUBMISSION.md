# PayPal AI Hackathon — Devpost submission copy (PayPilot Escrow)

Hackathon: https://paypalaihackathon.devpost.com/
Deadline: 12 Nov 2026, 12:00 pm PST = **Fri 13 Nov 2026, 04:00 (UTC+8)**
Repository draft only; this update does not verify or change the third-party submission. Reviewable text for the Devpost form: [`DEVPOST_FINAL_PASTE.md`](DEVPOST_FINAL_PASTE.md).

## Links (all public)

| What | URL |
|---|---|
| Demo video (YouTube, public, 2:50) | https://youtu.be/kL-quH7Iu8U |
| Hosted demo (Render, live PayPal Sandbox + Gemini) | https://paypilot-escrow-ai.onrender.com |
| Source (MIT) | https://github.com/W1nnnd/paypilot-escrow |

The Render free tier sleeps when idle: the first request can take ~30–60 s. The ledger is in memory, so a restart shows only the four seed rows. They are labelled **Replay (simulated)**.

## Requirement checklist

| Devpost requirement | Where it is met |
|---|---|
| Meaningful PayPal integration | Orders v2 `intent=AUTHORIZE` + buyer approval, Payments v2 capture/void, Invoicing v2 create/send/record-payment (`backend/paypal_client.py`, `backend/app.py`) |
| Meaningful AI | Gemini reviewer that decides whether escrowed money can be captured (`backend/auditor_agent.py`) |
| Working, runnable build | Hosted URL above, plus `README.md` → *Run & test* (current offline commands and scope are in README; historical Sandbox evidence is listed below) |
| Tools named and explained | "AI tools used" section below |
| Public repo with a visible licence | MIT, `LICENSE` at the repo root |
| Public YouTube video < 3 min | https://youtu.be/kL-quH7Iu8U (2:50) |

---

## Prize tracks we are targeting

The project is entered for the overall prizes. It was designed with three special prizes in mind. Each claim below points to code or evidence in this repo.

### 1. Best Use of AG Grid

AG Grid Community 31.3 is the main working surface of the app. It is the escrow **and** reconciliation ledger, not a decorative table. Concretely (`frontend/index.html`):

- **One row per PayPal escrow.** Live Sandbox rows carry the PayPal object chain; Replay rows use SIM-prefixed IDs: Order ID → Authorization ID → Capture ID → Invoice ID. A judge can copy any Sandbox transaction ID from the grid and look it up in the PayPal Sandbox.
- **State-aware cells.** `cellStyle` colours the *PayPal Escrow State* column by lifecycle: `ESCROW_AUTHORIZED` blue, `CAPTURED_SETTLED` green, `HOLD_FOR_REVISION`/`DISPUTE_FROZEN` amber, `VOIDED` grey. `valueFormatter` renders currency amounts and the AI confidence score ("98.6%" or "Pending").
- **Honesty column.** *Data Source* uses a formatter + style to show **PayPal Sandbox (live)** vs *Replay (simulated)* per row, to distinguish simulated rows from Sandbox API records.
- **Pinned ID column** (`pinned: "left"`) keeps the milestone ID visible while scrolling across the four PayPal ID columns.
- **Sort, filter and resize** on every column (`defaultColDef`), plus a **quick filter** (`quickFilterText`) that matches order IDs, contract names, e-mails and statuses. The video uses it to isolate `DISPUTE_FROZEN` rows (screenshot `04_grid_filter_dispute_frozen.png`).
- **Grid drives the workflow.** `onRowClicked` selects that milestone in the action panel (approve, authorize, audit, void), so the grid is how an operator picks what to act on.
- **Live updates.** After every PayPal call the grid is refreshed with `setGridOption("rowData", …)` and the KPI cards (locked vs settled totals) are recomputed from the same data.
- **Reconciliation export.** `exportDataAsCsv` downloads `PayPilot_Escrow_Ledger.csv` with all PayPal IDs for finance or bookkeeping.

### 2. Best Use of PayPal + AI

PayPal and AI are not side by side here; the AI sits **inside** the PayPal payment lifecycle and decides when money moves.

| Step | PayPal API | Role of AI |
|---|---|---|
| Lock funds | `POST /v2/checkout/orders` (`intent=AUTHORIZE`), buyer approves on PayPal, then `POST /v2/checkout/orders/{id}/authorize` | — (funds are held, not captured) |
| Review | — | Gemini reads the acceptance criteria, the deliverable and the evidence, and returns strict JSON: per-criterion `met`/reason/evidence, risk flags, recommended decision, confidence |
| Release | `POST /v2/payments/authorizations/{id}/capture` | Only if guardrails **and** Gemini approve and the merged score meets the server minimum of 80%; a request may raise but cannot lower it |
| Receipt | `POST /v2/invoicing/invoices` → `/send` → `/payments` | The audit summary is written into the invoice note, which is recorded as paid against the capture ID |
| Refuse | Hold kept, or `POST /v2/payments/authorizations/{id}/void` | `HOLD_FOR_REVISION` or `ESCALATE_DISPUTE` keeps money with the buyer |

Conservative controls in this Sandbox-only prototype (not evidence of real-money safety):
- **The AI can only make the decision stricter.** Final decision = the stricter of deterministic guardrails (Python AST, secret and `eval()` scans, criteria matching, submitter-reported test pass rate) and Gemini. Gemini's "approve" counts only if every criterion is met and there is no high-severity flag. An LLM error or invalid JSON blocks auto-capture.
- **Input handling.** The deliverable is passed as untrusted data, and the reviewer is told to ignore instructions inside it.
- **Explainable.** The *AI Reviewer Reasoning* panel shows the model actually used, its decision, and the reason and evidence for each criterion.
- **Model fallback is recorded.** `gemini-2.5-flash` → `gemini-3.5-flash` → `gemini-3.5-flash-lite`. The model used is stored in every verdict.

Verified with real calls (evidence files in `docs/`):
- `render_live_buyer_approval_results.json`: MS-1010, $275. A Sandbox buyer logged in and approved order `53K375713X218770W` → authorization `27H081894V8641109` → Gemini `AUTO_CAPTURE_APPROVED` 98.6% → capture `07944841D8062892J` `COMPLETED` → invoice `INV2-DENG-MAU8-5A2E-J4VN` `MARKED_AS_PAID`. Re-checked with read-only PayPal API calls on 31 Oct 2026.
- `sandbox_gemini_e2e_results.json`: a keyword-stuffed stub passed the keyword guardrails, but **Gemini flagged fake tests (high) and escalated**, so nothing was captured and the hold was voided. A deliverable with a hard-coded secret and a syntax error was escalated and voided.
- In live mode any PayPal error is returned as HTTP 502 with PayPal's error name and `debug_id`; nothing is faked.

### 3. Best Demo Delivery

- **Video:** https://youtu.be/kL-quH7Iu8U (2:50, 1080p, English voice-over and burned-in captions, no music). It was recorded on the **live Render deployment** against the **real PayPal Sandbox**. Story: problem (0:00) → live app (0:13) → buyer funds a milestone and PayPal refuses `/authorize` until approval (0:35) → funds held (0:56) → AI audit with Gemini reasoning (1:07) → capture + paid invoice (1:34) → stub deliverable blocked by Gemini and hold voided (1:48) → AG Grid reconciliation (2:09) → architecture (2:23) → impact (2:38). Transaction rows use Sandbox IDs; seeded Replay rows are simulated (`docs/DEMO_VIDEO_SCRIPT.md`, `demo/demo_run_log.json`).
- **Shown honestly:** the video says that it uses PayPal's Sandbox test card instead of a buyer login for one hold, and it labels the dispute example as a replay record.
- **Judges can repeat the demo; hosting and model latency varies** at https://paypilot-escrow-ai.onrender.com:
  1. Pick *Sandbox test card* (PayPal authorizes immediately) or *Buyer approves on PayPal* (approve with a Sandbox personal account, then **I approved — authorize now**) and click **+ New AUTHORIZE Hold**.
  2. Click **Load real deliverable** → **Run AI Audit & Trigger PayPal Capture** → watch the capture and invoice appear in the grid.
  3. Create another hold, **Load stubbed deliverable** → **Run AI Audit & Trigger PayPal Capture** → inspect the actual AI verdict → **Void Hold** when a hold remains.
  4. Use the grid's quick filter, then **Export Ledger CSV**.

Also relevant: **Best Use of Render**. The live app runs as a Render web service from `render.yaml` (Blueprint, health check `/api/health`, secrets only in Render env vars).

---

## Project name

PayPilot Escrow

## Tagline (≤200 chars)

AI-verified milestone escrow on PayPal: funds are authorized up front, Gemini audits the deliverable against the contract, and PayPal captures and invoices only when it passes.

## Description

See [`DEVPOST_FINAL_PASTE.md`](DEVPOST_FINAL_PASTE.md). It holds the exact Markdown for the Devpost "About the project" field, including the prize-track paragraphs above in a shorter form.

## Built with

python · fastapi · pydantic · httpx · paypal-orders-v2 · paypal-payments-v2 · paypal-invoicing-v2 · ag-grid · render · google-gemini

## AI tools used (required field)

- Inside the product: Google Gemini (`gemini-3.5-flash`, fallback `gemini-3.5-flash-lite`) via the Gemini API's OpenAI-compatible endpoint. It reads the deliverable, the acceptance criteria and the evidence, and returns a structured verdict (per-criterion met/reason/evidence, risk flags, recommended decision, confidence). The verdict is merged with deterministic AST and security checks, and it can only make the decision stricter. It gates capture or a hold/dispute state; void is a separate operator action.
- During development: an AI coding assistant helped write the code, tests and docs.

## Screenshots (gallery)

`docs/screenshots/01_dashboard_initial.png`, `02_ledger_after_e2e.png`, `03_ai_audit_auto_capture.png`, `04_grid_filter_dispute_frozen.png`, `05_new_authorize_hold.png` (live app, 31 Oct 2026), plus `live_03_released.png` (MS-1010 settled after the real buyer approval).

## Verification log

- **PayPal Sandbox** (30 Oct 2026, ~19:58 and ~20:42 UTC+8): OAuth; `intent=AUTHORIZE` order; `/authorize` refused with `ORDER_NOT_APPROVED` before approval; real authorization → capture; invoice created, sent, `MARKED_AS_PAID`; `/void` on dispute.
- **Real buyer login on the live app** (31 Oct 2026, ~00:25 UTC+8): MS-1010, see above. `live_02_paypal_error_cannot_pay_self.png` shows PayPal's `CANNOT_PAY_SELF` page from a first attempt that used the merchant account as the buyer.
- **Hosted test-card run** (31 Oct 2026, ~00:01 UTC+8): `docs/render_live_e2e_results.json`: capture `1KS51027F59380236` → invoice `INV2-XUPD-JTWV-PTSK-BJH6` `MARKED_AS_PAID`; the stub was held and voided; the secret-leak deliverable was escalated and voided.
- **Video** recorded 31 Oct 2026 (~11:55 UTC+8) and uploaded publicly to YouTube.
- **Historical tests (31 Oct):** 28/28 with PayPal and Gemini credentials. Current offline results and limitations should be checked using README commands; these historical runs do not certify later releases.

## Scope and authorization timing

The target use case is short-cycle software milestones, not long-term regulated escrow. PayPal documents an authorization window of up to 29 days and recommends capture within its first 3-day honor period. Later capture depends on risk checks and funds availability. This prototype does not implement renewal or indefinite holds. Source: https://developer.paypal.com/payment-methods/auth-honor/

Code is inspected, not executed. The shared ledger and audit evidence reset on restart. Production authentication, durable storage, automatic reconciliation and compliance review are out of scope. Existing Sandbox evidence establishes API integration, not customer adoption, measurable business impact or real-money safety.

## Deploying to Render

Render Blueprint (`render.yaml`, free Python web service). Set `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `GEMINI_API_KEY` (optional `PUBLIC_BASE_URL`, `AUDITOR_LLM_MODEL`) as Render environment variables; never commit them. The current service is deployed from `main` through the Render API (GitHub auto-deploy is not linked).
