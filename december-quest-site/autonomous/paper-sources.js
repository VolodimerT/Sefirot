import Core from './core.js';
import { fetchCsvWithRetry } from './csv-source.js';
import { europeResults, europeTeam } from './paper-europe.js';
import { readEuropeArchive } from './paper-europe-archive.js';
import { csvSeasons, internationalFiles, paperCompetitions } from './paper-registry.js';

const csvRoot='https://football-data.co.uk/';
const ligaRoot='https://api.openligadb.de/getmatchdata/';
const archiveRoot='https://raw.githubusercontent.com/openfootball/champions-league/abfaeddc2ee3d14f99ecc163c9ddb46cb4d67cef/';
const archives=[...['2024-25','2025-26'].flatMap(edition=>
  [['UCL','clq'],['UEL','elq'],['UECL','confq']].map(([code,name])=>[code,edition,name,true])),
  ['UECL','2024-25','conf',false]];
const britishTime=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit',
  hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
const parseLeagueDate=value=>Core.csvDate(value)?.toISOString().slice(0,10);
const id=row=>[row.date,row.home,row.away].join('|');

async function batches(jobs, size=3){
  const results=[];
  for(let i=0;i<jobs.length;i+=size)results.push(...await Promise.all(jobs.slice(i,i+size).map(run=>run())));
  return results;
}

async function openLigaData(fetcher,url){
  for(let attempt=0;attempt<2;attempt++){
    try{
      const response=await fetcher(url,{redirect:'error',signal:AbortSignal.timeout(6500)});
      if(!response.ok)throw Error('OPENLIGADB_HTTP_'+response.status);
      const body=await response.text();
      if(body.length>2500000)throw Error('OPENLIGADB_SIZE_LIMIT');
      return JSON.parse(body);
    }catch(error){
      const transient=['AbortError','TimeoutError','TypeError'].includes(error.name)||/^OPENLIGADB_HTTP_5/.test(error.message);
      if(attempt||!transient)throw error;
      await new Promise(resolve=>setTimeout(resolve,300));
    }
  }
}

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
    async european(cutoff, codes=['UCL','UEL','UECL']){
      const files=internationalFiles.filter(([competition])=>competition==='DFB_POKAL'?codes.includes(competition):codes.some(c=>c!=='DFB_POKAL'));
      const feeds=files.map(([competition,league,season])=>async()=>{
        const url=ligaRoot+league+'/'+season;
        try{
          const data=await openLigaData(fetcher,url);
          const receivedAt=clock();
          const rows=europeResults(data,competition,league,season,cutoff);
          if(rows.length<24)throw Error('INTERNATIONAL_SOURCE_INCOMPLETE');
          const fixtures=data.filter(x=>typeof x.matchIsFinished==='boolean'&&x.matchDateTimeUTC?.endsWith('Z'))
            .map(x=>({competition,home:europeTeam(x.team1?.teamName),away:europeTeam(x.team2?.teamName),
              kickoff:Date.parse(x.matchDateTimeUTC),finished:x.matchIsFinished,event_id:x.matchID,source:url,receivedAt}));
          return {competition,season,url,rows,fixtures,receivedAt};
        }catch(error){return {competition,season,url,rows:[],error:error.message};}
      });
      const archiveFeeds=codes.some(c=>c!=='DFB_POKAL')?archives.map(([competition,edition,name,qualifying])=>async()=>{
        const url=archiveRoot+edition+'/'+name+'.txt',season=Number(edition.slice(0,4));
        try{
          const response=await fetcher(url,{redirect:'error',signal:AbortSignal.timeout(9000)});
          if(!response.ok)throw Error('OPENFOOTBALL_HTTP_'+response.status);
          const rows=readEuropeArchive(await response.text(),competition,season,qualifying,cutoff);
          if(rows.length<50)throw Error('OPENFOOTBALL_ARCHIVE_INCOMPLETE');
          return {competition,season,url,rows,qualifying,receivedAt:clock()};
        }catch(error){return {competition,season,url,rows:[],error:error.message};}
      }):[];
      const [current,archive]=await Promise.all([batches(feeds),batches(archiveFeeds)]);
      const packs=[...current,...archive];
      return {rows:packs.flatMap(p=>p.rows),fixtures:packs.flatMap(p=>p.fixtures??[]),
        sources:packs.map(({rows,fixtures:_fixtures,...receipt})=>({...receipt,matches:rows.length})),
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
  if(!['EPL','CHAMPIONSHIP','ENGLAND_LEAGUE_1','ENGLAND_LEAGUE_2','NATIONAL_LEAGUE'].includes(competition))return {status:'UNSUPPORTED_QUOTE_FEED'};
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
