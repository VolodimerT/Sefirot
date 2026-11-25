import Core from './core.js';
import { duplicates } from './run.js';
import { paperCompetitions, paperDomestic, paperOddsSports } from './paper-registry.js';
import { domesticReplay } from './paper-validation.js';
import { europeTeam } from './paper-europe.js';
import { internationalState, validateInternational, forecastInternational } from './paper-international.js';
import { attachOdds, collectTimestampedOdds } from './odds-gateway.js';
import { collectOddsbunch, oddsbunchOffers } from './oddsbunch.js';
import { auditWeekly } from './paper-sources.js';
import { historyProfile } from './history.js';
import { collectGateway } from './gateway.js';

export const modes=Object.freeze({december:'DECEMBER_QUEST',daily:'DAILY_PAPER_TEST',replay:'HISTORICAL_REPLAY'});
const kyiv=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Kyiv',year:'numeric',month:'2-digit',day:'2-digit'});
const numericTime=value=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}T\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value)
  ? Date.parse(value) : NaN;
const contextLeagues=Object.freeze({EPL:39,LALIGA:140,SERIEA:135,BUNDES:78,LIGUE1:61,CHAMPIONSHIP:40,
  ENGLAND_LEAGUE_1:41,ENGLAND_LEAGUE_2:42,BUNDES_2:79,SERIEB:136,SEGUNDA:141,LIGUE2:62,
  PORTUGAL:94,NETHERLANDS:88,BELGIUM:144,TURKEY:203,UCL:2,UEL:3,UECL:848,DFB_POKAL:81,UPL:333,NATIONAL_LEAGUE:43});
const identity=(competition,name)=>paperCompetitions.get(competition)?.family==='international'?europeTeam(name):Core.canonical(competition,name);

function dailyInput(date, calendar){
  if(typeof date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(date)||!Number.isFinite(Date.parse(date+'T00:00:00Z'))
    ||new Date(date+'T00:00:00Z').toISOString().slice(0,10)!==date)throw Error('INVALID_PAPER_DATE');
  if(!Array.isArray(calendar)||calendar.length>300)throw Error('INVALID_PAPER_CALENDAR');
  const keys=new Set();
  for(const row of calendar){
    if(!row||!['fixture_key','competition','home_team','away_team'].every(k=>typeof row[k]==='string'&&row[k].trim()&&row[k].length<=160)
      ||!Number.isFinite(numericTime(row.kickoff))||keys.has(row.fixture_key))throw Error('INVALID_PAPER_FIXTURE');
    keys.add(row.fixture_key);
  }
  return calendar.filter(row=>kyiv.format(new Date(row.kickoff))===date);
}
const confirmed=(f,cutoff)=>{
  const observed=numericTime(f.checked_at);
  return f.timing_status==='confirmed'&&observed<=cutoff&&cutoff-observed<=24*3600000
    &&Array.isArray(f.fixture_sources)&&new Set(f.fixture_sources.flatMap(value=>{
      try{const url=new URL(value);return url.protocol==='https:'?[url.hostname]:[];}catch{return [];}
    })).size>=2;
};

async function loadCompetitions(codes, sources, cutoff){
  const international=codes.filter(code=>paperCompetitions.get(code)?.family==='international');
  const european=international.length?sources.european(cutoff,international).then(packet=>{
    const states=new Map();
    return {packet,analysis(code){
      const cup=code==='DFB_POKAL';
      if(!states.has(cup)){
        const results=packet.rows.filter(row=>(row.competition==='DFB_POKAL')===cup);
        states.set(cup,internationalState(results,cutoff));
      }
      return states.get(cup);
    }};
  }):null;
  const loaded=[];
  for(let i=0;i<codes.length;i+=3){
    const batch=await Promise.all(codes.slice(i,i+3).map(async code=>[code,await loadComp(code,sources,cutoff,european)]));
    loaded.push(...batch);
  }
  return loaded;
}

