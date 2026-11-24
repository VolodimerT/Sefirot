/* Optional reads through the existing gateway. Its own reservation governs every call. */
import Core from './core.js';

const leagues = { EPL: 39, LALIGA: 140, SERIEA: 135, BUNDES: 78, LIGUE1: 61 };
const sameTeam = (league, provider, calendar) =>
  Core.canonical(league, provider) === Core.canonical(league, calendar);

export function matchFixture(fixture, records) {
  const kickoff = Date.parse(fixture.kickoff);
  const matches = records.filter(row =>
    row.league?.id === leagues[fixture.competition] &&
    Number.isSafeInteger(row.fixture?.id) && row.fixture.id > 0 &&
    ['NS', 'TBD'].includes(row.fixture.status?.short) &&
    sameTeam(fixture.competition, row.teams?.home?.name, fixture.home_team) &&
    sameTeam(fixture.competition, row.teams?.away?.name, fixture.away_team));
  const row = matches.length === 1 ? matches[0] : null;
  if (!row) return { status: 'DATA_MISSING' };
  if (row.fixture.status.short === 'TBD' || Date.parse(row.fixture.date) !== kickoff) {
    return { status: 'KICKOFF_CONFLICT' };
  }
  return { status: 'CONFIRMED', fixture_id: row.fixture.id };
}

export async function collectGateway(project, token, candidates, now, fetcher = fetch) {
  const out = new Map();
  if (!project || !token) return { status: 'DATA_MISSING', reason: 'GATEWAY_NOT_CONFIGURED', fixtures: out };
  const grouped = new Map();
  for (const fixture of candidates) {
    const ahead = Date.parse(fixture.kickoff) - now;
    if (!Object.hasOwn(leagues, fixture.competition) || ahead <= 0 || ahead > 8 * 3600000) continue;
    const key = fixture.competition + '|' + fixture.kickoff.slice(0, 10);
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(fixture);
  }
  let remaining = 12;
  const get = async (endpoint, params) => {
    remaining--;
    const response = await fetcher(project + '/functions/v1/sefirot-sports-gateway', {
      method: 'POST', signal: AbortSignal.timeout(12000),
      headers: { 'Content-Type': 'application/json', 'x-sefirot-runner-token': token },
      body: JSON.stringify({ endpoint, params })
    });
    const body = await response.json();
    if (!response.ok || body?.ok !== true) {
      if (body?.error === 'SHARED_BUDGET_STOP') throw Error('GATEWAY_BUDGET_STOP');
      throw Error('GATEWAY_SOURCE_ERROR');
    }
    if (!Array.isArray(body.data?.response) || !Number.isFinite(Date.parse(body.received_at))) {
      throw Error('GATEWAY_SOURCE_SHAPE');
    }
    return { records: body.data.response, observed_at: body.received_at };
  };
  try {
    for (const group of grouped.values()) {
      if (remaining < 1) break;
      const sample = group[0];
      const gameList = await get('fixtures', { league: String(leagues[sample.competition]),
        season: '2026', date: sample.kickoff.slice(0, 10) });
      for (const fixture of group) {
        const check = matchFixture(fixture, gameList.records);
        out.set(fixture.fixture_key, { ...check, observed_at: gameList.observed_at });
      }
    }
    for (const game of candidates) {
      if (remaining < 2) break;
      const entry = out.get(game.fixture_key);
      if (entry?.status !== 'CONFIRMED') continue;
      const params = { fixture: String(entry.fixture_id) };
      const injuries = await get('injuries', params);
      entry.injuries = { count: injuries.records.length, observed_at: injuries.observed_at, published: injuries.records.length > 0 };
      if (Date.parse(game.kickoff) - now > 90 * 60000) continue;
      const lineups = await get('fixtures/lineups', params);
      entry.lineups = { confirmed_teams: lineups.records.filter(row => row.startXI?.length === 11).length,
        observed_at: lineups.observed_at };
    }
    return { status: grouped.size ? 'OK' : 'WAITING_WINDOW', fixtures: out };
  } catch (error) {
    return { status: 'DATA_MISSING', reason: error.message === 'GATEWAY_BUDGET_STOP' ? error.message : 'GATEWAY_SOURCE_ERROR', fixtures: out };
  }
}
