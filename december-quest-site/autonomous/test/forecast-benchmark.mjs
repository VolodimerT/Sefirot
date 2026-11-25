// Run each size in a fresh Node process. Optional --digest hashes entire forecasts separately.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {performance} from 'node:perf_hooks';
import Core from '../core.js';

const size = Number(process.argv[2]);
assert.ok([100, 500, 1000].includes(size));
let requests = 0;
globalThis.fetch = () => { requests++; throw Error('Offline benchmark'); };
const now = Date.UTC(2026, 10, 25);
const teams = Array.from({length: 20}, (_, i) => 'club' + i);
const history = Array.from({length: 380}, (_, i) => {
  const home = i % 20;
  const away = (home + 1 + Math.floor(i / 20)) % 20;
  const when = now - (381 - i) * 86400000;
  return {home: teams[home], away: teams[away], hg: (i * 13 % 17) % 5,
    ag: (i * 7 % 13) % 4, when, date: new Date(when).toISOString().slice(0, 10)};
});
function predict(i) {
  const row = history[i % history.length];
  return Core.forecast({fixture_key: String(i), competition: 'EPL', home_team: row.home,
    away_team: row.away, kickoff: new Date(now + (i + 1) * 3600000).toISOString()}, history, now);
}
for (let i = 0; i < 20; i++) predict(i);
const hash = process.argv.includes('--digest') ? createHash('sha256') : null;
const start = performance.now();
for (let i = 0; i < size; i++) {
  const result = predict(i);
  assert.equal(result.status, 'MODEL_ONLY');
  assert.equal(result.markets.length, 68);
  if (hash) hash.update(JSON.stringify(result));
}
console.log(JSON.stringify({size, ms: Math.round(performance.now() - start),
  maxRSSKiB: process.resourceUsage().maxRSS, requests, digest: hash?.digest('hex')}));