async function loadComp(code,sources,cutoff,europe){
  const spec=paperCompetitions.get(code);
  if(!spec)return {error:'COMPETITION_NOT_REGISTERED'};
  if(spec.missing)return {error:spec.missing};
  if(spec.family==='international'){
    const {packet,analysis}=await europe;
    const cup=code==='DFB_POKAL';
    const missing=packet.sources.filter(x=>x.error&&(x.competition==='DFB_POKAL')===cup);
    if(missing.length)return {packet,error:'INTERNATIONAL_HISTORY_INCOMPLETE'};
    const prepared=analysis(code);
    return {packet,prepared,quality:validateInternational(code,packet.rows,cutoff,prepared)};
  }
  const packet=await sources.domestic(code,cutoff);
  if(packet.missing.length)return {packet,error:'DOMESTIC_HISTORY_UNAVAILABLE'};
  if(!packet.rows.some(row=>cutoff-row.when<35*86400000))return {packet,error:'DOMESTIC_HISTORY_STALE'};
  return {packet,quality:domesticReplay(code,packet.rows,cutoff,paperDomestic)};
}

export async function executeReplay({competitions,sources,cutoff}){
  if(!Array.isArray(competitions)||!competitions.length||competitions.length>paperCompetitions.size||
    new Set(competitions).size!==competitions.length||!Number.isFinite(cutoff))throw Error('INVALID_REPLAY_PARAMETERS');
  const loaded=await loadCompetitions(competitions,sources,cutoff);
  const reports=loaded.map(([competition,data])=>({competition,qualification:data.quality??null,error:data.error??null,
    sources:data.packet?.sources?.filter(x=>!x.competition||(x.competition==='DFB_POKAL')===(competition==='DFB_POKAL'))??[]}));
  return {mode:modes.replay,cutoff:new Date(cutoff).toISOString(),date_only_archive:true,prospective:false,reports};
}

function providerKickoff(fixture,packet,cutoff){
  const kickoff=Date.parse(fixture.kickoff),home=identity(fixture.competition,fixture.home_team),away=identity(fixture.competition,fixture.away_team);
  const candidates=(packet?.fixtures??[]).filter(x=>x.competition===fixture.competition&&x.home===home&&x.away===away&&
    Math.abs(x.kickoff-kickoff)<48*3600000&&x.receivedAt<=cutoff);
  if(!candidates.length)return {status:'NO_ADDITIONAL_PROVIDER_MATCH'};
  const row=candidates.length===1?candidates[0]:null;
  if(!row||row.finished||row.kickoff!==kickoff)return {status:'PROVIDER_KICKOFF_CONFLICT'};
  return {status:'MATCH',event_id:row.event_id,source:row.source,checked_at:new Date(row.receivedAt).toISOString()};
}

function currentContext(entry,cutoff){
  const valid=timestamp=>cutoff-numericTime(timestamp)>=0&&cutoff-numericTime(timestamp)<=3600000;
  if(entry?.status!=='CONFIRMED'||!valid(entry.observed_at))return null;
  return {source:'API-Football via SEFIROT gateway',fixture_id:entry.fixture_id,referee:entry.referee??null,
    injuries:valid(entry.injuries?.observed_at)&&entry.injuries.published?entry.injuries:null,
    lineups:valid(entry.lineups?.observed_at)&&entry.lineups.confirmed_teams===2?entry.lineups:null};
}

function marketGate(forecast){
  const quotes=forecast?.markets.filter(m=>m.price_verified&&Number.isFinite(m.ev))??[];
  const positive=quotes.filter(m=>m.ev>0);
  const robust=positive.filter(m=>m.death_test==='PASS_CONDITIONAL');
  return {status:!forecast?'NO_MODEL':!quotes.length?'NO_VERIFIED_PRICE':!positive.length?'NO_EDGE':
    !robust.length?'FRAGILE_EDGE':'POSITIVE_EV_CONTEXT_PENDING',priced_markets:quotes.length,
    positive_ev_markets:positive.length,robust_markets:robust.length};
}

