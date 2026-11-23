/* December Quest autonomous PREMATCH model: purely deterministic, no wagers, no live feeds. */
const MODEL_VERSION='DQ-POISSON-0.1';
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
 const matrix=[];let row=[],cell='',quoted=false;
 for(let i=0;i<raw.length;i++){
  const ch=raw[i];
  if(ch==='"'){if(quoted&&raw[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}
  else if(ch===','&&!quoted){row.push(cell);cell='';}
  else if((ch==='\n'||ch==='\r')&&!quoted){if(ch==='\r'&&raw[i+1]==='\n')i++;row.push(cell);cell='';if(row.some(v=>v!==''))matrix.push(row);row=[];}
  else cell+=ch;
 }
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
 const records=parseCsv(text),out=[],now=Math.min(cutoff,Date.now()),today=new Date(now).toISOString().slice(0,10);
 for(const x of records){
  const date=csvDate(x.Date),hg=Number(x.FTHG),ag=Number(x.FTAG);
  if(!date||date.toISOString().slice(0,10)>=today||x.FTHG===''||x.FTAG===''||!Number.isInteger(hg)||!Number.isInteger(ag)||hg<0||ag<0||hg>12||ag>12)continue;
  const home=canonical(competition,x.HomeTeam),away=canonical(competition,x.AwayTeam);
  if(!home||!away||home===away)continue;
  out.push({home,away,hg,ag,date:date.toISOString().slice(0,10),when:date.getTime()});
 }
 return out;
}
function poisson(lambda,k){let p=Math.exp(-lambda);for(let i=1;i<=k;i++)p*=lambda/i;return p;}
function outcomes(lambdaH,lambdaA){
 const pH=Array.from({length:13},(_,i)=>poisson(lambdaH,i));
 const pA=Array.from({length:13},(_,i)=>poisson(lambdaA,i));
 let sum=0,home=0,draw=0,away=0,btts=0,over15=0,over25=0,over35=0,homeOver05=0,awayOver05=0;
 for(let h=0;h<pH.length;h++)for(let a=0;a<pA.length;a++){
  const p=pH[h]*pA[a];sum+=p;
  if(h>a)home+=p;else if(h===a)draw+=p;else away+=p;
  if(h>0&&a>0)btts+=p;
  if(h+a>1)over15+=p;if(h+a>2)over25+=p;if(h+a>3)over35+=p;
  if(h>0)homeOver05+=p;if(a>0)awayOver05+=p;
 }
 if(!(sum>.999))throw Error('POISSON_MASS_INVALID');
 const a={home:home/sum,draw:draw/sum,away:away/sum,btts:btts/sum,o15:over15/sum,o25:over25/sum,o35:over35/sum,home05:homeOver05/sum,away05:awayOver05/sum};
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
function forecast(fixt,seasonRows,now=Date.now()){
 const kickoff=Date.parse(fixt.kickoff);
 const status={fixture_key:fixt.fixture_key,competition:fixt.competition,kickoff:fixt.kickoff,
  generated_at:new Date(now).toISOString(),source_cutoff:new Date(now).toISOString(),
  model_version:MODEL_VERSION,status:'INSUFFICIENT_DATA',verdict:'пропуск',risk_class:'D',
  probabilities:{},markets:[],best_candidate:{},sample_n:0,evidence:{},notes:'Не подтверждено value: SHADOW / PASS'};
 if(!LEAGUE_FILES[fixt.competition]){status.status='UNSUPPORTED_LEAGUE';status.notes='Турнир вне покрытия публичной исторической модели. PASS.';return status;}
 if(!(Number.isFinite(kickoff)&&kickoff>now+20*60000)){status.status='SOURCE_ERROR';status.notes='Матч уже начался или слишком близко: прогноз запрещён.';return status;}
 if(!Array.isArray(seasonRows)||!seasonRows.length){status.status='SOURCE_ERROR';status.notes='Нет актуальной истории в разрешённых CSV. PASS.';return status;}
 const current=seasonRows.filter(r=>r.when<Math.min(now,kickoff)&&r.when<now&&r.when<kickoff);
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
 const probs=outcomes(lambdaH,lambdaA);
 status.probabilities={...probs,expected_goals_home:rounded(lambdaH,3),expected_goals_away:rounded(lambdaA,3)};
 const specs=[
 ['1X2','П1',probs.home],['1X2','Х',probs.draw],['1X2','П2',probs.away],
 ['Двойной шанс','1X',probs.home+probs.draw],['Двойной шанс','X2',probs.away+probs.draw],
 ['Тотал','ТБ 1.5',probs.o15],['Тотал','ТБ 2.5',probs.o25],['Тотал','ТБ 3.5',probs.o35],
 ['ОЗ','Да',probs.btts],['ОЗ','Нет',1-probs.btts],
 ['ИТ хозяев','ИТБ 0.5',probs.home05],['ИТ гостей','ИТБ 0.5',probs.away05]
 ];
 status.markets=specs.map(([market,pick,p])=>({market,pick,probability:rounded(p,5),odds:null,implied:null,ev:null,source:'MODEL_ONLY',verdict:'пропуск'}));
 status.status='MODEL_ONLY';
 status.evidence={...status.evidence,team_home_strength:{attack:rounded(h.attack,3),defense:rounded(h.defense,3)},team_away_strength:{attack:rounded(a.attack,3),defense:rounded(a.defense,3)},goals_source:'FT score only: not xG',
  fit_gate:'UNVERIFIED',lineups_gate:'UNVERIFIED',calibration_gate:'UNVERIFIED'};
 status.notes='Автоматические модельные вероятности. Тактический fit, составы, калибровка и котировки не подтверждены: PASS.';
 return status;
}
function attachQuotes(pred,weeklyRows,fixture,cutoff=Date.now()){
 if(pred.status!=='MODEL_ONLY'||!Array.isArray(weeklyRows))return pred;
 const day=new Date(fixture.kickoff).toISOString().slice(0,10);
 const found=weeklyRows.filter(r=>{
  const date=csvDate(r.Date);return date?.toISOString().slice(0,10)===day&&r.Div===LEAGUE_FILES[fixture.competition]&&
  canonical(fixture.competition,r.HomeTeam)===canonical(fixture.competition,fixture.home_team)&&
  canonical(fixture.competition,r.AwayTeam)===canonical(fixture.competition,fixture.away_team);
 });
 if(found.length!==1)return pred;
 const x=found[0],stake=1000;
 const variants=[['П1','B365H','home'],['Х','B365D','draw'],['П2','B365A','away']];
 let options=[];
 for(const [pick,k,pName] of variants){
  const odds=Number(x[k]),p=pred.probabilities[pName];
  if(!Number.isFinite(odds)||odds<=1.01||odds>100||typeof p!=='number')continue;
  const conditionalEV=rounded(stake*(p*odds-1),2);
  options.push({market:'1X2',pick,probability:p,odds,implied:rounded(1/odds,5),
   conditional_ev:conditionalEV,ev:null,source:'football-data.co.uk/fixtures.csv',bookmaker:'B365 via historical aggregator',
   quote_timestamp_verified:false,value_verified:false,verdict:'пропуск'});
 }
 if(!options.length)return pred;
 pred.markets=pred.markets.map(m=>options.find(x=>x.market===m.market&&x.pick===m.pick)||m);
 const candidates=options.filter(x=>x.conditional_ev>0).sort((a,b)=>b.conditional_ev-a.conditional_ev);
 if(candidates.length)pred.best_candidate={...candidates[0],reason:'ONLY CONDITIONAL EV; source quote freshness, calibration and tactical fit UNVERIFIED'};
 pred.status='WAITING_ODDS';
 pred.evidence={...pred.evidence,quote_found:true,quote_observed_fetch_at:new Date(cutoff).toISOString(),
  quote_provider_timestamp:null,quote_source:'https://football-data.co.uk/fixtures.csv'};
 pred.notes='Модель и котировка сопоставлены, но timestamp БК не подтверждён; EV условный. Без независимой проверки линии, состава и P — PASS.';
 return pred;
}
const Core={MODEL_VERSION,LEAGUE_FILES,ALIASES,canonical,parseCsv,csvDate,resultsFromCsv,poisson,outcomes,forecast,attachQuotes};
export default Core;