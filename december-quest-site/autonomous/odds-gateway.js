import Core from './core.js';
import { evaluateQuote } from './markets.js';

const hour = 3600000;
const horizon = 48 * hour;
const quoteAge = hour;
const publicationAge = 12 * hour;
const sourceUrl = 'https://api.the-odds-api.com/v4/sports/';
const csvUrl = 'https://football-data.co.uk/fixtures.csv';
const sports = { EPL:'soccer_epl', LALIGA:'soccer_spain_la_liga', SERIEA:'soccer_italy_serie_a',
  BUNDES:'soccer_germany_bundesliga', LIGUE1:'soccer_france_ligue_one' };
const csvBooks = { B365:'Bet365', BFD:'Betfred', BV:'Betvictor', BW:'Bwin', PP:'Paddy Power', SKB:'Sky Bet' };
const resultSuffix = {home:'H',draw:'D',away:'A'};
const iso = epoch => new Date(epoch).toISOString();
const round = value => Number(value.toFixed(6));
const verifiedTime = value => typeof value==='string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]00:00)$/.test(value)
  ? Date.parse(value) : NaN;
const team = (fixture,value) => {
  const canonical = Core.canonical(fixture.competition,value);
  if (fixture.competition==='EPL' && canonical==='leedsunited') return 'leeds';
  return canonical;
};
const bookIdentity = value => String(value||'').toLowerCase().replace(/[^a-z0-9]+/g,'');
const validPrice = value => typeof value==='number' && Number.isFinite(value) && value>1 && value<=100;
const isPrematch = (cutoff,kickoff) => Number.isFinite(cutoff) && Number.isFinite(kickoff) && kickoff>cutoff && kickoff-cutoff<=horizon;

export async function collectTimestampedOdds(fixtures, now, key, fetcher=fetch, clock=Date.now) {
  if (!key) return {status:'NOT_CONFIGURED',batches:[]};
  const leagues = [...new Set(fixtures.filter(f=>sports[f.competition] && f.timing_status==='confirmed' &&
    isPrematch(now,Date.parse(f.kickoff))).map(f=>f.competition))];
  const attempts = await Promise.all(leagues.map(async league=>{
    const endpoint = sourceUrl+sports[league]+'/odds';
    const params = new URLSearchParams({apiKey:key,regions:'eu',markets:'h2h,totals',oddsFormat:'decimal',dateFormat:'iso',
      commenceTimeFrom:iso(now).slice(0,19)+'Z',commenceTimeTo:iso(now+horizon).slice(0,19)+'Z'});
    try {
      const response = await fetcher(endpoint+'?'+params,{redirect:'error',signal:AbortSignal.timeout(7500)});
      if (!response.ok) return {league,error:'HTTP_'+response.status};
      const raw = await response.text();
      if (raw.length>2000000) return {league,error:'RESPONSE_TOO_LARGE'};
      const events = JSON.parse(raw);
      if (!Array.isArray(events) || events.length>500) return {league,error:'INVALID_RESPONSE'};
      return {league,endpoint,observedAt:clock(),events};
    } catch {
      // A transport exception can contain the complete URL and API key.
      return {league,error:'FETCH_ERROR'};
    }
  }));
  const batches=attempts.filter(entry=>!entry.error);
  return {status:!attempts.length?'NO_FIXTURES':batches.length===attempts.length?'OK':batches.length?'PARTIAL':'SOURCE_ERROR',
    batches,errors:attempts.filter(x=>x.error).map(({league,error})=>({league,error}))};
}

function marketRules(market) {
  if (market.kind==='1X2') return 'REGULATION_90_PLUS_STOPPAGE_1X2';
  if (market.kind==='TG' && market.line%1===0.5) return 'REGULATION_90_PLUS_STOPPAGE_HALF_GOAL_TOTAL';
  if (market.kind==='DNB') return 'REGULATION_90_PLUS_STOPPAGE_HANDICAP_DRAW_PUSH';
  return market.kind==='AH' || market.kind==='TG'
    ? 'REGULATION_90_PLUS_STOPPAGE_ASIAN_SPLIT_PUSH' : null;
}

