import json, re, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://paypilot-escrow-ai.onrender.com"
import os
OUT = Path(os.environ.get("DEMO_BUILD_DIR", "/workspace/demo-build")) / "shots"; OUT.mkdir(exist_ok=True)
REPO = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
LOG = {}
FIXCSS = ".main-grid{grid-template-columns:minmax(0,1.55fr) minmax(0,1fr)!important} pre.audit-box{white-space:pre-wrap;word-break:break-word}"
CURSOR_JS = """
(() => { if (document.getElementById('demo-cursor')) return;
 const c=document.createElement('div'); c.id='demo-cursor';
 c.style.cssText='position:fixed;z-index:99999;width:26px;height:26px;border-radius:50%;background:rgba(255,214,0,.55);border:3px solid #ffd600;pointer-events:none;left:-50px;top:-50px;transition:all .25s;box-shadow:0 0 18px #ffd600';
 document.body.appendChild(c);
 window.demoPoint=(x,y)=>{c.style.left=(x-13)+'px';c.style.top=(y-13)+'px';};
 window.demoHide=()=>{c.style.left='-50px';};
})();"""

def shot(page, name, full=False):
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
    print("shot", name, flush=True)

def point(page, locator):
    page.evaluate(CURSOR_JS)
    locator.scroll_into_view_if_needed()
    b = locator.bounding_box()
    page.evaluate(f"window.demoPoint({b['x']+b['width']/2},{b['y']+b['height']/2})")
    page.wait_for_timeout(350)

def hide(page):
    page.evaluate("window.demoHide && window.demoHide()")

