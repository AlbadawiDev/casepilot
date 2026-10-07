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
