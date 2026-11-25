import Core from './core.js';
import { duplicates } from './run.js';
import { paperCompetitions, paperDomestic } from './paper-registry.js';
import { domesticReplay } from './paper-validation.js';
import { europeReplay, europeVersion, transnationalForecast } from './paper-europe.js';
import { attachOdds, collectTimestampedOdds, decemberSports } from './odds-gateway.js';
import { auditWeekly } from './paper-sources.js';
import { historyProfile } from './history.js';

export const modes=Object.freeze({december:'DECEMBER_QUEST',daily:'DAILY_PAPER_TEST',replay:'HISTORICAL_REPLAY'});
const kyiv=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Kyiv',year:'numeric',month:'2-digit',day:'2-digit'});
const sports=Object.freeze({...decemberSports, CHAMPIONSHIP:'soccer_efl_champ', ENGLAND_LEAGUE_1:'soccer_england_league1',
  SEGUNDA:'soccer_spain_segunda_division',BELGIUM:'soccer_belgium_first_div',PORTUGAL:'soccer_portugal_primeira_liga',
  TURKEY:'soccer_turkey_super_league',UCL:'soccer_uefa_champs_league',UEL:'soccer_uefa_europa_league',
  UECL:'soccer_uefa_europa_conference_league'});
const numericTime=value=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}T\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value)
  ? Date.parse(value) : NaN;

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

async function loadCompetitions(codes, sources, cutoff, european){
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
    const packet=await europe;
    return {packet,quality:europeReplay(code,packet.rows,cutoff)};
  }
  const packet=await sources.domestic(code,cutoff);
  if(packet.missing.length)return {packet,error:'DOMESTIC_HISTORY_UNAVAILABLE'};
  if(!packet.rows.some(row=>cutoff-row.when<35*86400000))return {packet,error:'DOMESTIC_HISTORY_STALE'};
  return {packet,quality:domesticReplay(code,packet.rows,cutoff,paperDomestic)};
}

export async function executeReplay({competitions,sources,cutoff}){
  if(!Array.isArray(competitions)||!competitions.length||competitions.length>paperCompetitions.size||
    new Set(competitions).size!==competitions.length||!Number.isFinite(cutoff))throw Error('INVALID_REPLAY_PARAMETERS');
  const europe=competitions.some(code=>paperCompetitions.get(code)?.family==='international')
    ? sources.european(cutoff):null;
  const loaded=await loadCompetitions(competitions,sources,cutoff,europe);
  const reports=loaded.map(([competition,data])=>({competition,qualification:data.quality??null,error:data.error??null,
    sources:data.packet?.sources?.filter(x=>!x.competition||x.competition===competition)??[]}));
  return {mode:modes.replay,cutoff:new Date(cutoff).toISOString(),date_only_archive:true,prospective:false,reports};
}

