import assert from 'node:assert/strict';
import {test} from 'node:test';
import {grade, grades, distribution, evaluateQuote, standardMarkets}
  from '../../december-quest-site/autonomous/markets.js';
import Settlement from '../../december-quest-site/autonomous/settlement.js';
import Core from '../../december-quest-site/autonomous/core.js';
import {reference} from './settlement_reference.mjs';
import {compareSlates} from './express_replay.mjs';

const odds = 2.4;
const kickoff = '2026-10-12T19:00:00Z';
const unit = (outcome) => Object.fromEntries(grades.map(row => [row, Number(row === outcome)]));
const market = (id) => standardMarkets.find(row => row.id === id);
const caseList = [
  ['AH:home:-0.5', 0, 1, 'loss', 0],
  ['AH:home:-0.25', 1, 1, 'half_loss', 0.5],
  ['DNB:home:0', 2, 2, 'push', 1],
  ['AH:home:0.25', 1, 1, 'half_win', (odds + 1) / 2],
  ['TG:over:2.75', 3, 1, 'win', odds],
];

test('all five payouts match score grading and the actual settlement entry point', () => {
  for (const [marketId, hg, ag, result, factor] of caseList) {
    const spec = market(marketId);
    assert.equal(grade(spec, hg, ag), result);
    const settle = distribution(spec, [{home: hg, away: ag, probability: 1}]);
    assert.deepEqual(settle, unit(result));
    assert.equal(reference.legOutcomes({odds, settlement: settle})[0].factor, factor);
    const stored = Settlement.resultFromFixture(
      {competition:'EPL', fixture_key:'fixture', home_team:'Chelsea', away_team:'Liverpool', kickoff},
      [{date:'2026-10-12', home:'chelsea', away:'liverpool', kickoff:Date.parse(kickoff), hg, ag}],
      [{id:1, fixture_key:'fixture', model_version:Core.MODEL_VERSION, kickoff,
        generated_at:'2026-10-12T17:00:00Z', evidence:{fixture_timing_status:'confirmed'},
        markets:[{...spec, settlement:settle, baseline:settle}]}],
      Date.parse('2026-10-13T08:00:00Z'));
    assert.equal(stored.details.markets[0].outcome, result);
  }
  const settlement = {loss:0.20, half_loss:0.15, push:0.25, half_win:0.10, win:0.30};
  const referenceEV = reference.independentPortfolio([{fixtureId:'one', odds, settlement}]).expected;
  assert.ok(Math.abs(referenceEV - evaluateQuote(settlement, odds).expected_value) < 1e-6);
});

test('shared adverse ranks change the loss tail while preserving single marginals', () => {
  const settlement = {loss:0.5, half_loss:0, push:0, half_win:0, win:0.5};
  const legs = ['a','b','c'].map(fixtureId => ({fixtureId, odds:2, settlement}));
  assert.equal(reference.stressPortfolio(legs, 0).lossProbability, 0.875);
  assert.equal(reference.stressPortfolio(legs, 1).lossProbability, 0.5);
  assert.equal(reference.stressPortfolio(legs, 1).variance, 16);
  assert.equal(reference.stressPortfolio([legs[0]], 1).expected, 0);
  assert.throws(() => reference.stressPortfolio([legs[0], {...legs[1],fixtureId:' a '}], 1));
  assert.throws(() => reference.stressPortfolio(legs, NaN));
  assert.throws(() => reference.summarize([{p:NaN, factor:1}]));
  assert.throws(() => reference.summarize([{p:1, factor:Infinity}]));
  assert.throws(() => reference.summarize([{p:1.25, factor:2}, {p:-0.25, factor:0}]));
});

const selectedAt = '2026-10-12T17:05:00Z';
const slates = [ {day:'2026-10-12', selectedAt, legs: ['half_win','push','half_loss'].map((actualGrade, index) => ({
  fixtureId:String(index), odds:2, kickoff, actualGrade, settlement:unit(actualGrade),
  quoteVerified:true, virtualPolicyVerified:true, sealedAt:'2026-10-12T17:00:00Z',
  quotePublishedAt:'2026-10-12T16:00:00Z', quoteCapturedAt:'2026-10-12T16:59:00Z',
  resultAvailableAt:'2026-10-12T21:00:00Z',
}))} ];
const options = {asOf:'2026-10-13T00:00:00Z'};

test('single/duo/trio/pass compare the same chronological slate with push and partial outcomes', () => {
  const report = compareSlates(slates, options);
  assert.equal(report.paired_days, 1);
  assert.deepEqual(Object.values(report.byStrategy).map(x=>x.mean_unit_profit), [0.5,0.5,-0.25,0]);
  assert.equal(report.realExecution, false);
});

test('late pricing/early FT and missing evidence remain in the assigned denominator', () => {
  const missing = structuredClone(slates);
  missing[0].legs[1].quoteCapturedAt = '2026-10-12T17:06:00Z';
  const refused = compareSlates(missing, options);
  assert.equal(refused.assigned_days, 1);
  assert.equal(refused.paired_days, 0);
  assert.equal(refused.byStrategy.SINGLE.mean_unit_profit, null);
  missing[0].legs[1] = {...slates[0].legs[1], resultAvailableAt:kickoff};
  assert.equal(compareSlates(missing, options).paired_days, 0);
  assert.equal(compareSlates([], options).status, 'NO_PAIRED_SETTLEMENT_EVIDENCE');
});
