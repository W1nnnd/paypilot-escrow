import json, subprocess, sys, html
from pathlib import Path
from playwright.sync_api import sync_playwright
import os
B = Path(os.environ.get("DEMO_BUILD_DIR", "/workspace/demo-build")); S = B/"shots"
L = json.loads((B/"run_log.json").read_text())
A, BC, BS, CC = L["A"], L["B_create"], L["B_settle"], L["C_create"]
cap, inv = BS["capture"], BS["invoice"]
LIVE = ("PayPal Sandbox · LIVE_SANDBOX", "#10b981")
RIGHT = (1150, 0, 760, 1080)

# segment: (layout, payload, header, badge, caption, say(optional), callout)
SEG = []
def seg(layout, payload, header, badge, caption, say=None, callout=None):
    SEG.append(dict(layout=layout, payload=payload, header=header, badge=badge, caption=caption, say=say or caption, callout=callout))

seg("card","title","", None,
 "Freelancers wait weeks for milestone payments, and buyers hate paying for work that doesn't run.")
seg("card","title","", None,
 "PayPilot Escrow puts an AI reviewer between PayPal's authorize and capture steps, so money moves only when the work is verified.",
 "PayPilot Escrow puts an AI reviewer between PayPal's authorize and capture steps, so money moves only when the work is verified.")
seg("full",("s01_dashboard",None),"1 · Live app on Render", LIVE,
 "This is the live app on Render, connected to the real PayPal Sandbox. Every milestone is a PayPal Orders v2 order with intent AUTHORIZE.",
 "This is the live app on Render, connected to the real PayPal Sandbox. Every milestone is a PayPal Orders version 2 order, with intent authorize.")
seg("full",("s02_status",(950,0,970,546)),"1 · Live app on Render", LIVE,
 "The status card shows an OAuth token issued by the PayPal Sandbox, and the Gemini reviewer is configured.",
 "The status card shows an oh-auth token issued by the PayPal Sandbox, and the Gemini reviewer is configured.")
seg("full",("s01_dashboard",(0,170,1250,703)),"1 · Live app on Render", LIVE,
 "Every row is labelled LIVE_SANDBOX or Replay, so simulated data is never passed off as a real PayPal transaction.",
 "Every row is labelled live sandbox, or replay, so simulated data is never passed off as a real PayPal transaction.")
seg("full",("s03_click_new_hold",None),"2 · Buyer funds a milestone", LIVE,
 "The buyer creates a new 275 dollar milestone hold.")
seg("split",("s04_awaiting_approval",RIGHT),"2 · Buyer funds a milestone", LIVE,
 "PayPal returns a real order, and the milestone waits for the buyer's approval.",
 callout=[("Milestone", A["milestone_id"]),("PayPal order", A["paypal_order_id"]),("Status","AWAITING_BUYER_APPROVAL"),("Source","LIVE_SANDBOX")])
seg("full",("s06b_paypal_approval",None),"2 · Buyer approval on PayPal Sandbox", ("sandbox.paypal.com · checkout", "#38bdf8"),
 "The approve button opens PayPal's own Sandbox checkout for that order, where the buyer logs in and approves.")
seg("split",("s05_order_not_approved",(1150,350,760,730)),"2 · No approval, no hold", LIVE,
 "Until the buyer approves, PayPilot cannot authorize: PayPal answers ORDER_NOT_APPROVED, and nothing is held.",
 "Until the buyer approves, PayPilot cannot authorize. PayPal answers, order not approved, and nothing is held.",
 callout=[("authorize call","HTTP 422 from PayPal"),("issue","ORDER_NOT_APPROVED"),("funds held","none")])
seg("full",("s07_click_card_hold",None),"3 · Funds held in escrow", LIVE,
 "For this recording, we fund the next hold with PayPal's Sandbox test card instead of a buyer login.")