export async function executeDaily({date,calendar,sources,oddsKey='',clock=Date.now,fetcher=fetch}){
  const rows=dailyInput(date,calendar),start=clock();
  const distinct=duplicates(rows);
  const candidates=rows.filter(row=>Date.parse(row.kickoff)>start+20*60_000);
  const competitionCodes=[...new Set(candidates.filter(row=>confirmed(row,start)&&!distinct.has(row.fixture_key)).map(row=>row.competition))];
  const euro=competitionCodes.some(code=>paperCompetitions.get(code)?.family==='international')
    ? sources.european(start):null;
  const [completed,weekly]=await Promise.all([loadCompetitions(competitionCodes,sources,start,euro),
    candidates.length?sources.weekly():null]);
  const lookup=new Map(completed);
  const oddsTime=clock();
  const withModel=candidates.filter(row=>lookup.get(row.competition)?.quality?.admitted&&confirmed(row,oddsTime)&&
    !distinct.has(row.fixture_key)&&Date.parse(row.kickoff)>oddsTime+20*60_000);
  const odds=await collectTimestampedOdds(withModel,oddsTime,oddsKey,fetcher,clock,sports);
  const cutoff=clock(), cutoffText=new Date(cutoff).toISOString();
  const fixtures=candidates.filter(row=>Date.parse(row.kickoff)>cutoff+20*60_000).map(row=>{
    const data=lookup.get(row.competition), reasons=[];
    const kickoffVerified=confirmed(row,cutoff), registered=paperCompetitions.get(row.competition);
    if(distinct.has(row.fixture_key))reasons.push('DUPLICATE_FIXTURE');
    if(!kickoffVerified)reasons.push('KICKOFF_NOT_REVERIFIED');
    if(!registered)reasons.push('COMPETITION_NOT_REGISTERED');
    if(registered?.missing)reasons.push(registered.missing);
    if(data?.error&&!reasons.includes(data.error))reasons.push(data.error,...(data.packet?.missing||[]));
    if(data?.quality&&!data.quality.admitted)reasons.push(...data.quality.failures);
    if(row.displaced_home===true)reasons.push('VENUE_OUTSIDE_VALIDATION');
    if(data?.packet?.sources.some(s=>!s.error&&s.receivedAt>cutoff))reasons.push('SOURCE_OBSERVED_AFTER_CUTOFF');
    let forecast=null;
    if(!reasons.length&&data?.quality?.admitted){
      if(registered.family==='international'){
        const model=transnationalForecast(row,data.packet.rows,cutoff,true);
        if(model.reason)reasons.push(model.reason);
        else forecast={...model,model_version:europeVersion,status:'MODEL_ONLY'};
      }else{
        const model=Core.forecast(row,data.packet.rows,cutoff,true,paperDomestic);
        if(model.status==='MODEL_ONLY'){
          model.evidence.team_history=historyProfile(data.packet.rows,
            Core.canonical(row.competition,row.home_team),Core.canonical(row.competition,row.away_team),
            new Date(row.kickoff).toISOString(),cutoff);
          forecast=model;
        }
        else reasons.push('TEAM_HISTORY_OR_IDENTITY_INSUFFICIENT');
      }
    }
    const quote_audit=kickoffVerified?auditWeekly(weekly,row,cutoff):{status:'KICKOFF_NOT_REVERIFIED'};
    if(forecast)forecast=attachOdds({...forecast,source_cutoff:cutoffText,evidence:forecast.evidence??{}},null,row,odds,true,sports);
    if(!forecast?.evidence?.quote_price_verified){
      reasons.push(quote_audit.status==='UNSUPPORTED_QUOTE_FEED'?'TIMESTAMPED_ODDS_UNAVAILABLE':quote_audit.status,
        'DEATH_TEST_NOT_VERIFIED');
      if(odds.status==='NOT_CONFIGURED')reasons.push('TIMESTAMPED_ODDS_SOURCE_NOT_CONFIGURED');
    }
    reasons.push('LINEUPS_NOT_VERIFIED','TACTICAL_FIT_NOT_VERIFIED','PUBLIC_TRAP_NOT_VERIFIED','V21_2_FULL_GATE_NOT_VERIFIED');
    return {fixture_key:row.fixture_key,competition:row.competition,home:row.home_team,away:row.away_team,
      kickoff:row.kickoff,kickoff_verified:kickoffVerified,verdict:'PASS',reasons,
      quote_audit,forecast,fixture_sources:row.fixture_sources??[],
      unavailable_context:['LINEUPS','INJURIES','SUSPENSIONS','TACTICS','REFEREE_GATE']};
  });
  return {mode:modes.daily,date,verdict:'PASS',status:fixtures.length?'COMPLETED':'NO_UPCOMING_FIXTURES',
    input_fixtures:rows.length,excluded_by_time:rows.length-fixtures.length,
    cutoff:cutoffText,markets_evaluated:fixtures.reduce((n,row)=>n+(row.forecast?.markets.length??0),0),
    eligible_legs:0,bank_open:1000,bank_close:1000,virtual_stake:0,real_cost:0,
    odds_gateway:odds.status, fixtures,qualifications:Object.fromEntries(completed.map(([code,data])=>[code,
      {quality:data.quality??null,error:data.error??null,sources:data.packet?.sources??[]}]))};
}
