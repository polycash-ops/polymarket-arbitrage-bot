'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'dashboard.py'), 'utf8');
const scriptMatch = source.match(/<script>([\s\S]*?)<\/script>/);
assert.ok(scriptMatch, 'dashboard inline script exists');
const script = scriptMatch[1];
const functionNames = ['expectedCurrentUsContractId', 'isCurrentLiveQuoteResponse', 'canonicalPtbValue', 'updatePtbForContract', 'clearPtb'];
const snippets = functionNames.map(name => {
  const start = script.indexOf('function ' + name + '(');
  assert.notEqual(start, -1, name + ' is defined in production dashboard source');
  let depth = 0, opened = false, end = -1;
  for (let i = script.indexOf('{', start); i < script.length; i++) {
    if (script[i] === '{') { depth++; opened = true; }
    else if (script[i] === '}') { depth--; if (opened && depth === 0) { end = i + 1; break; } }
  }
  assert.notEqual(end, -1, name + ' body is complete');
  return script.slice(start, end);
}).join('\n');
const calls = [];
const elements = {};
const context = {
  Date, Number, activeTrustedUsContractId: null,
  put: (id, value) => calls.push([id, value]),
  el: id => (elements[id] ||= { textContent: '', className: '' }),
  usd: value => '$' + value,
  fmtTime: value => String(value),
};
vm.runInNewContext(snippets + '\nthis.api={expectedCurrentUsContractId,isCurrentLiveQuoteResponse,canonicalPtbValue,updatePtbForContract,clearPtb};', context);
const api = context.api;
const now = Date.parse('2026-10-18T12:00:00Z');
const good = {status:'verified', source:'polymarket_us_official', provenance_verified:true, contract_id:'btc-updown-15m-2026-10-18-1200z', price_to_beat:67234, retrieved_at:'2026-10-18T12:00:00Z', contract_start_at:'2026-10-18T12:00:00Z', contract_end_at:'2026-10-18T12:15:00Z'};
assert.equal(api.expectedCurrentUsContractId(now), 'btc-updown-15m-2026-10-18-1200z');
assert.equal(api.canonicalPtbValue(good, good.contract_id, now), 67234);
assert.equal(api.canonicalPtbValue(good, 'btc-updown-15m-2026-10-18-1215z', now), null, 'mismatched contract is rejected');
assert.equal(api.canonicalPtbValue({...good, source:'polymarket_gamma'}, good.contract_id, now), null, 'international source is rejected');
assert.equal(api.canonicalPtbValue({...good, contract_end_at:'2026-10-18T12:14:59Z'}, good.contract_id, now), null, 'wrong window length is rejected');
assert.equal(api.canonicalPtbValue({...good, contract_end_at:'2026-10-18T11:59:59Z'}, good.contract_id, now), null, 'expired contract target is rejected');
assert.equal(api.canonicalPtbValue({...good, retrieved_at:'2026-10-18T11:59:00Z'}, good.contract_id, now), null, 'stale API response is rejected');
assert.equal(api.canonicalPtbValue({...good, retrieved_at:'2026-10-18T12:13:59Z'}, good.contract_id, Date.parse('2026-10-18T12:14:00Z')), 67234, 'fixed PTB remains valid when freshly re-read late in its contract window');
assert.equal(api.isCurrentLiveQuoteResponse(2, 3), false, 'late response cannot overwrite newer request');
assert.equal(api.isCurrentLiveQuoteResponse(3, 3), true);
assert.equal(api.updatePtbForContract(good.contract_id, good, now), 67234);
assert.equal(api.updatePtbForContract('btc-updown-15m-2026-10-18-1215z', good, now), null, 'contract rollover clears prior PTB');
assert.ok(calls.some(([id, value]) => id === 'polyWindow' && String(value).includes('unavailable')));
assert.ok(!source.includes('gamma-api.polymarket.com'));
assert.ok(!source.includes('clob.polymarket.com'));
assert.ok(source.includes('NULL::double precision AS price_to_beat'));
console.log('PTB lifecycle tests passed');
