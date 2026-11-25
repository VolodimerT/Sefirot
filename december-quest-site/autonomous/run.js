import Core from './core.js';
import Validation from './validation.js';
import Settlement from './settlement.js';
import { collectGateway } from './gateway.js';
import { attachOdds, collectTimestampedOdds, oddsHorizonHours } from './odds-gateway.js';
import { historyProfile } from './history.js';
import { backupStatus, resultKey } from './result-backups.js';

const provider = 'https://football-data.co.uk';
const kyiv = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Kyiv', dateStyle: 'short', timeStyle: 'short' });
const hour = 3600000;
const historyAge = 35 * 24 * hour;
const currentSeason = '2627';
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

function oddsScope(fixture, cutoff, modeled, kickoffGate) {
  const distance=Date.parse(fixture.kickoff)-cutoff;
  if(distance>oddsHorizonHours*hour)return 'OUTSIDE_WINDOW';
  if(!(distance>0))return 'PAST_KICKOFF';
  if(!modeled)return 'MODEL_UNAVAILABLE';
  return kickoffGate==='CONFIRMED'&&fixture.timing_status==='confirmed'?'ELIGIBLE':'KICKOFF_UNVERIFIED';
}

function fixtureDecision(fixture, rows, packet, cutoff, duplicate) {
  const { current, gateway, weekly, odds } = packet;
  const fresh = entry => {
    const stamp=Date.parse(entry?.observed_at);
    return stamp<=cutoff&&cutoff-stamp<=hour;
  };
  const check = fresh(packet.check) ? packet.check : null;
  const lineups = fresh(check?.lineups) ? check.lineups : null;
  const injuries = fresh(check?.injuries) ? check.injuries : null;
  const stamp = Date.parse(fixture.checked_at);
  const official = fixture.timing_status === 'confirmed' && fixture.source_quality === 'official' &&
    Number.isFinite(stamp) && stamp <= cutoff && cutoff - stamp <= 72 * hour;
  const inWeeklyWindow = weekly?.ok && Number.isFinite(weekly.publishedAt) &&
    weekly.publishedAt <= weekly.observedAt && cutoff - weekly.publishedAt <= 12 * hour && weekly.observedAt <= cutoff &&
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
  const usableHistory = current && !duplicate && !conflicting;
  const forecast = Core.forecast(fixture, usableHistory ? rows : [], cutoff);
  const teamHistory = usableHistory ? historyProfile(rows, Core.canonical(fixture.competition,fixture.home_team),
    Core.canonical(fixture.competition,fixture.away_team),new Date(fixture.kickoff).toISOString(),cutoff,
    check?.status==='CONFIRMED' ? check.referee : null) : null;
  const row = !duplicate && !conflicting
    ? attachOdds(forecast, weekly, fixture, odds, kickoffGate === 'CONFIRMED') : forecast;
  const candidate = row.best_candidate;
  const scope=oddsScope(fixture,cutoff,Boolean(row.markets.length),kickoffGate);
  const fallbackUsed=packet.sources.some(source=>source.use_status==='FALLBACK'&&source.selected);
  const historySource=fallbackUsed?'League results from the selected upstream sources':row.evidence.source;
  if(teamHistory&&fallbackUsed)teamHistory.source=packet.sources.filter(source=>source.selected).map(source=>source.url);

  const reasons = [
    ...(kickoffGate === 'CONFIRMED' ? [] : [kickoffGate === 'DATA_MISSING' ? 'KICKOFF_UNVERIFIED' : kickoffGate]),
    ...(!Core.LEAGUE_FILES[fixture.competition] ? ['UNSUPPORTED_LEAGUE']
      : !current ? ['HISTORY_DATA_MISSING']
      : !row.markets.length && !duplicate && !conflicting ? ['INSUFFICIENT_TEAM_HISTORY'] : []),
    ...(row.evidence.quote_price_verified ? [] : [row.evidence.quote_found ? 'QUOTE_TIMESTAMP_UNVERIFIED' : scope==='OUTSIDE_WINDOW' ? 'ODDS_OUTSIDE_WINDOW' : 'ODDS_DATA_MISSING']),
    ...(lineups?.confirmed_teams === 2 ? [] : ['LINEUPS_DATA_MISSING']),
    'TACTICAL_FIT_UNVERIFIED', 'PUBLIC_TRAP_UNVERIFIED', 'DEATH_TEST_UNVERIFIED',
    ...(row.evidence.quote_found && (candidate.ev ?? candidate.conditional_ev_pct) <= 0 ? ['NO_EDGE'] : []),
    ...(candidate?.death_test==='FAIL_CONDITIONAL'?['DEATH_TEST_FAIL']:[])
  ];
  if (duplicate || kickoffGate === 'KICKOFF_CONFLICT') row.risk_class = 'RED';
  row.notes = reasons.join(', ');
  row.evidence = {
    ...row.evidence, source:historySource, team_history:teamHistory, history_fallback:fallbackUsed, home_name: fixture.home_team, away_name: fixture.away_team,
    fixture_source: fixture.source_url, fixture_checked_at: fixture.checked_at,
    fixture_timing_status: fixture.timing_status, kickoff_gate: kickoffGate,
    kickoff_confirmation: kickoffGate !== 'CONFIRMED' ? null
      : check?.status === 'CONFIRMED' ? 'GATEWAY'
      : official ? 'OFFICIAL_CALENDAR' : 'OFFICIAL_CALENDAR_AND_WEEKLY_CSV',
    weekly_kickoff: weeklyCheck ? { ...weeklyCheck, observed_at: new Date(weekly.observedAt).toISOString(),
      source: weekly.url } : null,
    gateway_status: gateway.status, gateway_reason: gateway.reason, gateway_fixture_id: check?.fixture_id,
    odds_gateway_status: odds.status, odds_publication_scope:scope,
    context_availability:{
      lineups:lineups?.confirmed_teams===2?'CONFIRMED':'UNKNOWN',
      injuries:injuries?.published?'REPORTED':'UNKNOWN',
      referee:check?.referee&&check.status==='CONFIRMED'?'ASSIGNED':'UNKNOWN',
      xg:row.evidence.xg?.home_at_home.matches&&row.evidence.xg?.away_away.matches?'HISTORICAL':'UNKNOWN',
      suspensions:'UNKNOWN', tactical_scheme:'UNKNOWN', tournament_context:'UNKNOWN'
    },
    gateway_observed_at: check?.observed_at, lineups, injuries,
    xg_status: row.evidence.xg?.home_at_home.matches && row.evidence.xg?.away_away.matches
      ? 'HISTORICAL_ONLY' : 'DATA_MISSING', pass_reasons: reasons, upstream_sources: packet.sources
  };
  return row;
}