seg("split",("s08_authorized_row",(0,170,1150,500)),"3 · Funds held in escrow", LIVE,
 "It creates a real PayPal authorization. The 275 dollars are now locked, not captured.",
 callout=[("Milestone", BC["milestone_id"]),("PayPal order", BC["paypal_order_id"]),("Authorization", BC["paypal_authorization_id"]),("Status","ESCROW_AUTHORIZED")])
seg("split",("s09_good_loaded",(1150,0,760,800)),"4 · Freelancer delivers", LIVE,
 "The freelancer submits the deliverable: a FastAPI capture endpoint with unit tests, plus the test output.",
 "The freelancer submits the deliverable: a FastAPI capture endpoint with unit tests, plus the test output.",
 callout=[("Criterion 1","Capture + invoice endpoint"),("Criterion 2","Unit tests for escrow states"),("Evidence","pytest: 3 passed")])
seg("split",("s10_reviewing",(1150,300,760,780)),"4 · AI audit", LIVE,
 "Clicking Run AI Audit starts the reviewer. Deterministic guardrails parse the code and scan for leaked secrets and unsafe calls.",
 "Clicking run AI audit starts the reviewer. Deterministic guardrails parse the code, and scan for leaked secrets and unsafe calls.",
 callout=[("Step 1","Python AST parse"),("Step 2","secret + unsafe-call scan"),("Step 3","Gemini per-criterion review")])
seg("split",("s11_ai_reasoning",(1150,600,770,480)),"4 · Gemini reviewer reasoning", LIVE,
 f"Then Gemini checks each acceptance criterion and explains its verdict with evidence from the code.",
 callout=[("Model", BS["model"]),("Gemini verdict", BS["llm_decision"]),("Guardrails", BS["guardrail"])])
seg("split",("s11_ai_reasoning",(1150,600,770,480)),"4 · Gemini reviewer reasoning", LIVE,
 f"Both agree: auto-capture approved, at {BS['confidence']} percent confidence, above the 80 percent threshold.",
 callout=[("Decision", BS["decision"]),("Confidence", f"{BS['confidence']}%"),("Threshold","80%")])
seg("split",("s12_capture_telemetry",(1150,380,770,700)),"5 · Capture", LIVE,
 f"PayPilot captures the authorization. PayPal reports the capture as COMPLETED.",
 f"PayPilot captures the authorization. PayPal reports the capture as completed.",
 callout=[("Capture ID", cap["capture_id"]),("Status", cap["status"]),("Amount", f"{cap['amount']['value']} {cap['amount']['currency_code']}"),("simulated", "false")])
seg("card","evidence","5 · Invoice", LIVE,
 "It then creates a PayPal invoice and records the payment against that capture, so the invoice is marked as paid.")
seg("split",("s14_settled_row",(0,170,1150,500)),"5 · Settled", LIVE,
 "In the ledger, the milestone is now captured and settled.",
 callout=[("Milestone", BC["milestone_id"]),("Status","CAPTURED_SETTLED"),("Invoice", inv["status"])])
seg("split",("s15_stub_loaded",(1150,0,760,800)),"6 · A bad deliverable", LIVE,
 "Now a stubbed deliverable on a new live hold: hard-coded return values, and a test that only asserts true.",
 callout=[("Milestone", CC["milestone_id"]),("Authorization", CC["paypal_authorization_id"]),("Deliverable","stubs + assert True")])
seg("split",("s16_ai_blocks",(1150,640,770,440)),"6 · AI blocks the payout", LIVE,
 "The keyword guardrails alone would have passed it, but Gemini flags the fake code and the fake tests.",
 callout=[("Guardrails", L["C_settle"]["guardrail"]),("Gemini verdict", L["C_settle"]["llm_decision"]),("Capture","none")])
seg("split",("s16_ai_blocks",(1150,640,770,440)),"6 · AI blocks the payout", LIVE,
 "The AI can only make a decision stricter, never looser, so the money stays on hold.",
 "The AI can only make a decision stricter, never looser, so the money stays on hold.",
 callout=[("Final decision", L["C_settle"]["decision"]),("Funds","still authorized")])