function unsupportedCompetition(code){
  if(code.startsWith('UEFA Youth League')||code.startsWith('World Cup U17'))return 'YOUTH_MODEL_NOT_VALIDATED';
  if(code.startsWith('Asia · AFC Champions League'))return 'AFC_MODEL_NOT_VALIDATED';
  if(code.startsWith('Япония J'))return 'JAPAN_RESULTS_ADAPTER_NOT_VALIDATED';
  if(/\b(?:Cup|Trophy)\b/.test(code))return 'CUP_MODEL_NOT_VALIDATED';
  return 'COMPETITION_NOT_REGISTERED';
}

export async function executeDaily({date,calendar,sources,oddsKey='',reserveOddsKey='',contextGateway={},clock=Date.now,fetcher=fetch}){
  const rows=dailyInput(date,calendar),start=clock();
  const distinct=duplicates(rows);
  const candidates=rows.filter(row=>Date.parse(row.kickoff)>start+20*60_000);
  const competitionCodes=[...new Set(candidates.filter(row=>confirmed(row,start)&&!distinct.has(row.fixture_key)).map(row=>row.competition))];
  const [completed,weekly]=await Promise.all([loadCompetitions(competitionCodes,sources,start),
    candidates.length?sources.weekly():null]);
  const lookup=new Map(completed);
  const oddsTime=clock();
  const withModel=candidates.filter(row=>{
    const data=lookup.get(row.competition);
    return data?.quality?.admitted&&confirmed(row,oddsTime)&&row.displaced_home!==true&&
      providerKickoff(row,data.packet,oddsTime).status!=='PROVIDER_KICKOFF_CONFLICT'&&
      !distinct.has(row.fixture_key)&&Date.parse(row.kickoff)>oddsTime+20*60_000;
  });
  const [odds,reserve,context]=await Promise.all([
    collectTimestampedOdds(withModel,oddsTime,oddsKey,fetcher,clock,paperOddsSports),
    collectOddsbunch(withModel,oddsTime,reserveOddsKey,identity,fetcher,clock),
    collectGateway(contextGateway.project,contextGateway.token,withModel,oddsTime,fetcher,contextLeagues,
      (competition,a,b)=>identity(competition,a)===identity(competition,b))]);
  const cutoff=clock(), cutoffText=new Date(cutoff).toISOString();
  const fixtures=candidates.filter(row=>Date.parse(row.kickoff)>cutoff+20*60_000).map(row=>{
    const data=lookup.get(row.competition), reasons=[];
    const provider=providerKickoff(row,data?.packet,cutoff);
    const kickoffVerified=confirmed(row,cutoff)&&provider.status!=='PROVIDER_KICKOFF_CONFLICT', registered=paperCompetitions.get(row.competition);
    const contextEntry=context.fixtures.get(row.fixture_key), facts=currentContext(contextEntry,cutoff);
    if(distinct.has(row.fixture_key))reasons.push('DUPLICATE_FIXTURE');
    if(!kickoffVerified)reasons.push(provider.status==='PROVIDER_KICKOFF_CONFLICT'?provider.status:'KICKOFF_NOT_REVERIFIED');
    if(contextEntry?.status==='KICKOFF_CONFLICT')reasons.push('CONTEXT_GATEWAY_KICKOFF_CONFLICT');
    if(!registered)reasons.push(unsupportedCompetition(row.competition));
    if(registered?.missing)reasons.push(registered.missing);
    if(data?.error&&!reasons.includes(data.error))reasons.push(data.error,...(data.packet?.missing||[]));
    if(data?.quality&&!data.quality.admitted)reasons.push(...data.quality.failures);
    if(row.displaced_home===true)reasons.push('VENUE_OUTSIDE_VALIDATION');
    if(data?.packet?.sources.some(s=>!s.error&&s.receivedAt>cutoff))reasons.push('SOURCE_OBSERVED_AFTER_CUTOFF');
    let forecast=null;
    if(!reasons.length&&data?.quality?.admitted){
      if(registered.family==='international'){
        const model=forecastInternational(row,data.packet.rows,cutoff,data.quality.selected_model,data.prepared);
        if(model.reason)reasons.push(model.reason);
        else forecast={...model,status:'MODEL_ONLY'};
      }else{
        const model=Core.forecast(row,data.packet.rows,cutoff,true,paperDomestic);
        if(model.status==='MODEL_ONLY'){
          model.evidence.team_history=historyProfile(data.packet.rows,
            Core.canonical(row.competition,row.home_team),Core.canonical(row.competition,row.away_team),
            new Date(row.kickoff).toISOString(),cutoff,facts?.referee);
          forecast=model;
        }
        else reasons.push('TEAM_HISTORY_OR_IDENTITY_INSUFFICIENT');
      }
    }
    const quote_audit=kickoffVerified?auditWeekly(weekly,row,cutoff):{status:'KICKOFF_NOT_REVERIFIED'};
    if(forecast)forecast=attachOdds({...forecast,source_cutoff:cutoffText,evidence:forecast.evidence??{}},null,row,odds,true,
      paperOddsSports,identity,oddsbunchOffers(reserve,row,cutoff));
    if(!forecast?.evidence?.quote_price_verified){
      reasons.push(quote_audit.status==='UNSUPPORTED_QUOTE_FEED'?'TIMESTAMPED_ODDS_UNAVAILABLE':quote_audit.status,
        'DEATH_TEST_NOT_VERIFIED');
      if(odds.status==='NOT_CONFIGURED'&&reserve.status==='NOT_CONFIGURED')reasons.push('TIMESTAMPED_ODDS_SOURCE_NOT_CONFIGURED');
    }
    const marketEvaluated=marketGate(forecast);
    if(['NO_EDGE','FRAGILE_EDGE'].includes(marketEvaluated.status))reasons.push(marketEvaluated.status);
    if(!facts?.lineups)reasons.push('LINEUPS_NOT_VERIFIED');
    reasons.push('TACTICAL_FIT_NOT_VERIFIED','PUBLIC_TRAP_NOT_VERIFIED','V21_2_FULL_GATE_NOT_VERIFIED');
    return {fixture_key:row.fixture_key,competition:row.competition,home:row.home_team,away:row.away_team,
      kickoff:row.kickoff,kickoff_verified:kickoffVerified,verdict:'PASS',reasons,
      quote_audit,forecast,fixture_sources:row.fixture_sources??[],provider_kickoff:provider,context:facts,
      quality_gates:{kickoff:kickoffVerified?'CONFIRMED':'BLOCKED',model:forecast?'AVAILABLE':'BLOCKED',
        lineups:facts?.lineups?'CONFIRMED':'NOT_VERIFIED',referee:'NOT_VERIFIED',tactical_fit:'NOT_VERIFIED',
        public_trap:'NOT_VERIFIED',correlation:'NOT_APPLICABLE',market:marketEvaluated},
      unavailable_context:[...(!facts?.lineups?['LINEUPS']:[]),...(!facts?.injuries?['INJURIES']:[]),'SUSPENSIONS','TACTICS','REFEREE_GATE']};
  });
  return {mode:modes.daily,date,verdict:'PASS',status:fixtures.length?'COMPLETED':'NO_UPCOMING_FIXTURES',
    input_fixtures:rows.length,excluded_by_time:rows.length-fixtures.length,
    cutoff:cutoffText,markets_evaluated:fixtures.reduce((n,row)=>n+(row.forecast?.markets.length??0),0),
    eligible_legs:0,bank_open:1000,bank_close:1000,virtual_stake:0,real_cost:0,
    odds_gateway:odds.status,reserve_odds_gateway:reserve.status,odds_failures:odds.errors??[],context_gateway:context.reason??context.status,
    fixtures,qualifications:Object.fromEntries(completed.map(([code,data])=>[code,
      {quality:data.quality??null,error:data.error??null,sources:data.packet?.sources??[]}]))};
}