def outline(page, sel, on=True):
    page.evaluate(f"""document.querySelector('{sel}').style.outline = {'"3px solid #ffd600"' if on else '""'}""")

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=1.2, locale="en-US")
    page = ctx.new_page()
    page.goto(URL, timeout=120000); page.wait_for_selector(".ag-row"); page.add_style_tag(content=FIXCSS); page.wait_for_timeout(2500)

    # A) buyer-approval order
    page.select_option("#funding", "paypal_buyer_approval")
    btn = page.get_by_role("button", name="+ New AUTHORIZE Hold")
    point(page, btn); shot(page, "s03_click_new_hold")
    with page.expect_response(lambda r: "/api/escrow/create" in r.url) as ri: btn.click()
    a = ri.value.json()["milestone"]; LOG["A"] = {k: a.get(k) for k in ("milestone_id","paypal_order_id","escrow_status","approve_url","paypal_mode")}
    page.wait_for_timeout(1500); hide(page)
    page.locator("#approval-box").scroll_into_view_if_needed()
    shot(page, "s04_awaiting_approval")
    page.screenshot(path=str(REPO / "05_new_authorize_hold.png"))
    # authorize before approval -> refused
    ab = page.get_by_role("button", name="I approved — authorize now")
    point(page, ab)
    with page.expect_response(lambda r: "/authorize" in r.url) as ri: ab.click()
    LOG["A_early_authorize_http"] = ri.value.status
    page.wait_for_timeout(1200); hide(page)
    page.locator("#audit-output").scroll_into_view_if_needed(); shot(page, "s05_order_not_approved")
    # PayPal Sandbox approval page (no login)
    pp = ctx.new_page()
    try:
        pp.goto(a["approve_url"], timeout=90000); pp.wait_for_load_state("networkidle", timeout=45000)
    except Exception as e: print("pp load", e)
    pp.wait_for_timeout(4000); pp.screenshot(path=str(OUT / "s06b_paypal_approval.png")); print("shot s06", pp.url[:60])
    pp.close()

    # B) sandbox test card -> real authorization
    page.bring_to_front(); page.evaluate("window.scrollTo(0,0)")
    page.select_option("#funding", "sandbox_test_card")
    point(page, btn); shot(page, "s07_click_card_hold")
    with page.expect_response(lambda r: "/api/escrow/create" in r.url) as ri: btn.click()
    bm = ri.value.json()["milestone"]; LOG["B_create"] = {k: bm.get(k) for k in ("milestone_id","paypal_order_id","paypal_authorization_id","escrow_status","paypal_mode")}
    page.wait_for_timeout(1500); hide(page); page.evaluate("window.scrollTo(0,0)")
    shot(page, "s08_authorized_row")
    # load good deliverable
    lb = page.get_by_role("button", name="Load real deliverable"); point(page, lb); lb.click(); page.wait_for_timeout(800)
    page.fill("#acceptance-evidence", "pytest samples/good_capture_endpoint.py: 3 passed")
    shot(page, "s09_good_loaded")
    run = page.get_by_role("button", name="Run AI Audit & Trigger PayPal Capture"); point(page, run)
    t0 = time.time()
    with page.expect_response(lambda r: "verify-and-settle" in r.url, timeout=120000) as ri: run.click()
    page.wait_for_timeout(300); shot(page, "s10_reviewing")
    out = ri.value.json(); LOG["B_settle_s"] = round(time.time()-t0,1)
    LOG["B_settle"] = {"decision": out["audit_report"]["decision"], "confidence": out["audit_report"]["confidence_score"],
        "score_details": out["audit_report"].get("score_details"),
        "guardrail": out["audit_report"]["guardrail_decision"], "model": out["audit_report"]["llm_review"].get("model"),
        "llm_decision": out["audit_report"]["llm_review"].get("recommended_decision"),
        "capture": out.get("paypal_capture"), "invoice": out.get("paypal_invoice"), "invoice_error": out.get("paypal_invoice_error"),
        "status": out["milestone"]["escrow_status"], "mode": out["paypal_mode"]}
    page.wait_for_timeout(1800); hide(page)
    page.locator("#ai-panel").scroll_into_view_if_needed(); shot(page, "s11_ai_reasoning")
    page.locator("#ai-panel").screenshot(path=str(OUT / "s11b_ai_panel.png"))
    page.screenshot(path=str(REPO / "03_ai_audit_auto_capture.png"))
    # telemetry: scroll inside pre to the capture/invoice part
    page.evaluate("""(()=>{const pre=document.getElementById('audit-output');const t=pre.textContent;const i=t.indexOf('"paypal_capture"');
       if(i>0){const lines=t.slice(0,i).split('\\n').length; pre.scrollTop=Math.max(0,(lines-2)*15.5);} })()""")
    page.locator("#audit-output").scroll_into_view_if_needed(); shot(page, "s12_capture_telemetry")
    page.evaluate("""(()=>{const pre=document.getElementById('audit-output');const t=pre.textContent;const i=t.indexOf('"paypal_invoice"');
       if(i>0){const lines=t.slice(0,i).split('\\n').length; pre.scrollTop=Math.max(0,(lines-2)*15.5);} })()""")
    shot(page, "s13_invoice_telemetry")
    page.evaluate("window.scrollTo(0,0)"); shot(page, "s14_settled_row")

    # C) stub deliverable on a new card hold -> AI blocks
    page.select_option("#funding", "sandbox_test_card")
    with page.expect_response(lambda r: "/api/escrow/create" in r.url) as ri: btn.click()
    cm = ri.value.json()["milestone"]; LOG["C_create"] = {k: cm.get(k) for k in ("milestone_id","paypal_authorization_id","escrow_status")}
    page.wait_for_timeout(1200)
    sb = page.get_by_role("button", name="Load stubbed deliverable"); point(page, sb); sb.click(); page.wait_for_timeout(800)
    page.fill("#acceptance-evidence", "")
    page.locator("#artifact-content").scroll_into_view_if_needed(); shot(page, "s15_stub_loaded")
    point(page, run)
    with page.expect_response(lambda r: "verify-and-settle" in r.url, timeout=120000) as ri: run.click()
    out = ri.value.json()
    LOG["C_settle"] = {"score_details": out["audit_report"].get("score_details"), "decision": out["audit_report"]["decision"], "guardrail": out["audit_report"]["guardrail_decision"],
        "llm_decision": out["audit_report"]["llm_review"].get("recommended_decision"), "model": out["audit_report"]["llm_review"].get("model"),
        "capture": out.get("paypal_capture"), "status": out["milestone"]["escrow_status"]}
    page.wait_for_timeout(1800); hide(page)
    page.locator("#ai-panel").scroll_into_view_if_needed(); shot(page, "s16_ai_blocks")
    # void the held authorization
    vb = page.get_by_role("button", name="Void Hold"); point(page, vb)
    with page.expect_response(lambda r: "/void" in r.url) as ri: vb.click()
    v = ri.value.json(); LOG["C_void"] = (v.get("paypal_void") or {}) | {"status": (v.get("milestone") or {}).get("escrow_status")}
    page.wait_for_timeout(1200); hide(page); page.locator("#audit-output").scroll_into_view_if_needed(); shot(page, "s17_voided")

    page.evaluate("window.scrollTo(0,0)")
    page.fill("#quick-filter", "DISPUTE"); page.dispatch_event("#quick-filter", "input"); page.wait_for_timeout(1000)
    page.screenshot(path=str(REPO / "04_grid_filter_dispute_frozen.png")); shot(page, "s18_dispute_filter")
    page.fill("#quick-filter", "Sandbox"); page.dispatch_event("#quick-filter", "input"); page.wait_for_timeout(1000)
    shot(page, "s19_live_filter")
    page.fill("#quick-filter", ""); page.dispatch_event("#quick-filter", "input"); page.wait_for_timeout(1000)
    shot(page, "s20_ledger_final")
    page.screenshot(path=str(REPO / "02_ledger_after_e2e.png"))
    b.close()

OUT.parent / "run_log.json".write_text(json.dumps(LOG, indent=2))
print(json.dumps(LOG, indent=1)[:4000])