seg("split",("s17_voided",(1150,380,770,700)),"6 · Void the hold", LIVE,
 "The buyer can void the authorization, which releases the hold in PayPal.",
 callout=[("Void", L["C_void"]["status"]),("Authorization", L["C_void"]["authorization_id"])])
seg("full",("s18_dispute_filter",(0,0,1250,703)),"7 · Reconciliation ledger", ("Replay record (simulated)", "#f59e0b"),
 "Deliverables with a leaked key or an eval call are frozen for dispute review. This one is a clearly labelled replay record.",
 "Deliverables with a leaked key, or an eval call, are frozen for dispute review. This one is a clearly labelled replay record.")
seg("full",("s20_ledger_final",(0,0,1250,703)),"7 · Reconciliation ledger", LIVE,
 "The AG Grid ledger reconciles locked and settled amounts, and every live row carries its real PayPal IDs.",
 "The AG Grid ledger reconciles locked and settled amounts, and every live row carries its real PayPal I Ds.")
seg("card","arch","8 · Architecture", None,
 "Under the hood: FastAPI on Render calls PayPal OAuth, Orders v2, Payments v2 and Invoicing v2.",
 "Under the hood: FastAPI on Render calls PayPal oh-auth, Orders version 2, Payments version 2, and Invoicing version 2.")
seg("card","arch","8 · Architecture", None,
 "The auditor combines Python AST checks, rule-based guardrails and Gemini, with a fallback chain of models.",
 "The auditor combines Python syntax tree checks, rule-based guardrails, and Gemini, with a fallback chain of models.")
seg("card","impact","9 · Impact", None,
 "Freelancers get paid the moment work is verified. Buyers never pay for broken work. Every decision is explained.")
seg("card","impact","9 · Impact", None,
 "PayPilot Escrow. Open source under the MIT licence, and live on Render today.",
 "PayPilot Escrow. Open source under the M I T licence, and live on Render today.")

CSS = """*{margin:0;padding:0;box-sizing:border-box} body{width:1920px;height:1080px;background:#0b1220;font-family:Inter,'Noto Sans',sans-serif;color:#e6edf7;overflow:hidden;position:relative}
.hdr{position:absolute;top:0;left:0;right:0;height:70px;display:flex;align-items:center;justify-content:space-between;padding:0 40px;background:#070c16;border-bottom:1px solid #1f2b40}
.brand{font-weight:800;font-size:24px;color:#fff}.brand span{color:#38bdf8}.sc{font-size:24px;font-weight:600;color:#cbd5e1}
.badge{font-size:19px;font-weight:700;padding:7px 16px;border-radius:999px;border:2px solid}
.cap{position:absolute;bottom:0;left:0;right:0;height:110px;display:flex;align-items:center;justify-content:center;padding:0 90px;background:#000;font-size:31px;line-height:1.3;text-align:center;color:#fff;font-weight:500}
.stage{position:absolute;top:70px;left:0;right:0;height:900px;display:flex;align-items:center;justify-content:center;gap:36px}
.crop{overflow:hidden;position:relative;border:1px solid #2a3a55;border-radius:10px;box-shadow:0 10px 40px rgba(0,0,0,.6)}
.crop img{position:absolute}
.call{width:620px;display:flex;flex-direction:column;gap:20px}
.kv{background:#111b2e;border:1px solid #24344f;border-left:6px solid #38bdf8;border-radius:10px;padding:16px 22px}
.k{font-size:20px;color:#8fa3bf;text-transform:uppercase;letter-spacing:.06em}.v{font-size:32px;font-weight:700;color:#fff;font-family:'DejaVu Sans Mono',monospace;word-break:break-all;margin-top:4px}
.card{position:absolute;top:70px;left:0;right:0;height:900px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px;padding:0 140px;text-align:center}
h1{font-size:84px;font-weight:800;color:#fff} h2{font-size:40px;font-weight:500;color:#9fb3cc}
.pill{display:inline-block;margin:6px;font-size:26px;padding:10px 20px;border-radius:999px;background:#10233a;border:1px solid #2a4a6e;color:#bfe3ff}
.box{background:#111b2e;border:2px solid #2a4a6e;border-radius:14px;padding:18px 24px;font-size:27px;font-weight:600;color:#fff;min-width:250px}
.row{display:flex;gap:26px;align-items:center;justify-content:center}.arr{font-size:40px;color:#38bdf8}
.small{font-size:22px;color:#8fa3bf;font-weight:400;margin-top:6px}
.ev{display:grid;grid-template-columns:330px 820px;gap:14px 30px;text-align:left;font-size:30px}.ev div:nth-child(odd){color:#8fa3bf}.ev div:nth-child(even){font-family:'DejaVu Sans Mono',monospace;color:#fff;font-weight:700}
"""
def header(s):
    left = '<div class="brand">PayPilot <span>Escrow</span> · live demo</div>'
    mid = f'<div class="sc">{html.escape(s["header"])}</div>' if s["header"] else '<div></div>'
    if s["badge"]:
        t,c = s["badge"]; right = f'<div class="badge" style="color:{c};border-color:{c}">{html.escape(t)}</div>'
    else: right = '<div class="badge" style="color:#8fa3bf;border-color:#2a3a55">paypilot-escrow-ai.onrender.com</div>'
    return f'<div class="hdr">{left}{mid}{right}</div>'