function csvOffers(fixture, weekly, cutoff, kickoff) {
  if (!weekly?.ok || !Number.isFinite(weekly.publishedAt) ||
      !(weekly.publishedAt<=weekly.observedAt && weekly.observedAt<=cutoff && cutoff-weekly.publishedAt<=publicationAge) ||
      !isPrematch(cutoff,kickoff) || Core.weeklyKickoff(weekly.records,fixture)?.status!=='MATCH') return () => [];
  const [raw] = Core.matchWeekly(weekly.records,fixture);
  const line = typeof raw.AHh==='string' && raw.AHh.trim() ? Number(raw.AHh) : null;
  return market => Object.entries(csvBooks).flatMap(([prefix, bookmaker])=>{
    let field;
    if (market.kind==='1X2') field=prefix+resultSuffix[market.side];
    else if (prefix==='B365' && market.kind==='TG' && market.line===2.5) field=prefix+(market.side==='over'?'>':'<')+'2.5';
    else if (prefix==='B365' && Number.isFinite(line) && ['DNB','AH'].includes(market.kind) &&
        market.line===(market.side==='home'?line:-line)) field=prefix+(market.side==='home'?'AHH':'AHA');
    const odds=Number(raw[field]);
    return field && validPrice(odds) ? [{
      bookmaker,bookmaker_id:bookIdentity(bookmaker),odds,source:csvUrl,
      observed_at:iso(weekly.observedAt),published_at:iso(weekly.publishedAt),quote_updated_at:null
    }] : [];
  });
}

function apiOffers(fixture, collected, cutoff, kickoff, confirmed) {
  if (!confirmed || !isPrematch(cutoff,kickoff)) return () => [];
  const batch=collected?.batches?.find(x=>x.league===fixture.competition);
  if (!batch || !(batch.observedAt<=cutoff && cutoff-batch.observedAt<=quoteAge)) return () => [];
  const events=batch.events.filter(event=>event?.sport_key===sports[fixture.competition] &&
    verifiedTime(event.commence_time)===kickoff && event.completed!==true && event.live!==true &&
    team(fixture,event.home_team)===team(fixture,fixture.home_team) && team(fixture,event.away_team)===team(fixture,fixture.away_team));
  if (events.length!==1 || !Array.isArray(events[0].bookmakers)) return () => [];
  return market => {
    const key=market.kind==='1X2'?'h2h':market.kind==='TG'&&market.line%1===0.5?'totals':null;
    if (!key) return [];
    const offers=new Map();
    for (const book of events[0].bookmakers) {
      if (!book||!Array.isArray(book.markets)||/exchange|betfair_ex/i.test((book.key||'')+' '+(book.title||''))) continue;
      const id=bookIdentity(book.title||book.key);
      if (!id||id.length>50||typeof book.title!=='string'||book.title.length>70) continue;
      const [packet,...extra]=book.markets.filter(x=>x?.key===key);
      if (!packet||extra.length||!Array.isArray(packet.outcomes)) continue;
      const updated=verifiedTime(packet.last_update ?? book.last_update);
      if (!(updated<=batch.observedAt && cutoff-updated<=quoteAge)) continue;
      const outcomes=packet.outcomes.filter(x=>validPrice(x?.price));
      const home=team(fixture,fixture.home_team), away=team(fixture,fixture.away_team);
      let matches;
      if (key==='h2h') {
        const names=new Set(outcomes.map(x=>team(fixture,x.name)));
        if (outcomes.length!==3||names.size!==3||!names.has(home)||!names.has(away)||!names.has('draw')) continue;
        const target=({home,away,draw:'draw'})[market.side];
        matches=outcomes.filter(x=>team(fixture,x.name)===target);
      } else {
        const line=outcomes.filter(x=>typeof x.point==='number'&&x.point===market.line);
        const names=new Set(line.map(x=>String(x.name).toLowerCase()));
        if (line.length!==2||!names.has('over')||!names.has('under')) continue;
        matches=line.filter(x=>String(x.name).toLowerCase()===market.side);
      }
      if (matches.length!==1) continue;
      const prior=offers.get(id);
      const odds=matches[0].price;
      if (prior && prior.updated>updated) continue;
      if (prior?.updated===updated && (prior.ambiguous||prior.odds!==odds)) {
        offers.set(id,{updated,ambiguous:true});
        continue;
      }
      offers.set(id,{bookmaker:book.title,bookmaker_id:id,odds,source:batch.endpoint,
        observed_at:iso(batch.observedAt),published_at:null,quote_updated_at:iso(updated),updated});
    }
    return [...offers.values()].filter(x=>!x.ambiguous)
      .sort((a,b)=>b.updated-a.updated||a.bookmaker_id.localeCompare(b.bookmaker_id)).slice(0,10)
      .map(({updated,...offer})=>offer);
  };
}

