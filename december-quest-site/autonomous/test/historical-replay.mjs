/* Read-only QA. Run with archived <season>-<division>.csv and an explicit UTC cutoff. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import Core from '../core.js';
import Validation, { walkForward } from '../validation.js';
import { grade, grades, removeMargin, evaluateQuote } from '../markets.js';

const [directory, cutoff] = process.argv.slice(2);
const now=Date.parse(cutoff);
if (!directory || !Number.isFinite(now) || !cutoff.endsWith('Z')) throw Error('Supply CSV directory and an explicit UTC cutoff');
const files={};
const key=row=>[row.date,row.home,row.away].join('|');
const mean=xs=>xs.length?xs.reduce((sum,value)=>sum+value,0)/xs.length:null;

function pairedInterval(rows) {
  const days=new Map();
  for(const {date,delta} of rows) {
    const day=days.get(date)||{sum:0,n:0};
    day.sum+=delta;
    day.n++;
    days.set(date,day);
  }
  if(rows.length<30||days.size<10)return null;
  let seed=20261201;
  const rng=()=>{seed=(Math.imul(1664525,seed)+1013904223)>>>0;return seed/4294967296;};
  const blocks=[...days.values()];
  const samples=Array.from({length:2000},()=>{
    let sum=0,n=0;
    for(let i=0;i<blocks.length;i++){
      const block=blocks[Math.floor(rng()*blocks.length)];
      sum+=block.sum;
      n+=block.n;
    }
    return sum/n;
  }).sort((a,b)=>a-b);
  return [samples[50],samples[1949]];
}

const results=[];
const markets=new Map(), quoteChecks=new Map();
const calibration=Array.from({length:10},()=>({n:0,probability:0,actual:0}));
for(const [competition,division] of Object.entries(Core.LEAGUE_FILES)){
  const history=new Map(), closing=new Map(), conflicts=new Set();
  for(const season of ['2526','2627']){
    const name=season+'-'+division+'.csv';
    const csv=await readFile(resolve(directory,name),'utf8');
    files[name]=createHash('sha256').update(csv).digest('hex');
    for(const row of Core.resultsFromCsv(csv,competition,now)){
      const id=key(row),prior=history.get(id);
      if(prior&&(prior.hg!==row.hg||prior.ag!==row.ag||prior.kickoff!==row.kickoff))conflicts.add(id);
      history.set(id,row);
    }
    if (season!=='2627') continue;
    for(const row of Core.parseCsv(csv)){
      const date=Core.csvDate(row.Date)?.toISOString().slice(0,10);
      if(!date)continue;
      const id=key({date,home:Core.canonical(competition,row.HomeTeam),away:Core.canonical(competition,row.AwayTeam)});
      const margin=removeMargin(['B365CH','B365CD','B365CA'].map(k=>Number(row[k])));
      if(margin)closing.set(id,{probabilities:margin.probabilities,row});
    }
  }
  for(const id of conflicts){history.delete(id);closing.delete(id);}
  const rows=[...history.values()];
  const validation=Validation.backtest(competition,rows,now);
  const observations=[], fromLeague=[], fromMarket=[];
  for(const {game,forecast,asof,outcome,baseline} of walkForward(competition,rows,now,true)){
    assert.ok(Date.parse(forecast.evidence.latest_training_date+'T00:00:00Z')<asof);
    assert.ok(forecast.evidence.latest_training_date<game.date);
    assert.ok(Math.abs(forecast.probabilities.home+forecast.probabilities.draw+forecast.probabilities.away-1)<.00005);
    const model=Validation.measure(forecast.probabilities,outcome);
    const prior=Validation.measure(baseline,outcome);
    const archived=closing.get(key(game));
    if(archived){
      const [home,draw,away]=archived.probabilities;
      const close=Validation.measure({home,draw,away},outcome);
      fromMarket.push({date:game.date,model,reference:close,delta:model.brier-close.brier});
    }
    observations.push({date:game.date,model,delta:model.brier-prior.brier});
    fromLeague.push(prior);
    for(const [result,label] of [['H','home'],['D','draw'],['A','away']]){
      const p=forecast.probabilities[label];
      const bucket=calibration[Math.min(9,Math.floor(p*10))];
      bucket.n++;
      bucket.probability+=p;
      bucket.actual+=Number(result===outcome);
    }
    for(const market of forecast.markets){
      assert.ok(Math.abs(Object.values(market.settlement).reduce((sum,p)=>sum+p,0)-1)<.0001);
      const actual=grade(market,game.hg,game.ag);
      assert.ok(grades.includes(actual));
      const brier=probs=>grades.reduce((sum,k)=>sum+(probs[k]-Number(k===actual))**2,0);
      const logloss=probs=>-Math.log(Math.max(.000001,probs[actual]));
      const totals=markets.get(market.kind)||{outcomes:0,brier:0,baseline_brier:0,logloss:0,baseline_logloss:0};
      totals.outcomes++;
      totals.brier+=brier(market.settlement);
      totals.baseline_brier+=brier(market.baseline);
      totals.logloss+=logloss(market.settlement);
      totals.baseline_logloss+=logloss(market.baseline);
      markets.set(market.kind,totals);
      const quote=archived?.row;
      if(!quote)continue;
      let numeric;
      if(market.kind==='1X2')numeric=quote['B365C'+({home:'H',draw:'D',away:'A'})[market.side]];
      if(market.kind==='TG'&&market.line===2.5)numeric=quote[market.side==='over'?'B365C>2.5':'B365C<2.5'];
      const line=quote.AHCh?.trim()?Number(quote.AHCh):null;
      if(['DNB','AH'].includes(market.kind)&&line!==null&&market.line===(market.side==='home'?line:-line)) {
        numeric=quote[market.side==='home'?'B365CAHH':'B365CAHA'];
      }
      const odds=Number(numeric);
      if(!(odds>1&&odds<=100))continue;
      const d=market.settlement, value=evaluateQuote(d,odds);
      const reference=d.win*(odds-1)+d.half_win*(odds-1)/2-d.half_loss/2-d.loss;
      assert.ok(value && Math.abs(value.expected_value-reference)<.000001);
      assert.ok(Math.abs(value.implied-1/odds)<.000001);
      const stress=Object.values(value.price_stress).filter(n=>n!==null);
      assert.ok(stress.every((n,i)=>i===0||n<=stress[i-1]));
      quoteChecks.set(market.kind,(quoteChecks.get(market.kind)||0)+1);
    }
  }
  assert.equal(observations.length,validation.sample_n);
  results.push({competition, n:observations.length, model_brier:mean(observations.map(x=>x.model.brier)),
    baseline_brier:mean(fromLeague.map(x=>x.brier)), model_logloss:mean(observations.map(x=>x.model.logloss)),
    baseline_logloss:mean(fromLeague.map(x=>x.logloss)), paired_model_minus_baseline_ci95:pairedInterval(observations),
    closing_reference:{n:fromMarket.length, model_brier:mean(fromMarket.map(x=>x.model.brier)),
      brier:mean(fromMarket.map(x=>x.reference.brier)), model_logloss:mean(fromMarket.map(x=>x.model.logloss)),
      logloss:mean(fromMarket.map(x=>x.reference.logloss)), paired_model_minus_reference_ci95:pairedInterval(fromMarket)}});
}
const marketSummary=Object.fromEntries([...markets].map(([kind,{outcomes,...totals}])=>
  [kind,{outcomes,...Object.fromEntries(Object.entries(totals).map(([name,value])=>[name,value/outcomes]))}]));
console.log(JSON.stringify({type:'HISTORICAL_WALK_FORWARD',model_version:Core.MODEL_VERSION,cutoff,files,results,
  markets:marketSummary,archive_quote_formula_checks:Object.fromEntries(quoteChecks),calibration:calibration.map(({n,probability,actual},i)=>
    ({lower:i/10,n,probability:n?probability/n:null,actual:n?actual/n:null}))},null,2));