def crop_html(name, box, maxw, maxh):
    x,y,w,h = box or (0,0,1920,1080)
    sc = min(maxw/w, maxh/h)
    return (f'<div class="crop" style="width:{w*sc:.0f}px;height:{h*sc:.0f}px"><img src="file://{S}/{name}.png" '
            f'style="width:{1920*sc:.0f}px;left:{-x*sc:.0f}px;top:{-y*sc:.0f}px"></div>')

def card(kind):
    if kind=="title":
        return ('<div class="card"><h1>PayPilot Escrow</h1><h2>AI-verified milestone payments on PayPal</h2>'
                '<div><span class="pill">Orders v2 · AUTHORIZE</span><span class="pill">Payments v2 · capture / void</span>'
                '<span class="pill">Invoicing v2</span><span class="pill">Gemini reviewer</span></div>'
                '<div class="small">Recorded on the live Render deployment against the real PayPal Sandbox</div></div>')
    if kind=="evidence":
        rows=[("Capture ID",cap["capture_id"]),("Capture status",cap["status"]),("Invoice ID",inv["invoice_id"]),
              ("Invoice number",inv["invoice_number"]),("Invoice steps"," → ".join(s["step"] for s in inv["steps"])),
              ("Invoice status",inv["status"]),("Mode",inv["mode"]+"  (simulated: false)")]
        body="".join(f"<div>{html.escape(k)}</div><div>{html.escape(v)}</div>" for k,v in rows)
        return f'<div class="card"><h2 style="color:#fff;font-weight:700">Real PayPal Sandbox objects from this run · {html.escape(BC["milestone_id"])}</h2><div class="ev">{body}</div></div>'
    if kind=="arch":
        return ('<div class="card"><div class="row"><div class="box">Single-page UI<div class="small">AG Grid ledger · AI reasoning panel</div></div><div class="arr">→</div>'
                '<div class="box">FastAPI on Render<div class="small">escrow state machine · provenance labels</div></div></div>'
                '<div class="row" style="gap:60px"><div class="arr">↙</div><div class="arr">↘</div></div>'
                '<div class="row"><div class="box" style="border-color:#10b981">PayPal Sandbox REST<div class="small">OAuth2 · Orders v2 (AUTHORIZE)<br>Payments v2 (capture · void)<br>Invoicing v2 (create · send · record payment)</div></div>'
                '<div class="box" style="border-color:#a78bfa">AI auditor<div class="small">Python AST + rule guardrails<br>Gemini via OpenAI-compatible API<br>model fallback · stricter-only merge</div></div></div></div>')
    if kind=="impact":
        return ('<div class="card"><h1 style="font-size:64px">Escrow that releases itself<br>when the work is verifiably done</h1>'
                '<div class="row"><div class="box">Freelancers<div class="small">paid on verification, not after weeks</div></div>'
                '<div class="box">Buyers<div class="small">never pay for broken work</div></div><div class="box">Everyone<div class="small">every decision explained</div></div></div>'
                '<h2 style="font-size:32px">github.com/W1nnnd/paypilot-escrow · paypilot-escrow-ai.onrender.com · MIT</h2></div>')

