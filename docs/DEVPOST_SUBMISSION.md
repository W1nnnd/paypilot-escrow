# PayPal AI Hackathon — Devpost submission copy (PayPilot Escrow)

Hackathon: https://paypalaihackathon.devpost.com/
Deadline: 12 Nov 2026, 12:00 pm PST = **Fri 13 Nov 2026, 04:00 (UTC+8)**
Required: text description; a functional demo (hosted URL or complete run instructions); the AI tools used; a **public** GitHub/GitLab/Bitbucket repository with a visible licence; a public YouTube demo under 3 minutes.

## Gaps to close before submitting (updated 31 Oct 2026, 12:15 UTC+8)

**Done and verified with real calls:**
- **PayPal Sandbox** (30 Oct, ~19:58 and ~20:42 UTC+8). OAuth token; `intent=AUTHORIZE` order with the buyer approve link; `/authorize` refused with `ORDER_NOT_APPROVED` until the buyer approves; real authorization → `/capture`; invoice created, sent and recorded as paid (`MARKED_AS_PAID`); `/void` on dispute. Nothing is invented in live mode.
- **AI requirement (Gemini).** The auditor calls Gemini through the OpenAI-compatible endpoint. Models actually used: **`gemini-3.5-flash`** or **`gemini-3.5-flash-lite`** (fallback chain). `gemini-2.5-flash` is tried first but returns 404 ("no longer available to new users"), and the fallback is recorded in every verdict. Gemini returns per-criterion reasons, evidence and risk flags, and it can only make the decision stricter. Evidence from the 30 Oct ~20:42 UTC+8 run is in `docs/sandbox_gemini_e2e_results.json`:
  - real deliverable → Gemini approves → PayPal capture → invoice `MARKED_AS_PAID`;
  - stubbed, keyword-stuffed deliverable → keyword guardrails approve, **Gemini flags fake tests (high) and escalates** → no capture, hold kept, then voided;
  - hard-coded secret plus syntax error → both escalate → hold voided.
