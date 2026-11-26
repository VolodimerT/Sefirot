/* Compare preregistered virtual portfolios on matched days, with abstentions. */
import { reference } from './settlement_reference.mjs';

const GRADES = ['loss', 'half_loss', 'push', 'half_win', 'win'];
const strategies = {SINGLE: 1, DUO: 2, TRIO: 3, PASS: 0};
const timestamp = val => typeof val === 'string' && val.endsWith('Z') ? Date.parse(val) : NaN;

function eligible(leg, selection, studyEnd) {
  if (typeof leg?.fixtureId !== 'string' || !leg.fixtureId.trim()) return false;
  const kickoff = timestamp(leg.kickoff), seal = timestamp(leg.sealedAt);
  const published = timestamp(leg.quotePublishedAt), captured = timestamp(leg.quoteCapturedAt);
  const outcome = timestamp(leg.resultAvailableAt);
  return leg.virtualPolicyVerified === true && leg.quoteVerified === true &&
    published <= captured && captured <= seal && seal <= selection &&
    selection <= kickoff - 20 * 60_000 && kickoff + 90 * 60_000 <= outcome &&
    outcome <= studyEnd && GRADES.includes(leg.actualGrade) &&
    Number.isFinite(leg.odds) && leg.odds > 1 && leg.odds <= 100;
}

export function compareSlates(slates, {asOf, commonRankWeights = [0, 0.25, 0.5, 1]} = {}) {
  const end = timestamp(asOf);
  if (!Array.isArray(slates) || !Number.isFinite(end) || end > Date.now() ||
      !Array.isArray(commonRankWeights) || !commonRankWeights.length || commonRankWeights.length > 20 ||
      commonRankWeights.some(w => !Number.isFinite(w) || w < 0 || w > 1))
    throw Error('invalid settlement replay protocol');
  const days = new Set(), fixtures = new Set(), results = [];
  for (const slate of slates) {
    const selection = timestamp(slate?.selectedAt), legs = slate?.legs;
    if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(slate?.day) || days.has(slate.day) ||
        !Number.isFinite(selection) || selection > end ||
        new Date(selection).toISOString().slice(0, 10) !== slate.day ||
        !Array.isArray(legs) || legs.length !== 3 ||
        legs.some(leg => typeof leg?.fixtureId !== 'string' || !leg.fixtureId.trim()))
      throw Error('invalid preregistered slate');
    days.add(slate.day);
    for (const leg of legs) {
      const id = leg.fixtureId.trim();
      if (fixtures.has(id)) throw Error('fixture repeated in the study');
      fixtures.add(id);
    }
    // Require the same three candidates across all policies, so partial data
    // cannot silently improve one policy's sample. Preserve refusals in coverage.
    if (!legs.every(leg => eligible(leg, selection, end))) {
      results.push({day: slate.day, status: 'PASS_INCOMPLETE_EVIDENCE', strategies: {PASS: {realized: 0}}});
      continue;
    }
    const summary = {};
    for (const [policy, count] of Object.entries(strategies)) {
      const prefix = legs.slice(0, count);
      const realized = prefix.reduce((product, leg) =>
        product * reference.legOutcomes({...leg,settlement: Object.fromEntries(
          GRADES.map(grade => [grade, Number(grade === leg.actualGrade)]))})[0].factor, 1) - 1;
      const stress = count ? commonRankWeights.map(weight => {
        const result = reference.stressPortfolio(prefix, weight);
        return {weight, expected: result.expected, lossProbability: result.lossProbability,
          variance: result.variance};
      }) : [];
      summary[policy] = {realized, stress};
    }
    results.push({day: slate.day, status: 'PAIRED_VIRTUAL_ONLY', strategies: summary});
  }

  const paired = results.filter(row => row.status === 'PAIRED_VIRTUAL_ONLY');
  const byStrategy = {};
  for (const name of Object.keys(strategies)) {
    const realized = paired.map(row => row.strategies[name].realized);
    byStrategy[name] = {compared_days: paired.length, mean_unit_profit: realized.length ?
      realized.reduce((sum, value) => sum + value, 0) / realized.length : null};
  }
  return {status: paired.length ? 'DESCRIPTIVE_ONLY' : 'NO_PAIRED_SETTLEMENT_EVIDENCE',
    assigned_days: slates.length, paired_days: paired.length, byStrategy, results,
    sensitivity: 'COMMON_RANK_STRESS_NOT_ESTIMATED_DEPENDENCE', realExecution: false};
}
