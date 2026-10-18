'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '..', 'dashboard.py'), 'utf8');
const match = source.match(/<script>([\s\S]*?)<\/script>/);
assert.ok(match, 'dashboard must contain script block');
let script = match[1];
const bootstrap = script.lastIndexOf('clock();setInterval(clock,1000);');
assert.ok(bootstrap >= 0, 'bootstrap anchor');
script = script.slice(0, bootstrap);

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
const window = {__reservoirCanonicalIdentity: null, __reservoirAlertGeneration: 0};
const document = {
  getElementById: element,
  createElement: tag => ({tag, textContent: '', children: [], appendChild(n) { this.children.push(n); }}),
  createElementNS: (ns, tag) => ({ns, tag, attrs: {}, setAttribute(k,v){this.attrs[k]=v;}, appendChild(n){(this.children||=[]).push(n);}, textContent:''}),
};

let fetchImpl = null;
const fetch = async (url) => fetchImpl(String(url));

// Evaluate dashboard functions in sandbox
const sandbox = {window, document, fetch, console, setInterval: () => 0, clearInterval: () => {}, Date, Math, JSON, parseFloat, Number, String, Array, Object, Promise, Map, Set, Error};
const vm = require('node:vm');
vm.createContext(sandbox);
vm.runInContext(script, sandbox);

const {refreshLiveQuotes, put} = sandbox;
assert.equal(typeof refreshLiveQuotes, 'function');

function text(id){ return element(id).textContent; }

async function scenario(name, {canonical, ptb, polySlug}) {
  fetchImpl = async (url) => {
    if (url.startsWith('/api/live-quotes')) {
      return {ok:true, json: async () => ({
        sources: {},
        reference: {source:'BINANCE', price: 80000, received_at: '2026-10-17T21:31:00+00:00'},
        polymarket: {slug: polySlug, midpoint: 0.62, bid: 0.61, ask: 0.63, received_at: '2026-10-17T21:31:00+00:00'},
      })};
    }
    if (url.startsWith('/api/current-contract')) {
      return {ok:true, json: async () => ({
        status: canonical ? 'OPEN' : 'NO_OPEN_CONTRACT',
        contract: canonical,
        price_to_beat: ptb,
      })};
    }
    if (url.startsWith('/api/contract-price-series')) {
      return {ok:true, json: async () => ({ok:true, status:'OK', points:[{captured_at:'2026-10-17T21:31:00+00:00', midpoint:0.5}]})};
    }
    if (url.startsWith('/api/active-alert')) {
      return {ok:true, json: async () => ({status:'NONE'})};
    }
    throw new Error('unexpected '+url);
  };
  await refreshLiveQuotes();
  return {
    name,
    ptb: text('polyPriceToBeat'),
    ptbMeta: text('polyPriceToBeatMeta'),
    up: text('polyUpPct'),
    down: text('polyDownPct'),
    status: text('polyQuoteStatus'),
    identity: window.__reservoirCanonicalIdentity,
  };
}

(async () => {
  // 1) Open contract, untrusted PTB → UNAVAILABLE
  let r = await scenario('untrusted', {
    canonical: {identity:'cpc-btc-a', question:'BTC', start_at:'2026-10-17T21:30:00+00:00', end_at:'2026-10-17T21:45:00+00:00'},
    ptb: {status:'UNAVAILABLE', value:null, reason:'metadata_source_unverified', contract_id:'cpc-btc-a'},
    polySlug: 'cpc-btc-a',
  });
  assert.match(r.ptb, /UNAVAILABLE/);
  assert.equal(r.up, '—');
  assert.equal(r.down, '—');
  assert.match(r.status, /UNAVAILABLE|US QUOTES/);

  // 2) Trusted AVAILABLE matching identity
  r = await scenario('trusted_match', {
    canonical: {identity:'cpc-btc-a', question:'BTC', start_at:'2026-10-17T21:30:00+00:00', end_at:'2026-10-17T21:45:00+00:00'},
    ptb: {status:'AVAILABLE', value:81453.25, currency:'USD', source_field:'assetPriceTerms.priceToBeat', contract_id:'cpc-btc-a', index_symbol:'BRTI', window_start:'2026-10-17T21:30:00+00:00', window_end:'2026-10-17T21:45:00+00:00'},
    polySlug: 'cpc-btc-a',
  });
  assert.ok(r.ptb.includes('81,453') || r.ptb.includes('81453'), r.ptb);
  assert.equal(r.up, '—'); // still no US quotes

  // 3) Wrong contract_id on PTB → clear
  r = await scenario('wrong_contract', {
    canonical: {identity:'cpc-btc-a', question:'BTC', start_at:'2026-10-17T21:30:00+00:00', end_at:'2026-10-17T21:45:00+00:00'},
    ptb: {status:'AVAILABLE', value:81453.25, currency:'USD', contract_id:'cpc-btc-OTHER', source_field:'assetPriceTerms.priceToBeat'},
    polySlug: 'cpc-btc-a',
  });
  assert.match(r.ptb, /UNAVAILABLE/);

  // 4) Rollover: no open contract clears target
  r = await scenario('rollover_clear', {
    canonical: null,
    ptb: {status:'AVAILABLE', value:81453.25, currency:'USD', contract_id:'cpc-btc-a'},
    polySlug: 'cpc-btc-a',
  });
  assert.match(r.ptb, /UNAVAILABLE/);
  assert.equal(r.identity, null);

  // 5) International slug match still does not fill US UP/DOWN
  r = await scenario('intl_blocked', {
    canonical: {identity:'cpc-btc-a', question:'BTC', start_at:'2026-10-17T21:30:00+00:00', end_at:'2026-10-17T21:45:00+00:00'},
    ptb: {status:'UNAVAILABLE', reason:'metadata_source_unverified'},
    polySlug: 'cpc-btc-a',
  });
  assert.equal(r.up, '—');
  assert.equal(r.down, '—');

  console.log('PASS: PTB lifecycle — untrusted/unavailable, trusted match, wrong-id clear, rollover clear, international blocked from US panel');
})().catch(e => { console.error('FAIL', e); process.exit(1); });
