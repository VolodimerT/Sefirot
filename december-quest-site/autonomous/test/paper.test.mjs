import assert from 'node:assert/strict';
import Core from '../core.js';
import { executeDaily, executeReplay, modes } from '../paper-runner.js';
import { auditWeekly } from '../paper-sources.js';
import { readEuropeArchive } from '../paper-europe-archive.js';
import { forecastInternational, internationalState } from '../paper-international.js';
import { collectGateway } from '../gateway.js';
import { europeResults, europeTeam } from '../paper-europe.js';
import { paperCompetitions, paperDomestic, paperOddsSports } from '../paper-registry.js';
import { attachOdds, collectTimestampedOdds, decemberSports } from '../odds-gateway.js';

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
assert.deepEqual(Object.keys(paperOddsSports).sort(),[...paperCompetitions.keys()].filter(code=>!['UPL','NATIONAL_LEAGUE'].includes(code)).sort());
const routes=[];
const provider=async input=>{routes.push(new URL(input).pathname);return Response.json([]);};
const additional=[{...fixture,competition:'BUNDES_2'},{...fixture,competition:'NETHERLANDS'}];
assert.equal((await collectTimestampedOdds(additional,now,'qa',provider,()=>now,paperOddsSports)).status,'OK');
assert.deepEqual(routes.sort(),['/v4/sports/soccer_germany_bundesliga2/odds','/v4/sports/soccer_netherlands_eredivisie/odds']);
assert.equal((await collectTimestampedOdds(additional,now,'qa',provider,()=>now,decemberSports)).status,'NO_FIXTURES');
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

const archive=readEuropeArchive([
  '= UEFA Champions League - Quali 2025/26','▪ 1. Round','  Tue Jul 8 2025',
  '  20:00 Sabah (AZE) v FC Barcelona (ESP) 1-2 (0-1)',
  '  20:00 Inter (ITA) v AS Roma (ITA) 3-2 a.e.t. (2-2, 2-2)',
  '▪ Round of 16','  Thu Dec 4 2025','  20:00 Sabah (AZE) v FC Barcelona (ESP) 2-1'
].join('\n'),'UCL',2025,true,now);
assert.equal(archive.length,1);
assert.equal(archive[0].competition,'UCL_QUAL');
assert.equal(archive[0].away,'barcelona');
assert.equal(archive[0].homeCountry,'AZE');
assert.throws(()=>readEuropeArchive('unexpected','UCL',2025,true,now),/ARCHIVE_COMPETITION_MISMATCH/);

const internationalRows=Array.from({length:64},(_,index)=>{
  const when=now-(66-index)*86400000;
  return {competition:'UCL',home:'sabah',away:'barcelona',homeCountry:'AZE',awayCountry:'ESP',
    when,date:new Date(when).toISOString().slice(0,10),hg:index%2,ag:2};
});
const candidate={competition:'UCL',home_team:'Sabah FK',away_team:'Barcelona'};
const model='DQ-INTERNATIONAL-POISSON-0.1';
const good=forecastInternational(candidate,internationalRows,now,model);
assert.equal(good.model_version,model);
assert.equal(good.markets.length,68);
assert.ok(Math.abs(good.probabilities.home+good.probabilities.draw+good.probabilities.away-1)<0.0001);
const sameDay={...internationalRows[0],when:now-3600000,date:new Date(now).toISOString().slice(0,10),hg:10,ag:0};
assert.deepEqual(forecastInternational(candidate,[...internationalRows,sameDay],now,model),good);
assert.equal(forecastInternational({...candidate,displaced_home:true},internationalRows,now,model).reason,
  'VENUE_OUTSIDE_VALIDATION');
assert.equal(internationalState(internationalRows,now).state.tournaments.get('UCL').n,64);

const when=new Date(now+50*60_000).toISOString();
const sample={...candidate,kickoff:when,fixture_key:'qa-ucl',timing_status:'confirmed'};
const timestamp=new Date(now-60000).toISOString();
const artifact=(home,away)=>{
  const squad=Array.from({length:11},(_,id)=>({player:{id:id+1}}));
  return [{team:{name:home},formation:'4-3-3',startXI:squad},{team:{name:away},formation:'4-4-2',startXI:squad}];
};
const observed=[];
const gateway=await collectGateway('https://test.invalid','local-qa',[sample],now,async(_url,req)=>{
  const called=JSON.parse(req.body); observed.push(called.endpoint);
  const response=called.endpoint==='fixtures'?[{fixture:{id:123,date:when,status:{short:'NS'},referee:'Test Referee'},
    league:{id:2},teams:{home:{name:'Sabah'},away:{name:'FC Barcelona'}}}]
    :called.endpoint==='injuries'?[]:artifact('Sabah','FC Barcelona');
  return Response.json({ok:true,received_at:timestamp,data:{response}});
},{UCL:2},(_league,a,b)=>europeTeam(a)===europeTeam(b));
assert.deepEqual(observed,['fixtures','injuries','fixtures/lineups']);
assert.deepEqual(gateway.fixtures.get(sample.fixture_key).lineups.formations,{home:'4-3-3',away:'4-4-2'});
assert.equal(gateway.fixtures.get(sample.fixture_key).injuries.published,false);

const oddsFixture={...sample,home_team:'Sabah FK',away_team:'Barcelona'};
const oddsEvent={id:'event-1',sport_key:paperOddsSports.UCL,commence_time:when,home_team:'Sabah',away_team:'FC Barcelona',
  bookmakers:[{title:'Book One',last_update:timestamp,markets:[{key:'h2h',outcomes:[
    {name:'Sabah',price:3.2},{name:'Draw',price:3.6},{name:'FC Barcelona',price:2}
  ]}]}]};
const wire=events=>({batches:[{league:'UCL',endpoint:'https://api.the-odds-api.com/test',observedAt:now,events}]});
const output=attachOdds({...good,source_cutoff:new Date(now).toISOString(),status:'MODEL_ONLY'},null,oddsFixture,
  wire([oddsEvent]),true,paperOddsSports,(_league,name)=>europeTeam(name));
assert.equal(output.evidence.quote_price_verified,true);
assert.equal(output.best_candidate.provider_event_id,'event-1');
assert.equal(output.best_candidate.quote_timestamp_scope,'BOOKMAKER');
for(const bad of [{...oddsEvent,live:true},{...oddsEvent,id:''},{...oddsEvent,
  bookmakers:[{...oddsEvent.bookmakers[0],last_update:new Date(now+1).toISOString()}]}]){
  const blocked=attachOdds({...good,source_cutoff:new Date(now).toISOString(),status:'MODEL_ONLY'},null,oddsFixture,
    wire([bad]),true,paperOddsSports,(_league,name)=>europeTeam(name));
  assert.ok(blocked.markets.every(m=>m.ev===null));
}
console.log('PASS — international archive and day-batched model, tactical gateway receipts and market provenance');