function collectMarket(market, alternatives, verified) {
  const rules = marketRules(market);
  if (!rules || !alternatives.length) return market;
  const sorted = alternatives.slice().sort((a,b)=>a.odds-b.odds||a.bookmaker_id.localeCompare(b.bookmaker_id));
  const middle = Math.floor(sorted.length/2);
  const median = sorted.length%2 ? sorted[middle].odds : (sorted[middle-1].odds+sorted[middle].odds)/2;
  // Use an observed price for EV, with the lower middle offer breaking ties.
  const offer = sorted[Math.floor((sorted.length-1)/2)];
  const metrics=evaluateQuote(market.settlement,offer.odds);
  if (!metrics) return market;
  const {expected_value,...diagnostics}=metrics;
  return {...market,...diagnostics,...offer,market_odds:round(median),quote_count:sorted.length,
    settlement_rules:rules,quote_timestamp_verified:verified,price_verified:verified,value_verified:false,
    ev:verified?expected_value:null,conditional_ev_pct:verified?null:expected_value,
    death_test:diagnostics.sensitivity['-0.05']>0?'PASS_CONDITIONAL':'FAIL_CONDITIONAL',
    quotes:sorted};
}

export function attachOdds(forecast, weekly, fixture, collected, confirmed) {
  if (forecast.status!=='MODEL_ONLY') return forecast;
  const cutoff=Date.parse(forecast.source_cutoff),kickoff=Date.parse(fixture.kickoff);
  const primary=apiOffers(fixture,collected,cutoff,kickoff,confirmed);
  const fallback=csvOffers(fixture,weekly,cutoff,kickoff);
  const markets=forecast.markets.map(market=>{
    const verified=primary(market);
    return verified.length?collectMarket(market,verified,true):collectMarket(market,fallback(market),false);
  });
  const ranked=markets.filter(x=>x.odds!==null).sort((a,b)=>
    Number(b.price_verified)-Number(a.price_verified)||((b.ev??b.conditional_ev_pct)-(a.ev??a.conditional_ev_pct)));
  if(!ranked.length) return forecast;
  const best=ranked[0], alternative=ranked.find(x=>x.market!==best.market);
  const {quotes,...summary}=best;
  return {...forecast,markets,status:'WAITING_ODDS',
    best_candidate:{...summary,alternative:alternative?{market:alternative.market,pick:alternative.pick,
      ev:alternative.ev,conditional_ev_pct:alternative.conditional_ev_pct}:null},
    evidence:{...forecast.evidence,quote_found:true,quote_price_verified:best.price_verified,
      quote_observed_fetch_at:best.observed_at,quote_provider_timestamp:best.quote_updated_at,quote_source:best.source},
    notes:best.price_verified?'Цена и EV рассчитаны. Остальные фильтры действуют: PASS.'
      :'Время обновления отдельной цены у БК неизвестно. EV условный.'};
}
