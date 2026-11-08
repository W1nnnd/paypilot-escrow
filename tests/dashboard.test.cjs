/* DOM unit regressions. No browser, network, PayPal, or model calls. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync('frontend/index.html', 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const sample = fs.readFileSync('samples/good_capture_endpoint.py', 'utf8');
const row = id => ({milestone_id:id, milestone_title:'Capture endpoint', project_name:'Demo', amount:3200,
  currency:'USD', paypal_mode:'REPLAY_SIMULATED', escrow_status:'ESCROW_AUTHORIZED',
  due_date:'2026-11-08', progress_pct:25, required_criteria:['Implement capture'], ai_decision:'PENDING_DELIVERABLE'});
function ledger(rows) { return {milestones:rows, metrics:{total_milestones:rows.length, live_sandbox_records:0,
  escrow_locked_by_currency:{EUR:1850,USD:7300}, settled_captured_by_currency:{USD:2400}}}; }
function response(out, status=200) { return {ok:status<300, status, json:async()=>JSON.parse(JSON.stringify(out))}; }
async function setup(t, handler) {
  const dom = new JSDOM(html, {url:'http://localhost/', runScripts:'outside-only'});
  t.after(()=>dom.window.close());
  await new Promise(resolve=>dom.window.addEventListener('load',resolve,{once:true}));
  const win=dom.window;
  win.fetch=handler;
  win.eval(script);
  return {win, doc:win.document};
}

test('fallback ledger renders without AG Grid and keeps money currencies separate',async t=>{
  const {win,doc}=await setup(t,async()=>response(ledger([row('MS-1002')])));
  await win.refreshLedger();
  assert.match(doc.getElementById('kpi-locked').textContent,/EUR 1,850.00\nUSD 7,300.00/);
  assert.match(doc.getElementById('escrowGrid').textContent,/AG Grid could not load/);
  assert.equal(doc.getElementById('export-button').disabled,true);
  assert.equal(doc.getElementById('audit-button').disabled,false);
});

test('untrusted milestone titles and dates remain literal text',async t=>{
  const m={...row('MS-1002'),milestone_title:'<img src=x onerror=alert(1)>',due_date:'<svg onload=alert(1)>'};
  const {win,doc}=await setup(t,async()=>response(ledger([m])));
  await win.refreshLedger();
  assert.equal(doc.querySelectorAll('#ganttContainer svg, #milestone-select img').length,0);
  assert.match(doc.getElementById('ganttContainer').textContent,/<svg onload=/);
  assert.match(doc.getElementById('milestone-select').textContent,/<img src=/);
});

test('double click guard performs one request and restores controls',async t=>{
  let release;
  const {win,doc}=await setup(t,async()=>response(ledger([row('MS-1002')])));
  await win.refreshLedger();
  let count=0;
  const pending=win.runAction('Working',async()=>{count++;await new Promise(r=>release=r);});
  assert.equal(doc.getElementById('demo-button').disabled,true);
  await win.runAction('Repeated',async()=>count++);
  assert.equal(count,1);
  release(); await pending;
  assert.equal(doc.getElementById('demo-button').disabled,false);
});

test('fresh replay runs can repeat without reusing a settled milestone',async t=>{
  let rows=[row('MS-1002')]; const audited=[];
  const {win,doc}=await setup(t,async(url,opts)=>{
    if(url==='/api/milestones')return response(ledger(rows));
    if(url==='/api/samples/good')return response({content:sample});
    if(url==='/api/demo/replay') { const m=row(`MS-${1002+rows.length}`);rows.push(m);return response({status:'ok',milestone:m}); }
    if(url==='/api/escrow/verify-and-settle') {
      const body=JSON.parse(opts.body);audited.push(body.milestone_id);
      const m=rows.find(x=>x.milestone_id===body.milestone_id);m.escrow_status='CAPTURED_SETTLED';
      return response({status:'ok',milestone:m});
    }
    throw new Error('Unexpected route '+url);
  });
  await win.refreshLedger();
  await win.prefillAndRunDemo(); await win.prefillAndRunDemo();
  assert.equal(audited.length,2); assert.notEqual(audited[0],audited[1]);
  assert.equal(rows[0].escrow_status,'ESCROW_AUTHORIZED');
  assert.equal(doc.getElementById('audit-button').disabled,true);
  assert.equal(doc.getElementById('demo-button').disabled,false);
});

test('completed operation response survives failed ledger refresh',async t=>{
  let reads=0;
  const {win,doc}=await setup(t,async(url)=>{
    if(url==='/api/milestones'){if(++reads>1)throw new Error('offline');return response(ledger([row('MS-1002')]));}
    return response({status:'ok',milestone:{...row('MS-1002'),escrow_status:'VOIDED'}});
  });
  await win.refreshLedger();await win.voidSelected();
  assert.match(doc.getElementById('audit-output').textContent,/VOIDED/);
  assert.match(doc.getElementById('action-status').textContent,/operation completed, but the ledger could not refresh/);
  assert.equal(doc.getElementById('demo-button').disabled,true);
  assert.equal(doc.getElementById('refresh-button').disabled,false);
});

test('unknown mutation result blocks retry until explicit ledger refresh',async t=>{
  const {win,doc}=await setup(t,async(url)=>{
    if(url==='/api/milestones')return response(ledger([row('MS-1002')]));
    if(url==='/api/paypal/status')return response({mode:'REPLAY_SIMULATED'});
    throw new Error('Network disconnected');
  });
  await win.refreshLedger();await win.voidSelected();
  assert.match(doc.getElementById('action-status').textContent,/may still have completed/);
  assert.equal(doc.getElementById('void-button').disabled,true);
  await win.refreshDashboard();
  assert.equal(doc.getElementById('void-button').disabled,false);
});

test('pending capture is warned, never displayed as successful settlement',async t=>{
  const pending={...row('MS-1002'),escrow_status:'CAPTURE_PENDING'};
  const {win,doc}=await setup(t,async(url)=>response(url==='/api/milestones'?ledger([pending]):{status:'pending',milestone:pending}));
  await win.refreshLedger(); await win.postJson('/mock');
  assert.equal(doc.getElementById('audit-button').disabled,true);
  assert.equal(doc.getElementById('void-button').disabled,true);
  assert.equal(doc.getElementById('action-status').dataset.kind,'error');
  assert.match(doc.getElementById('action-status').textContent,/Payment is not confirmed/);
});

test('invalid reported pass rate makes no audit request',async t=>{
  let posts=0;
  const {win,doc}=await setup(t,async(url,opts)=>{if(opts.method==='POST')posts++;return response(ledger([row('MS-1002')]));});
  await win.refreshLedger();doc.getElementById('artifact-content').value=sample;
  doc.getElementById('test-pass-rate').value='';await win.submitVerification();
  assert.equal(posts,0);assert.match(doc.getElementById('action-status').textContent,/between 0 and 100/);
  assert.equal(doc.getElementById('audit-button').disabled,false);
});

test('load failure is visible and retry can restore the dashboard',async t=>{
  let fail=true;
  const {win,doc}=await setup(t,async url=>{
    if(url==='/api/paypal/status')return response({mode:'REPLAY_SIMULATED'});
    if(fail)throw new Error('offline');return response(ledger([row('MS-1002')]));
  });
  await win.refreshDashboard();
  assert.equal(doc.getElementById('demo-button').disabled,true);
  assert.match(doc.getElementById('action-status').textContent,/Could not load the ledger/);
  fail=false;await win.refreshDashboard();
  assert.equal(doc.getElementById('demo-button').disabled,false);
});

test('audit evidence separates approval from unconfirmed payment and provides report link',async t=>{
  const m={...row('MS-1002'),escrow_status:'CAPTURE_UNKNOWN',last_audit_report:{
    audit_id:'AUD-test',evaluated_at:'2026-11-08T00:00:00Z',artifact_sha256:'abc123',
    effective_threshold:80,server_minimum_threshold:80,audit:{decision:'AUTO_CAPTURE_APPROVED',
      auto_release_eligible:true,confidence_score:92,guardrail_decision:'AUTO_CAPTURE_APPROVED',
      llm_review:{status:'OK'},checks:[{passed:true,criterion:'<script>text</script>',evidence:'reviewed'}]}}};
  const {win,doc}=await setup(t,async()=>response(ledger([m])));
  await win.refreshLedger();
  assert.match(doc.getElementById('decision-body').textContent,/CAPTURE_UNKNOWN/);
  assert.match(doc.getElementById('decision-body').textContent,/not payment confirmation/);
  assert.equal(doc.querySelectorAll('#decision-body script').length,0);
  assert.equal(doc.getElementById('audit-report-link').getAttribute('href'),'/api/escrow/MS-1002/audit-report?download=true');
  assert.equal(doc.getElementById('audit-button').disabled,true);
});

test('fresh stub demo loads the stub and reports actual verdict',async t=>{
  const rows=[row('MS-1002')];let sampleRoute;let auditPayload;
  const {win,doc}=await setup(t,async(url,opts)=>{
    if(url==='/api/milestones')return response(ledger(rows));
    if(url.startsWith('/api/samples/')){sampleRoute=url;return response({content:'def stub(): return True'});}
    if(url==='/api/demo/replay'){const m=row('MS-2000');rows.push(m);return response({status:'ok',milestone:m});}
    auditPayload=JSON.parse(opts.body);rows[1].escrow_status='HOLD_FOR_REVISION';
    return response({status:'ok',milestone:rows[1]});
  });
  await win.refreshLedger();await win.prefillAndRunDemo('stub');
  assert.equal(sampleRoute,'/api/samples/stub');assert.equal(auditPayload.milestone_id,'MS-2000');
  assert.match(doc.getElementById('action-status').textContent,/HOLD_FOR_REVISION/);
});
