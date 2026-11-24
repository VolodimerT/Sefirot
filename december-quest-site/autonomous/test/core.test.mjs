import assert from 'node:assert/strict';
import Core from '../core.js';
import { walkForward } from '../validation.js';
import { evaluateQuote, grade, standardMarkets, removeMargin } from '../markets.js';
import { historyProfile, matchStatistics } from '../history.js';
import { duplicates, questFixture } from '../run.js';
import { collectGateway, matchFixture } from '../gateway.js';
import { attachOdds, collectTimestampedOdds } from '../odds-gateway.js';
const base=Date.parse('2026-11-23T12:00:00Z');
const fixture={fixture_key:'EPL-2026-12-01-test',competition:'EPL',home_team:'Manchester City',away_team:'Leeds',kickoff:'2026-12-01T22:00:00+02:00'};
let data=[];
for(let i=0;i<16;i++){
 const day=new Date(Date.UTC(2026,8,1+i*4,12)).toISOString().slice(0,10);
 data.push({home:'mancity',away:'leeds',hg:2+i%3,ag:i%2,date:day,when:Date.parse(day+'T12:00:00Z')});
 data.push({home:'leeds',away:'mancity',hg:i%3,ag:1+i%3,date:day,when:Date.parse(day+'T12:00:00Z')});
}
const p=Core.forecast(fixture,data,base);
assert.equal(p.status,'MODEL_ONLY');
assert.equal(p.verdict,'пропуск');
assert.equal(p.risk_class,'D');
assert.equal(p.markets.length,68);
assert.equal(p.sample_n,32);
assert.ok(p.markets.every(x=>x.odds===null&&x.ev===null));
assert.ok(p.probabilities.home>0);
assert.ok(Math.abs(p.probabilities.home+p.probabilities.draw+p.probabilities.away-1)<0.00005);
assert.ok(p.probabilities.o15>=p.probabilities.o25&&p.probabilities.o25>=p.probabilities.o35);
assert.ok(p.evidence.latest_training_date<'2026-11-23');
assert.equal(Core.canonical('EPL','Manchester City'),'mancity');
assert.equal(Core.forecast({...fixture,competition:'UCL'},data,base).status,'UNSUPPORTED_LEAGUE');
assert.equal(Core.forecast(fixture,data.slice(0,8),base).status,'INSUFFICIENT_DATA');
assert.equal(Core.forecast({...fixture,kickoff:'2026-11-22T21:00:00+02:00'},data,base).status,'SOURCE_ERROR');
assert.equal(Core.parseCsv('HomeTeam,AwayTeam,FTHG,FTAG,Date\n"Man, City",Leeds,3,1,11/11/2026\n')[0].HomeTeam,'Man, City');
assert.equal(Core.resultsFromCsv('Div,Date,HomeTeam,AwayTeam,FTHG,FTAG\nE0,23/11/2026,Man City,Leeds,2,0\nE0,22/11/2026,Leeds,Man City,0,1\n','EPL',base).length,1);
const oddsCutoff=Date.parse(fixture.kickoff)-3600000;
const model=Core.forecast(fixture,data,oddsCutoff);
const odds=[{Div:'E0',Date:'01/12/2026',Time:'20:00',HomeTeam:'Man City',AwayTeam:'Leeds',B365H:'2.05',B365D:'3.5',B365A:'3.8'}];
const weekly={ok:true,records:odds,publishedAt:oddsCutoff-60000,observedAt:oddsCutoff};
const informative=attachOdds(model,weekly,fixture);
const home=result=>result.markets.find(x=>x.id==='1X2:home:0');
assert.equal(informative.status,'WAITING_ODDS');
assert.equal(informative.verdict,'пропуск');
assert.equal(home(informative).odds,2.05);
assert.equal(home(informative).value_verified,false);
assert.ok(informative.markets.every(x=>x.ev===null));
assert.equal(attachOdds(model,{...weekly,records:[{...odds[0],HomeTeam:'Wrong Team'}]},fixture).status,'MODEL_ONLY');
assert.equal(attachOdds(model,{...weekly,publishedAt:oddsCutoff-13*3600000},fixture).status,'MODEL_ONLY');
assert.equal(attachOdds(model,{...weekly,publishedAt:oddsCutoff+1},fixture).status,'MODEL_ONLY');
assert.equal(informative.evidence.quote_provider_timestamp,null);
assert.deepEqual(Core.forecast(fixture,data,base),p);
const sameDay={home:'mancity',away:'leeds',hg:12,ag:0,date:'2026-11-23',when:base-1000};
assert.deepEqual(Core.forecast(fixture,[sameDay,...data],base),p);

