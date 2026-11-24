/* Strict date-only walk-forward calibration; never trains on test-day or future games. */
import Core from './core.js';
const limit=80;
const clip=p=>Math.max(.000001,Math.min(.999999,p));
function measure(p,actual){
 const y={home:actual==='H'?1:0,draw:actual==='D'?1:0,away:actual==='A'?1:0};
 return {brier:(p.home-y.home)**2+(p.draw-y.draw)**2+(p.away-y.away)**2,
         logloss:-Math.log(clip(p[actual==='H'?'home':actual==='D'?'draw':'away']))};
}
function baseline(rows){
 let h=1,d=1,a=1;
 for(const r of rows){if(r.hg>r.ag)h++;else if(r.hg===r.ag)d++;else a++;}
 const sum=h+d+a;return {home:h/sum,draw:d/sum,away:a/sum};
}
export function* walkForward(competition,rows,now,includeMarkets=false){
 const today=new Date(now).toISOString().slice(0,10);
 const eligible=rows.filter(x=>x.date>='2026-09-01'&&x.date<today&&x.when<now).sort((a,b)=>a.when-b.when).slice(-limit);
 for(const game of eligible){
  const asof=Date.parse(game.date+'T00:00:00Z')-86400000; // one day before fixture date
  const pre=rows.filter(r=>r.date<game.date&&r.when<asof);
  if(pre.length<30)continue;
  const fixture={fixture_key:'BACKTEST-'+competition+'-'+game.date+'-'+game.home,competition,
    home_team:game.home,away_team:game.away,kickoff:game.date+'T22:00:00Z'};
  const forecast=Core.forecast(fixture,pre,asof,includeMarkets);
  if(forecast.status==='MODEL_ONLY')yield {game,forecast,asof,
    outcome:game.hg>game.ag?'H':game.hg<game.ag?'D':'A',baseline:baseline(pre)};
 }
}

function backtest(competition,rows,now=Date.now()){
 let n=0,modelBrier=0,modelLL=0,baseBrier=0,baseLL=0,first=null,last=null;
 for(const {game,forecast,outcome,baseline} of walkForward(competition,rows,now)){
  const mm=measure(forecast.probabilities,outcome),bb=measure(baseline,outcome);
  n++;modelBrier+=mm.brier;modelLL+=mm.logloss;baseBrier+=bb.brier;baseLL+=bb.logloss;
  if(!first||game.date<first)first=game.date;if(!last||game.date>last)last=game.date;
 }
 const metrics=n?{model_brier:Math.round(modelBrier/n*10000)/10000,
   baseline_brier:Math.round(baseBrier/n*10000)/10000,
   model_logloss:Math.round(modelLL/n*10000)/10000,
   baseline_logloss:Math.round(baseLL/n*10000)/10000}:{
    model_brier:null,baseline_brier:null,model_logloss:null,baseline_logloss:null};
 const relative=n?Math.round((1-metrics.model_brier/metrics.baseline_brier)*10000)/10000:null;
 const status=n<20?'INSUFFICIENT':metrics.model_brier<metrics.baseline_brier-.01&&metrics.model_logloss<metrics.baseline_logloss-.005?'PROMISING':'NO_EDGE';
 return {competition,model_version:Core.MODEL_VERSION,sample_n:n,
  ...metrics,relative_skill:relative,status,
  rationale:'DAY_LEVEL_WALK_FORWARD; test fixtures strictly unseen; baseline prior league H/D/A; coverage is observational not proof of value. Period '+(first||'NA')+'..'+(last||'NA')};
}
export default {backtest,measure,baseline};
