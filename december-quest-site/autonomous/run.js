import Core from './core.js';
import Validation from './validation.js';
import Settlement from './settlement.js';
import { collectGateway } from './gateway.js';

const provider = 'https://football-data.co.uk';
const kyiv = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Kyiv', dateStyle: 'short', timeStyle: 'short' });
const hour = 3600000;
const fixtureLimit = 300;
const columns = 'fixture_key,competition,home_team,away_team,kickoff,source_url,source_quality,timing_status,checked_at';
const listPath = 'sefirot_december_quest_fixtures?select=' + columns + '&order=kickoff.asc,fixture_key.asc&limit=' + (fixtureLimit + 1);

function questFixture(fixture) {
  if (!Number.isFinite(Date.parse(fixture.kickoff))) return false;
  const stamp = kyiv.format(new Date(fixture.kickoff));
  return stamp.startsWith('2026-12-') && stamp.slice(-5) >= '21:00' && stamp.slice(-5) <= '23:00';
}
function duplicates(fixtures) {
  const groups = new Map();
  const found = new Set();
  for (const fixture of fixtures) {
    const key = [fixture.competition,
      ...['home_team','away_team'].map(side => Core.canonical(fixture.competition,fixture[side])).sort()].join('|');
    const previous = groups.get(key) || [];
    for (const row of previous) {
      if (Math.abs(Date.parse(row.kickoff) - Date.parse(fixture.kickoff)) > 36 * hour) continue;
      found.add(row.fixture_key);
      found.add(fixture.fixture_key);
    }
    previous.push(fixture);
    groups.set(key, previous);
  }
  return found;
}

function fixtureDecision(fixture, rows, packet, cutoff, duplicate) {
  const { current, gateway, weekly, check } = packet;
  const stamp = Date.parse(fixture.checked_at);
  const official = fixture.timing_status === 'confirmed' && fixture.source_quality === 'official' &&
    Number.isFinite(stamp) && stamp <= cutoff && cutoff - stamp <= 72 * hour;
  const inWeeklyWindow = weekly?.ok && weekly.observedAt <= cutoff &&
    cutoff - weekly.observedAt <= hour && Date.parse(fixture.kickoff) - cutoff <= 48 * hour;
  const weeklyCheck = inWeeklyWindow ? Core.weeklyKickoff(weekly.records,fixture) : null;
  const conflicting = check?.status === 'KICKOFF_CONFLICT' ||
    ['KICKOFF_CONFLICT','KICKOFF_AMBIGUOUS'].includes(weeklyCheck?.status);
  const crossChecked = weeklyCheck?.status === 'MATCH' &&
    fixture.timing_status === 'confirmed' && fixture.source_quality === 'official';
  const kickoffGate = duplicate ? 'DUPLICATE_FIXTURE'
    : conflicting ? 'KICKOFF_CONFLICT'
    : check?.status === 'CONFIRMED' || official || crossChecked ? 'CONFIRMED'
    : 'DATA_MISSING';
  const forecast = Core.forecast(fixture, current && !duplicate && !conflicting ? rows : [], cutoff);
  const row = weekly?.ok && !duplicate && !conflicting
    ? Core.attachQuotes(forecast, weekly.records, fixture, weekly.observedAt) : forecast;
  const reasons = [
    ...(kickoffGate === 'CONFIRMED' ? [] : [kickoffGate === 'DATA_MISSING' ? 'KICKOFF_UNVERIFIED' : kickoffGate]),
    ...(!Core.LEAGUE_FILES[fixture.competition] ? ['UNSUPPORTED_LEAGUE']
      : !current ? ['HISTORY_DATA_MISSING']
      : !row.markets.length && !duplicate && !conflicting ? ['INSUFFICIENT_TEAM_HISTORY'] : []),
    row.evidence.quote_found ? 'QUOTE_TIMESTAMP_UNVERIFIED' : 'ODDS_DATA_MISSING',
    ...(check?.lineups?.confirmed_teams === 2 ? [] : ['LINEUPS_DATA_MISSING']),
    'TACTICAL_FIT_UNVERIFIED', 'PUBLIC_TRAP_UNVERIFIED', 'DEATH_TEST_UNVERIFIED',
    ...(row.evidence.quote_found&&row.best_candidate.conditional_ev_pct<=0?['NO_EDGE']:[]),
    ...(row.evidence.quote_found&&row.best_candidate.death_test==='FAIL_CONDITIONAL'?['DEATH_TEST_FAIL']:[])
  ];
  if (duplicate || kickoffGate === 'KICKOFF_CONFLICT') row.risk_class = 'RED';
  row.notes = reasons.join(', ');
  row.evidence = {
    ...row.evidence, home_name: fixture.home_team, away_name: fixture.away_team,
    fixture_source: fixture.source_url, fixture_checked_at: fixture.checked_at,
    fixture_timing_status: fixture.timing_status, kickoff_gate: kickoffGate,
    kickoff_confirmation: kickoffGate !== 'CONFIRMED' ? null
      : check?.status === 'CONFIRMED' ? 'GATEWAY'
      : official ? 'OFFICIAL_CALENDAR' : 'OFFICIAL_CALENDAR_AND_WEEKLY_CSV',
    weekly_kickoff: weeklyCheck ? { ...weeklyCheck, observed_at: new Date(weekly.observedAt).toISOString(),
      source: weekly.url } : null,
    gateway_status: gateway.status, gateway_reason: gateway.reason, gateway_fixture_id: check?.fixture_id,
    gateway_observed_at: check?.observed_at, lineups: check?.lineups, injuries: check?.injuries,
    xg_status: row.evidence.xg?.home_at_home.matches && row.evidence.xg?.away_away.matches
      ? 'HISTORICAL_ONLY' : 'DATA_MISSING', pass_reasons: reasons, upstream_sources: packet.sources
  };
  return row;
}