const stamp=delta=>new Date(oddsCutoff+delta).toISOString();
const book=(name,price,last_update=stamp(-60000))=>({
 key:name,title:name,last_update,
 markets:[{key:'h2h',outcomes:[{name:'Manchester City',price},{name:'Leeds United',price:3.8},{name:'Draw',price:3.6}]},
  {key:'totals',outcomes:[{name:'Over',point:2.5,price:2},{name:'Under',point:2.5,price:1.8}]}]
});
const event={sport_key:'soccer_epl',commence_time:new Date(fixture.kickoff).toISOString(),home_team:'Man City',away_team:'Leeds United',
 bookmakers:[book('One',2),book('Two',2.4),book('Three',2.6),book('Four',3),book('Four',3),
  book('Stale',9,stamp(-3600001)),book('Future',9,stamp(1)),book('Betfair Exchange',9),
  book('Conflict',8),book('Conflict',9)]};
const collected=await collectTimestampedOdds([{...fixture,timing_status:'confirmed'}],oddsCutoff,'synthetic',async url=>{
 const request=new URL(url);
 assert.equal(request.pathname,'/v4/sports/soccer_epl/odds');
 assert.equal(request.searchParams.get('regions'),'eu');
 assert.equal(request.searchParams.get('markets'),'h2h,totals');
 return Response.json([event]);
},()=>oddsCutoff);
assert.equal(collected.status,'OK');
assert.equal((await collectTimestampedOdds([fixture],oddsCutoff,'',()=>assert.fail())).status,'NOT_CONFIGURED');
assert.equal((await collectTimestampedOdds([fixture],oddsCutoff,'synthetic',()=>assert.fail())).status,'NO_FIXTURES');
const verified=attachOdds(model,weekly,fixture,collected,true);
assert.equal(verified.verdict,'пропуск');
assert.equal(verified.risk_class,model.risk_class);
assert.deepEqual(verified.probabilities,model.probabilities);
assert.deepEqual(verified.markets.map(x=>x.settlement),model.markets.map(x=>x.settlement));
assert.equal(home(verified).market_odds,2.5);
assert.equal(home(verified).odds,2.4);
assert.equal(home(verified).quote_count,4);
assert.equal(home(verified).price_verified,true);
assert.equal(home(verified).value_verified,false);
assert.equal(home(verified).conditional_ev_pct,null);
assert.equal(home(verified).quote_updated_at,stamp(-60000));
assert.equal(home(verified).settlement_rules,'REGULATION_90_PLUS_STOPPAGE_1X2');
assert.equal(home(verified).implied,0.416667);
const marketPrices=verified.markets.filter(row=>row.kind==='1X2').map(row=>row.quotes.find(q=>q.bookmaker==='Two').fair_probability);
assert.ok(Math.abs(marketPrices.reduce((total,value)=>total+value,0)-1)<0.000002);
assert.ok(Math.abs(home(verified).fair_probability*home(verified).fair_odds-1)<0.00001);
assert.equal(home(informative).fair_probability,undefined);
assert.ok(Math.abs(home(verified).ev-(home(model).settlement.win*2.4-1))<0.000001);
assert.ok(Math.abs(home(verified).price_stress[5]-(home(model).settlement.win*2.4*.95-1))<0.000001);
assert.equal(verified.markets.find(x=>x.id==='TG:over:2.5').price_verified,true);
assert.equal(verified.markets.find(x=>x.id==='TG:over:2.25').ev,null);
const alter=events=>({...collected,batches:[{...collected.batches[0],events}]});
for(const unsafe of [[{...event,live:true}],[{...event,completed:true}],
  [{...event,commence_time:'2026-12-01T20:05:00Z'}],[event,event]]) {
 assert.equal(attachOdds(model,null,fixture,alter(unsafe),true).status,'MODEL_ONLY');
}
assert.equal(attachOdds(model,null,fixture,collected,false).status,'MODEL_ONLY');
assert.equal(attachOdds({...model,source_cutoff:new Date(fixture.kickoff).toISOString()},null,fixture,collected,true).status,'MODEL_ONLY');
assert.equal(attachOdds(model,weekly,fixture,{status:'SOURCE_ERROR',batches:[]},true).evidence.quote_price_verified,false);
const unavailable=await collectTimestampedOdds([{...fixture,timing_status:'confirmed'}],oddsCutoff,'synthetic',
 async url=>{throw Error(url);});
assert.deepEqual(unavailable.errors,[{league:'EPL',error:'FETCH_ERROR'}]);

const [validXg,missingXg]=Core.resultsFromCsv(
 '\uFEFFDiv,Date,HomeTeam,AwayTeam,FTHG,FTAG,HxG,AxG\nE0,22/11/2026,Man City,Leeds,2,0,1.6,0\nE0,21/11/2026,Man City,Leeds,2,0,,0\n',
 'EPL',base);
