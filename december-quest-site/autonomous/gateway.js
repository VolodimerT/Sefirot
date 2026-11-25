/* Optional reads through the existing gateway. Its own reservation governs every call. */
import Core from './core.js';

const leagues = { EPL: 39, LALIGA: 140, SERIEA: 135, BUNDES: 78, LIGUE1: 61 };
const sameTeam = (league, provider, calendar) =>
  Core.canonical(league, provider) === Core.canonical(league, calendar);

export function matchFixture(fixture, records, leagueIds=leagues, same=sameTeam) {
  const kickoff = Date.parse(fixture.kickoff);
  const matches = records.filter(row =>
    row.league?.id === leagueIds[fixture.competition] &&
    Number.isSafeInteger(row.fixture?.id) && row.fixture.id > 0 &&
    same(fixture.competition, row.teams?.home?.name, fixture.home_team) &&
    same(fixture.competition, row.teams?.away?.name, fixture.away_team));
  const row = matches.length === 1 ? matches[0] : null;
  if (!row) return { status: 'DATA_MISSING' };
  if (row.fixture.status?.short !== 'NS' || Date.parse(row.fixture.date) !== kickoff) {
    return { status: 'KICKOFF_CONFLICT' };
  }
  const referee=typeof row.fixture.referee==='string' && row.fixture.referee.length<=100
    ? row.fixture.referee.trim() || null : null;
  return { status: 'CONFIRMED', fixture_id: row.fixture.id, referee };
}

export async function collectGateway(project, token, candidates, now, fetcher=fetch, paperLeagueIds, same=sameTeam) {
  const leagueIds=paperLeagueIds??leagues;
  const out = new Map();
  if (!project || !token) return { status: 'DATA_MISSING', reason: 'GATEWAY_NOT_CONFIGURED', fixtures: out };
  const grouped = new Map();
  for (const fixture of candidates) {
    const ahead = Date.parse(fixture.kickoff) - now;
    if (!Object.hasOwn(leagueIds, fixture.competition) || ahead <= 0 || ahead > 8 * 3600000) continue;
    const day=paperLeagueIds?new Date(fixture.kickoff).toISOString().slice(0,10):fixture.kickoff.slice(0,10);
    const key = fixture.competition + '|' + day;
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
    for (const [key, group] of grouped) {
      if (remaining < 1) break;
      const sample = group[0];
      const date=key.split('|')[1];
      const season=paperLeagueIds?String(Number(date.slice(0,4))-Number(Number(date.slice(5,7))<7)):'2026';
      const gameList = await get('fixtures', { league: String(leagueIds[sample.competition]),season,date });
      for (const fixture of group) {
        const check = matchFixture(fixture, gameList.records,leagueIds,same);
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
      const formations={};
      const confirmedTeams=[game.home_team,game.away_team].filter((team,index)=>{
        const matches=lineups.records.filter(row=>same(game.competition,row.team?.name,team));
        const match=matches.length===1?matches[0]:null;
        const valid=match?.startXI?.length===11;
        if(paperLeagueIds&&valid&&typeof match.formation==='string'&&/^\d(?:-\d){2,4}$/.test(match.formation))
          formations[index===0?'home':'away']=match.formation;
        return valid;
      });
      entry.lineups = { confirmed_teams: confirmedTeams.length, observed_at: lineups.observed_at };
      if(paperLeagueIds)entry.lineups.formations=formations;
    }
    return { status: grouped.size ? 'OK' : 'WAITING_WINDOW', fixtures: out };
  } catch (error) {
    return { status: 'DATA_MISSING', reason: error.message === 'GATEWAY_BUDGET_STOP' ? error.message : 'GATEWAY_SOURCE_ERROR', fixtures: out };
  }
}
