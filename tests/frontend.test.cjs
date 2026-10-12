'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function loadFrontend() {
  const nodes = new Map();
  const document = {
    addEventListener() {}, querySelectorAll: () => [],
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, {
        value: '', textContent: '', innerHTML: '', disabled: false,
        classList: { toggle() {}, add() {}, remove() {} },
        parentElement: { classList: { toggle() {} } }, focus() {},
        options: ['open', 'in_progress', 'resolved'].map(value => ({ value })),
        open: false, showModal() { this.open = true; }, close() { this.open = false; },
      });
      return nodes.get(selector);
    },
  };
  const context = vm.createContext({ document, URLSearchParams, console, setTimeout, clearTimeout, fetch: async () => { throw new Error('No network'); } });
  vm.runInContext(fs.readFileSync('static/app.js', 'utf8'), context);
  return { context, nodes, run: source => vm.runInContext(source, context) };
}

test('ticket HTML escapes stored markup and attribute delimiters', () => {
  const { run } = loadFrontend();
  const html = run(`rowMarkup({id:10, title:'<img src=x onerror=alert(1)>', code:'CP-0010', requester:'"<script>alert(1)</script>', category:'Access', priority:'high', status:'open', assignee:'<svg onload=alert(1)>', due_at:'2099-01-01T00:00:00Z'})`);
  assert.ok(html.includes('&lt;img'));
  assert.ok(html.includes('&quot;&lt;script&gt;'));
  assert.ok(html.includes('&lt;svg'));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('<script>'));
});

test('overdue indicator excludes resolved requests', () => {
  const { run } = loadFrontend();
  const ticket = `{id:1,title:'Synthetic incident',code:'CP-0001',requester:'Demo',priority:'high',due_at:'2000-01-01T00:00:00Z'}`;
  assert.match(run(`rowMarkup({...${ticket},status:'open'})`), /Overdue/);
  assert.doesNotMatch(run(`rowMarkup({...${ticket},status:'resolved'})`), /Overdue/);
});

test('older search responses cannot replace the newest results', async () => {
  const { run, nodes } = loadFrontend();
  run(`state.user={role:'admin'}; globalThis.pending=[]; api = async path => path==='/api/stats'?{total:9}:new Promise(resolve=>pending.push(resolve));`);
  const older = run('loadTickets()');
  const newest = run('loadTickets()');
  run(`pending[1]({tickets:[{id:2,title:'Latest search match',code:'CP-0002',requester:'Demo',priority:'low',status:'open',due_at:'2099-01-01T00:00:00Z'}],total:1,pages:1})`);
  await newest;
  run(`pending[0]({tickets:[{id:1,title:'Stale search match',code:'CP-0001',requester:'Demo',priority:'low',status:'open',due_at:'2099-01-01T00:00:00Z'}],total:1,pages:1})`);
  await older;
  assert.match(nodes.get('#ticket-rows').innerHTML, /Latest search match/);
  assert.doesNotMatch(nodes.get('#ticket-rows').innerHTML, /Stale search match/);
});

test('network failure shows connection feedback', async () => {
  const { run, nodes } = loadFrontend();
  await assert.rejects(run(`api('/api/health')`), /local server is running/);
  assert.equal(nodes.get('#connection-status').textContent, 'Connection unavailable');
});

const adminSession = `{user:{id:1,name:'Demo administrator',role:'admin'},csrf:'old-token'}`;
const agentSession = `{user:{id:2,name:'Demo agent',role:'agent'},csrf:'new-token'}`;
const detail = id => `({ticket:{id:${id},code:'CP-000${id}',title:'Request ${id}',description:'Synthetic request',requester:'Demo',status:'open',priority:'low',category:'Other',assignee_id:null},comments:[],audit:[]})`;

test('older detail responses cannot replace the last ticket opened', async () => {
  const { run, nodes } = loadFrontend();
  run(`setAuthenticated(${adminSession}); globalThis.pending=[]; api=async()=>new Promise(resolve=>pending.push(resolve));`);
  const older = run('showTicket(1)');
  const latest = run('showTicket(2)');
  run(`pending[1](${detail(2)})`);
  await latest;
  run(`pending[0](${detail(1)})`);
  await older;
  assert.equal(nodes.get('#detail-title').textContent, 'Request 2');
  assert.equal(run('state.selected.id'), 2);
});

test('detail from a previous sign-in is discarded after changing accounts', async () => {
  const { run, nodes } = loadFrontend();
  run(`setAuthenticated(${adminSession}); api=async()=>new Promise(resolve=>globalThis.finishDetail=resolve);`);
  const pending = run('showTicket(1)');
  run(`clearSession(); setAuthenticated(${agentSession});`);
  run(`finishDetail(${detail(1)})`);
  await pending;
  assert.equal(run('state.selected'), null);
  assert.notEqual(nodes.get('#detail-title')?.textContent, 'Request 1');
  assert.notEqual(nodes.get('#detail-dialog')?.open, true);
});

test('a delayed 401 from the previous session cannot sign out the new account', async () => {
  const { run, nodes } = loadFrontend();
  run(`setAuthenticated(${adminSession}); fetch=async()=>new Promise(resolve=>globalThis.finishFetch=resolve);`);
  const pending = run(`api('/api/tickets')`);
  const rejected = assert.rejects(pending, /Old session expired/);
  run(`clearSession(); setAuthenticated(${agentSession}); finishFetch({status:401,ok:false,json:async()=>({error:'Old session expired'})});`);
  await rejected;
  assert.equal(run('state.user.id'), 2);
  assert.equal(run('state.csrf'), 'new-token');
  assert.equal(nodes.get('#login-error').textContent, '');
});

