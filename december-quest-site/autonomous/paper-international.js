/* International results only. Regulation scores, UTC-day batches and fixed parameters. */
import Core from './core.js';
import { modelMarkets } from './markets.js';
import { leagueWalkForward, paperPolicy } from './paper-validation.js';
import { europeTeam, europeAssociation, transnationalForecast } from './paper-europe.js';

const day=86400000;
const bounded=(x,low,high)=>Math.min(high,Math.max(low,x));
const rate=x=>bounded(x,.35,3.2);
const models=['DQ-EUROPE-ELO-0.1','DQ-INTERNATIONAL-ELO-0.2','DQ-INTERNATIONAL-POISSON-0.1'];
const key=(competition,home,away,date)=>[competition,home,away,date].join('|');
const policy={...paperPolicy,archive:{...paperPolicy.archive,since:'2025-08-01'}};
const displaced=new Set(['UKR','ISR','BLR']);
const neutral=game=>game.neutral===true||displaced.has(game.homeCountry??europeAssociation(game.home));

function prior(state,competition,balanced){
  const t=state.tournaments.get(competition)??{home:0,away:0,n:0};
  const h=(t.home+30*1.55)/(t.n+30),a=(t.away+30*1.2)/(t.n+30);
  return balanced?[(h+a)/2,(h+a)/2]:[h,a];
}

function snapshot(state,fixture){
  const h=state.clubs.get(fixture.home),a=state.clubs.get(fixture.away);
  const [baseH,baseA]=prior(state,fixture.competition,neutral(fixture));
  const homeCountry=fixture.homeCountry??h?.country??europeAssociation(fixture.home);
  const awayCountry=fixture.awayCountry??a?.country??europeAssociation(fixture.away);
  const countryDiff=(state.countries.get(homeCountry)??0)-(state.countries.get(awayCountry)??0);
  const strength=((h?.elo??0)-(a?.elo??0)+.35*countryDiff)/575;
  return {h,a,baseH,baseA,homeCountry,awayCountry,
    elo:[rate(baseH*Math.exp(strength)),rate(baseA*Math.exp(-strength))],
    poisson:[
      rate(baseH*Math.exp((h?.attack??0)+(a?.defence??0)+.001*countryDiff)),
      rate(baseA*Math.exp((a?.attack??0)+(h?.defence??0)-.001*countryDiff))
    ]};
}

function learn(state,game){
  const p=snapshot(state,game);
  const expected=1/(1+10**(-((p.h?.elo??0)-(p.a?.elo??0)+(neutral(game)?0:50))/400));
  const observed=game.hg===game.ag ? .5 : Number(game.hg>game.ag);
  const diff=observed-expected;
  const residual=[game.hg-p.poisson[0],game.ag-p.poisson[1]].map(x=>bounded(x,-3,3));
  for(const [i,team] of [game.home,game.away].entries()){
    const prev=state.clubs.get(team)??{n:0,elo:0,attack:0,defence:0};
    const country=(i?p.awayCountry:p.homeCountry)??prev.country;
    const elapsed=Number.isFinite(prev.when)?Math.max(0,game.when-prev.when)/day:0;
    const retain=Math.exp(-Math.max(0,elapsed-90)/730);
    state.clubs.set(team,{n:prev.n+1,when:game.when,country,elo:retain*prev.elo+(i?-24:24)*diff,
      attack:bounded(retain*prev.attack+.052*residual[i],-.85,.85),
      defence:bounded(retain*prev.defence+.052*residual[1-i],-.85,.85)});
  }
  if(p.homeCountry&&p.awayCountry&&p.homeCountry!==p.awayCountry){
    state.countries.set(p.homeCountry,(state.countries.get(p.homeCountry)??0)+8*diff);
    state.countries.set(p.awayCountry,(state.countries.get(p.awayCountry)??0)-8*diff);
  }
  const t=state.tournaments.get(game.competition)??{home:0,away:0,n:0};
  state.tournaments.set(game.competition,{home:t.home+(neutral(game)?(game.hg+game.ag)/2:game.hg),
    away:t.away+(neutral(game)?(game.hg+game.ag)/2:game.ag),n:t.n+1});
}

