import { removeMargin } from './markets.js';

const base='https://oddsbunch.com/api/data/v1/';
const leagues={UCL:1,CHAMPIONSHIP:14};
const hour=3600000;
const iso=t=>new Date(t).toISOString();
const utc=value=>typeof value==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+]00:00)$/.test(value)
  ?Date.parse(value):NaN;
const bookKey=label=>String(label??'').toLowerCase().replace(/[^a-z0-9]/g,'');
const round=x=>Number(x.toFixed(6));

async function get(path,params,key,fetcher){
  const response=await fetcher(base+path+'?'+new URLSearchParams(params),{redirect:'error',
    signal:AbortSignal.timeout(7500),headers:{Authorization:'Bearer '+key,Accept:'application/json'}});
  if(!response.ok)throw Error('HTTP_'+response.status);
  const raw=await response.text();
  if(raw.length>2000000)throw Error('RESPONSE_TOO_LARGE');
  const packet=JSON.parse(raw);
  if(packet?.ok!==true||packet?.meta?.tier!=='free'||!Array.isArray(packet.data)||packet.meta.next_page||
    (packet.billing?.charged??0)!==0)throw Error('UNSAFE_PROVIDER_ENVELOPE');
  return packet;
}

const fits=(m,f,identity)=>m?.sport==='soccer'&&m.status==='scheduled'&&m.league?.id===leagues[f.competition]&&
  Number.isSafeInteger(m.id)&&m.id>0&&utc(m.start_time)===Date.parse(f.kickoff)&&
  identity(f.competition,m.home?.name_en??m.home?.name)===identity(f.competition,f.home_team)&&
  identity(f.competition,m.away?.name_en??m.away?.name)===identity(f.competition,f.away_team);

export async function collectOddsbunch(fixtures,start,key,identity,fetcher=fetch,clock=Date.now){
  const matches=new Map();
  if(!key)return {status:'NOT_CONFIGURED',matches};
  const candidates=fixtures.filter(f=>Object.hasOwn(leagues,f.competition)&&Date.parse(f.kickoff)>start&&
    Date.parse(f.kickoff)-start<=48*hour);
  if(!candidates.length)return {status:'NO_FIXTURES',matches};
  try{
    const kickoffTimes=candidates.map(f=>Date.parse(f.kickoff));
    const discovery=await get('matches',{league:[...new Set(candidates.map(f=>leagues[f.competition]))].join(','),
      from:iso(Math.min(...kickoffTimes)-60000),to:iso(Math.max(...kickoffTimes)+60000),status:'scheduled',limit:'100',lang:'en'},key,fetcher);
    const wanted=new Map();
    for(const fixture of candidates){
      const found=discovery.data.filter(m=>fits(m,fixture,identity));
      if(found.length===1&&!wanted.has(found[0].id))wanted.set(found[0].id,fixture);
    }
    if(!wanted.size)return {status:'NO_MATCHED_EVENTS',matches};
    const ids=[...wanted.keys()].slice(0,20);
    const packet=await get('odds',{ids:ids.join(','),markets:'1x2,handicap,totals',
      main_only:'true',max_charge:'0',limit:'20',lang:'en'},key,fetcher);
    const observed=clock(),asOf=utc(packet.meta.data_as_of),generated=utc(packet.meta.generated_at);
    if(!(asOf<=generated&&generated<=observed&&observed-asOf<=15*60000))
      return {status:'STALE_OR_INVALID_SNAPSHOT',matches};
    for(const id of ids){
      const fixture=wanted.get(id);
      const found=packet.data.filter(x=>x.match?.id===id);
      if(found.length!==1)continue;
      const row=found[0];
      if(row.pass!=='odds_free'||row.source!=='free_snapshot'||!fits(row.match,fixture,identity))continue;
      matches.set(fixture.fixture_key,{row,observed,asOf,generated});
    }
    return {status:matches.size?'OK':'NO_MATCHED_SNAPSHOTS',matches};
  }catch(error){
    return {status:/^(?:HTTP_[0-9]{3}|RESPONSE_TOO_LARGE|UNSAFE_PROVIDER_ENVELOPE)$/.test(error.message)
      ?error.message:'SOURCE_ERROR',matches};
  }
}

export function oddsbunchOffers(collected,fixture,cutoff){
  const packet=collected?.matches.get(fixture.fixture_key),kickoff=Date.parse(fixture.kickoff);
  if(!packet||!(packet.observed<=cutoff&&cutoff<kickoff&&cutoff-packet.asOf<=15*60000))return ()=>[];
  const {row,observed,asOf,generated}=packet;
  return market=>{
    const group={ '1X2':'1x2',AH:'handicap',DNB:'handicap',TG:'totals'}[market.kind];
    if(!group||!Array.isArray(row.markets))return [];
    const groups=row.markets.filter(x=>x?.market===group);
    if(groups.length!==1||!Array.isArray(groups[0].lines))return [];
    const point=group==='handicap'&&market.side==='away'?-market.line:market.line;
    const lines=groups[0].lines.filter(x=>x?.market===group&&(group==='1x2'?x.line===null:x.line===point));
    if(lines.length!==1||!Array.isArray(lines[0].books))return [];
    const sides=group==='1x2'?['home','draw','away']:group==='totals'?['over','under']:['home','away'];
    const selected=sides.indexOf(market.side), offerRows=new Map();
    if(selected<0)return [];
    for(const b of lines[0].books){
      const id=bookKey(b?.bookmaker),changed=utc(b?.changed_at),seen=utc(b?.seen_at);
      if(!id||id.length>50||/exchange|betfair/.test(id)||b.suspended!==false||
        !(changed<=seen&&seen<=asOf&&cutoff-changed<=hour&&cutoff-seen<=30*60000)||
        !Number.isInteger(b.age_sec)||Math.abs(b.age_sec-(generated-changed)/1000)>3)continue;
      const prices=sides.map(s=>b[s]), fair=removeMargin(prices);
      if(!fair||fair.overround<0||fair.overround>.20)continue;
      const offer={bookmaker:b.bookmaker,bookmaker_id:id,odds:prices[selected],source:base+'odds',
        provider_event_id:String(row.match.id),observed_at:iso(observed),published_at:iso(asOf),
        quote_updated_at:iso(changed),quote_confirmed_at:iso(seen),quote_timestamp_scope:'MARKET',
        fair_probability:round(fair.probabilities[selected]),fair_odds:round(1/fair.probabilities[selected]),
        overround:round(fair.overround)};
      if(offerRows.has(id)){offerRows.set(id,null);continue;}
      offerRows.set(id,offer);
    }
    return [...offerRows.values()].filter(Boolean).sort((a,b)=>b.quote_updated_at.localeCompare(a.quote_updated_at)).slice(0,10);
  };
}
