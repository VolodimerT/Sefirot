import assert from 'node:assert/strict';
import Core from '../core.js';
import { executeDaily, executeReplay, modes } from '../paper-runner.js';
import { auditWeekly } from '../paper-sources.js';
import { europeResults } from '../paper-europe.js';
import { paperDomestic } from '../paper-registry.js';

const now=Date.parse('2026-11-25T09:30:00Z');
const booth=['https://league.example.test/match','https://archive.example.test/match'];
const fixture={fixture_key:'paper-fixture',competition:'CHAMPIONSHIP',home_team:'Bolton Wanderers',
  away_team:'West Bromwich Albion',kickoff:'2026-11-25T16:00:00+02:00',timing_status:'confirmed',
  checked_at:'2026-11-25T09:00:00Z',fixture_sources:booth};
const rows=[fixture,{...fixture,fixture_key:'started',home_team:'Derby',kickoff:'2026-11-25T09:00:00Z'},
  {...fixture,fixture_key:'future-proof',home_team:'Watford',checked_at:'2026-11-25T10:00:00Z'},
  {...fixture,fixture_key:'another-date',kickoff:'2026-11-26T08:00:00+02:00'}];
let reads=0;
const sources={
  domestic:async()=>{reads++;return {rows:[],missing:['2627_MISSING'],sources:[]};},
  weekly:async()=>({error:'UNAVAILABLE'}),
  european:()=>assert.fail('Paper must collect only requested families')
};
assert.equal(Core.forecast(fixture,[],now).status,'UNSUPPORTED_LEAGUE');
assert.equal(Core.forecast(fixture,[],now,true,paperDomestic).status,'SOURCE_ERROR');
const result=await executeDaily({date:'2026-11-25',calendar:rows,clock:()=>now,sources});
assert.equal(result.mode,modes.daily);
assert.equal(result.input_fixtures,3);
assert.equal(result.excluded_by_time,1);
assert.equal(result.fixtures.length,2);
assert.equal(reads,1);
assert.equal(result.real_cost,0);
assert.equal(result.virtual_stake,0);
assert.equal(result.eligible_legs,0);
assert.ok(result.fixtures[0].reasons.includes('2627_MISSING'));
assert.ok(result.fixtures[1].reasons.includes('KICKOFF_NOT_REVERIFIED'));
assert.equal((await executeDaily({date:'2026-11-28',calendar:rows,clock:()=>now,sources})).status,'NO_UPCOMING_FIXTURES');
await assert.rejects(executeDaily({date:'2026-02-30',calendar:rows,clock:()=>now,sources}),/INVALID_PAPER_DATE/);
await assert.rejects(executeDaily({date:'2026-11-25',calendar:[fixture,{...fixture}],clock:()=>now,sources}),/INVALID_PAPER_FIXTURE/);
const duplicate=await executeDaily({date:'2026-11-25',calendar:[fixture,{...fixture,fixture_key:'alias',home_team:'Bolton'}],clock:()=>now,sources});
assert.equal(duplicate.fixtures.filter(f=>f.reasons.includes('DUPLICATE_FIXTURE')).length,2);
const replay=await executeReplay({competitions:['UPL'],cutoff:now,sources});
assert.equal(replay.mode,modes.replay);
assert.equal(replay.prospective,false);
assert.equal(replay.reports[0].error,'NO_VALIDATED_UKRAINE_RESULTS_FEED');
const indicative={url:'https://football-data.co.uk/fixtures.csv',observedAt:now,publishedAt:now-13*3600000,
  records:[{Div:'E1',Date:'25/11/2026',Time:'14:00',HomeTeam:'Bolton',AwayTeam:'West Brom',B365H:'2.5',B365D:'3.5',B365A:'3'}]};
assert.deepEqual(auditWeekly(indicative,fixture,now),{status:'STALE_CSV_PUBLICATION',indicative_price_count:3,
  published_at:new Date(indicative.publishedAt).toISOString(),source:indicative.url});
assert.equal(auditWeekly(indicative,{...fixture,kickoff:'2026-11-25T16:01:00+02:00'},now).status,'ODDS_EVENT_NOT_FOUND');
assert.equal(auditWeekly({...indicative,publishedAt:now-3600000},fixture,now).status,'PER_QUOTE_TIMESTAMP_UNKNOWN');
assert.equal(auditWeekly({...indicative,observedAt:NaN},fixture,now).status,'QUOTE_FEED_UNAVAILABLE');
const summer=Date.parse('2026-08-25T09:00:00Z');
assert.equal(auditWeekly({...indicative,observedAt:summer,publishedAt:summer-3600000,
  records:[{...indicative.records[0],Date:'25/08/2026',Time:'15:00'}]},
  {...fixture,kickoff:'2026-08-25T14:00:00Z'},summer).status,'PER_QUOTE_TIMESTAMP_UNKNOWN');

const game={matchID:1,leagueShortcut:'ucl',leagueSeason:2026,group:{groupName:'1. Spieltag'},
  matchDateTimeUTC:'2026-11-24T19:45:00Z',matchIsFinished:true,team1:{teamName:'FC Barcelona'},team2:{teamName:'Sabah'},
  matchResults:[{resultTypeKind:'After90Minutes',pointsTeam1:2,pointsTeam2:1}]};
assert.equal(europeResults([game,{...game,matchID:2,matchDateTimeUTC:'2026-11-25T00:30:00Z'}],'UCL','ucl',2026,now).length,1);
assert.equal(europeResults([{...game,group:{groupName:'Finale'}}],'UCL','ucl',2026,now).length,0);
assert.throws(()=>europeResults([game],'UEL','uel2026',2026,now),/INTERNATIONAL_COMPETITION_MISMATCH/);
console.log('PASS — isolated paper/replay modes, kickoff/cutoff, fixture receipts, stale odds and UEFA phase');
