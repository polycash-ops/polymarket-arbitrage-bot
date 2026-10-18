'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '..', 'dashboard.py'), 'utf8');
const match = source.match(/<script>([\s\S]*?)<\/script>/);
assert.ok(match, 'dashboard must contain its actual script block');
let script = match[1];
const bootstrap = script.lastIndexOf('clock();setInterval(clock,1000);');
assert.ok(bootstrap >= 0, 'script bootstrap anchor must be present');
script = script.slice(0, bootstrap); // evaluate real functions without starting polling timers

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    id, textContent: '', className: '', children: [],
    replaceChildren(...nodes) { this.children = nodes; },
    appendChild(node) { this.children.push(node); },
    setAttribute() {},
  });
  return elements.get(id);
}
const window = {__reservoirCanonicalIdentity: 'old', __reservoirAlertGeneration: 4};
const document = {getElementById: element, createElement: tag => ({tag, textContent: '', children: [], appendChild(n) { this.children.push(n); }}), createElementNS: (ns, tag) => ({ns, tag, attrs: {}, setAttribute(k,v) { this.attrs[k]=v; }, appendChild(n) { (this.children ||= []).push(n); }, textContent: ''})};
let calls = [];
let lateAlertMode = false;
let rejectLateAlert;
const fetch = async url => {
  calls.push(String(url));
  if (String(url).startsWith('/api/active-alert') && lateAlertMode) {
    return new Promise((resolve, reject) => { rejectLateAlert = reject; });
  }
  if (String(url).startsWith('/api/live-quotes')) return {ok:true, json:async()=>({
    sources:{}, reference:{}, polymarket:{slug:'new', question:'BTC Up or Down 15m', start_at:'2026-10-17T21:30:00+00:00', end_at:'2026-10-17T21:45:00+00:00', midpoint:0.5, bid:0.49, ask:0.51}
  })};
  if (String(url).startsWith('/api/current-contract')) return {ok:true, json:async()=>({status:'OPEN', contract:{identity:'new', question:'BTC Up or Down 15m', start_at:'2026-10-17T21:30:00+00:00', end_at:'2026-10-17T21:45:00+00:00'}})};
  throw new Error('unexpected fetch '+url);
};
const context = {window, document, fetch, console, Date, Intl, Math, Number, String, Object, Array, Promise, setInterval:()=>0, clearInterval:()=>0};
vm.createContext(context);
vm.runInContext(script, context, {filename:'dashboard-inline.js'});
vm.runInContext(`refreshContractPriceChart = () => {}; activeAlertState = {contractIdentity:'old', annotations:[{direction:'UP'}]}; priceChartSlug='old'; lastPriceSeries={contract_identity:'old'};`, context);
element('alertDirection').textContent = 'UP';
element('alertAnnotationCount').textContent = '1';
element('alertIssued').textContent = 'old issuance';

(async () => {
  await context.refreshLiveQuotes();
  assert.equal(window.__reservoirCanonicalIdentity, 'new');
  assert.equal(window.__reservoirAlertGeneration, 6, 'rollover invalidates old alert requests and starts a fresh request');
  const state = vm.runInContext('activeAlertState', context);
  assert.equal(state.contractIdentity, null, 'rollover clears previous contract alert identity');
  assert.deepEqual(Array.from(state.annotations), [], 'rollover clears previous graph markers');
  assert.equal(element('alertDirection').textContent, 'No active UP/DOWN alert.');
  assert.equal(element('alertAnnotationCount').textContent, 0);
  assert.equal(element('alertIssued').textContent, '—');

  const lateAccepted = context.applyAlertPayload(4, {status:'ACTIVE', contract:{identity:'old'}, alert:{direction:'UP'}, graph_annotations:[{direction:'UP'}]});
  assert.equal(lateAccepted, false, 'late prior-generation response is ignored');
  const wrongIdentityAccepted = context.applyAlertPayload(6, {status:'ACTIVE', contract:{identity:'old'}, alert:{direction:'UP'}, graph_annotations:[]});
  assert.equal(wrongIdentityAccepted, false, 'same-generation wrong-contract response is ignored');
  const currentAccepted = context.applyAlertPayload(6, {status:'NO_ACTIVE_ALERT', contract:{identity:'new'}, alert:null, graph_annotations:[]});
  assert.equal(currentAccepted, true, 'current-contract response may update panel');
  assert.ok(calls.some(url=>url.startsWith('/api/current-contract')));

  element('alertStatus').textContent = 'CHECKING';
  element('alertMessage').textContent = 'new contract is being checked';
  lateAlertMode = true;
  const pendingAlertRefresh = context.refreshActiveAlert();
  context.bumpAlertGeneration();
  rejectLateAlert(new Error('late old-contract network failure'));
  await pendingAlertRefresh;
  assert.equal(element('alertStatus').textContent, 'CHECKING', 'late alert error cannot overwrite new contract status');
  assert.equal(element('alertMessage').textContent, 'new contract is being checked', 'late alert error cannot overwrite new contract message');
  console.log('PASS: frontend rollover clears old alert/markers and rejects late success, wrong-identity, and late-error responses');
})().catch(err => { console.error(err); process.exitCode = 1; });