test('a 401 from the current session still returns to sign-in', async () => {
  const { run, nodes } = loadFrontend();
  run(`setAuthenticated(${adminSession}); fetch=async()=>({status:401,ok:false,json:async()=>({error:'Session expired'})});`);
  await assert.rejects(run(`api('/api/tickets')`), /Session expired/);
  assert.equal(run('state.user'), null);
  assert.equal(nodes.get('#login-error').textContent, 'Your session ended. Sign in again.');
});

test('dashboard results from a previous sign-in cannot populate the new account', async () => {
  const { run, nodes } = loadFrontend();
  run(`setAuthenticated(${adminSession}); globalThis.pending=[]; api=async()=>new Promise(resolve=>pending.push(resolve));`);
  const pending = run('loadOverview()');
  run(`clearSession(); setAuthenticated(${agentSession});
    pending[0]({total:999,active:999,overdue:0,resolved:0,by_status:{open:999}});
    pending[1]({tickets:[]}); pending[2]({tickets:[]});`);
  await pending;
  assert.notEqual(nodes.get('#metric-total')?.textContent, 999);
});

test('a completed sign-out from the previous session cannot clear the new account', async () => {
  const { run } = loadFrontend();
  run(`setAuthenticated(${adminSession}); api=async()=>new Promise(resolve=>globalThis.finishSignOut=resolve);`);
  const pending = run('logout()');
  run(`clearSession(); setAuthenticated(${agentSession}); finishSignOut({ok:true});`);
  await pending;
  assert.equal(run('state.user?.id'), 2);
});

test('CSV preview escapes both imported values and validation feedback', () => {
  const { run, nodes } = loadFrontend();
  run(`renderImportPreview({row_count:1,already_imported:false,errors:[{row:2,field:'<img>',message:'"<script>alert(1)</script>'}],rows:[{row:2,title:'<svg onload=alert(1)>',category:'<b>Other</b>',priority:'high',requester:'<img src=x>'}]})`);
  const html=nodes.get('#import-preview').innerHTML;
  assert.match(html,/&lt;svg/);
  assert.match(html,/&quot;&lt;script&gt;/);
  assert.doesNotMatch(html,/<script|<img|<svg|<b>/);
});

test('editing CSV while preview is pending discards the old confirmation', async () => {
  const { run, nodes } = loadFrontend();
  run(`setAuthenticated(${adminSession}); $('#import-csv').value='old input'; api=async()=>new Promise(resolve=>globalThis.finishPreview=resolve);`);
  const pending=run('previewImport({preventDefault(){}})');
  run(`$('#import-csv').value='new input'; invalidateImport(); finishPreview({can_commit:true,content_hash:'old-hash',row_count:1,errors:[],rows:[]});`);
  await pending;
  assert.equal(run('state.importPreview'),null);
  assert.equal(nodes.get('#import-commit').disabled,true);
  assert.equal(nodes.get('#import-preview').innerHTML,'');
});

test('CSV preview from a previous sign-in cannot arm import for another account', async () => {
  const { run, nodes } = loadFrontend();
  run(`setAuthenticated(${adminSession}); $('#import-csv').value='old input'; api=async()=>new Promise(resolve=>globalThis.finishPreview=resolve);`);
  const pending=run('previewImport({preventDefault(){}})');
  run(`clearSession(); setAuthenticated(${agentSession}); finishPreview({can_commit:true,content_hash:'old-hash',row_count:1,errors:[],rows:[]});`);
  await pending;
  assert.equal(run('state.importPreview'),null);
  assert.equal(nodes.get('#import-commit').disabled,true);
});

test('import requires an unchanged confirmed preview and administrator role', async () => {
  const { run } = loadFrontend();
  run(`setAuthenticated(${adminSession}); globalThis.calls=0; api=async()=>{calls++;return {}};`);
  await run('commitImport()');
  run(`state.importPreview={text:'confirmed input',hash:'hash'}; $('#import-csv').value='changed input';`);
  await run('commitImport()');
  run(`$('#import-csv').value='confirmed input'; state.user.role='agent';`);
  await run('commitImport()');
  assert.equal(run('calls'),0);
});

test('a failed import retains the same batch hash for a safe duplicate retry', async () => {
  const { run, nodes } = loadFrontend();
  run(`setAuthenticated(${adminSession}); $('#import-csv').value='confirmed input';
    state.importPreview={text:'confirmed input',hash:'stable-hash'}; globalThis.calls=[]; setView=()=>{};
    api=async(path,options)=>{calls.push(options.body);if(calls.length===1)throw new Error('Connection interrupted');return {duplicate:true,imported_count:2}};`);
  await run('commitImport()');
  assert.equal(run('state.importBusy'),false);
  assert.equal(nodes.get('#import-commit').disabled,false);
  assert.match(nodes.get('#import-error').textContent,/retry this batch safely/);
  await run('commitImport()');
  assert.equal(run('calls.length'),2);
  assert.equal(run('calls[0].content_hash'),run('calls[1].content_hash'));
  assert.equal(run('calls[0].csv_text'),run('calls[1].csv_text'));
  assert.equal(run('state.importPreview'),null);
  assert.match(nodes.get('#toast').textContent,/already imported/);
});