assert.equal(validXg.hxg,1.6);
assert.equal(validXg.axg,0);
assert.equal(missingXg.hxg,undefined);
assert.ok(p.markets.every(row=>Math.abs(Object.values(row.settlement).reduce((sum,n)=>sum+n,0)-1)<1e-8));
const metrics=matchStatistics({HS:'12',AS:'9',HST:'4',AST:'5',HC:'7',AC:'2',HF:'10',AF:'12',HY:'0',AY:'1'});
assert.deepEqual(metrics.yellow_cards,[0,1]);
assert.equal(matchStatistics({HY:'',AY:'1'}).yellow_cards,undefined);
assert.equal(matchStatistics({HS:'2',AS:'4',HST:'3',AST:'2'}).shots_on_target,undefined);
const enriched=data.map(row=>({...row,metrics,referee:'QA Referee'}));
const contextual=historyProfile([...enriched,{...sameDay,metrics}], 'mancity','leeds',
 new Date(fixture.kickoff).toISOString(),base,'QA Referee');
assert.deepEqual(contextual.home.form.map(form=>form.n),[5,10,20]);
assert.equal(contextual.home.metrics.shots.n,16);
assert.deepEqual(contextual.away.metrics.corners.rate,{for:2,against:7});
assert.equal(contextual.referee.n,32);
assert.equal(contextual.referee.yc_per_game,1);
assert.equal(contextual.referee.low_card_matches,32);
assert.ok(contextual.home.latest_league_result<'2026-11-23');
assert.deepEqual(Core.forecast(fixture,enriched,base),p);
const fair=removeMargin([2,4,4]);
assert.deepEqual(fair,{overround:0,probabilities:[.5,.25,.25]});
assert.equal(removeMargin([2,null,4]),null);
assert.equal(removeMargin([2]),null);
const byId=id=>standardMarkets.find(row=>row.id===id);
assert.equal(grade(byId('DNB:home:0'),1,1),'push');
assert.equal(grade(byId('AH:home:-0.75'),2,1),'half_win');
assert.equal(grade(byId('AH:away:0.75'),2,1),'half_loss');
assert.equal(grade(byId('TG:over:2.25'),1,1),'half_loss');
assert.equal(grade(byId('TG:under:2.25'),1,1),'half_win');
assert.equal(grade(byId('TG:under:2'),1,1),'push');
assert.equal(grade(byId('DC:12:0'),1,1),'loss');
assert.equal(grade(byId('TH:over:1.25'),1,1),'half_loss');
const forecastEV=evaluateQuote({win:.3,half_win:.2,push:.15,half_loss:.1,loss:.25},2);
assert.equal(forecastEV.expected_value,.1);
assert.equal(forecastEV.break_even_odds,1.75);
assert.equal(forecastEV.sensitivity['-0.05'],.03);
assert.deepEqual(forecastEV.price_stress,{2:.084,3:.076,4:.068,5:.06});
assert.equal(evaluateQuote(null,2),null);
assert.equal(evaluateQuote({win:1},2),null);
assert.equal(questFixture(fixture),true);
assert.equal(questFixture({...fixture,kickoff:'2026-12-01T23:01:00+02:00'}),false);
const alias={...fixture,fixture_key:'duplicate',home_team:'Man City'};
assert.deepEqual([...duplicates([fixture,alias])],[fixture.fixture_key,'duplicate']);
const providerRecord={league:{id:39},fixture:{id:27,date:fixture.kickoff,status:{short:'NS'}},
 teams:{home:{name:'Man City'},away:{name:'Leeds'}}};
assert.equal(matchFixture(fixture,[providerRecord]).fixture_id,27);
assert.equal(matchFixture(fixture,[{...providerRecord,fixture:{...providerRecord.fixture,status:{short:'1H'}}}]).status,'KICKOFF_CONFLICT');
assert.equal(matchFixture(fixture,[providerRecord,providerRecord]).status,'DATA_MISSING');
assert.equal((await collectGateway('https://test.invalid','',[fixture],base,()=>assert.fail())).reason,'GATEWAY_NOT_CONFIGURED');
let gatewayRequests=0;
const stop=await collectGateway('https://test.invalid','synthetic',[fixture],Date.parse(fixture.kickoff)-3600000,async()=>{
 gatewayRequests++;
 return Response.json({error:'SHARED_BUDGET_STOP'},{status:429});
});
assert.equal(stop.reason,'GATEWAY_BUDGET_STOP');
assert.equal(gatewayRequests,1);
const lateDraw={...data[0],date:'2026-11-20',when:Date.parse('2026-11-20T12:00:00Z'),hg:1,ag:1};
const outcomes=Array.from(walkForward('EPL',[...data,lateDraw],base));
assert.deepEqual(new Set(outcomes.map(row=>row.outcome)),new Set(['H','D','A']));
for(const {game,outcome} of outcomes)assert.equal(outcome,Math.sign(game.hg-game.ag)===1?'H':Math.sign(game.hg-game.ag)===0?'D':'A');
console.log('PASS — автономная модель, cutoff, азиатские расчёты, xG, дедупликация и gateway');