export async function execute({ rest, csv, gateway = (fixtures, now) => collectGateway(null, null, fixtures, now), clock = Date.now }) {
  const started = clock();
  const recent = await rest('sefirot_december_quest_auto_runs?select=started_at,run_status,model_version&order=started_at.desc&limit=1');
  if (recent[0]?.run_status === 'OK' && recent[0].model_version === Core.MODEL_VERSION &&
      started - Date.parse(recent[0].started_at) < 6 * hour) return { skipped: 'RUN_WITHIN_SIX_HOURS' };
  const calendar = await rest(listPath);
  if (!Array.isArray(calendar) || calendar.length > fixtureLimit) throw Error('FIXTURE_SOURCE_LIMIT');
  const all = calendar.filter(questFixture);
  const duplicate = duplicates(all);
  const upcoming = all.filter(fixture => Date.parse(fixture.kickoff) > started + 30 * 60000);
  const leagues = [...new Set(all.map(row => row.competition))].filter(key => Object.hasOwn(Core.LEAGUE_FILES, key));
  const urls = leagues.flatMap(code => ['2627', '2526'].map(season => ({
    code, season, url: provider + '/mmz4281/' + season + '/' + Core.LEAGUE_FILES[code] + '.csv'
  })));
  if (leagues.length) urls.push({ code: 'weekly', season: 'weekly', url: provider + '/fixtures.csv' });

  const [sources, gatewayResult] = await Promise.all([
    Promise.all(urls.map(async row => {
      try {
        const text = await csv(row.url);
        const records = Core.parseCsv(text);
        if (row.code !== 'weekly' && !records.some(record =>
          record.Div === Core.LEAGUE_FILES[row.code] && Core.csvDate(record.Date) &&
          /^\d+$/.test(record.FTHG) && /^\d+$/.test(record.FTAG))) throw Error('EMPTY_RESULT_SOURCE');
        return { ...row, text, records, ok: true, observedAt: clock() };
      } catch (error) {
        return { ...row, ok: false, error: String(error.message).slice(0, 80) };
      }
    })),
    gateway(upcoming.filter(fixture => !duplicate.has(fixture.fixture_key)), started)
  ]);
  const cutoff = clock();
  const errors = sources.filter(pack => !pack.ok).map(pack => pack.code + ':' + pack.season + ' ' + pack.error);
  if (gatewayResult.reason && gatewayResult.reason !== 'GATEWAY_NOT_CONFIGURED') errors.push(gatewayResult.reason);
  const history = new Map();
  for (const code of leagues) {
    const unique = new Map(), conflicts = new Set();
    for (const pack of sources.filter(pack => pack.code === code && pack.ok)) {
      for (const row of Core.resultsFromCsv(pack.text, code, cutoff)) {
        const key = [row.date, row.home, row.away].join('|');
        const prior = unique.get(key);
        if (prior && (prior.hg !== row.hg || prior.ag !== row.ag || prior.kickoff !== row.kickoff)) conflicts.add(key);
        unique.set(key, { ...row, source_url: pack.url });
      }
    }
    for (const key of conflicts) unique.delete(key);
    if (conflicts.size) errors.push(code + ':CONFLICTING_RESULTS');
    history.set(code, [...unique.values()]);
  }
  const hasCurrent = code => sources.some(pack => pack.code === code && pack.season === '2627' && pack.ok) &&
    history.get(code)?.some(row => cutoff - row.when < 35 * 24 * hour);
  const weekly = sources.find(pack => pack.code === 'weekly');
  const validations = leagues.filter(hasCurrent).map(code => Validation.backtest(code, history.get(code), cutoff));
  const validation = new Map(validations.map(row => [row.competition, row]));
  const forecasts = upcoming.filter(fixture => Date.parse(fixture.kickoff) > cutoff + 20 * 60000).map(fixture => {
    const row = fixtureDecision(fixture, history.get(fixture.competition), {
      current: hasCurrent(fixture.competition), weekly, gateway: gatewayResult,
      check: gatewayResult.fixtures.get(fixture.fixture_key),
      sources: sources.filter(pack => pack.code === fixture.competition).map(pack => ({
        url: pack.url, ok: pack.ok, observed_at: pack.ok ? new Date(pack.observedAt).toISOString() : null
      }))
    }, cutoff, duplicate.has(fixture.fixture_key));
    row.evidence.walk_forward = validation.get(fixture.competition) || null;
    return row;
  });

  const past = all.filter(fixture => !duplicate.has(fixture.fixture_key) && hasCurrent(fixture.competition) &&
    Date.parse(fixture.kickoff) < cutoff - 3 * hour);
  const settled = [];
  if (past.length) {
    const snapshots = await rest('rpc/dq_pending_predictor_snapshots', { method: 'POST', body: JSON.stringify({
      p_fixture_keys: past.map(row => row.fixture_key), p_model_version: Core.MODEL_VERSION
    }) });
    const index = new Map(snapshots.map(snapshot => [snapshot.fixture_key, snapshot]));
    for (const fixture of past) {
      const snapshot = index.get(fixture.fixture_key);
      if (!snapshot) continue;
      const result = Settlement.resultFromFixture(fixture, history.get(fixture.competition), [snapshot], cutoff);
      if (result) settled.push(result);
    }
  }

  const success = sources.filter(pack => pack.ok).length;
  const run = { started_at: new Date(started).toISOString(), model_version: Core.MODEL_VERSION,
    fetch_ok: success, sources_attempted: urls.length, errors: errors.slice(0,20),
    run_status: errors.length ? success ? 'PARTIAL' : 'SOURCE_ERROR' : 'OK' };
  const committed = await rest('rpc/dq_commit_predictor_run', { method: 'POST', body: JSON.stringify({
    p_run: run, p_forecasts: forecasts, p_validation: validations, p_settlements: settled
  }) });
  return { ...committed, status: run.run_status, model_version: Core.MODEL_VERSION, sources_ok: success,
    sources_attempted: urls.length, source_errors: run.errors, gateway: gatewayResult.status, wagers_executed: 0 };
}

export { questFixture, duplicates };
