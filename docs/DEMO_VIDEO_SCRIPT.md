# PayPilot Escrow — 3-minute demo video script

Target length: 2:45 (hard limit: judges stop at 3:00). Must be a public YouTube video, English narration, and show the app actually running. Use no third-party music unless it is licensed. Screen-record at 1600×1000 or 1920×1080.

> **Before recording:** the hackathon requires a working PayPal Sandbox integration and meaningful AI. Record the PayPal steps in **live Sandbox mode** (`PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` set, buyer approval completed) and with `GEMINI_API_KEY` set so the Gemini reviewer runs (see `DEVPOST_SUBMISSION.md` → "Gaps to close before submitting"). If you record in Replay mode, say so on screen. Never present replay IDs as real PayPal transactions.

| Time | Screen | Narration (voice-over) |
| :--- | :--- | :--- |
| 0:00–0:15 | Title card: "PayPilot Escrow: AI-verified milestone payments on PayPal" | "Freelancers don't want to wait weeks for milestone payments, and buyers don't want to pay for work that doesn't run. PayPilot Escrow puts an AI auditor between PayPal's authorize and capture steps." |
| 0:15–0:35 | Dashboard (`01_dashboard_initial.png` state): KPI cards, AG Grid ledger, milestone timeline | "Every milestone in the ledger is a PayPal order with intent AUTHORIZE. The buyer's funds are held, not captured. AG Grid gives the buyer a live reconciliation view of locked and settled amounts." |
| 0:35–1:00 | Click **+ New PayPal AUTHORIZE Hold** → buyer approves in the PayPal Sandbox popup → new row MS-1006 `ESCROW_AUTHORIZED` (`05_new_authorize_hold.png`) | "The buyer creates a new milestone and approves it with PayPal. PayPilot authorizes the order, and the authorization ID shows up in the grid." |
| 1:00–1:40 | Create a live hold (+ New AUTHORIZE Hold), click **Load real deliverable**, then click **Run AI Audit & Trigger PayPal Capture**. Show the telemetry: per-criterion checks, confidence, decision `AUTO_CAPTURE_APPROVED` (`03_ai_audit_auto_capture.png`) | "The freelancer submits a deliverable. The auditor checks it against each acceptance criterion in the contract: does the code parse, are the required endpoints and tests there, are there leaked secrets or unsafe eval calls. Then Gemini writes a reasoned verdict for each criterion, shown in the AI Reviewer Reasoning panel. It can block a payout but never force one. Above the eighty percent threshold, PayPilot captures the authorization and creates a PayPal invoice with the audit attached." |
| 1:40–2:05 | Submit the bad deliverable (eval + hard-coded key) to MS-1004 → `ESCALATE_DISPUTE`, status `DISPUTE_FROZEN`, no capture. Filter the grid on "DISPUTE" (`04_grid_filter_dispute_frozen.png`) | "Now a bad deliverable: a hard-coded API key and an eval call. Confidence falls to twenty-eight percent, so the money stays held and the milestone is frozen for human review. The AI can release funds but can never force a payout." |
| 2:05–2:25 | **Export Ledger CSV**; quick view of the PayPal Sandbox dashboard showing the captured payment and the invoice | "Finance exports the reconciled ledger in one click, and every capture and invoice matches a real PayPal Sandbox transaction." |
| 2:25–2:45 | Architecture slide: FastAPI on Render → PayPal Orders v2 / Payments v2 / Invoicing v2; auditor (AST + rules + Gemini); AG Grid front end | "PayPilot runs on Render with FastAPI and PayPal's Orders, Payments and Invoicing APIs. It's open source under the MIT licence. Escrow that releases itself when the work is verifiably done." |

## Recording checklist

- [ ] Server started with Sandbox credentials. The KPI card shows "PayPal Sandbox · live" (`/api/paypal/status` → `connected: true`).
- [ ] Start from a fresh ledger (restart the server).
- [ ] Show the browser URL bar, and the Render URL if deployed.
- [ ] No real personal emails or credentials on screen. Use only Sandbox test accounts.
- [ ] Under 3:00. Upload to YouTube as Public and paste the link into Devpost.
