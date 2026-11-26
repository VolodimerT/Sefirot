import Core from './core.js';
import Validation from './validation.js';

export const paperPolicy={
  archive:{since:'2026-01-01',before:'2026-07-01',minimum:100},
  recent:{since:'2026-07-01',before:null,minimum:60},
  calibrationLimit:0.10,
  brierMargin:0.005,
  logLossMargin:0.005
};
const keys=['home','draw','away'];
const result=({hg,ag})=>hg===ag?'D':hg>ag?'H':'A';
const round=n=>Number(n.toFixed(6));

function improvementInterval(blocks,n,mean,key){
  if(blocks.size<2)return null;
  const residual=[...blocks.values()].reduce((sum,block)=>sum+(block[key]-mean*block.n)**2,0);
  const margin=1.96*Math.sqrt(blocks.size/(blocks.size-1)*residual)/n;
  return [round(mean-margin),round(mean+margin)];
}

export function leagueWalkForward(rows, forecast, end, policy=paperPolicy){
  const cutoffDay=new Date(end).toISOString().slice(0,10);
  const games=rows.filter(g=>g.date<cutoffDay&&g.when<end).sort((a,b)=>a.when-b.when);
  const cohorts=Object.fromEntries(['archive','recent'].map(key=>[key,{n:0,total:0,modelBrier:0,baselineBrier:0,
    modelLogLoss:0,baselineLogLoss:0,blocks:new Map(),bins:Array.from({length:10},()=>({n:0,p:0,y:0}))}]));
  for(const game of games){
    const name=['archive','recent'].find(key=>game.date>=policy[key].since
      &&(!policy[key].before||game.date<policy[key].before));
    if(!name)continue;
    const sums=cohorts[name];
    sums.total++;
    const asof=Date.parse(game.date+'T00:00:00Z');
    const training=games.filter(row=>row.date<game.date&&row.when<asof);
    if(training.length<30)continue;
    const kickoff=game.kickoff??asof+12*3600000;
    const p=forecast(game,training,asof,kickoff);
    if(!p)continue;
    if(!keys.every(key=>Number.isFinite(p[key])&&p[key]>0&&p[key]<1)
      ||Math.abs(keys.reduce((sum,key)=>sum+p[key],0)-1)>0.0001)throw Error('PROBABILITY_INVARIANT');
    const actual=result(game), model=Validation.measure(p,actual);
    const baseline=Validation.measure(Validation.baseline(training),actual);
    sums.n++;sums.modelBrier+=model.brier;sums.baselineBrier+=baseline.brier;
    sums.modelLogLoss+=model.logloss;sums.baselineLogLoss+=baseline.logloss;
    const block=sums.blocks.get(game.date)??{n:0,brier:0,logLoss:0};
    block.n++;block.brier+=baseline.brier-model.brier;block.logLoss+=baseline.logloss-model.logloss;
    sums.blocks.set(game.date,block);
    for(const [i,key] of keys.entries()){
      const bin=sums.bins[Math.min(9,Math.floor(p[key]*10))];
      bin.n++;bin.p+=p[key];bin.y+=Number(['H','D','A'][i]===actual);
    }
  }
  const scored=Object.fromEntries(Object.entries(cohorts).map(([name,sum])=>{
    const n=sum.n;
    if(!n)return [name,{n,total:sum.total,brier:null,baseline_brier:null,log_loss:null,baseline_log_loss:null,ece:null}];
    return [name,{n,total:sum.total,brier:round(sum.modelBrier/n),baseline_brier:round(sum.baselineBrier/n),
      log_loss:round(sum.modelLogLoss/n),baseline_log_loss:round(sum.baselineLogLoss/n),
      ece:round(sum.bins.reduce((total,bin)=>total+Math.abs(bin.p-bin.y),0)/(3*n)),
      validation_dates:sum.blocks.size,brier_gain_approx95:improvementInterval(sum.blocks,n,(sum.baselineBrier-sum.modelBrier)/n,'brier'),
      log_loss_gain_approx95:improvementInterval(sum.blocks,n,(sum.baselineLogLoss-sum.modelLogLoss)/n,'logLoss')}];
  }));
  const failures=Object.entries(scored).flatMap(([key,metric])=>{
    if(metric.n<policy[key].minimum)return [key.toUpperCase()+'_INSUFFICIENT_VALIDATION_SAMPLE'];
    if(metric.brier>metric.baseline_brier-policy.brierMargin||metric.log_loss>metric.baseline_log_loss-policy.logLossMargin)
      return [key.toUpperCase()+'_BASELINE_NOT_BEATEN'];
    if(metric.ece>policy.calibrationLimit)return [key.toUpperCase()+'_CALIBRATION_GATE'];
    return [];
  });
  return {admitted:!failures.length,failures, ...scored};
}

export function domesticReplay(competition,rows,cutoff,leagueFiles){
  return leagueWalkForward(rows,(game,history,asof,kickoff)=>{
    const forecast=Core.forecast({fixture_key:game.home+'|'+game.away,competition,
      home_team:game.home,away_team:game.away,kickoff:new Date(kickoff).toISOString()},history,asof,false,leagueFiles);
    return forecast.status==='MODEL_ONLY'?forecast.probabilities:null;
  },cutoff);
}
