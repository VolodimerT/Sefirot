/* Grade completed 90-minute results against the last eligible seal. */
import Core from './core.js';
import { grade, grades } from './markets.js';
import Validation from './validation.js';

const round = value => Number(value.toFixed(6));
function valid1X2(p) {
  return ['home', 'draw', 'away'].every(key => Number.isFinite(p?.[key]) && p[key] > 0 && p[key] < 1)
    && Math.abs(p.home + p.draw + p.away - 1) < 0.0001;
}
function score(probabilities, observed, keys) {
  return {
    brier: round(keys.reduce((sum, key) => sum + (probabilities[key] - Number(key === observed)) ** 2, 0)),
    logloss: round(-Math.log(Math.max(0.000001, probabilities[observed])))
  };
}
function resultFromFixture(fixture, history, snapshots, now = Date.now()) {
  if (!Object.hasOwn(Core.LEAGUE_FILES, fixture.competition)) return null;
  const kickoff = Date.parse(fixture.kickoff);
  if (!Number.isFinite(kickoff) || kickoff >= now - 3 * 3600000) return null;
  const day = new Date(kickoff).toISOString().slice(0, 10);
  if (day >= new Date(now).toISOString().slice(0, 10)) return null;

  const home = Core.canonical(fixture.competition, fixture.home_team);
  const away = Core.canonical(fixture.competition, fixture.away_team);
  const actual = history.filter(row => row.date === day && row.home === home && row.away === away);
  if (actual.length !== 1) return null;
  const seal = snapshots.find(row => row.fixture_key === fixture.fixture_key &&
    row.model_version === Core.MODEL_VERSION && Date.parse(row.kickoff) === kickoff &&
    Date.parse(row.generated_at) < kickoff && row.evidence?.fixture_timing_status === 'confirmed');
  if (!seal) return null;

  const { hg, ag } = actual[0];
  const result = hg > ag ? 'H' : hg < ag ? 'A' : 'D';
  const observed = { H: 'home', D: 'draw', A: 'away' }[result];
  const model = valid1X2(seal.probabilities) ? Validation.measure(seal.probabilities, result) : null;
  const baseline = seal.evidence.baseline_1x2;
  const aggregateBaseline = valid1X2(baseline) ? Validation.measure(baseline, result) : null;
  const markets = seal.markets.filter(row => row.settlement && row.baseline).map(row => {
    const outcome = grade(row, hg, ag);
    return { id: row.id, market: row.market, pick: row.pick, outcome,
      model: score(row.settlement, outcome, grades), baseline: score(row.baseline, outcome, grades) };
  });
  return {
    fixture_key: fixture.fixture_key, snapshot_id: seal.id, kickoff: fixture.kickoff,
    actual_home_goals: hg, actual_away_goals: ag, result,
    model_brier: model ? round(model.brier) : null,
    model_logloss: model ? round(model.logloss) : null,
    source_quality: 'secondary', source_url: actual[0].source_url,
    details: {
      model_version: seal.model_version, competition: fixture.competition, observed,
      probabilities: model ? seal.probabilities : null, baseline: aggregateBaseline, markets,
      decision: seal.evidence.decision, sealed_at: seal.generated_at
    }
  };
}
export default { resultFromFixture };
