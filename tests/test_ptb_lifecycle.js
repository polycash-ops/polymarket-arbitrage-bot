'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '..', 'dashboard.py'), 'utf8');
const scriptMatch = source.match(/<script>([\s\S]*?)<\/script>/);
assert.ok(scriptMatch, 'dashboard inline script exists');
const script = scriptMatch[1];
const functionNames = ['isCurrentLiveQuoteResponse', 'canonicalPtbValue', 'updatePtbForContract', 'clearPtb'];
const snippets = functionNames.map(name => {
  const start = script.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} is defined in production dashboard source`);
  let depth = 0, opened = false, end = -1;
  for (let i = script.indexOf('{', start); i < script.length; i++) {
    if (script[i] === '{') { depth++; opened = true; }
    else if (script[i] === '}') { depth--; if (opened && depth === 0) { end = i + 1; break; } }
  }
  assert.notEqual(end, -1, `${name} body is complete`);
  return script.slice(start, end);
}).join('\n');
const calls = [];
const elements = {};
const context = {
  Date,
  Number,
  activeTrustedUsContractId: null,
  put: (id, value) => calls.push([id, value]),
  el: id => (elements[id] ||= { textContent: '', className: '' }),
  usd: value => '$' + value,
};
vm.runInNewContext(snippets + '\nthis.api={isCurrentLiveQuoteResponse,canonicalPtbValue,updatePtbForContract,clearPtb};', context);
const api = context.api;
const now = Date.parse('2026-10-18T12:00:00Z');
const good = {status:'verified', source:'polymarket_us_official', provenance_verified:true, contract_id:'us-1', price_to_beat:67234, observed_at:'2026-10-18T11:59:55Z', contract_start_at:'2026-10-18T11:59:50Z', contract_end_at:'2026-10-18T12:15:00Z'};
assert.equal(api.canonicalPtbValue(good, 'us-1', now), 67234);
assert.equal(api.canonicalPtbValue(good, 'us-2', now), null, 'mismatched contract is rejected');
assert.equal(api.canonicalPtbValue({...good, source:'polymarket_gamma'}, 'us-1', now), null, 'international source is rejected');
assert.equal(api.canonicalPtbValue({...good, observed_at:'2026-10-18T11:58:00Z'}, 'us-1', now), null, 'pre-contract target is rejected');
assert.equal(api.canonicalPtbValue({...good, contract_end_at:'2026-10-18T11:59:59Z'}, 'us-1', now), null, 'expired contract target is rejected');
assert.equal(api.canonicalPtbValue({...good, observed_at:'2026-10-18T12:00:55Z'}, 'us-1', now), null, 'late target observation is rejected');
assert.equal(api.canonicalPtbValue({...good, observed_at:'2026-10-18T12:01:00Z'}, 'us-1', now), null, 'future response is rejected');
assert.equal(api.canonicalPtbValue(good, 'us-1', Date.parse('2026-10-18T12:14:00Z')), 67234, 'fixed PTB remains valid throughout its contract window');
assert.equal(api.isCurrentLiveQuoteResponse(2, 3), false, 'late response cannot overwrite newer request');
assert.equal(api.isCurrentLiveQuoteResponse(3, 3), true);
assert.equal(api.updatePtbForContract('us-1', good, now), 67234);
assert.equal(api.updatePtbForContract('us-2', good, now), null, 'contract rollover clears prior PTB');
assert.ok(calls.some(([id, value]) => id === 'polyWindow' && String(value).includes('unavailable')));
assert.ok(!source.includes('gamma-api.polymarket.com'));
assert.ok(!source.includes('clob.polymarket.com'));
assert.ok(source.includes('NULL::double precision AS price_to_beat'));
console.log('PTB lifecycle tests passed');