function admissions(p,game,state){
  const n=Math.min(p.h?.n??0,p.a?.n??0);
  if(!p.homeCountry||!p.awayCountry)return {reason:'UNMAPPED_ASSOCIATION'};
  if(n<4)return {reason:'INSUFFICIENT_TEAM_INTERNATIONAL_HISTORY'};
  if(!state.tournaments.has(game.competition)||state.tournaments.get(game.competition).n<60)
    return {reason:'INSUFFICIENT_INTERNATIONAL_HISTORY'};
  return {n};
}

export function internationalState(rows,cutoff){
  const today=new Date(cutoff).toISOString().slice(0,10);
  const matches=rows.filter(x=>x.date<today&&x.when<cutoff).sort((a,b)=>a.when-b.when||
    a.home.localeCompare(b.home)||a.away.localeCompare(b.away));
  const state={clubs:new Map(),countries:new Map(),tournaments:new Map()};
  const predicted=new Map();
  for(let first=0;first<matches.length;){
    let end=first+1;
    while(end<matches.length&&matches[end].date===matches[first].date)end++;
    for(const game of matches.slice(first,end)){
      const p=snapshot(state,game);
      if(neutral(game)||admissions(p,game,state).reason)continue;
      predicted.set(key(game.competition,game.home,game.away,game.date),
        [Core.outcomes(...p.elo),Core.outcomes(...p.poisson)]);
    }
    for(const game of matches.slice(first,end))learn(state,game);
    first=end;
  }
  return {matches,state,predicted};
}

export function validateInternational(competition,history,cutoff,prepared=internationalState(history,cutoff)){
  const target=prepared.matches.filter(x=>x.competition===competition);
  const evaluations=models.map((model,index)=>({model,...leagueWalkForward(target,(game,_training,asof)=>{
    if(neutral(game))return null;
    if(index===0)return transnationalForecast({competition,home_team:game.home,away_team:game.away},
      prepared.matches,asof,false).probabilities;
    return prepared.predicted.get(key(competition,game.home,game.away,game.date))?.[index-1];
  },cutoff,policy)}));
  // Select once using the archive. The recent holdout can veto the chosen model.
  const eligible=evaluations.filter(x=>!x.failures.some(f=>f.startsWith('ARCHIVE_')))
    .sort((a,b)=>a.archive.log_loss-b.archive.log_loss||a.archive.brier-b.archive.brier);
  const selected=eligible[0];
  if(!selected)return {...evaluations[0],admitted:false,selected_model:null,candidates:evaluations};
  return {...selected,selected_model:selected.model,candidates:evaluations};
}

export function forecastInternational(fixture,history,cutoff,model,prepared=internationalState(history,cutoff)){
  const {state,matches}=prepared;
  const game={competition:fixture.competition,home:europeTeam(fixture.home_team),away:europeTeam(fixture.away_team)};
  if(fixture.displaced_home===true||neutral(game))return {reason:'VENUE_OUTSIDE_VALIDATION'};
  if(model===models[0])return {...transnationalForecast(fixture,matches,cutoff,true),model_version:model};
  const p=snapshot(state,game), eligible=admissions(p,game,state);
  if(eligible.reason)return eligible;
  const lambda=model===models[1]?p.elo:p.poisson;
  const grid=Core.scoreGrid(...lambda);
  return {model_version:model,sample_n:eligible.n,
    probabilities:{...Core.outcomes(...lambda),expected_goals_home:lambda[0],expected_goals_away:lambda[1]},
    markets:modelMarkets(grid,Core.scoreGrid(p.baseH,p.baseA)),
    evidence:{home_association:p.homeCountry,away_association:p.awayCountry,
      latest_training_date:matches.at(-1)?.date,training_matches:matches.length,
      source:'International regulation results',uncertainty:'See date-blocked holdout score intervals'}};
}