export async function execute(options) {
  const {rest} = options;
  const claim = await rest('rpc/dq_claim_predictor_run', {method:'POST',
    body:JSON.stringify({p_model_version:Core.MODEL_VERSION})});
  if (claim?.skipped) return {...claim, model_version:Core.MODEL_VERSION};
  const started = Date.parse(claim?.checked_at);
  if (!claim?.token || !Number.isFinite(started)) throw Error('INVALID_RUN_CLAIM');
  try {
    return await runClaimed(options, started, claim.token);
  } catch (error) {
    // A disconnected caller may have committed. Only this token can be released.
    try {
      await rest('rpc/dq_release_predictor_run', {method:'POST',body:JSON.stringify({p_token:claim.token})});
    } catch { /* DB expiry recovers a lost release. Preserve the original error. */ }
    throw error;
  }
}

async function runClaimed({ rest, csv, gateway = (fixtures, now) => collectGateway(null, null, fixtures, now),
  odds = (fixtures, now) => collectTimestampedOdds(fixtures, now, null), backup = null, clock = Date.now }, started, token) {
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

  const eligible = upcoming.filter(fixture => !duplicate.has(fixture.fixture_key));
  const [sources, gatewayResult, oddsResult] = await Promise.all([
    Promise.all(urls.map(async row => {
      try {
        const input = await csv(row.url);
        const text = typeof input === 'string' ? input : input.text;
        const publishedAt = typeof input === 'string' ? null : input.publishedAt;
        const records = Core.parseCsv(text);
        if (row.code !== 'weekly' && !records.some(record =>
          record.Div === Core.LEAGUE_FILES[row.code] && Core.csvDate(record.Date) &&
          /^\d+$/.test(record.FTHG) && /^\d+$/.test(record.FTAG))) throw Error('EMPTY_RESULT_SOURCE');
        return { ...row, records, ok: true, publishedAt, observedAt: clock() };
      } catch (error) {
        return { ...row, ok: false, error: String(error.message).slice(0, 80) };
      }
    })),
    gateway(eligible, started), odds(eligible, started)
  ]);
  const initialCutoff = clock();
  const errors = sources.filter(pack => !pack.ok).map(pack => pack.code + ':' + pack.season + ' ' + pack.error);
  if (gatewayResult.reason && gatewayResult.reason !== 'GATEWAY_NOT_CONFIGURED') errors.push(gatewayResult.reason);
  for (const {league, error} of oddsResult.errors || []) errors.push('ODDS:' + league + ':' + error);
  const primaryHistory = new Map(), unresolved = new Map();
  const sourceFacts = new Map();
  for (const code of leagues) {
    const unique = new Map(), conflicts = new Set();
    for (const pack of sources.filter(pack => pack.code === code && pack.ok)) {
      const rows = Core.resultsFromRecords(pack.records, code, initialCutoff);
      const latest = rows.reduce((date,row)=>Math.max(date,row.when),-Infinity);
      sourceFacts.set(pack.url,{completed_rows:rows.length,
        latest_result_at:Number.isFinite(latest)?new Date(latest).toISOString().slice(0,10):null});
      for (const row of rows) {
        const key = resultKey(row);
        const prior = unique.get(key);
        if (prior && (prior.hg !== row.hg || prior.ag !== row.ag || prior.kickoff !== row.kickoff)) conflicts.add(key);
        if (!prior || pack.season==='2627') unique.set(key, { ...row, season:pack.season, source_url:pack.url });
      }
    }
    for (const key of conflicts) unique.delete(key);
    if (conflicts.size) errors.push(code + ':CONFLICTING_RESULTS');
    primaryHistory.set(code,[...unique.values()]);
    unresolved.set(code,conflicts);
  }
  const history=new Map(primaryHistory);
  const freshSeason=(rows,at)=>rows.some(row=>row.season===currentSeason&&at-row.when<historyAge);
  const requests=backup?leagues.flatMap(code=>['2627','2526']
    .filter(season=>season===currentSeason?!freshSeason(primaryHistory.get(code),initialCutoff)
      :!primaryHistory.get(code).some(row=>row.season===season))
    .map(season=>({code,season}))):[];
  const alternativePacks=await Promise.all(requests.map(({code,season})=>backup(code,season,initialCutoff)));
  const cutoff=clock();
  for(const [i,pack] of alternativePacks.entries()){
    const {code,season}=requests[i];
    const primary=primaryHistory.get(code);
    const status=backupStatus(pack,primary,cutoff);
    if(pack){
      const completed=pack.rows||[];
      const newest=completed.reduce((mostRecent,row)=>row.date>mostRecent?row.date:mostRecent,'');
      sources.push({...pack,use_status:status});
      sourceFacts.set(pack.url,{completed_rows:completed.length,expected_games:pack.expectedGames,latest_result_at:newest||null});
    }
    if(status==='FALLBACK'){
      const safe=pack.rows.filter(row=>!unresolved.get(code).has(resultKey(row))).map(row=>({...row,source_url:pack.url}));
      if(!safe.length){errors.push(code+':'+season+' BACKUP_NO_UNCONTESTED_RESULTS');continue;}
      history.set(code,[...history.get(code).filter(row=>row.season!==season),...safe]);
      errors.push(code+':'+season+' HISTORY_BACKUP_USED');
    }else{
      errors.push(code+':'+season+' HISTORY_BACKUP_'+status);
    }
  }
  const hasCurrent=code=>freshSeason(history.get(code)||[],cutoff);
  const weekly = sources.find(pack => pack.code === 'weekly');
  // Keep the published baseline and official FT timeline on the primary data.
  const validations = leagues.filter(code=>freshSeason(primaryHistory.get(code),cutoff)&&primaryHistory.get(code).some(row=>row.season==='2526'))
    .map(code => Validation.backtest(code, primaryHistory.get(code), cutoff));
  const validation = new Map(validations.map(row => [row.competition, row]));
  const forecasts = upcoming.filter(fixture => Date.parse(fixture.kickoff) > cutoff + 20 * 60000).map(fixture => {
    const row = fixtureDecision(fixture, history.get(fixture.competition), {
      current: hasCurrent(fixture.competition), weekly, gateway: gatewayResult, odds: oddsResult,
      check: gatewayResult.fixtures.get(fixture.fixture_key),
      sources: sources.filter(pack => pack.code === fixture.competition).map(pack => ({
        url: pack.url, season:pack.season, ok:pack.ok,
        observed_at:pack.ok ? new Date(pack.observedAt).toISOString() : null,
        published_at:Number.isFinite(pack.publishedAt) && pack.publishedAt<=pack.observedAt
          ? new Date(pack.publishedAt).toISOString() : null,
        ...sourceFacts.get(pack.url), error:pack.error??null, cached:pack.cached??false,
        use_status:pack.use_status??(pack.ok?'PRIMARY':'UNAVAILABLE'),
        selected:history.get(fixture.competition)?.some(row=>row.source_url===pack.url)??false
      }))
    }, cutoff, duplicate.has(fixture.fixture_key));
    row.evidence.walk_forward = validation.get(fixture.competition) || null;
    return row;
  });

  const past = all.filter(fixture => !duplicate.has(fixture.fixture_key) && freshSeason(primaryHistory.get(fixture.competition)||[],cutoff) &&
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
      const result = Settlement.resultFromFixture(fixture, primaryHistory.get(fixture.competition), [snapshot], cutoff);
      if (result) settled.push(result);
    }
  }

  const success = sources.filter(pack => pack.ok).length;
  const run = { started_at: new Date(started).toISOString(), model_version: Core.MODEL_VERSION,
    fetch_ok: success, sources_attempted: urls.length + requests.length, errors: errors.slice(0,20),
    run_status: errors.length ? success ? 'PARTIAL' : 'SOURCE_ERROR' : 'OK' };
  const committed = await rest('rpc/dq_finish_predictor_run', { method: 'POST', body: JSON.stringify({
    p_token: token, p_run: run, p_forecasts: forecasts, p_validation: validations, p_settlements: settled
  }) });
  return { ...committed, status: run.run_status, model_version: Core.MODEL_VERSION, sources_ok: success,
    sources_attempted: urls.length + requests.length, source_errors: run.errors, gateway: gatewayResult.status,
    odds_gateway: oddsResult.status, verified_odds_fixtures: forecasts.filter(row=>row.evidence.quote_price_verified).length,
    odds_eligible_fixtures:forecasts.filter(row=>row.evidence.odds_publication_scope==='ELIGIBLE').length,
    odds_outside_publication_window:forecasts.filter(row=>row.evidence.odds_publication_scope==='OUTSIDE_WINDOW').length,
    fixtures_using_history_backup:forecasts.filter(row=>row.evidence.history_fallback).length,
    wagers_executed: 0 };
}

export { questFixture, duplicates, oddsScope };