def page_html(s):
    if s["layout"]=="card": stage = card(s["payload"])
    else:
        name, box = s["payload"]
        if s["layout"]=="full": stage = f'<div class="stage">{crop_html(name, box, 1600, 880)}</div>'
        else:
            calls = "".join(f'<div class="kv"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(str(v))}</div></div>' for k,v in s["callout"])
            stage = f'<div class="stage">{crop_html(name, box, 1150, 870)}<div class="call">{calls}</div></div>'
    return f'<html><head><style>{CSS}</style></head><body>{header(s)}{stage}<div class="cap">{html.escape(s["caption"])}</div></body></html>'

PIPER = "/workspace/.demo-venv/bin/piper"; VOICE = str(B/"voices/en_US-ryan-high.onnx")
LS = sys.argv[1] if len(sys.argv)>1 else "1.0"
def dur(f): return float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(f)]))

with sync_playwright() as p:
    br = p.chromium.launch(); pg = br.new_page(viewport={"width":1920,"height":1080})
    for i,s in enumerate(SEG):
        hp = B/"frames"/f"f{i:02d}.html"; hp.write_text(page_html(s))
        pg.goto(f"file://{hp}"); pg.wait_for_timeout(250); pg.screenshot(path=str(B/"frames"/f"f{i:02d}.png"))
    br.close()

total=0; lst=[]; scenes=[]
for i,s in enumerate(SEG):
    wav = B/"audio"/f"a{i:02d}.wav"
    subprocess.run([PIPER,"-m",VOICE,"--length_scale",LS,"--sentence_silence","0.25","-f",str(wav)], input=s["say"].encode(), check=True, capture_output=True)
    d = dur(wav) + 0.45
    out = B/"segs"/f"s{i:02d}.mp4"
    subprocess.run(["ffmpeg","-loglevel","error","-y","-loop","1","-framerate","30","-i",str(B/"frames"/f"f{i:02d}.png"),"-i",str(wav),
        "-filter_complex","[1:a]aresample=48000,apad[a]","-map","0:v","-map","[a]","-t",f"{d:.3f}",
        "-c:v","libx264","-pix_fmt","yuv420p","-preset","medium","-crf","18","-tune","stillimage","-c:a","aac","-b:a","160k","-ar","48000","-ac","2",str(out)],check=True)
    lst.append(f"file '{out}'"); scenes.append((round(total,1), s["header"] or "Title", s["caption"])); total+=d
(B/"segs/list.txt").write_text("\n".join(lst)+"\n")
final = Path("/workspace/paypal-paypilot-escrow/demo/paypilot_demo.mp4"); final.parent.mkdir(exist_ok=True)
subprocess.run(["ffmpeg","-loglevel","error","-y","-f","concat","-safe","0","-i",str(B/"segs/list.txt"),
  "-vf","fade=t=in:st=0:d=0.6","-af","afade=t=in:st=0:d=0.3,loudnorm=I=-16:TP=-1.5","-c:v","libx264","-pix_fmt","yuv420p","-crf","20","-preset","medium","-tune","stillimage","-r","30",
  "-c:a","aac","-b:a","160k","-ar","48000","-movflags","+faststart",str(final)],check=True)
(B/"scenes.json").write_text(json.dumps(scenes,indent=1))
print("total", round(total,1), "final", dur(final))
