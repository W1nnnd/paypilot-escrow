# PayPilot Escrow — demo video script (as recorded)

**Rendered file:** `demo/paypilot_demo.mp4` — 1920×1080, 30 fps, H.264 + AAC, **2:50** (hard limit 3:00). English captions are burned in; a matching subtitle file is `demo/paypilot_demo.en.srt`.
**Voice-over:** offline TTS (Piper, `en_US-ryan-high` voice). No music, no third-party logos beyond the PayPal Sandbox checkout page itself.

## What was recorded

All app footage is headless Chromium (Playwright) screenshots of the **live Render deployment** (`https://paypilot-escrow-ai.onrender.com`) against the **real PayPal Sandbox**, taken on 31 Oct 2026 (~11:55 UTC+8). Every PayPal ID shown comes from that run:

| Step | Milestone | Real Sandbox objects |
| :--- | :--- | :--- |
| Buyer-approval order (not approved in the recording) | MS-1008 | order `6UV35299MM8519423`; `/authorize` before approval → PayPal `422 ORDER_NOT_APPROVED` |
| Test-card hold → AI pass → capture → invoice | MS-1009 | order `4VY9649463045174A`, authorization `83297955U0548854K`, capture `3RN795234W837005T` (`COMPLETED`), invoice `INV2-MPEX-SJC6-DNHX-TAKA` (`MARKED_AS_PAID`); Gemini model `gemini-3.5-flash-lite`, confidence 98.6% |
| Stubbed deliverable → AI blocks → void | MS-1010 | authorization `33T638749X3260030`; guardrails `AUTO_CAPTURE_APPROVED`, Gemini `HOLD_FOR_REVISION` → final `HOLD_FOR_REVISION`; void `VOIDED` |
| Dispute filter | MS-1004 | **Replay (simulated)** seed record, labelled as such on screen |

Honesty notes shown or spoken in the video:
- The PayPal buyer-approval page is shown, but the recording does **not** log in as the Sandbox buyer. The video says so and funds the next hold with PayPal's **Sandbox test card**, which produces a real authorization.
- The dispute example (MS-1004) is a replay seed record and is labelled "Replay record (simulated)" in the header badge and the narration.

## Scene list and narration (timecodes from the rendered file)

| Time | Scene | Caption / narration |
| :--- | :--- | :--- |
| 0:00.0 | Title | Freelancers wait weeks for milestone payments, and buyers hate paying for work that doesn't run. |
| 0:05.3 | Title | PayPilot Escrow puts an AI reviewer between PayPal's authorize and capture steps, so money moves only when the work is verified. |
| 0:13.0 | 1 · Live app on Render | This is the live app on Render, connected to the real PayPal Sandbox. Every milestone is a PayPal Orders v2 order with intent AUTHORIZE. |
| 0:22.2 | 1 · Live app on Render | The status card shows an OAuth token issued by the PayPal Sandbox, and the Gemini reviewer is configured. |
| 0:28.3 | 1 · Live app on Render | Every row is labelled LIVE_SANDBOX or Replay, so simulated data is never passed off as a real PayPal transaction. |
| 0:35.5 | 2 · Buyer funds a milestone | The buyer creates a new 275 dollar milestone hold. |
| 0:39.4 | 2 · Buyer funds a milestone | PayPal returns a real order, and the milestone waits for the buyer's approval. |
| 0:43.5 | 2 · Buyer approval on PayPal Sandbox | The approve button opens PayPal's own Sandbox checkout for that order, where the buyer logs in and approves. |
| 0:49.4 | 2 · No approval, no hold | Until the buyer approves, PayPilot cannot authorize: PayPal answers ORDER_NOT_APPROVED, and nothing is held. |
| 0:56.0 | 3 · Funds held in escrow | For this recording, we fund the next hold with PayPal's Sandbox test card instead of a buyer login. |
| 1:01.3 | 3 · Funds held in escrow | It creates a real PayPal authorization. The 275 dollars are now locked, not captured. |
| 1:07.5 | 4 · Freelancer delivers | The freelancer submits the deliverable: a FastAPI capture endpoint with unit tests, plus the test output. |
| 1:14.1 | 4 · AI audit | Clicking Run AI Audit starts the reviewer. Deterministic guardrails parse the code and scan for leaked secrets and unsafe calls. |
| 1:22.3 | 4 · Gemini reviewer reasoning | Then Gemini checks each acceptance criterion and explains its verdict with evidence from the code. |
| 1:27.6 | 4 · Gemini reviewer reasoning | Both agree: auto-capture approved, at 98.6 percent confidence, above the 80 percent threshold. |
| 1:34.4 | 5 · Capture | PayPilot captures the authorization. PayPal reports the capture as COMPLETED. |
| 1:39.1 | 5 · Invoice | It then creates a PayPal invoice and records the payment against that capture, so the invoice is marked as paid. |
| 1:45.4 | 5 · Settled | In the ledger, the milestone is now captured and settled. |
| 1:48.8 | 6 · A bad deliverable | Now a stubbed deliverable on a new live hold: hard-coded return values, and a test that only asserts true. |
| 1:55.1 | 6 · AI blocks the payout | The keyword guardrails alone would have passed it, but Gemini flags the fake code and the fake tests. |
| 2:00.6 | 6 · AI blocks the payout | The AI can only make a decision stricter, never looser, so the money stays on hold. |
| 2:05.5 | 6 · Void the hold | The buyer can void the authorization, which releases the hold in PayPal. |
| 2:09.7 | 7 · Reconciliation ledger | Deliverables with a leaked key or an eval call are frozen for dispute review. This one is a clearly labelled replay record. |
| 2:17.1 | 7 · Reconciliation ledger | The AG Grid ledger reconciles locked and settled amounts, and every live row carries its real PayPal IDs. |
| 2:23.4 | 8 · Architecture | Under the hood: FastAPI on Render calls PayPal OAuth, Orders v2, Payments v2 and Invoicing v2. |
| 2:31.3 | 8 · Architecture | The auditor combines Python AST checks, rule-based guardrails and Gemini, with a fallback chain of models. |
| 2:38.3 | 9 · Impact | Freelancers get paid the moment work is verified. Buyers never pay for broken work. Every decision is explained. |
| 2:45.0 | 9 · Impact | PayPilot Escrow. Open source under the MIT licence, and live on Render today. |

## How to re-render

1. `python demo/capture.py` (needs Playwright + Chromium) re-runs the live flow on Render and writes screenshots plus `run_log.json` (PayPal object IDs only; no credentials or tokens). Warm the free Render instance first (`/api/health`); cold start takes 30–60 s. Note: each run creates new Sandbox orders.
2. `python demo/build.py 0.92` renders caption frames, the Piper voice-over and the final MP4 with ffmpeg (`0.92` = speech rate).

## Upload checklist (owner action)

- [ ] Watch the MP4 once end to end.
- [ ] Upload to YouTube as **Public**, title e.g. "PayPilot Escrow — AI-verified milestone payments on PayPal (Sandbox demo)", and attach `paypilot_demo.en.srt` as English subtitles.
- [ ] Paste the YouTube link into the Devpost submission.
