import Core from './core.js';
import { fetchCsvWithRetry } from './csv-source.js';
import { europeResults } from './paper-europe.js';
import { csvSeasons, internationalFiles, paperCompetitions } from './paper-registry.js';

const csvRoot='https://football-data.co.uk/';
const ligaRoot='https://api.openligadb.de/getmatchdata/';
const britishTime=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit',
  hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
const parseLeagueDate=value=>Core.csvDate(value)?.toISOString().slice(0,10);
const id=row=>[row.date,row.home,row.away].join('|');

export function paperSources(fetcher=fetch, clock=Date.now){
  const csv=fetcher===fetch
    ? url=>fetchCsvWithRetry(url,true)
    : async url=>{
      const r=await fetcher(url);if(!r.ok)throw Error('CSV_HTTP_'+r.status);
      return {text:await r.text(),publishedAt:Date.parse(r.headers.get('last-modified')||'')};
    };
  return {
    async domestic(competition,cutoff){
      const division=paperCompetitions.get(competition)?.division;
      if(!division)return {rows:[],sources:[],missing:['UNREGISTERED_CSV_DIVISION']};
      const packs=await Promise.all(csvSeasons.map(async season=>{
        const url=csvRoot+'mmz4281/'+season+'/'+division+'.csv';
        try{
          const {text,publishedAt}=await csv(url);
          const receivedAt=clock();
          const start='20'+season.slice(0,2)+'-07-01', end='20'+season.slice(2)+'-07-01';
          const rows=Core.resultsFromCsv(text,competition,cutoff,division).filter(row=>row.date>=start&&row.date<end);
          if(rows.length<24)throw Error('CSV_INSUFFICIENT_SEASON_RESULTS');
          if(Number.isFinite(publishedAt)&&publishedAt>receivedAt)throw Error('PROVIDER_PUBLICATION_IN_FUTURE');
          return {season,url,rows,receivedAt};
        }catch(error){return {season,url,rows:[],error:error.message};}
      }));
      const indexed=new Map(), conflict=new Set();
      for(const pack of packs)for(const row of pack.rows){
        const key=id(row), prior=indexed.get(key);
        if(prior&&(row.hg!==prior.hg||row.ag!==prior.ag))conflict.add(key);
        if(!prior)indexed.set(key,row);
      }
      for(const key of conflict)indexed.delete(key);
      return {rows:[...indexed.values()], sources:packs.map(({rows,...receipt})=>({...receipt,matches:rows.length})),
        missing:[...packs.filter(p=>p.error).map(p=>p.season+'_'+p.error),...(conflict.size?['CONFLICTING_RESULTS']:[])]};
    },
    async european(cutoff){
      const packs=await Promise.all(internationalFiles.map(async ([competition,league,season])=>{
        const url=ligaRoot+league+'/'+season;
        try{
          const response=await fetcher(url,{redirect:'error',signal:AbortSignal.timeout(9000)});
          if(!response.ok)throw Error('OPENLIGADB_HTTP_'+response.status);
          const body=await response.text();
          if(body.length>2500000)throw Error('OPENLIGADB_SIZE_LIMIT');
          const receivedAt=clock();
          const rows=europeResults(JSON.parse(body),competition,league,season,cutoff);
          if(rows.length<24)throw Error('INTERNATIONAL_SOURCE_INCOMPLETE');
          return {competition,season,url,rows,receivedAt};
        }catch(error){return {competition,season,url,rows:[],error:error.message};}
      }));
      return {rows:packs.flatMap(p=>p.rows),sources:packs.map(({rows,...receipt})=>({...receipt,matches:rows.length})),
        missing:packs.filter(p=>p.error).map(p=>p.competition+'_'+p.season+'_'+p.error)};
    },
    async weekly(){
      try{
        const {text,publishedAt}=await csv(csvRoot+'fixtures.csv');
        return {url:csvRoot+'fixtures.csv',records:Core.parseCsv(text),publishedAt,observedAt:clock()};
      }catch(error){return {error:error.message};}
    }
  };
}

export function auditWeekly(weekly, fixture, cutoff){
  const competition=fixture.competition;
  if(!['EPL','CHAMPIONSHIP','ENGLAND_LEAGUE_1','ENGLAND_LEAGUE_2'].includes(competition))return {status:'UNSUPPORTED_QUOTE_FEED'};
  if(!Array.isArray(weekly?.records)||!Number.isFinite(weekly.observedAt)||weekly.observedAt>cutoff)
    return {status:'QUOTE_FEED_UNAVAILABLE'};
  const kickoff=Date.parse(fixture.kickoff);
  if(!Number.isFinite(kickoff)||kickoff<=cutoff)return {status:'TIME_UNVERIFIED'};
  const part=Object.fromEntries(britishTime.formatToParts(kickoff).map(({type,value})=>[type,value]));
  const localDate=`${part.year}-${part.month}-${part.day}`, localTime=`${part.hour}:${part.minute}`;
  const home=Core.canonical(competition,fixture.home_team),away=Core.canonical(competition,fixture.away_team);
  const matches=weekly.records.filter(row=>row.Div===paperCompetitions.get(competition)?.division
    &&parseLeagueDate(row.Date)===localDate&&row.Time===localTime
    &&Core.canonical(competition,row.HomeTeam)===home&&Core.canonical(competition,row.AwayTeam)===away);
  if(matches.length!==1)return {status:matches.length?'ODDS_EVENT_AMBIGUOUS':'ODDS_EVENT_NOT_FOUND'};
  const known=/^(?:(?:B365|BFD|BV|BW|PP|SKB)[HDA]|B365(?:[<>]2\.5|AH[HA]))$/;
  const count=Object.entries(matches[0]).filter(([field,value])=>known.test(field)&&Number(value)>1&&Number(value)<=100).length;
  const published=weekly.publishedAt;
  return {status:!(published<=weekly.observedAt)?'QUOTE_TIMESTAMP_UNKNOWN'
     :cutoff-published>12*3600000?'STALE_CSV_PUBLICATION':'PER_QUOTE_TIMESTAMP_UNKNOWN',
    indicative_price_count:count,published_at:Number.isFinite(published)?new Date(published).toISOString():null,source:weekly.url};
}