- **Real buyer login and approval on the live app (31 Oct 2026, ~00:25 UTC+8).** Milestone **MS-1010**, $275.00: the buyer logged in to PayPal Sandbox with a Sandbox personal account and approved order `53K375713X218770W` (`payment_source: paypal`). PayPal redirected back to PayPilot, which authorized it (`27H081894V8641109`). Gemini (`gemini-3.5-flash-lite`) returned `AUTO_CAPTURE_APPROVED` at 98.6%, then PayPilot captured `07944841D8062892J` (`COMPLETED`) and invoice `INV2-DENG-MAU8-5A2E-J4VN` was recorded as paid (`MARKED_AS_PAID`). The order, authorization, capture and invoice states were re-checked with read-only PayPal API calls on 31 Oct ~12:10 UTC+8: `docs/render_live_buyer_approval_results.json`, screenshots `docs/screenshots/live_01_dashboard.png` and `live_03_released.png`. (`live_02_paypal_error_cannot_pay_self.png` shows PayPal's `CANNOT_PAY_SELF` page from the first attempt, when the merchant account was used as the buyer.)
- **Demo video recorded (31 Oct 2026, ~11:55 UTC+8).** `demo/paypilot_demo.mp4`, 2:50, 1080p, English voice-over and captions (`demo/paypilot_demo.en.srt`), recorded on the live Render app against the real Sandbox: MS-1008 order `6UV35299MM8519423` refused with `ORDER_NOT_APPROVED` before approval; MS-1009 test-card authorization `83297955U0548854K` → Gemini 98.6% → capture `3RN795234W837005T` → invoice `INV2-MPEX-SJC6-DNHX-TAKA` `MARKED_AS_PAID`; MS-1010 stub held by Gemini and voided. Details: `docs/DEMO_VIDEO_SCRIPT.md`, `demo/demo_run_log.json`. (The ledger is in memory and restarts with each deploy, so MS-10xx numbers repeat across runs; the PayPal IDs are unique.)
- **Labelling.** Replay mode shows "Replay (simulated)" with `SIM-` IDs. The KPI card names the active AI reviewer model, and the dashboard has an **AI Reviewer Reasoning** panel.
- **Tests.** 28/28 pass with PayPal and Gemini credentials. Without credentials: 21 pass, 7 live tests skipped.

**Still open:**
1. **Buyer approval with a real Sandbox buyer login: done** (MS-1010, see above).
2. **Screenshots: done.** `docs/screenshots/01`–`05` were retaken from the live app on 31 Oct 2026 (live Sandbox rows, AI Reviewer Reasoning panel).
3. **Repository.** Published (public, MIT): https://github.com/W1nnnd/paypilot-escrow.
4. **Hosted demo: done.** https://paypilot-escrow-ai.onrender.com is a Render free web service in Singapore (deployed from `main` via the Render API; GitHub is not linked, so each push needs a manual redeploy), running live PayPal Sandbox and Gemini. A test-card run on 31 Oct 2026 at ~00:01 UTC+8 is in `docs/render_live_e2e_results.json`: real deliverable → Gemini approves → capture `1KS51027F59380236` → invoice `INV2-XUPD-JTWV-PTSK-BJH6` `MARKED_AS_PAID`; the stubbed deliverable was held by Gemini and then voided; the deliverable with a hard-coded secret was escalated and voided. Note: the free tier sleeps when idle, so the first request takes ~30–60 s, and the in-memory ledger resets on restart.
5. **Video: recorded, not yet uploaded.** `demo/paypilot_demo.mp4` (2:50). Owner action: upload to YouTube as Public (attach `demo/paypilot_demo.en.srt`) and paste the link below.

## Project name

PayPilot Escrow

## Tagline (≤200 chars)

AI-verified milestone escrow on PayPal: funds are authorized up front, an AI auditor checks the deliverable against the contract, and PayPal captures and invoices automatically when it passes.

## Description (Markdown)

### Inspiration
Freelance and micro-SaaS work stalls on trust. Buyers won't pay before the code works, and freelancers wait weeks for milestone sign-off. PayPal already offers a two-step payment, authorize now and capture later. We put an AI auditor between those two steps.

### What it does
- **Lock funds.** Each milestone is a PayPal Orders v2 order with `intent=AUTHORIZE`. The buyer approves it on PayPal; PayPilot then calls `/authorize` and the funds are held.
- **Audit the deliverable.** When the freelancer submits code or an API spec, the Deliverable Auditor checks it against each acceptance criterion: AST syntax, required endpoints and tests, leaked secrets, `eval()`, and the test pass rate. Google Gemini (`gemini-3.5-flash`) then reads the deliverable and evidence and returns a reasoned, per-criterion verdict with risk flags. It can block or escalate a payout, but it can never approve one the guardrails rejected. Output: confidence score, risk score and a decision (`AUTO_CAPTURE_APPROVED`, `HOLD_FOR_REVISION` or `ESCALATE_DISPUTE`).
- **Settle automatically.** At or above the contract threshold (80% by default), PayPilot calls `POST /v2/payments/authorizations/{id}/capture`, then creates a PayPal invoice with the audit attached and records it as paid. Below it, funds stay held: revise or escalate. A disputed hold can be voided back to the buyer. The AI can release money but can't force a payout.
- **Reconcile.** An AG Grid workbench shows each milestone's status, AI score and PayPal IDs, with quick filters, a timeline and CSV export.

### How we built it
FastAPI and Pydantic back end. PayPal REST: OAuth2 client credentials, Orders v2 (authorize intent + buyer approval redirect), Payments v2 capture/void, Invoicing v2 (create, send, record payment). The auditor is Python `ast` + rule checks + a Gemini verdict over the OpenAI-compatible API (strict JSON, prompt-injection-hardened, strict-only merging). The front end is a single page with AG Grid Community 31. It deploys to Render with `render.yaml`. A zero-config **Replay mode** lets judges try the UI without credentials. It is clearly labelled and makes no PayPal calls.

### Challenges
Modelling escrow on PayPal's authorize/capture lifecycle (authorization validity and honor periods), and keeping the AI's power bounded: it can only release funds, and every decision is explainable per criterion.

### What's next
Partial captures for multi-part milestones, automatic `void` on dispute timeout, re-authorization before the honor period ends, webhook-driven state (`PAYMENT.CAPTURE.COMPLETED`), and buyer/freelancer views.

## Built with

python · fastapi · pydantic · httpx · paypal-orders-v2 · paypal-payments-v2 · paypal-invoicing-v2 · ag-grid · render · google-gemini

## AI tools used (required field)

- Inside the product: Google Gemini `gemini-3.5-flash` via the Gemini API's OpenAI-compatible endpoint. It reads the deliverable, the acceptance criteria and any evidence, and returns a structured verdict (per-criterion met/reason/evidence, risk flags, recommended decision). That verdict is combined with deterministic AST and security checks, and it can only make the decision stricter.
- During development: an AI coding assistant helped write the code, tests and docs.

## Links

- Repository: https://github.com/W1nnnd/paypilot-escrow
- Hosted demo: https://paypilot-escrow-ai.onrender.com (live PayPal Sandbox + Gemini; Replay rows are labelled)
- Video: YouTube link (to add after upload; file `demo/paypilot_demo.mp4`, script `docs/DEMO_VIDEO_SCRIPT.md`)

## Screenshots (gallery)

`docs/screenshots/01_dashboard_initial.png`, `02_ledger_after_e2e.png`, `03_ai_audit_auto_capture.png`, `04_grid_filter_dispute_frozen.png`, `05_new_authorize_hold.png` (live app, 31 Oct 2026), plus `live_03_released.png` (MS-1010 settled after the real buyer approval)

## Deploying to Render (what's needed)

- A Render account. Either connect GitHub in the Render dashboard (Blueprint → pick the repo; `render.yaml` defines the free Python web service), or use a Render API key for CLI/API deploys. Render deploys from a Git repo, so the public GitHub repo has to exist first.
- Environment variables in Render: `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` (Sandbox REST app), `GEMINI_API_KEY`, and optionally `PUBLIC_BASE_URL` (defaults to Render's `RENDER_EXTERNAL_URL`) and `AUDITOR_LLM_MODEL`. Never commit them.
- PayPal Sandbox personal (buyer) and business (seller) test accounts, used to approve orders in the demo.
