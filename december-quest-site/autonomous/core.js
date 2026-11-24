/* December Quest autonomous PREMATCH model: purely deterministic, no wagers, no live feeds. */
import { evaluateQuote, modelMarkets } from './markets.js';

const MODEL_VERSION='DQ-POISSON-0.3';
const LEAGUE_FILES={EPL:'E0',LALIGA:'SP1',SERIEA:'I1',BUNDES:'D1',LIGUE1:'F1'};
const ALIASES={
 EPL:{'Hull City':'Hull','Nottingham Forest':"Nott'm Forest",'Manchester City':'Man City','Manchester United':'Man United'},
 LALIGA:{'Deportivo Alavés':'Alaves','FC Barcelona':'Barcelona','Celta Vigo':'Celta','Atlético Madrid':'Ath Madrid','Real Betis':'Betis','Sevilla FC':'Sevilla','Málaga CF':'Malaga','Elche CF':'Elche','Racing Santander':'Santander','Real Madrid CF':'Real Madrid','CA Osasuna':'Osasuna','Espanyol':'Espanol'},
 SERIEA:{'Bologna FC 1909':'Bologna','AS Roma':'Roma','SSC Napoli':'Napoli','US Lecce':'Lecce','AC Milan':'Milan','Parma Calcio 1913':'Parma','ACF Fiorentina':'Fiorentina','Cagliari Calcio':'Cagliari','Udinese Calcio':'Udinese','Frosinone Calcio':'Frosinone','Como 1907':'Como','Juventus FC':'Juventus','AC Monza':'Monza'},
 BUNDES:{'Bayern München':'Bayern Munich','SC Paderborn 07':'Paderborn','Hamburger SV':'Hamburg','FC Schalke 04':'Schalke 04'},
 LIGUE1:{'Toulouse FC':'Toulouse','Paris Saint-Germain':'Paris SG','RC Strasbourg Alsace':'Strasbourg','FC Lorient':'Lorient','AS Monaco':'Monaco','Angers SCO':'Angers','RC Lens':'Lens','Havre AC':'Le Havre','Le Mans FC':'Le Mans','Olympique de Marseille':'Marseille','OGC Nice':'Nice','AJ Auxerre':'Auxerre','Stade Brestois 29':'Brest','ESTAC Troyes':'Troyes','Olympique Lyonnais':'Lyon'}
};
const cmp=x=>String(x||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'').trim();
const canonical=(league,team)=>cmp(ALIASES[league]?.[team]||team);
const bounded=(x,lo,hi)=>Math.min(hi,Math.max(lo,x));
const rounded=(x,d=4)=>Number(x.toFixed(d));
function parseCsv(raw){
 if(typeof raw!=='string'||raw.length<15||raw.length>4500000||raw.slice(0,200).includes('<html'))throw Error('CSV_BAD_FORMAT');
 raw=raw.replace(/^\uFEFF/,'');
 const matrix=[];let row=[],cell='',quoted=false;
 for(let i=0;i<raw.length;i++){
  const ch=raw[i];
  if(ch==='"'){if(quoted&&raw[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}
  else if(ch===','&&!quoted){row.push(cell);cell='';}
  else if((ch==='\n'||ch==='\r')&&!quoted){if(ch==='\r'&&raw[i+1]==='\n')i++;row.push(cell);cell='';if(row.some(v=>v!==''))matrix.push(row);row=[];}
  else cell+=ch;
 }
 if(quoted)throw Error('CSV_UNCLOSED_QUOTE');
 if(cell||row.length){row.push(cell);matrix.push(row);}
 const headers=matrix.shift()?.map(v=>v.trim())||[];
 if(!headers.includes('HomeTeam')||!headers.includes('AwayTeam'))throw Error('CSV_WRONG_SCHEMA');
 const records=[];
 for(const r of matrix){if(r.length<3)continue;const o={};headers.forEach((k,i)=>{if(k)o[k]=r[i]??'';});records.push(o);}
 return records;
}
function csvDate(v){
 const m=String(v||'').trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/);
 if(!m)return null;const y=Number(m[3])<100?2000+Number(m[3]):Number(m[3]);
 const d=new Date(Date.UTC(y,Number(m[2])-1,Number(m[1]),12));
 return d.getUTCFullYear()===y&&d.getUTCMonth()===Number(m[2])-1&&d.getUTCDate()===Number(m[1])?d:null;
}
function resultsFromCsv(text,competition,cutoff){
 const records=parseCsv(text),out=[],today=new Date(cutoff).toISOString().slice(0,10);
 for(const x of records){
  const date=csvDate(x.Date),hg=Number(x.FTHG),ag=Number(x.FTAG);
  if(x.Div!==LEAGUE_FILES[competition]||!date||date.toISOString().slice(0,10)>=today||x.FTHG===''||x.FTAG===''||!Number.isInteger(hg)||!Number.isInteger(ag)||hg<0||ag<0||hg>12||ag>12)continue;
  const home=canonical(competition,x.HomeTeam),away=canonical(competition,x.AwayTeam);
  if(!home||!away||home===away)continue;
  const xg=[x.HxG,x.AxG].map(value=>typeof value==='string'&&/^\d+(?:\.\d+)?$/.test(value.trim())?Number(value):null);
  const validXg=xg.every(value=>value!==null&&value>=0&&value<=15);
  out.push({home,away,hg,ag,date:date.toISOString().slice(0,10),when:date.getTime(),
   ...(validXg?{hxg:xg[0],axg:xg[1]}:{})});
 }
 return out;
}
function poisson(lambda,k){let p=Math.exp(-lambda);for(let i=1;i<=k;i++)p*=lambda/i;return p;}
function scoreGrid(lambdaH,lambdaA){
 const pH=Array.from({length:13},(_,i)=>poisson(lambdaH,i));
 const pA=Array.from({length:13},(_,i)=>poisson(lambdaA,i));
 const grid=[]; let sum=0;
 for(let home=0;home<pH.length;home++)for(let away=0;away<pA.length;away++){
  const probability=pH[home]*pA[away];
  grid.push({home,away,probability});sum+=probability;
 }
 if(!(sum>.999))throw Error('POISSON_MASS_INVALID');
 return grid.map(cell=>({...cell,probability:cell.probability/sum}));
}
function outcomes(grid){
 let home=0,draw=0,away=0,btts=0,over15=0,over25=0,over35=0,homeOver05=0,awayOver05=0;
 for(const {home:h,away:a,probability:p} of grid){
  if(h>a)home+=p;else if(h===a)draw+=p;else away+=p;
  if(h>0&&a>0)btts+=p;
  if(h+a>1)over15+=p;if(h+a>2)over25+=p;if(h+a>3)over35+=p;
  if(h>0)homeOver05+=p;if(a>0)awayOver05+=p;
 }
 const a={home,draw,away,btts,o15:over15,o25:over25,o35:over35,home05:homeOver05,away05:awayOver05};
 return Object.fromEntries(Object.entries(a).map(([k,v])=>[k,rounded(bounded(v,0,1),5)]));
}
function strength(inputs,side,lgF,lgA,alpha=4){
 const played=inputs.length;
 if(!played)return {attack:1,defense:1,effective:0,played:0};
 let weight=0,gf=0,ga=0;
 for(const x of inputs){weight+=x.weight;gf+=x.gf*x.weight;ga+=x.ga*x.weight;}
 return {attack:((gf+alpha*lgF)/(weight+alpha))/lgF,
         defense:((ga+alpha*lgA)/(weight+alpha))/lgA,
         effective:weight,played};
}
function xgSummary(rows,homeSide){
 const available=rows.filter(row=>Number.isFinite(row.hxg)&&Number.isFinite(row.axg));
 const count=available.length;
 if(!count)return {matches:0,total:rows.length,xg:null,xga:null};
 return {matches:count,total:rows.length,
  xg:rounded(available.reduce((sum,row)=>sum+(homeSide?row.hxg:row.axg),0)/count,3),
  xga:rounded(available.reduce((sum,row)=>sum+(homeSide?row.axg:row.hxg),0)/count,3)};
}
function forecast(fixt,seasonRows,now=Date.now(),includeMarkets=true){
 const kickoff=Date.parse(fixt.kickoff);
 const status={fixture_key:fixt.fixture_key,competition:fixt.competition,kickoff:fixt.kickoff,
  generated_at:new Date(now).toISOString(),source_cutoff:new Date(now).toISOString(),
  model_version:MODEL_VERSION,status:'INSUFFICIENT_DATA',verdict:'пропуск',risk_class:'D',
  probabilities:{},markets:[],best_candidate:{},sample_n:0,evidence:{},notes:'Не подтверждено value: SHADOW / PASS'};
 if(!LEAGUE_FILES[fixt.competition]){status.status='UNSUPPORTED_LEAGUE';status.notes='Турнир вне покрытия публичной исторической модели. PASS.';return status;}
 if(!(Number.isFinite(kickoff)&&kickoff>now+20*60000)){status.status='SOURCE_ERROR';status.notes='Матч уже начался или слишком близко: прогноз запрещён.';return status;}
 if(!Array.isArray(seasonRows)||!seasonRows.length){status.status='SOURCE_ERROR';status.notes='Нет актуальной истории в разрешённых CSV. PASS.';return status;}
 const day=new Date(now).toISOString().slice(0,10);
 const current=seasonRows.filter(r=>r.date<day&&Number.isFinite(r.when)&&r.when<now);
 if(current.length<24){status.notes='Истории лиги слишком мало. PASS.';return status;}
 const home=canonical(fixt.competition,fixt.home_team),away=canonical(fixt.competition,fixt.away_team);
 const matchesH=current.filter(r=>r.home===home||r.away===home);
 const matchesA=current.filter(r=>r.home===away||r.away===away);
 const hHome=current.filter(r=>r.home===home),aAway=current.filter(r=>r.away===away);
 status.sample_n=Math.min(matchesH.length,matchesA.length);
 status.evidence={home_team:home,away_team:away,home_matches:matchesH.length,away_matches:matchesA.length,
  home_at_home:hHome.length,away_away:aAway.length,training_matches:current.length,
  oldest_training_date:current.reduce((z,r)=>r.date<z?r.date:z,'9999-99-99'),
  latest_training_date:current.reduce((z,r)=>r.date>z?r.date:z,'0000-00-00'),
  source:'football-data.co.uk: current and previous season results',validation:'NO_ODDS_OR_LINEUPS',model_version:MODEL_VERSION,
  boundary:'completed matches strictly before both now and fixture kickoff'};
 if(includeMarkets)status.evidence.xg={source:'football-data.co.uk HxG/AxG',
  home_at_home:xgSummary(hHome,true),away_away:xgSummary(aAway,false)};
 if(matchesH.length<6||matchesA.length<6||hHome.length<2||aAway.length<2){
  status.notes='Недостаточная командная история, точная идентификация или домашняя/гостевая выборка. PASS.';return status;
 }
 const wRows=current.map(r=>({...r,weight:bounded(Math.exp(-(now-r.when)/(200*86400000)),.05,1)}));
 let leagueN=0,leagueH=0,leagueA=0;
 for(const r of wRows){leagueN+=r.weight;leagueH+=r.hg*r.weight;leagueA+=r.ag*r.weight;}
 const leagueHome=bounded(leagueH/leagueN,.6,2.5),leagueAway=bounded(leagueA/leagueN,.5,2.5);
 const h=strength(wRows.filter(r=>r.home===home).map(r=>({weight:r.weight,gf:r.hg,ga:r.ag})),'home',leagueHome,leagueAway);
 const a=strength(wRows.filter(r=>r.away===away).map(r=>({weight:r.weight,gf:r.ag,ga:r.hg})),'away',leagueAway,leagueHome);
 const lambdaH=bounded(leagueHome*h.attack*a.defense,.35,3.2),lambdaA=bounded(leagueAway*a.attack*h.defense,.35,3.2);
 const grid=scoreGrid(lambdaH,lambdaA);
 const probs=outcomes(grid);
 status.probabilities={...probs,expected_goals_home:rounded(lambdaH,3),expected_goals_away:rounded(lambdaA,3)};
 if(includeMarkets)status.markets=modelMarkets(grid,scoreGrid(leagueHome,leagueAway));
 let homeWins=1,draws=1,awayWins=1;
 for(const row of current){
  if(row.hg>row.ag)homeWins++;else if(row.hg===row.ag)draws++;else awayWins++;
 }
 const total=homeWins+draws+awayWins;
 status.evidence.baseline_1x2={home:homeWins/total,draw:draws/total,away:awayWins/total};
 status.status='MODEL_ONLY';
 status.evidence={...status.evidence,team_home_strength:{attack:rounded(h.attack,3),defense:rounded(h.defense,3)},team_away_strength:{attack:rounded(a.attack,3),defense:rounded(a.defense,3)},goals_source:'FT score only: not xG',
  fit_gate:'UNVERIFIED',lineups_gate:'UNVERIFIED',calibration_gate:'UNVERIFIED'};
 status.notes='Автоматические модельные вероятности. Тактический fit, составы, калибровка и котировки не подтверждены: PASS.';
 return status;
}
function attachQuotes(pred,weeklyRows,fixture,observedAt){
 if(pred.status!=='MODEL_ONLY'||!Array.isArray(weeklyRows)||!Number.isFinite(observedAt)||
    observedAt>=Date.parse(fixture.kickoff)||observedAt>Date.parse(pred.source_cutoff))return pred;
 const day=new Date(fixture.kickoff).toISOString().slice(0,10);
 const found=weeklyRows.filter(row=>csvDate(row.Date)?.toISOString().slice(0,10)===day&&
  row.Div===LEAGUE_FILES[fixture.competition]&&
  canonical(fixture.competition,row.HomeTeam)===canonical(fixture.competition,fixture.home_team)&&
  canonical(fixture.competition,row.AwayTeam)===canonical(fixture.competition,fixture.away_team));
 if(found.length!==1)return pred;
 const raw=found[0];
 const books={B365:'Bet365',BFD:'Betfred',BV:'Betvictor',BW:'Bwin',PP:'Paddy Power',SKB:'Sky Bet'};
 const resultSuffix={home:'H',draw:'D',away:'A'};
 const rawLine=typeof raw.AHh==='string'&&raw.AHh.trim()?Number(raw.AHh):null;
 const marketOdds=pred.markets.map(m=>{
  const offers=[];
  for(const [prefix,bookmaker] of Object.entries(books)){
   let field;
   if(m.kind==='1X2')field=prefix+resultSuffix[m.side];
   else if(prefix==='B365'&&m.kind==='TG'&&m.line===2.5)field=prefix+(m.side==='over'?'>':'<')+'2.5';
   else if(prefix==='B365'&&rawLine!==null&&['DNB','AH'].includes(m.kind)&&
      m.line===(m.side==='home'?rawLine:-rawLine))field=prefix+(m.side==='home'?'AHH':'AHA');
   if(!field)continue;
   const price=Number(raw[field]);
   const metrics=evaluateQuote(m.settlement,price);
   if(!metrics)continue;
   const {expected_value,...diagnostics}=metrics;
   offers.push({...diagnostics,odds:price,conditional_ev_pct:expected_value,
    source:'football-data.co.uk/fixtures.csv',bookmaker,observed_at:new Date(observedAt).toISOString(),
    quote_timestamp_verified:false,value_verified:false,
    death_test:diagnostics.sensitivity['-0.05']>0?'PASS_CONDITIONAL':'FAIL_CONDITIONAL'});
  }
  offers.sort((a,b)=>b.odds-a.odds);
  return offers.length?{...m,...offers[0],quotes:offers}:m;
 });
 const quoted=marketOdds.filter(m=>m.odds!==null).sort((a,b)=>b.conditional_ev_pct-a.conditional_ev_pct);
 if(!quoted.length)return pred;
 const alternative=quoted.find(m=>m.market!==quoted[0].market);
 return {...pred,markets:marketOdds,status:'WAITING_ODDS',
  best_candidate:{...quoted[0],alternative:alternative?{market:alternative.market,pick:alternative.pick,conditional_ev_pct:alternative.conditional_ev_pct}:null},
  evidence:{...pred.evidence,quote_found:true,quote_observed_fetch_at:new Date(observedAt).toISOString(),
   quote_provider_timestamp:null,quote_source:'https://football-data.co.uk/fixtures.csv'},
  notes:'Время публикации котировки не подтверждено. EV условный.'};
}
const Core={MODEL_VERSION,LEAGUE_FILES,ALIASES,canonical,parseCsv,csvDate,resultsFromCsv,poisson,
 outcomes:(home,away)=>outcomes(scoreGrid(home,away)),forecast,attachQuotes};
export default Core;
